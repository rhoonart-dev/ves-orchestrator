-- =====================================================================
-- 0051_editor_partial_reuse.sql — 장초수 scan 무한 재생성 수선 (2026-08-19, F-303)
--
-- 약 5.7시간을 넘는 원본은 비트레이트 하한(비디오 120 + 오디오 40kbps) 때문에 scan 이
-- 항상 400MB 상한을 넘어 업로드되지 않는다. 캐시 판정이 scan 존재를 요구하므로 그런
-- run 은 열 때마다 재생성 잡을 돌리고도 영상이 없는 무한 루프였다(0045 머리말의
-- 418MB 실측이 남긴 구멍). 어댑터가 상한 초과 시 **시도 마커**(media.scan_skip)를
-- 남기고, 캐시 판정은 '신 세대 scan 있음' 또는 '신 세대가 시도했음'을 인정한다.
--
-- 부분 재생성(F-303 본체 — 전역 스프라이트·파형·scan 재사용, 재렌더 후 재진입
-- 2~5분 → 수십 초)은 어댑터 단독(reuse_assets)이라 이 파일엔 델타가 없다.
--
-- ⚠ 적용 순서: DB 먼저(updater 게이트 ★③ — 0048~0050 과 같다).
--
-- 본문은 0049 판(0045 영상 유무 + 0048 scan_gen + 0049 tts_gen) 전문 + scan_skip 델타.
-- 짝: ves/adapters/editor_assets.py(reuse_assets·scan_skip) · 대시보드 상한 초과 안내.
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

    -- 캐시 재사용 조건(0045 + 0048 + 0049 + 0051): ready · 만료 전 · 편집용 영상까지
    -- 갖춤(또는 신 세대가 상한 초과로 **시도했음** — scan_skip) · 신 세대 내레이션 오디오.
    SELECT status, expires_at,
           (sprites->'assets'->'media'->>'scan') AS scan_key,
           coalesce((sprites->'assets'->'media'->>'scan_bytes')::bigint, 0) AS scan_bytes,
           coalesce((sprites->'assets'->'media'->>'scan_gen')::int, 1) AS scan_gen,
           (sprites->'assets'->'media'->>'scan_skip') AS scan_skip,
           coalesce((sprites->'assets'->>'tts_gen')::int, 0) AS tts_gen
      INTO v_ex FROM public.editor_assets WHERE run_id = v_gen.run_id;
    IF FOUND AND v_ex.status = 'ready' AND v_ex.expires_at > now() + interval '1 day'
       AND ( (v_ex.scan_key IS NOT NULL AND v_ex.scan_bytes <= 400 * 1024 * 1024
              AND v_ex.scan_gen >= 2)
          OR v_ex.scan_skip IS NOT NULL )
       AND v_ex.tts_gen >= 1 THEN
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
VALUES ('orchestrator','0051','claude (편집실 장초수 scan 시도 마커 — 무한 재생성 수선)')
ON CONFLICT DO NOTHING;
