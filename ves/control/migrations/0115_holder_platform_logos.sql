-- 0115 — 플랫폼 로고를 권리사마다 (2026-09-30)
-- 권리사(레이블리 licensed_video.company, 예: 쿠팡플레이) 로고를 한 번 넣으면 같은 권리사 작품이 모두 같이 쓴다.
-- 저장은 0112 로고 표 그대로, 작품 제목 자리에 권리사 열쇠('권리사:<이름>')를 둔다 — 이름·기본·빼기·파일 버전 규칙을 그대로 쓴다.
-- 자동으로 묶인 권리사가 틀렸거나 쓰기 싫을 수 있어 작품마다 고른다(work_platform_logo_source):
--   holder(기본, 줄 없음) 레이블리 권리사 로고 · other 고른 권리사 로고 · work 이 작품에만 올린 로고 · none 안 씀.

CREATE OR REPLACE FUNCTION public.holder_asset_key(p_holder text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$ SELECT '권리사:' || btrim(p_holder) $$;

CREATE TABLE IF NOT EXISTS public.work_platform_logo_source (
 work_title text PRIMARY KEY CHECK (length(work_title) BETWEEN 1 AND 300),
 mode text NOT NULL CHECK (mode IN ('holder','other','work','none')),
 holder text CHECK (holder IS NULL OR length(btrim(holder)) BETWEEN 1 AND 100),
 updated_by uuid REFERENCES auth.users(id),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((mode = 'other') = (holder IS NOT NULL))
);
ALTER TABLE public.work_platform_logo_source ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.work_platform_logo_source FROM anon, authenticated;
GRANT SELECT ON public.work_platform_logo_source TO authenticated;
GRANT ALL ON public.work_platform_logo_source TO service_role;
DROP POLICY IF EXISTS work_platform_logo_source_read ON public.work_platform_logo_source;
CREATE POLICY work_platform_logo_source_read ON public.work_platform_logo_source FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'reviewer'));

-- 드라이브 찾기에 이 작품의 권리사를 같이 적는다(맥미니가 레이블리에서 읽음)
ALTER TABLE public.work_logo_scans ADD COLUMN IF NOT EXISTS holder text;

