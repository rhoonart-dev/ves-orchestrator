-- 0116 — 작품 관리를 웹에서 (2026-09-30)
-- 워크스페이스 작품 관리는 레이블리 작품 DB(licensed_video)와 로고 저장(서비스 키)을 작업 컴퓨터의 로컬 서버로 해 왔다.
-- 웹 주소(기존 대시보드 /v2/)에서도 되게:
--   ① laeebly_works — 레이블리 작품 정보의 읽기 사본. 스케줄러 노드가 10분마다 맞춘다(laeebly_sync, channels_mirror 와 같은 방식).
--      레이블리 접속 정보를 브라우저나 서버 함수 비밀 값에 둘 필요가 없다.
--   ② 로고 올리기: 브라우저가 ves-work-assets 의 최종 자리(works/<id>/<sha>.<ext>)에 바로 올리고 register_work_asset 로 적는다.
--   ③ 로고 이름·기본·빼기·되돌리기(work_logo_variant) · 플랫폼 로고 출처(set_platform_logo_source) — 로컬 서버 work_assets_api 와 같은 규칙.

CREATE TABLE IF NOT EXISTS public.laeebly_works (
 id text PRIMARY KEY,
 title text NOT NULL,
 video_type text,
 thumbnail text,
 guide text,
 identification_code text,
 required_hashtags_title text,
 required_hashtags_description text,
 required_hashtags_notice text,
 copyrights_holder_name text,
 geo_block_required boolean,
 geo_block_regions text[],
 geo_block_mode text,
 company text,
 download_link text,
 synced_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS laeebly_works_title ON public.laeebly_works (title);
ALTER TABLE public.laeebly_works ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.laeebly_works FROM anon, authenticated;
GRANT SELECT ON public.laeebly_works TO authenticated;
GRANT ALL ON public.laeebly_works TO service_role;
DROP POLICY IF EXISTS laeebly_works_read ON public.laeebly_works;
CREATE POLICY laeebly_works_read ON public.laeebly_works FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));

-- 작품 한 건(같은 제목이 여럿이면 에셋 주인을 짐작하지 않는다 — work_assets_api.work_record 와 같은 규칙)
CREATE OR REPLACE FUNCTION public._laeebly_work(p_work_id text) RETURNS public.laeebly_works
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
DECLARE w public.laeebly_works;
BEGIN
  SELECT * INTO w FROM public.laeebly_works WHERE id = p_work_id;
  IF NOT FOUND THEN RAISE EXCEPTION '작품을 찾지 못했어요'; END IF;
  IF (SELECT count(*) FROM public.laeebly_works WHERE title = w.title) <> 1 THEN
    RAISE EXCEPTION '같은 제목의 작품이 여러 개예요. 작품 연결을 먼저 확인해 주세요';
  END IF;
  RETURN w;
END $$;
REVOKE ALL ON FUNCTION public._laeebly_work(text) FROM public, anon, authenticated;

