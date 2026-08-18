-- =====================================================================
-- 0048_editor_scan_fps.sql — 편집실 scan 프레임 상향의 캐시 판정 (2026-08-19, F-206)
--
-- 편집실 원본 미리보기(scan)가 끊기는 원인은 인코딩이 아니라 소스였다 — scrub 소스가
-- 4fps 분석 프록시(`*_480.mp4` 우선)라 scan 이 4fps 를 물려받는다. 어댑터가 scan 소스를
-- **마스터 우선 + fps=24** 로 바꿨으므로(editor_assets.py: pick_scan_source·SCAN_FPS),
-- 구 코드가 만든 4fps scan 은 한 번 다시 떠야 한다. 그 판정을 여기 넣는다.
--
-- 왜 fps>=24 조건이 아니라 **세대 마커(scan_gen)** 인가:
--   마스터가 그 노드에서 GC 된 run 은 재생성해도 프록시 폴백(4fps)이다. fps 를 조건으로
--   걸면 그런 run 은 열 때마다 재생성 잡이 돌고도 조건을 영영 못 채운다 — 0045 머리말의
--   '상한 초과 스캔 418MB' 무한 재생성과 같은 패턴. 세대 마커는 "신 코드 산출물인가"만
--   물으므로 구 scan 은 한 번 재생성되고, 폴백 결과도 캐시로 인정된다(라벨이 fps 를 알린다).
--
-- ⚠ 적용 순서: **노드 어댑터 배포가 먼저다.** 이 파일을 먼저 적용하면 구 어댑터 노드가
-- scan_gen 없는 재료를 다시 써서(coalesce→1) 노드 자동 업데이트가 돌 때까지 열 때마다
-- 재생성된다 — 유한하지만 무거운 낭비. version_watch 로 전 노드 갱신을 확인한 뒤 적용.
--
-- 본문은 0045 판 전문 + 캐시 조건 한 줄(scan_gen) 델타. 재료 구성이 늘면 이 조건에
-- 한 줄씩 붙인다는 0045 규율 그대로다.
-- 짝: ves/adapters/editor_assets.py(pick_scan_source·SCAN_GEN=2) · 대시보드 fps 라벨.
-- =====================================================================

CREATE OR REPLACE FUNCTION public.request_editor_assets(p_review_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_ex record; v_job uuid;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;

    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload INTO v_rq
      FROM public.review_queue rq WHERE rq.id = p_review_id;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 검수 항목입니다'; END IF;
    IF v_rq.work_order_id IS NULL THEN
        RAISE EXCEPTION '작업지시 없는 카드는 편집실 대상이 아닙니다(잔망루피 등)';
    END IF;

    SELECT j.node_id, j.result->>'run_id' AS run_id, j.result->>'run_dir' AS run_dir
      INTO v_gen
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY coalesce(j.finished_at, j.updated_at) DESC LIMIT 1;
    IF v_gen.run_id IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/node) 없음 — 편집실을 열 수 없습니다';
    END IF;

    -- 캐시 재사용 조건(0045 + 0048): ready · 만료 전 · 편집용 영상까지 갖춤 ·
    -- **신 세대 scan**(0048 — 구 4fps scan 은 한 번 다시 뜬다. 머리말 참고).
    SELECT status, expires_at,
           (sprites->'assets'->'media'->>'scan') AS scan_key,
           coalesce((sprites->'assets'->'media'->>'scan_bytes')::bigint, 0) AS scan_bytes,
           coalesce((sprites->'assets'->'media'->>'scan_gen')::int, 1) AS scan_gen
      INTO v_ex FROM public.editor_assets WHERE run_id = v_gen.run_id;
    IF FOUND AND v_ex.status = 'ready' AND v_ex.expires_at > now() + interval '1 day'
       AND v_ex.scan_key IS NOT NULL AND v_ex.scan_bytes <= 400 * 1024 * 1024
       AND v_ex.scan_gen >= 2 THEN
        RETURN jsonb_build_object('run_id', v_gen.run_id, 'status', 'ready', 'cached', true);
    END IF;

    INSERT INTO public.editor_assets (run_id, work_order_id, review_id, status, updated_at)
    VALUES (v_gen.run_id, v_rq.work_order_id, p_review_id, 'pending', now())
    ON CONFLICT (run_id) DO UPDATE SET status='pending', review_id=excluded.review_id,
        error=NULL, updated_at=now();

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('editor_assets', v_rq.work_order_id,
            jsonb_build_object('run_id', v_gen.run_id, 'run_dir', v_gen.run_dir,
                               'review_id', p_review_id,
                               'channel_slug', v_rq.channel_slug),
            'editor_assets:' || v_gen.run_id,
            ARRAY[]::uuid[], ARRAY['generate', 'node:' || v_gen.node_id], 1800, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
    RETURNING id INTO v_job;

    PERFORM public._audit('editor_open','review_queue', p_review_id::text,
            jsonb_build_object('run_id', v_gen.run_id, 'job', v_job, 'node', v_gen.node_id));
    RETURN jsonb_build_object('run_id', v_gen.run_id, 'status', 'pending',
                              'job_id', v_job, 'node', v_gen.node_id);
END $$;

REVOKE ALL     ON FUNCTION public.request_editor_assets(uuid) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.request_editor_assets(uuid) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0048','claude (편집실 scan 마스터 우선 24fps — 캐시 세대 마커)')
ON CONFLICT DO NOTHING;
