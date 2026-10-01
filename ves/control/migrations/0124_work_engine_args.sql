-- 0124 작품별 엔진 기본 설정(2026-10-01) — 작업 컴퓨터에서 명령어에 붙여 돌리던 작품 설정(디자인 · 목소리 · 대본 방식 · 말 빠르기)을
-- 작품 카드에 적어 두고, 작업을 저장할 때 자동으로 붙인다. 작업에 직접 준 값이 이긴다.
-- 계기: 로또 7-8화를 맥미니로 돌렸더니 기본 디자인 · 기본 목소리로 나왔다(작업 컴퓨터는 lotto_tving_v2 · ElevenLabs 목소리 · 단계형 대본).
ALTER TABLE public.work_cards ADD COLUMN engine_args jsonb NOT NULL DEFAULT '{}'::jsonb
  CHECK (jsonb_typeof(engine_args) = 'object');
COMMENT ON COLUMN public.work_cards.engine_args IS '작업에 자동으로 붙는 엔진 설정(0111 c_keys 와 같은 어휘) — design_preset · voice · script_flow · speed · copy · pov 등';

UPDATE public.work_cards SET engine_args = '{"design_preset":"lotto_tving_v2","voice":"elevenlabs:DkAJhrMznCtWh38YrjTv","script_flow":"staged","speed":"fast"}'::jsonb
 WHERE work_title = '로또 1등도 출근합니다';

CREATE OR REPLACE FUNCTION public.set_work_engine_args(p_work text, p_args jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_bad text;
  c_args constant text[] := ARRAY['design_preset','style_preset','script_flow','voice','speed','copy',
                                  'copy_pos','logo_width','range','pov','cover_cut_guard','stt'];
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF jsonb_typeof(coalesce(p_args, '{}'::jsonb)) <> 'object' THEN RAISE EXCEPTION '엔진 설정은 JSON 객체여야 해요'; END IF;
  SELECT k INTO v_bad FROM jsonb_object_keys(coalesce(p_args, '{}'::jsonb)) k WHERE NOT (k = ANY (c_args)) LIMIT 1;
  IF v_bad IS NOT NULL THEN RAISE EXCEPTION '모르는 엔진 설정: %', v_bad; END IF;
  INSERT INTO public.work_cards(work_title, updated_by, updated_at) VALUES (p_work, auth.uid()::text, now())
  ON CONFLICT (work_title) DO NOTHING;
  UPDATE public.work_cards SET engine_args = jsonb_strip_nulls(coalesce(p_args, '{}'::jsonb)), updated_by = auth.uid()::text, updated_at = now()
   WHERE work_title = p_work;
  PERFORM public._audit('set_work_engine_args', 'work_cards', p_work, jsonb_build_object('args', p_args));
  RETURN coalesce(p_args, '{}'::jsonb);
END $$;
REVOKE ALL ON FUNCTION public.set_work_engine_args(text, jsonb) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_work_engine_args(text, jsonb) TO authenticated;

-- 작업 저장 때 작품 기본 엔진 설정을 붙인다(0121 save_tikitaka_tasks 와 같고 v_opts 한 줄만 다르다)
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
  -- 작품 기본 엔진 설정(0124)을 깔고 작업에 준 값으로 덮는다
  v_opts := public._tikitaka_task_options(coalesce(p_options, '{}'::jsonb) || jsonb_build_object('args',
              coalesce((SELECT engine_args FROM public.work_cards WHERE work_title = v_src.work_title), '{}'::jsonb)
              || coalesce(p_options->'args', '{}'::jsonb)));
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
VALUES ('orchestrator','0124','claude (작품별 엔진 기본 설정)');
