-- =====================================================================
-- 0045_editor_media_cache.sql — 편집실 재료 캐시 판정에 '영상 유무'를 넣는다 (2026-08-17)
--
-- 0042 의 캐시 분기는 status='ready' 와 만료일만 봤다. 그 사이 재료의 **구성이 늘었다** —
-- 스프라이트·파형만 있던 것에 편집용 영상(scan·closeups)이 추가됐다. 그래서 옛 재료를
-- 가진 run 은 "ready 니까 그대로 쓰자"로 걸러져 **영상 없는 편집실**이 열린다
-- (2026-08-17 실측: 6건 중 4건에 media 없음, 1건은 상한 초과 스캔 418MB).
--
-- 캐시는 '있다/없다'가 아니라 **'지금 화면이 요구하는 것을 갖췄는가'**로 판정해야 한다.
-- 앞으로 재료가 또 늘면 이 조건에 한 줄씩 붙인다.
-- 짝: ves/adapters/editor_assets.py(_build_media) · 대시보드 '편집실'.
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

    -- 캐시 재사용 조건(0045): ready · 만료 전 · **편집용 영상까지 갖춤**.
    -- scan 이 없거나 상한(400MB)을 넘는 옛 인코딩이면 다시 만든다 — 4시간물 스캔이
    -- 그 크기면 브라우저가 열지 못한다.
    SELECT status, expires_at,
           (sprites->'assets'->'media'->>'scan') AS scan_key,
           coalesce((sprites->'assets'->'media'->>'scan_bytes')::bigint, 0) AS scan_bytes
      INTO v_ex FROM public.editor_assets WHERE run_id = v_gen.run_id;
    IF FOUND AND v_ex.status = 'ready' AND v_ex.expires_at > now() + interval '1 day'
       AND v_ex.scan_key IS NOT NULL AND v_ex.scan_bytes <= 400 * 1024 * 1024 THEN
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
VALUES ('orchestrator','0045','claude (편집실 캐시 판정에 편집용 영상 유무 반영)')
ON CONFLICT DO NOTHING;
