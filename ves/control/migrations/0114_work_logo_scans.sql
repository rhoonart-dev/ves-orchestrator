-- 0114 — 드라이브에서 작품 로고 가져오기 (2026-09-29)
-- 작품 관리에서 '드라이브에서 가져오기' → 맥미니가 rclone 으로 폴더를 훑어 그림만 모은다(scan_work_logos 잡).
-- 폴더는 레이블리 licensed_video.download_link(드라이브 소스 가져오기와 같은 링크), 없거나 폴더가 아니면 사람이 넣은 링크.
-- 후보 원본은 처음부터 ves-work-assets 의 최종 자리(works/<id>/<sha>.<ext>)에 올리고, 미리보기는 ves-outputs(logo_scans/…)에.
-- 사람이 고르면 import_work_logos 가 그 자리를 그대로 로고로 적는다 — 브라우저·로컬 서버가 파일을 다시 옮기지 않는다.
-- 드라이브·레이블리 접근은 맥미니에만 있어 웹사이트에서도 그대로 돈다.

CREATE TABLE IF NOT EXISTS public.work_logo_scans (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 work_id text NOT NULL,                          -- 레이블리 licensed_video.id
 work_title text,                                -- 맥미니가 레이블리에서 확인한 제목(가져오기는 이 값으로)
 folder_url text,                                -- 사람이 넣은 링크. 비었으면 레이블리 링크
 source text NOT NULL DEFAULT 'laeebly' CHECK (source IN ('laeebly','manual')),
 used_url text,                                  -- 실제로 훑은 링크
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','done','need_folder','failed')),
 reason text,                                    -- need_folder·failed 일 때 사람이 읽는 한 줄
 total int,                                      -- 폴더에서 찾은 그림 수
 skipped int,                                    -- 이미 넣은 그림 수
 candidates jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{id,path,name,mime,ext,bytes,width,height,sha256,object_key,thumb_key,logoish,imported}]
 job_id uuid,
 node_id text,
 requested_by uuid REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,
 finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS work_logo_scans_work ON public.work_logo_scans (work_id, created_at DESC);
ALTER TABLE public.work_logo_scans ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.work_logo_scans FROM anon, authenticated;
GRANT SELECT ON public.work_logo_scans TO authenticated;
GRANT ALL ON public.work_logo_scans TO service_role;
DROP POLICY IF EXISTS work_logo_scans_read ON public.work_logo_scans;
CREATE POLICY work_logo_scans_read ON public.work_logo_scans FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'operator'));

