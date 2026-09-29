-- 0112 — 작품 로고 여러 개 + 채널별로 고르기 (2026-09-29)
-- 같은 작품을 여러 채널이 쓸 때 채널마다 다른 로고(흰색·컬러·가로형…)를 쓰고 싶다.
-- work_asset_versions(0106)는 그대로 '불변 버전'이고, 이제 (작품, 용도, 이름) 마다 가장 최근 버전이 그 로고의 현재 파일이다.
-- work_asset_variants: 이름 붙은 로고 목록 — 작품·용도마다 기본 하나, 뺀 것은 retired_at(파일·기록은 남긴다).
-- channel_work_assets: 채널이 그 작품에서 쓸 로고 이름. 없으면 기본.
-- 영상 생성(tikitaka_generate)은 work_asset_for(채널, 작품, 용도)로 고른다 — 쓰기는 워크스페이스 서버(service_role)와 아래 RPC 만.

ALTER TABLE public.work_asset_versions ADD COLUMN IF NOT EXISTS label text NOT NULL DEFAULT '기본'
  CHECK (length(btrim(label)) BETWEEN 1 AND 30);
CREATE INDEX IF NOT EXISTS work_asset_versions_label ON public.work_asset_versions(work_title, role, label, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS public.work_asset_variants (
 work_title text NOT NULL,
 role text NOT NULL CHECK (role IN ('work_logo','platform_logo')),
 label text NOT NULL CHECK (length(btrim(label)) BETWEEN 1 AND 30),
 is_default boolean NOT NULL DEFAULT false,
 retired_at timestamptz,
 created_by uuid REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (work_title, role, label),
 CHECK (NOT (is_default AND retired_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS work_asset_variants_one_default
  ON public.work_asset_variants(work_title, role) WHERE is_default;
ALTER TABLE public.work_asset_variants ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.work_asset_variants FROM anon, authenticated;
GRANT SELECT ON public.work_asset_variants TO authenticated;
GRANT ALL ON public.work_asset_variants TO service_role;
DROP POLICY IF EXISTS work_asset_variants_read ON public.work_asset_variants;
CREATE POLICY work_asset_variants_read ON public.work_asset_variants FOR SELECT TO authenticated
  USING (public.has_role((SELECT auth.uid()), 'viewer'));

-- 이미 올라가 있던 로고는 '기본' 한 개로
INSERT INTO public.work_asset_variants(work_title, role, label, is_default, created_at)
SELECT DISTINCT ON (work_title, role) work_title, role, '기본', true, min(created_at) OVER (PARTITION BY work_title, role)
  FROM public.work_asset_versions WHERE role IN ('work_logo','platform_logo')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.channel_work_assets (
 token_slug text NOT NULL,
 work_title text NOT NULL,
 role text NOT NULL CHECK (role IN ('work_logo','platform_logo')),
 label text NOT NULL,
 updated_by uuid REFERENCES auth.users(id),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (token_slug, work_title, role)
);
ALTER TABLE public.channel_work_assets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.channel_work_assets FROM anon, authenticated;
GRANT SELECT ON public.channel_work_assets TO authenticated;
GRANT ALL ON public.channel_work_assets TO service_role;
DROP POLICY IF EXISTS channel_work_assets_read ON public.channel_work_assets;
CREATE POLICY channel_work_assets_read ON public.channel_work_assets FOR SELECT TO authenticated
  USING (public.has_role((SELECT auth.uid()), 'viewer'));

-- 채널이 그 작품에서 쓸 로고 고르기 — p_label 이 NULL 이면 기본으로 돌린다(선택 행 삭제)
CREATE OR REPLACE FUNCTION public.set_channel_work_asset(p_slug text, p_work text, p_role text, p_label text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF p_role NOT IN ('work_logo','platform_logo') THEN RAISE EXCEPTION '로고 용도가 이상해요: %', p_role; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN RAISE EXCEPTION '없는 채널이에요: %', p_slug; END IF;
  IF p_label IS NULL THEN
    DELETE FROM public.channel_work_assets WHERE token_slug = p_slug AND work_title = p_work AND role = p_role;
    RETURN jsonb_build_object('label', NULL);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM public.work_asset_variants
                  WHERE work_title = p_work AND role = p_role AND label = p_label AND retired_at IS NULL) THEN
    RAISE EXCEPTION '이 작품에 없는 로고예요: %', p_label;
  END IF;
  INSERT INTO public.channel_work_assets(token_slug, work_title, role, label, updated_by, updated_at)
  VALUES (p_slug, p_work, p_role, p_label, auth.uid(), now())
  ON CONFLICT (token_slug, work_title, role) DO UPDATE SET label = EXCLUDED.label, updated_by = EXCLUDED.updated_by, updated_at = now();
  RETURN jsonb_build_object('label', p_label);
END $$;
REVOKE ALL ON FUNCTION public.set_channel_work_asset(text, text, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_channel_work_asset(text, text, text, text) TO authenticated;

-- 영상 생성이 쓸 로고 한 장: 채널이 고른 것(뺀 로고면 무시) → 기본 → 그 이름의 가장 최근 버전
CREATE OR REPLACE FUNCTION public.work_asset_for(p_slug text, p_work text, p_role text)
RETURNS SETOF public.work_asset_versions LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  WITH pick AS (
    SELECT coalesce(
      (SELECT c.label FROM public.channel_work_assets c
         JOIN public.work_asset_variants v ON v.work_title = c.work_title AND v.role = c.role AND v.label = c.label AND v.retired_at IS NULL
        WHERE c.token_slug = p_slug AND c.work_title = p_work AND c.role = p_role),
      (SELECT v.label FROM public.work_asset_variants v
        WHERE v.work_title = p_work AND v.role = p_role AND v.is_default AND v.retired_at IS NULL)) AS label)
  SELECT w.* FROM public.work_asset_versions w, pick
   WHERE w.work_title = p_work AND w.role = p_role AND w.label = pick.label
   ORDER BY w.created_at DESC, w.id DESC LIMIT 1
$$;
REVOKE ALL ON FUNCTION public.work_asset_for(text, text, text) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.work_asset_for(text, text, text) TO service_role;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0112','claude (작품 로고 여러 개 + 채널별 고르기)');
