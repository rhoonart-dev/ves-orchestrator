-- 0128 채널 + 작품 설명란 고정(2026-10-02) — 검수 카드에서 고친 설명란을 '이 채널 · 이 작품' 기본값으로 저장한다.
-- 저장해 두면 다음 영상부터 설명란이 이 문구로 채워진다(검수 카드에서 그때그때 고칠 수 있다). 비우면 예전 자동 기본값으로.
CREATE TABLE public.channel_work_descriptions (
 token_slug text NOT NULL,
 work_title text NOT NULL,
 description text NOT NULL CHECK (length(description) BETWEEN 1 AND 5000),
 updated_by uuid DEFAULT auth.uid(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (token_slug, work_title)
);
COMMENT ON TABLE public.channel_work_descriptions IS '채널 + 작품 유튜브 설명란 고정 문구 — 검수 카드 설명란 기본값';
ALTER TABLE public.channel_work_descriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY channel_work_descriptions_read ON public.channel_work_descriptions FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.channel_work_descriptions TO authenticated;

CREATE OR REPLACE FUNCTION public.set_channel_work_description(p_slug text, p_work text, p_description text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '검수자 권한이 필요해요'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN RAISE EXCEPTION '없는 채널이에요: %', p_slug; END IF;
  IF coalesce(btrim(p_description), '') = '' THEN
    DELETE FROM public.channel_work_descriptions WHERE token_slug = p_slug AND work_title = p_work;
  ELSE
    IF length(p_description) > 5000 THEN RAISE EXCEPTION '설명은 5000자까지예요'; END IF;
    INSERT INTO public.channel_work_descriptions(token_slug, work_title, description, updated_by, updated_at)
    VALUES (p_slug, p_work, p_description, auth.uid(), now())
    ON CONFLICT (token_slug, work_title) DO UPDATE SET description = EXCLUDED.description, updated_by = auth.uid(), updated_at = now();
  END IF;
  PERFORM public._audit('set_channel_work_description', 'channel_work_descriptions', p_slug || ':' || p_work,
          jsonb_build_object('length', length(coalesce(p_description, ''))));
END $$;
REVOKE ALL ON FUNCTION public.set_channel_work_description(text, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_channel_work_description(text, text, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0128','claude (채널 + 작품 설명란 고정)');