-- 찾기 — 같은 작품을 찾는 중이면 그 줄을 돌려준다(두 번 눌러도 잡 하나)
CREATE OR REPLACE FUNCTION public.request_work_logo_scan(p_work_id text, p_folder text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_id uuid; v_job uuid; v_folder text := nullif(btrim(coalesce(p_folder, '')), '');
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '로고를 넣으려면 운영자 권한이 필요해요'; END IF;
  IF coalesce(btrim(p_work_id), '') = '' OR length(p_work_id) > 100 THEN RAISE EXCEPTION '작품 정보가 없어요'; END IF;
  IF v_folder IS NOT NULL AND v_folder !~ '^https://drive\.google\.com/[A-Za-z0-9_/?=&.%-]+$' THEN
    RAISE EXCEPTION '구글 드라이브 폴더 링크를 넣어 주세요';
  END IF;
  SELECT s.id INTO v_id FROM public.work_logo_scans s JOIN public.job_queue j ON j.id = s.job_id
   WHERE s.work_id = p_work_id AND s.status IN ('pending','running') AND s.folder_url IS NOT DISTINCT FROM v_folder
     AND s.created_at > now() - interval '30 minutes' AND j.status IN ('pending','running')   -- 잡이 먼저 죽은 줄은 다시 쓰지 않는다
   ORDER BY s.created_at DESC LIMIT 1;
  IF v_id IS NOT NULL THEN RETURN jsonb_build_object('scan_id', v_id, 'reused', true); END IF;
  INSERT INTO public.work_logo_scans (work_id, folder_url, source, requested_by)
  VALUES (p_work_id, v_folder, CASE WHEN v_folder IS NULL THEN 'laeebly' ELSE 'manual' END, auth.uid())
  RETURNING id INTO v_id;
  -- 레이블리 연결과 드라이브 인증이 둘 다 있는 노드(스케줄러 노드 = 드라이브 동기화 담당)
  INSERT INTO public.job_queue (kind, params, idempotency_key, required_caps, lease_ttl_sec, priority, max_attempts)
  VALUES ('scan_work_logos', jsonb_build_object('scan_id', v_id::text), 'logo-scan:' || v_id::text,
          ARRAY['network','scheduler'], 300, 250, 1)
  RETURNING id INTO v_job;
  UPDATE public.work_logo_scans SET job_id = v_job WHERE id = v_id;
  PERFORM public._audit('request_work_logo_scan', 'work_logo_scans', v_id::text,
          jsonb_build_object('work_id', p_work_id, 'folder', v_folder));
  RETURN jsonb_build_object('scan_id', v_id, 'reused', false);
END $$;
REVOKE ALL ON FUNCTION public.request_work_logo_scan(text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.request_work_logo_scan(text, text) TO authenticated;

-- 넣기 — 고른 후보를 이름 붙은 로고로(0112 규칙: 처음 로고는 기본, '기본으로'면 기본을 옮긴다).
-- p_items: [{id, label, default}] — 이미 있는 이름은 거절(그 로고의 파일을 몰래 바꾸지 않게. 파일 교체는 '교체'로)
CREATE OR REPLACE FUNCTION public.import_work_logos(p_scan uuid, p_items jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE s public.work_logo_scans%ROWTYPE; it jsonb; c jsonb; v_label text; v_def boolean; v_n int := 0;
        v_first boolean; v_labels text[] := '{}'; v_ids text[] := '{}'; w int; h int;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '로고를 넣으려면 운영자 권한이 필요해요'; END IF;
  SELECT * INTO s FROM public.work_logo_scans WHERE id = p_scan FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION '찾은 기록이 없어요'; END IF;
  IF s.status <> 'done' OR s.work_title IS NULL THEN RAISE EXCEPTION '아직 다 찾지 못했어요'; END IF;
  IF p_items IS NULL OR jsonb_typeof(p_items) <> 'array' OR jsonb_array_length(p_items) = 0 THEN RAISE EXCEPTION '넣을 로고를 골라 주세요'; END IF;
  IF jsonb_array_length(p_items) > 30 THEN RAISE EXCEPTION '한 번에 30개까지 넣을 수 있어요'; END IF;
  FOR it IN SELECT * FROM jsonb_array_elements(p_items) LOOP
    SELECT x INTO c FROM jsonb_array_elements(s.candidates) x WHERE x->>'id' = it->>'id';
    IF c IS NULL THEN RAISE EXCEPTION '목록에 없는 그림이에요'; END IF;
    IF coalesce((c->>'imported')::boolean, false) OR (it->>'id') = ANY(v_ids) THEN RAISE EXCEPTION '이미 넣은 그림이에요'; END IF;
    v_label := btrim(coalesce(it->>'label', ''));
    IF length(v_label) < 1 OR length(v_label) > 30 THEN RAISE EXCEPTION '로고 이름은 1~30자로 적어 주세요'; END IF;
    IF lower(v_label) = ANY(v_labels) OR EXISTS (SELECT 1 FROM public.work_asset_variants
         WHERE work_title = s.work_title AND role = 'work_logo' AND lower(label) = lower(v_label) AND retired_at IS NULL) THEN
      RAISE EXCEPTION '''%'' 이름의 로고가 이미 있어요. 다른 이름을 적어 주세요', v_label;
    END IF;
    v_labels := v_labels || lower(v_label); v_ids := v_ids || (it->>'id');
    v_def := coalesce((it->>'default')::boolean, false);
    v_first := NOT EXISTS (SELECT 1 FROM public.work_asset_variants
                            WHERE work_title = s.work_title AND role = 'work_logo' AND is_default AND retired_at IS NULL);
    IF v_def OR v_first THEN
      UPDATE public.work_asset_variants SET is_default = false, updated_at = now()
       WHERE work_title = s.work_title AND role = 'work_logo' AND is_default;
    END IF;
    INSERT INTO public.work_asset_variants (work_title, role, label, is_default, created_by)
    VALUES (s.work_title, 'work_logo', v_label, v_def OR v_first, auth.uid())
    ON CONFLICT (work_title, role, label) DO UPDATE SET retired_at = NULL, is_default = EXCLUDED.is_default, updated_at = now();
    -- 표시 크기: 올리기 화면 기본값(최대 가로 620 · 세로 300, 원본 비율 유지)과 같다. 작품 관리의 '교체'에서 고친다
    w := 620; h := 300;
    INSERT INTO public.work_asset_versions (id, work_id, work_title, role, object_key, sha256, filename, mime, bytes,
                                            width, height, render_width, render_height, created_by, label)
    VALUES ((c->>'id')::uuid, s.work_id, s.work_title, 'work_logo', c->>'object_key', c->>'sha256',
            left(coalesce(c->>'name', 'logo'), 240), c->>'mime', (c->>'bytes')::int,
            (c->>'width')::int, (c->>'height')::int, w, h, auth.uid(), v_label);
    v_n := v_n + 1;
  END LOOP;
  UPDATE public.work_logo_scans SET candidates = (
    SELECT jsonb_agg(CASE WHEN x->>'id' = ANY(v_ids) THEN x || '{"imported":true}'::jsonb ELSE x END ORDER BY o)
      FROM jsonb_array_elements(s.candidates) WITH ORDINALITY t(x, o))
   WHERE id = p_scan;
  INSERT INTO public.dashboard_actions (actor, action, target_kind, target_id, payload)
  VALUES (auth.uid(), 'workspace_import_drive_logos', 'work_logo_scan', p_scan::text,
          jsonb_build_object('work_title', s.work_title, 'ids', to_jsonb(v_ids), 'labels', to_jsonb(v_labels)));
  RETURN jsonb_build_object('imported', v_n);
END $$;
REVOKE ALL ON FUNCTION public.import_work_logos(uuid, jsonb) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.import_work_logos(uuid, jsonb) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0114','claude (드라이브에서 작품 로고 가져오기: 찾기 표 + 요청·넣기 RPC)');