-- 로고를 둘 열쇠: 작품 제목, 또는 플랫폼 로고를 권리사에 둘 때 권리사 열쇠(0115). (열쇠, 버전 기록의 work_id)
CREATE OR REPLACE FUNCTION public._asset_key(p_work_id text, p_role text, p_target text, OUT key text, OUT owner text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
DECLARE w public.laeebly_works := public._laeebly_work(p_work_id); v_holder text;
BEGIN
  IF p_role NOT IN ('work_logo','platform_logo') THEN RAISE EXCEPTION '로고 용도를 확인해 주세요'; END IF;
  IF coalesce(p_target, 'work') <> 'holder' THEN key := w.title; owner := w.id; RETURN; END IF;
  IF p_role <> 'platform_logo' THEN RAISE EXCEPTION '권리사에는 플랫폼 로고만 넣을 수 있어요'; END IF;
  SELECT holder INTO v_holder FROM public.work_platform_logo_source WHERE work_title = w.title AND mode = 'other';
  v_holder := nullif(btrim(coalesce(v_holder, w.company, '')), '');
  IF v_holder IS NULL THEN RAISE EXCEPTION '이 작품의 권리사를 몰라요. 이 작품에만 넣어 주세요'; END IF;
  key := public.holder_asset_key(v_holder); owner := 'holder:' || v_holder;
END $$;
REVOKE ALL ON FUNCTION public._asset_key(text, text, text) FROM public, anon, authenticated;

-- 올린 파일 적기 — 파일은 브라우저가 이미 저장소 최종 자리에 올렸다. 자리 모양·크기·형식을 저장소 기록과 맞춰 본다
CREATE OR REPLACE FUNCTION public.register_work_asset(p_work_id text, p_role text, p_target text, p_object_key text,
  p_sha256 text, p_filename text, p_width int, p_height int, p_render_width int, p_render_height int,
  p_label text DEFAULT NULL, p_default boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE k record; o record; v_id uuid; v_mime text; v_bytes int; v_label text; v_have int; v_first boolean;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  SELECT * INTO k FROM public._asset_key(p_work_id, p_role, p_target);
  IF p_object_key !~ '^works/[0-9a-f-]{36}/[0-9a-f]{64}\.(png|jpg|webp)$' OR split_part(split_part(p_object_key, '/', 3), '.', 1) <> p_sha256 THEN
    RAISE EXCEPTION '파일 자리가 이상해요';
  END IF;
  SELECT metadata INTO o FROM storage.objects WHERE bucket_id = 'ves-work-assets' AND name = p_object_key;
  IF NOT FOUND THEN RAISE EXCEPTION '올린 파일을 찾지 못했어요. 다시 올려 주세요'; END IF;
  v_mime := o.metadata->>'mimetype'; v_bytes := (o.metadata->>'size')::int;
  IF v_mime NOT IN ('image/png','image/jpeg','image/webp') THEN RAISE EXCEPTION 'PNG·JPG·WebP 이미지만 올릴 수 있어요'; END IF;
  IF v_bytes IS NULL OR v_bytes < 1 OR v_bytes > 6291456 THEN RAISE EXCEPTION '6MB 이하 파일을 올려 주세요'; END IF;
  IF p_width IS NULL OR p_height IS NULL OR p_width < 1 OR p_height < 1 OR p_width::bigint * p_height > 16000000 THEN
    RAISE EXCEPTION '최대 1,600만 화소 이미지를 올려 주세요';
  END IF;
  IF p_render_width NOT BETWEEN 16 AND 1080 OR p_render_height NOT BETWEEN 16 AND 1920 THEN RAISE EXCEPTION '표시 크기를 확인해 주세요'; END IF;
  v_id := split_part(p_object_key, '/', 2)::uuid;
  v_label := nullif(regexp_replace(btrim(coalesce(p_label, '')), '\s+', ' ', 'g'), '');
  SELECT count(*) INTO v_have FROM public.work_asset_variants WHERE work_title = k.key AND role = p_role AND retired_at IS NULL;
  v_label := coalesce(v_label, CASE WHEN v_have = 0 THEN '기본' END);
  IF v_label IS NULL THEN RAISE EXCEPTION '로고 이름을 적어 주세요'; END IF;
  IF length(v_label) > 30 THEN RAISE EXCEPTION '로고 이름은 1~30자로 적어 주세요'; END IF;
  v_first := NOT EXISTS (SELECT 1 FROM public.work_asset_variants WHERE work_title = k.key AND role = p_role AND is_default AND retired_at IS NULL);
  IF p_default OR v_first THEN
    UPDATE public.work_asset_variants SET is_default = false, updated_at = now() WHERE work_title = k.key AND role = p_role AND is_default;
  END IF;
  -- 이름이 이미 있으면 그 로고의 파일 교체(새 버전), 없으면 새 로고
  INSERT INTO public.work_asset_variants (work_title, role, label, is_default, created_by)
  VALUES (k.key, p_role, v_label, p_default OR v_first, auth.uid())
  ON CONFLICT (work_title, role, label) DO UPDATE SET retired_at = NULL,
    is_default = public.work_asset_variants.is_default OR EXCLUDED.is_default, updated_at = now();
  INSERT INTO public.work_asset_versions (id, work_id, work_title, role, object_key, sha256, filename, mime, bytes,
                                          width, height, render_width, render_height, created_by, label)
  VALUES (v_id, k.owner, k.key, p_role, p_object_key, p_sha256, left(coalesce(nullif(p_filename, ''), 'logo'), 240), v_mime, v_bytes,
          p_width, p_height, p_render_width, p_render_height, auth.uid(), v_label);
  INSERT INTO public.dashboard_actions (actor, action, target_kind, target_id, payload)
  VALUES (auth.uid(), 'workspace_upload_asset', 'work_asset', v_id::text,
          jsonb_build_object('work_id', p_work_id, 'role', p_role, 'sha256', p_sha256, 'target', coalesce(p_target, 'work'), 'key', k.key));
  RETURN jsonb_build_object('id', v_id, 'label', v_label);
END $$;
REVOKE ALL ON FUNCTION public.register_work_asset(text, text, text, text, text, text, int, int, int, int, text, boolean) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.register_work_asset(text, text, text, text, text, text, int, int, int, int, text, boolean) TO authenticated;

-- 로고 기본 · 이름 · 빼기 · 되돌리기(뺄 때 돌려준 채널 선택까지)
CREATE OR REPLACE FUNCTION public.work_logo_variant(p_work_id text, p_role text, p_target text, p_label text, p_action text,
  p_new_label text DEFAULT NULL, p_picks text[] DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE k record; v public.work_asset_variants; v_new text; v_picks text[];
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  SELECT * INTO k FROM public._asset_key(p_work_id, p_role, p_target);
  IF p_action = 'restore' THEN
    UPDATE public.work_asset_variants SET retired_at = NULL, updated_at = now()
     WHERE work_title = k.key AND role = p_role AND label = p_label AND retired_at IS NOT NULL RETURNING * INTO v;
    IF NOT FOUND THEN RAISE EXCEPTION '되돌릴 로고가 없어요. 새로고침해 주세요'; END IF;
    INSERT INTO public.channel_work_assets (token_slug, work_title, role, label, updated_by)
    SELECT s, k.key, p_role, p_label, auth.uid() FROM unnest(coalesce(p_picks, '{}')) s ON CONFLICT DO NOTHING;
  ELSE
    SELECT * INTO v FROM public.work_asset_variants WHERE work_title = k.key AND role = p_role AND label = p_label AND retired_at IS NULL FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 로고예요. 새로고침해 주세요'; END IF;
    IF p_action = 'default' THEN
      UPDATE public.work_asset_variants SET is_default = false, updated_at = now() WHERE work_title = k.key AND role = p_role AND is_default;
      UPDATE public.work_asset_variants SET is_default = true, updated_at = now() WHERE work_title = k.key AND role = p_role AND label = p_label;
    ELSIF p_action = 'rename' THEN
      v_new := regexp_replace(btrim(coalesce(p_new_label, '')), '\s+', ' ', 'g');
      IF length(v_new) NOT BETWEEN 1 AND 30 THEN RAISE EXCEPTION '로고 이름은 1~30자로 적어 주세요'; END IF;
      IF v_new <> p_label THEN
        IF EXISTS (SELECT 1 FROM public.work_asset_variants WHERE work_title = k.key AND role = p_role AND label = v_new) THEN
          RAISE EXCEPTION '같은 이름의 로고가 이미 있어요';
        END IF;
        UPDATE public.work_asset_variants SET label = v_new WHERE work_title = k.key AND role = p_role AND label = p_label;
        UPDATE public.work_asset_versions SET label = v_new WHERE work_title = k.key AND role = p_role AND label = p_label;
        UPDATE public.channel_work_assets SET label = v_new WHERE work_title = k.key AND role = p_role AND label = p_label;
      END IF;
    ELSIF p_action = 'retire' THEN
      IF v.is_default THEN RAISE EXCEPTION '기본 로고는 뺄 수 없어요. 다른 로고를 먼저 기본으로 정해 주세요'; END IF;
      UPDATE public.work_asset_variants SET retired_at = now(), updated_at = now() WHERE work_title = k.key AND role = p_role AND label = p_label;
      WITH gone AS (DELETE FROM public.channel_work_assets WHERE work_title = k.key AND role = p_role AND label = p_label RETURNING token_slug)
      SELECT array_agg(token_slug) INTO v_picks FROM gone;
    ELSE RAISE EXCEPTION '할 일을 확인해 주세요';
    END IF;
  END IF;
  INSERT INTO public.dashboard_actions (actor, action, target_kind, target_id, payload)
  VALUES (auth.uid(), 'workspace_logo_variant', 'work_asset', p_work_id,
          jsonb_build_object('role', p_role, 'label', p_label, 'action', p_action, 'new_label', p_new_label, 'key', k.key));
  RETURN jsonb_build_object('ok', true, 'picks', to_jsonb(coalesce(v_picks, '{}')));
END $$;
REVOKE ALL ON FUNCTION public.work_logo_variant(text, text, text, text, text, text, text[]) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.work_logo_variant(text, text, text, text, text, text, text[]) TO authenticated;

-- 플랫폼 로고 출처(0115) — 레이블리 정보는 바꾸지 않는다
CREATE OR REPLACE FUNCTION public.set_platform_logo_source(p_work_id text, p_mode text, p_holder text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE w public.laeebly_works; v_holder text := nullif(regexp_replace(btrim(coalesce(p_holder, '')), '\s+', ' ', 'g'), '');
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF p_mode NOT IN ('holder','other','work','none') THEN RAISE EXCEPTION '플랫폼 로고를 어디서 쓸지 골라 주세요'; END IF;
  w := public._laeebly_work(p_work_id);
  IF p_mode = 'other' THEN
    IF v_holder IS NULL OR NOT EXISTS (SELECT 1 FROM public.laeebly_works WHERE btrim(company) = v_holder) THEN
      RAISE EXCEPTION '레이블리에 있는 권리사를 골라 주세요';
    END IF;
  ELSE v_holder := NULL;
  END IF;
  IF p_mode = 'holder' THEN DELETE FROM public.work_platform_logo_source WHERE work_title = w.title;
  ELSE
    INSERT INTO public.work_platform_logo_source (work_title, mode, holder, updated_by) VALUES (w.title, p_mode, v_holder, auth.uid())
    ON CONFLICT (work_title) DO UPDATE SET mode = EXCLUDED.mode, holder = EXCLUDED.holder, updated_by = EXCLUDED.updated_by, updated_at = now();
  END IF;
  INSERT INTO public.dashboard_actions (actor, action, target_kind, target_id, payload)
  VALUES (auth.uid(), 'workspace_platform_logo_source', 'work_asset', p_work_id, jsonb_build_object('mode', p_mode, 'holder', v_holder));
  RETURN jsonb_build_object('ok', true);
END $$;
REVOKE ALL ON FUNCTION public.set_platform_logo_source(text, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_platform_logo_source(text, text, text) TO authenticated;

-- 저장소: 로고 미리보기(서명 URL)는 보기 권한부터, 올리기는 운영자만 · 최종 자리 모양일 때만
DROP POLICY IF EXISTS ves_work_assets_read ON storage.objects;
CREATE POLICY ves_work_assets_read ON storage.objects FOR SELECT TO authenticated
 USING (bucket_id = 'ves-work-assets' AND public.has_role((SELECT auth.uid()), 'viewer'));
DROP POLICY IF EXISTS ves_work_assets_upload ON storage.objects;
CREATE POLICY ves_work_assets_upload ON storage.objects FOR INSERT TO authenticated
 WITH CHECK (bucket_id = 'ves-work-assets' AND public.has_role((SELECT auth.uid()), 'operator')
             AND name ~ '^works/[0-9a-f-]{36}/[0-9a-f]{64}\.(png|jpg|webp)$');

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0116','claude (작품 관리를 웹에서: 레이블리 작품 사본 · 로고 올리기·바꾸기 RPC · 저장소 정책)');
