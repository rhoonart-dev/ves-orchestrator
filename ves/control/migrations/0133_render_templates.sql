-- 0133 렌더 템플릿(2026-10-02) — 대시보드에서 정한 영상 모양(제목 폰트 · 제목 1·2줄 색 · 대사/내레이션 자막 폰트 · 색 ·
-- 로고 아래 필수 문구 · 권리사 로고/문구)을 이름 붙여 저장하고, 채널 × 작품(없으면 작품 기본)에 지정한다.
-- 맥미니(tikitaka_generate)는 작업을 시작할 때 render_template_for 로 지금 지정된 템플릿을 읽어 엔진 --design-json 으로 넘긴다.
-- 템플릿에 없는 값(크기 · 위치 · 화면비)은 작품 엔진 설정의 design_preset 이나 엔진 기본을 따른다.
-- '실제 모양 보기'는 맥미니가 실제 영상 한 편을 그 템플릿으로 다시 렌더해 두 장(대사 · 내레이션)을 올린다(template_preview 잡).

CREATE TABLE public.render_templates (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 name text NOT NULL UNIQUE CHECK (length(btrim(name)) BETWEEN 1 AND 60),
 design jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(design) = 'object'),
 note text,
 created_by uuid DEFAULT auth.uid(), updated_by uuid DEFAULT auth.uid(),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 retired_at timestamptz
);
COMMENT ON TABLE public.render_templates IS '렌더 템플릿 — design 은 엔진 design 키 중 템플릿이 다루는 것만(_render_template_design)';

CREATE TABLE public.channel_work_templates (
 token_slug text NOT NULL, work_title text NOT NULL,
 template_id uuid NOT NULL REFERENCES public.render_templates(id),
 updated_by uuid DEFAULT auth.uid(), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (token_slug, work_title)
);
COMMENT ON TABLE public.channel_work_templates IS '이 채널에서 이 작품을 만들 때 쓰는 템플릿 — 없으면 work_cards.render_template_id';

ALTER TABLE public.work_cards ADD COLUMN render_template_id uuid REFERENCES public.render_templates(id);
COMMENT ON COLUMN public.work_cards.render_template_id IS '작품 기본 템플릿(채널 × 작품 지정이 없을 때)';

