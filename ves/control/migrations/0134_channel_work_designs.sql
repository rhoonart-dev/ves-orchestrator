-- 0134 채널 × 작품 영상 모양(2026-10-02) — 템플릿을 이름 붙여 따로 관리하지 않고, 채널 템플릿 화면에서 채널마다 작품 탭을 골라 값을 바로 정한다.
-- 순서: 이 채널 × 작품 값(channel_work_designs, 작품 기본 위에 칸 단위로) → 작품 기본(work_cards.render_design, 화면의 '모든 채널') → 0133 이름 템플릿 지정 → 엔진 기본.
-- 값의 어휘와 검사는 0133 _render_template_design 그대로. 0133 이름 템플릿(지금 쓰던 엔진 템플릿 5개)은 화면의 '불러오기' 재료로 남긴다.

CREATE TABLE public.channel_work_designs (
 token_slug text NOT NULL, work_title text NOT NULL,
 design jsonb NOT NULL CHECK (jsonb_typeof(design) = 'object'),
 updated_by uuid DEFAULT auth.uid(), updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (token_slug, work_title)
);
COMMENT ON TABLE public.channel_work_designs IS '이 채널에서 이 작품을 만들 때의 영상 모양(제목 · 자막 · 내레이션 폰트와 색 · 로고 아래 문구 · 권리사)';
ALTER TABLE public.work_cards ADD COLUMN render_design jsonb CHECK (render_design IS NULL OR jsonb_typeof(render_design) = 'object');
COMMENT ON COLUMN public.work_cards.render_design IS '작품 기본 영상 모양(모든 채널) — 채널 × 작품 값이 없을 때';

ALTER TABLE public.channel_work_designs ENABLE ROW LEVEL SECURITY;
CREATE POLICY channel_work_designs_read ON public.channel_work_designs FOR SELECT TO authenticated USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.channel_work_designs TO authenticated;

-- 이 채널 × 작품 값 저장(p_design NULL = 지우고 작품 기본 따르기)
CREATE OR REPLACE FUNCTION public.set_channel_work_design(p_slug text, p_work text, p_design jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v jsonb;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN RAISE EXCEPTION '없는 채널이에요: %', p_slug; END IF;
  IF p_design IS NULL THEN
    DELETE FROM public.channel_work_designs WHERE token_slug = p_slug AND work_title = p_work;
  ELSE
    v := public._render_template_design(p_design);
    INSERT INTO public.channel_work_designs(token_slug, work_title, design) VALUES (p_slug, p_work, v)
    ON CONFLICT (token_slug, work_title) DO UPDATE SET design = EXCLUDED.design, updated_by = auth.uid(), updated_at = now();
  END IF;
  PERFORM public._audit('set_channel_work_design', 'channel_work_designs', p_slug || ':' || p_work, jsonb_build_object('design', v));
  RETURN v;
END $$;

-- 작품 기본(모든 채널) 저장(p_design NULL = 지우기)
CREATE OR REPLACE FUNCTION public.set_work_design(p_work text, p_design jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v jsonb;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  v := CASE WHEN p_design IS NULL THEN NULL ELSE public._render_template_design(p_design) END;
  UPDATE public.work_cards SET render_design = v, updated_at = now() WHERE work_title = p_work;
  IF NOT FOUND THEN RAISE EXCEPTION '작품 카드가 없어요: %', p_work; END IF;
  PERFORM public._audit('set_work_design', 'work_cards', p_work, jsonb_build_object('design', v));
  RETURN v;
END $$;

-- 맥미니가 작업을 시작할 때 읽는다 — 이 채널 × 작품 → 작품 기본 → 0133 이름 템플릿 지정
CREATE OR REPLACE FUNCTION public.render_template_for(p_slug text, p_work text)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT coalesce(
    -- 채널 값은 작품 기본 위에 칸 단위로 얹는다(비워 둔 칸은 작품 기본을 따른다)
    (SELECT jsonb_build_object('name', '채널 × 작품', 'design', coalesce(w.render_design, '{}'::jsonb) || d.design, 'from', 'channel_work')
       FROM public.channel_work_designs d LEFT JOIN public.work_cards w ON w.work_title = d.work_title
      WHERE d.token_slug = p_slug AND d.work_title = p_work AND d.design <> '{}'::jsonb),
    (SELECT jsonb_build_object('name', '작품 기본', 'design', w.render_design, 'from', 'work')
       FROM public.work_cards w WHERE w.work_title = p_work AND w.render_design IS NOT NULL AND w.render_design <> '{}'::jsonb),
    (SELECT jsonb_build_object('id', t.id, 'name', t.name, 'design', t.design,
                               'from', CASE WHEN c.template_id IS NOT NULL THEN 'channel' ELSE 'work_template' END)
       FROM public.render_templates t
       LEFT JOIN public.channel_work_templates c ON c.token_slug = p_slug AND c.work_title = p_work
      WHERE t.retired_at IS NULL
        AND t.id = coalesce(c.template_id, (SELECT render_template_id FROM public.work_cards WHERE work_title = p_work))
      LIMIT 1))
$$;

REVOKE ALL ON FUNCTION public.set_channel_work_design(text, text, jsonb) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_channel_work_design(text, text, jsonb) TO authenticated;
REVOKE ALL ON FUNCTION public.set_work_design(text, jsonb) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_work_design(text, jsonb) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0134','claude (채널 × 작품 영상 모양)');