-- 넣기 — 그림마다 용도(role)와, 플랫폼 로고면 어디에(scope: holder 권리사 · work 이 작품만)
-- p_holder: 찾기 기록에 권리사가 없을 때(옛 맥미니 코드) 화면이 넘기는 권리사. 작품이 '다른 권리사'를 골랐으면 그쪽이 먼저.
DROP FUNCTION IF EXISTS public.import_work_logos(uuid, jsonb);
CREATE OR REPLACE FUNCTION public.import_work_logos(p_scan uuid, p_items jsonb, p_holder text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE s public.work_logo_scans%ROWTYPE; it jsonb; c jsonb; v_label text; v_def boolean; v_n int := 0;
        v_first boolean; v_seen text[] := '{}'; v_ids text[] := '{}'; v_role text; v_scope text;
        v_holder text; v_key text; v_work_id text;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '로고를 넣으려면 운영자 권한이 필요해요'; END IF;
  SELECT * INTO s FROM public.work_logo_scans WHERE id = p_scan FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION '찾은 기록이 없어요'; END IF;
  IF s.status <> 'done' OR s.work_title IS NULL THEN RAISE EXCEPTION '아직 다 찾지 못했어요'; END IF;
  IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN RAISE EXCEPTION '넣을 로고를 골라 주세요'; END IF;
  IF jsonb_array_length(p_items) > 30 THEN RAISE EXCEPTION '한 번에 30개까지 넣을 수 있어요'; END IF;
  SELECT holder INTO v_holder FROM public.work_platform_logo_source WHERE work_title = s.work_title AND mode = 'other';
  v_holder := nullif(btrim(coalesce(v_holder, s.holder, p_holder, '')), '');
  FOR it IN SELECT * FROM jsonb_array_elements(p_items) LOOP
    SELECT x INTO c FROM jsonb_array_elements(s.candidates) x WHERE x->>'id' = it->>'id';
    IF c IS NULL THEN RAISE EXCEPTION '목록에 없는 그림이에요'; END IF;
    IF coalesce((c->>'imported')::boolean, false) OR (it->>'id') = ANY(v_ids) THEN RAISE EXCEPTION '이미 넣은 그림이에요'; END IF;
    v_role := coalesce(it->>'role', 'work_logo');
    IF v_role NOT IN ('work_logo','platform_logo') THEN RAISE EXCEPTION '로고 용도를 확인해 주세요'; END IF;
    v_scope := CASE WHEN v_role = 'platform_logo' THEN coalesce(it->>'scope', 'holder') ELSE 'work' END;
    IF v_scope NOT IN ('holder','work') THEN RAISE EXCEPTION '로고를 넣을 곳을 확인해 주세요'; END IF;
    IF v_scope = 'holder' THEN
      IF v_holder IS NULL THEN RAISE EXCEPTION '이 작품의 권리사를 몰라요. ''이 작품에만 넣기''로 넣어 주세요'; END IF;
      v_key := public.holder_asset_key(v_holder); v_work_id := 'holder:' || v_holder;
    ELSE
      v_key := s.work_title; v_work_id := s.work_id;
    END IF;
    v_label := btrim(coalesce(it->>'label', ''));
    IF length(v_label) < 1 OR length(v_label) > 30 THEN RAISE EXCEPTION '로고 이름은 1~30자로 적어 주세요'; END IF;
    IF (v_key || '|' || v_role || '|' || lower(v_label)) = ANY(v_seen) OR EXISTS (SELECT 1 FROM public.work_asset_variants
         WHERE work_title = v_key AND role = v_role AND lower(label) = lower(v_label) AND retired_at IS NULL) THEN
      RAISE EXCEPTION '''%'' 이름의 로고가 이미 있어요. 다른 이름을 적어 주세요', v_label;
    END IF;
    v_seen := v_seen || (v_key || '|' || v_role || '|' || lower(v_label)); v_ids := v_ids || (it->>'id');
    v_def := coalesce((it->>'default')::boolean, false);
    v_first := NOT EXISTS (SELECT 1 FROM public.work_asset_variants
                            WHERE work_title = v_key AND role = v_role AND is_default AND retired_at IS NULL);
    IF v_def OR v_first THEN
      UPDATE public.work_asset_variants SET is_default = false, updated_at = now()
       WHERE work_title = v_key AND role = v_role AND is_default;
    END IF;
    INSERT INTO public.work_asset_variants (work_title, role, label, is_default, created_by)
    VALUES (v_key, v_role, v_label, v_def OR v_first, auth.uid())
    ON CONFLICT (work_title, role, label) DO UPDATE SET retired_at = NULL, is_default = EXCLUDED.is_default, updated_at = now();
    -- 표시 크기: 올리기 화면 기본값과 같다(작품 로고 620×300 · 플랫폼 로고 180×80). '교체'에서 고친다
    INSERT INTO public.work_asset_versions (id, work_id, work_title, role, object_key, sha256, filename, mime, bytes,
                                            width, height, render_width, render_height, created_by, label)
    VALUES ((c->>'id')::uuid, v_work_id, v_key, v_role, c->>'object_key', c->>'sha256',
            left(coalesce(c->>'name', 'logo'), 240), c->>'mime', (c->>'bytes')::int,
            (c->>'width')::int, (c->>'height')::int,
            CASE WHEN v_role = 'work_logo' THEN 620 ELSE 180 END, CASE WHEN v_role = 'work_logo' THEN 300 ELSE 80 END,
            auth.uid(), v_label);
    v_n := v_n + 1;
  END LOOP;
  UPDATE public.work_logo_scans SET candidates = (
    SELECT jsonb_agg(CASE WHEN x->>'id' = ANY(v_ids) THEN x || '{"imported":true}'::jsonb ELSE x END ORDER BY o)
      FROM jsonb_array_elements(s.candidates) WITH ORDINALITY t(x, o))
   WHERE id = p_scan;
  INSERT INTO public.dashboard_actions (actor, action, target_kind, target_id, payload)
  VALUES (auth.uid(), 'workspace_import_drive_logos', 'work_logo_scan', p_scan::text,
          jsonb_build_object('work_title', s.work_title, 'holder', v_holder, 'ids', to_jsonb(v_ids), 'items', p_items));
  RETURN jsonb_build_object('imported', v_n);
END $$;
REVOKE ALL ON FUNCTION public.import_work_logos(uuid, jsonb, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.import_work_logos(uuid, jsonb, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0115','claude (플랫폼 로고를 권리사마다: 권리사 열쇠 · 작품별 선택 · 넣기에 용도)');
