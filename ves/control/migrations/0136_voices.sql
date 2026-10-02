-- 0136 내레이션 목소리(2026-10-02) — 목소리는 채널 × 작품 값(채널 템플릿의 작품 탭). 비우면 작품 기본(work_cards.engine_args.voice).
-- 고르는 목록은 tts_voices(ElevenLabs 계정 목소리 사본, 한국어 위주) — 미리 듣기 주소(preview_url)를 같이 둔다.
-- 작업 저장(save_tikitaka_tasks)은 다시 작품 엔진 설정을 옮겨 담지 않는다 — 맥미니가 작업을 시작할 때 그 순간의 작품 설정 · 채널 목소리를 읽는다.
CREATE TABLE public.tts_voices (
 id text PRIMARY KEY,                     -- 'elevenlabs:<voice_id>' (엔진 --voice 값 그대로)
 name text NOT NULL, gender text, language text, preview_url text,
 sort int NOT NULL DEFAULT 100, active boolean NOT NULL DEFAULT true,
 updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.tts_voices ENABLE ROW LEVEL SECURITY;
CREATE POLICY tts_voices_read ON public.tts_voices FOR SELECT TO authenticated USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.tts_voices TO authenticated;

ALTER TABLE public.channel_work_designs ADD COLUMN voice text REFERENCES public.tts_voices(id);
ALTER TABLE public.channel_work_designs ALTER COLUMN design SET DEFAULT '{}'::jsonb;

-- 이 채널 × 작품 목소리(p_voice NULL = 작품 기본 따르기)
CREATE OR REPLACE FUNCTION public.set_channel_work_voice(p_slug text, p_work text, p_voice text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN RAISE EXCEPTION '없는 채널이에요: %', p_slug; END IF;
  IF p_voice IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.tts_voices WHERE id = p_voice AND active) THEN RAISE EXCEPTION '없는 목소리예요'; END IF;
  INSERT INTO public.channel_work_designs(token_slug, work_title, design, voice) VALUES (p_slug, p_work, '{}'::jsonb, p_voice)
  ON CONFLICT (token_slug, work_title) DO UPDATE SET voice = EXCLUDED.voice, updated_by = auth.uid(), updated_at = now();
  DELETE FROM public.channel_work_designs WHERE token_slug = p_slug AND work_title = p_work AND voice IS NULL AND design = '{}'::jsonb;
  PERFORM public._audit('set_channel_work_voice', 'channel_work_designs', p_slug || ':' || p_work, jsonb_build_object('voice', p_voice));
END $$;
REVOKE ALL ON FUNCTION public.set_channel_work_voice(text, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_channel_work_voice(text, text, text) TO authenticated;

-- 0134 의 '값 지우기'가 목소리까지 지우지 않게 — 모양 값만 비우고, 목소리가 남아 있으면 줄은 남긴다
CREATE OR REPLACE FUNCTION public.set_channel_work_design(p_slug text, p_work text, p_design jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v jsonb;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN RAISE EXCEPTION '없는 채널이에요: %', p_slug; END IF;
  v := CASE WHEN p_design IS NULL THEN '{}'::jsonb ELSE public._render_template_design(p_design) END;
  INSERT INTO public.channel_work_designs(token_slug, work_title, design) VALUES (p_slug, p_work, v)
  ON CONFLICT (token_slug, work_title) DO UPDATE SET design = EXCLUDED.design, updated_by = auth.uid(), updated_at = now();
  DELETE FROM public.channel_work_designs WHERE token_slug = p_slug AND work_title = p_work AND voice IS NULL AND design = '{}'::jsonb;
  PERFORM public._audit('set_channel_work_design', 'channel_work_designs', p_slug || ':' || p_work, jsonb_build_object('design', v));
  RETURN CASE WHEN v = '{}'::jsonb THEN NULL ELSE v END;
END $$;

-- 작업 저장: 작품 엔진 설정을 옮겨 담지 않는다(0121 과 같은 본문 — 시작할 때 맥미니가 읽는다)
CREATE OR REPLACE FUNCTION public.save_tikitaka_tasks(p_source uuid, p_channels text[], p_options jsonb, p_start boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_src record; v_key text; v_opts jsonb; v_slug text; v_no int; v_ids uuid[] := '{}'; v_id uuid; v_out jsonb := '[]'::jsonb;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF coalesce(cardinality(p_channels), 0) = 0 THEN RAISE EXCEPTION '만들 채널을 골라 주세요'; END IF;
  IF cardinality(p_channels) > 10 THEN RAISE EXCEPTION '채널은 한 번에 10개까지 고를 수 있어요'; END IF;
  SELECT * INTO v_src FROM public.sources WHERE id = p_source;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 원본이에요'; END IF;
  v_key := coalesce(v_src.episode_label, v_src.episode::text);
  IF v_key IS NULL THEN RAISE EXCEPTION '회차를 모르는 원본이에요 — 회차가 있는 원본으로 작업해 주세요'; END IF;
  v_opts := public._tikitaka_task_options(p_options);
  PERFORM pg_advisory_xact_lock(hashtext('tikitaka_tasks:' || v_src.work_title || ':' || v_key));
  SELECT coalesce(max(work_no), 0) INTO v_no FROM public.tikitaka_tasks WHERE work_title = v_src.work_title AND episode_key = v_key;
  FOREACH v_slug IN ARRAY (SELECT array_agg(DISTINCT s) FROM unnest(p_channels) s) LOOP
    PERFORM public._tikitaka_channel(v_slug, v_src.work_title);
    v_no := v_no + 1;
    INSERT INTO public.tikitaka_tasks(work_title, episode_key, work_no, source_id, compilation_id, channel_slug, options, created_by)
    VALUES (v_src.work_title, v_key, v_no, v_src.id, v_src.compilation_id, v_slug, v_opts, auth.uid())
    RETURNING id INTO v_id;
    v_ids := v_ids || v_id;
    v_out := v_out || jsonb_build_object('task_id', v_id, 'work_no', v_no, 'channel', v_slug);
    PERFORM public._audit('save_tikitaka_task', 'tikitaka_tasks', v_id::text,
            jsonb_build_object('work', v_src.work_title, 'episode', v_key, 'no', v_no, 'channel', v_slug, 'options', v_opts));
  END LOOP;
  IF p_start THEN PERFORM public.start_tikitaka_tasks(v_ids); END IF;
  RETURN v_out;
END $$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0136','claude (내레이션 목소리 · 작업 시작 때 작품 설정)');