CREATE TABLE public.render_template_previews (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 template_id uuid REFERENCES public.render_templates(id) ON DELETE SET NULL,
 design jsonb NOT NULL,
 video_id uuid NOT NULL REFERENCES public.tikitaka_videos(id) ON DELETE CASCADE,
 state text NOT NULL CHECK (state IN ('running','done','failed')),
 error text, job_id uuid,
 files jsonb NOT NULL DEFAULT '{}'::jsonb,
 requested_by uuid DEFAULT auth.uid(),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.render_template_previews IS '실제 모양 보기 — files{dialogue|narration: ves-outputs 키}';

ALTER TABLE public.render_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.channel_work_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.render_template_previews ENABLE ROW LEVEL SECURITY;
CREATE POLICY render_templates_read ON public.render_templates FOR SELECT TO authenticated USING (public.has_role((SELECT auth.uid()), 'viewer'));
CREATE POLICY channel_work_templates_read ON public.channel_work_templates FOR SELECT TO authenticated USING (public.has_role((SELECT auth.uid()), 'viewer'));
CREATE POLICY render_template_previews_read ON public.render_template_previews FOR SELECT TO authenticated USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.render_templates, public.channel_work_templates, public.render_template_previews TO authenticated;

-- 템플릿 design 검사 · 정리 — 모르는 키 · 없는 폰트 · 색 형식이 틀리면 거절(조용히 빠지면 다른 모양이 나간다)
CREATE OR REPLACE FUNCTION public._render_template_design(p jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE k text; v text;
  c_fonts constant text[] := ARRAY['JalnanGothic','Jalnan','NotoSansCJKkr-Black','mulmaru','Griun'];
  c_colors constant text[] := ARRAY['title_color','title_color2','subtitle_color','tts_color','work_caption_color','platform_color'];
  c_logos constant text[] := ARRAY['tving_logo','coupangplay_icon','coupangplay_logo'];
  out jsonb := '{}'::jsonb;
BEGIN
  p := coalesce(p, '{}'::jsonb);
  IF jsonb_typeof(p) <> 'object' THEN RAISE EXCEPTION '템플릿 값이 이상해요'; END IF;
  FOR k, v IN SELECT key, value #>> '{}' FROM jsonb_each(p) LOOP
    v := nullif(btrim(coalesce(v, '')), '');
    CONTINUE WHEN v IS NULL;
    IF k IN ('title_font','subtitle_font','tts_font') THEN
      IF NOT v = ANY (c_fonts) THEN RAISE EXCEPTION '없는 폰트예요: %', v; END IF;
    ELSIF k = ANY (c_colors) THEN
      IF v !~ '^#[0-9A-Fa-f]{6}$' THEN RAISE EXCEPTION '색은 #RRGGBB 형식이어야 해요: %', v; END IF;
      v := upper(v);
    ELSIF k = 'platform_image' THEN
      IF NOT v = ANY (c_logos) THEN RAISE EXCEPTION '없는 권리사 로고예요: %', v; END IF;
    ELSIF k IN ('work_caption','platform_text') THEN
      IF length(v) > 60 THEN RAISE EXCEPTION '문구는 60자까지 쓸 수 있어요'; END IF;
    ELSE
      RAISE EXCEPTION '템플릿에서 다루지 않는 값이에요: %', k;
    END IF;
    out := out || jsonb_build_object(k, v);
  END LOOP;
  RETURN out;
END $$;

-- 저장(새로 만들기 · 고치기) — 운영자부터. 고친 값은 다음 작업부터 쓴다(이미 만든 영상은 그대로)
CREATE OR REPLACE FUNCTION public.save_render_template(p_id uuid, p_name text, p_design jsonb, p_note text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_id uuid; v_design jsonb := public._render_template_design(p_design);
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF length(btrim(coalesce(p_name, ''))) = 0 THEN RAISE EXCEPTION '템플릿 이름을 적어 주세요'; END IF;
  IF EXISTS (SELECT 1 FROM public.render_templates WHERE name = btrim(p_name) AND id IS DISTINCT FROM p_id) THEN
    RAISE EXCEPTION '같은 이름의 템플릿이 있어요: %', btrim(p_name);
  END IF;
  IF p_id IS NULL THEN
    INSERT INTO public.render_templates(name, design, note) VALUES (btrim(p_name), v_design, nullif(btrim(coalesce(p_note, '')), ''))
    RETURNING id INTO v_id;
  ELSE
    UPDATE public.render_templates SET name = btrim(p_name), design = v_design, note = nullif(btrim(coalesce(p_note, '')), ''),
           updated_by = auth.uid(), updated_at = now()
     WHERE id = p_id AND retired_at IS NULL RETURNING id INTO v_id;
    IF v_id IS NULL THEN RAISE EXCEPTION '없는 템플릿이에요'; END IF;
  END IF;
  PERFORM public._audit('save_render_template', 'render_templates', v_id::text, jsonb_build_object('name', p_name, 'design', v_design));
  RETURN v_id;
END $$;

-- 지우기(보관) — 채널 × 작품 · 작품 기본에 쓰이고 있으면 거절
CREATE OR REPLACE FUNCTION public.retire_render_template(p_id uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF EXISTS (SELECT 1 FROM public.channel_work_templates WHERE template_id = p_id)
     OR EXISTS (SELECT 1 FROM public.work_cards WHERE render_template_id = p_id) THEN
    RAISE EXCEPTION '채널이나 작품에 지정된 템플릿이라 지울 수 없어요. 먼저 다른 템플릿으로 바꿔 주세요.';
  END IF;
  UPDATE public.render_templates SET retired_at = now(), updated_by = auth.uid(), updated_at = now() WHERE id = p_id;
  PERFORM public._audit('retire_render_template', 'render_templates', p_id::text, '{}'::jsonb);
END $$;

-- 채널 × 작품 지정(p_template NULL = 지정 풀기 → 작품 기본)
CREATE OR REPLACE FUNCTION public.set_channel_work_template(p_slug text, p_work text, p_template uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN RAISE EXCEPTION '없는 채널이에요: %', p_slug; END IF;
  IF p_template IS NULL THEN
    DELETE FROM public.channel_work_templates WHERE token_slug = p_slug AND work_title = p_work;
  ELSE
    IF NOT EXISTS (SELECT 1 FROM public.render_templates WHERE id = p_template AND retired_at IS NULL) THEN RAISE EXCEPTION '없는 템플릿이에요'; END IF;
    INSERT INTO public.channel_work_templates(token_slug, work_title, template_id) VALUES (p_slug, p_work, p_template)
    ON CONFLICT (token_slug, work_title) DO UPDATE SET template_id = EXCLUDED.template_id, updated_by = auth.uid(), updated_at = now();
  END IF;
  PERFORM public._audit('set_channel_work_template', 'channel_work_templates', p_slug || ':' || p_work, jsonb_build_object('template', p_template));
END $$;

-- 작품 기본 템플릿
CREATE OR REPLACE FUNCTION public.set_work_template(p_work text, p_template uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF p_template IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.render_templates WHERE id = p_template AND retired_at IS NULL) THEN
    RAISE EXCEPTION '없는 템플릿이에요';
  END IF;
  UPDATE public.work_cards SET render_template_id = p_template, updated_at = now() WHERE work_title = p_work;
  IF NOT FOUND THEN RAISE EXCEPTION '작품 카드가 없어요: %', p_work; END IF;
  PERFORM public._audit('set_work_template', 'work_cards', p_work, jsonb_build_object('template', p_template));
END $$;

-- 이 채널에서 이 작품을 만들 때 쓰는 템플릿 — 맥미니(서비스 키)가 작업 시작 때 읽는다
CREATE OR REPLACE FUNCTION public.render_template_for(p_slug text, p_work text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT jsonb_build_object('id', t.id, 'name', t.name, 'design', t.design,
                            'from', CASE WHEN c.template_id IS NOT NULL THEN 'channel' ELSE 'work' END)
    FROM public.render_templates t
    LEFT JOIN public.channel_work_templates c ON c.token_slug = p_slug AND c.work_title = p_work
   WHERE t.retired_at IS NULL
     AND t.id = coalesce(c.template_id, (SELECT render_template_id FROM public.work_cards WHERE work_title = p_work))
   LIMIT 1
$$;

-- 실제 모양 보기 — 고른 영상을 만든 맥미니가 그 템플릿으로 한 번 다시 렌더해 두 장을 올린다(작업 폴더는 건드리지 않는다)
CREATE OR REPLACE FUNCTION public.request_template_preview(p_design jsonb, p_video uuid, p_template uuid DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v record; v_design jsonb := public._render_template_design(p_design); v_id uuid; job uuid;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  SELECT id, work_order_id, suffix, node_id INTO v FROM public.tikitaka_videos WHERE id = p_video;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
  IF v.node_id IS NULL THEN RAISE EXCEPTION '이 영상을 만든 맥미니를 알 수 없어요'; END IF;
  v_id := gen_random_uuid();
  INSERT INTO public.job_queue(work_order_id, kind, params, idempotency_key, required_caps, lease_ttl_sec, priority)
  VALUES (v.work_order_id, 'template_preview',
          jsonb_build_object('preview_id', v_id, 'video_id', v.id, 'work_order_id', v.work_order_id, 'suffix', v.suffix, 'design', v_design),
          'template-preview:' || v_id, ARRAY['generate', 'node:' || v.node_id], 300, 180)
  RETURNING id INTO job;
  INSERT INTO public.render_template_previews(id, template_id, design, video_id, state, job_id)
  VALUES (v_id, p_template, v_design, p_video, 'running', job);
  RETURN v_id;
END $$;

REVOKE ALL ON FUNCTION public.save_render_template(uuid, text, jsonb, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.save_render_template(uuid, text, jsonb, text) TO authenticated;
REVOKE ALL ON FUNCTION public.retire_render_template(uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.retire_render_template(uuid) TO authenticated;
REVOKE ALL ON FUNCTION public.set_channel_work_template(text, text, uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_channel_work_template(text, text, uuid) TO authenticated;
REVOKE ALL ON FUNCTION public.set_work_template(text, uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_work_template(text, uuid) TO authenticated;
REVOKE ALL ON FUNCTION public.render_template_for(text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.render_template_for(text, text) TO authenticated;
REVOKE ALL ON FUNCTION public.request_template_preview(jsonb, uuid, uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.request_template_preview(jsonb, uuid, uuid) TO authenticated;

-- 지금 쓰던 엔진 템플릿 파일(app/data/channel_designs)의 템플릿 항목만 옮겨 담는다 — 지정은 하지 않는다(사람이 고른다)
INSERT INTO public.render_templates(name, design, note, created_by, updated_by) VALUES
 ('지금불륜 · 노랑 빨강 제목', '{"title_font":"JalnanGothic","title_color":"#FDE657","title_color2":"#FB513E","tts_color":"#FFE23C","work_caption":"풀 영상은 쿠팡플레이에서 시청하세요","work_caption_color":"#FFFFFF"}', 'jigeum_v2 에서 옮김', NULL, NULL),
 ('지금불륜 · 흰 빨강 제목', '{"title_font":"JalnanGothic","title_color":"#FFFFFF","title_color2":"#FF3C3C","tts_color":"#FFE23C","platform_text":"지금 쿠팡플레이에서 무료로 시청하세요","platform_image":"coupangplay_icon"}', 'jigeum 에서 옮김', NULL, NULL),
 ('로또 · 흰 노랑 제목', '{"title_font":"JalnanGothic","title_color":"#FFFFFF","title_color2":"#FBC001","tts_color":"#FFE23C","platform_image":"tving_logo"}', 'lotto_tving_v2 에서 옮김', NULL, NULL),
 ('로또 · 흰 빨강 제목', '{"title_font":"JalnanGothic","title_color":"#FFFFFF","title_color2":"#FF3C3C","tts_color":"#FFE23C","platform_text":"티빙"}', 'lotto_tving 에서 옮김', NULL, NULL),
 ('가왕쇼', '{"title_font":"JalnanGothic","title_color":"#FFFFFF","title_color2":"#FF3B30","subtitle_font":"JalnanGothic","subtitle_color":"#FFFFFF","tts_color":"#F783AC","work_caption":"티빙에서 풀버전 시청 및 투표 가능!","work_caption_color":"#FFFFFF","platform_image":"tving_logo"}', 'gawangsho 에서 옮김', NULL, NULL);

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0133','claude (렌더 템플릿)');
