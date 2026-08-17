-- =====================================================================
-- 0042_editor_assets.sql — 검수함 '편집실' 1단계: 원본 타임라인 재료 (2026-08-16)
--
-- 편집실은 "이 쇼츠가 원본 어디에서 왔는가"를 보여주는 화면이다. 그러려면 브라우저가
-- 원본 전체 길이의 시각 재료를 가져야 하는데 마스터는 4~5GB 이고 ves-sources 는 RLS 밖이다.
-- 그래서 원본 대신 **축소 재료**(스프라이트 썸네일·파형)를 노드가 만들어 ves-outputs 에
-- 올리고, 화면이 그릴 좌표(클립 구간·자막)는 **이 테이블에 jsonb 로 직접** 넣는다.
--
-- 왜 좌표를 스토리지가 아니라 DB 에 두는가:
--   · edit_plan.json 은 ves-outputs 에 있지만 브라우저의 JSON fetch 는 CORS 변수가 있다
--   · subtitle_segments.json 은 ves-runs 라 브라우저가 **아예** 못 읽는다(정책)
--   노드는 둘 다 로컬에서 읽으므로 여기서 합쳐 두면 화면은 평소 쓰던 select 하나로 끝난다.
--   새 스토리지 정책도, CORS 도 필요 없다. 이미지·영상만 서명 URL 로 간다.
--
-- 온디맨드: 편집은 소수 영상에만 일어난다. 매 run 마다 만들면 하루 20채널 × 수백 MB 가
-- 쌓인다. 사람이 편집실을 열 때 RPC 가 잡을 넣고, 7일 뒤 GC 가 치운다(expires_at).
-- 짝: ves/adapters/editor_assets.py · 대시보드 '편집실' 탭.
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.editor_assets (
    run_id         text PRIMARY KEY,
    work_order_id  uuid REFERENCES public.work_orders(id) ON DELETE CASCADE,
    review_id      uuid,
    status         text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','ready','failed')),
    duration_sec   double precision,
    -- 화면이 그리는 좌표 정본: {clips:[{start_sec,end_sec,offset_sec,role,…}], subtitles:[…]}
    -- clips 는 **원본 절대초**, subtitles 는 편집본 시각 + 역산한 원본 시각을 함께 담는다.
    timeline       jsonb,
    -- 스프라이트 배치 + 스토리지 키: {interval,grid,thumb_w,count,sheets,assets:{global,edges,wave}}
    sprites        jsonb,
    node_id        text,
    error          text,
    expires_at     timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.editor_assets IS
  '편집실 원본 타임라인 재료(온디맨드, 7일 만료). run_id 당 1행 — 같은 run 을 다시 열면 덮어쓴다.';

CREATE INDEX IF NOT EXISTS editor_assets_wo_idx ON public.editor_assets(work_order_id);
CREATE INDEX IF NOT EXISTS editor_assets_exp_idx ON public.editor_assets(expires_at);

ALTER TABLE public.editor_assets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ves_dash_read ON public.editor_assets;
CREATE POLICY ves_dash_read ON public.editor_assets
  FOR SELECT TO authenticated USING (true);
-- 쓰기는 워커(service_role)만 — RLS 를 우회하므로 정책을 따로 두지 않는다(R12 와 같은 규율).

-- ── 편집실 열기: 재료 생성 요청 ────────────────────────────────────────
-- reviewer 가 검수 카드에서 누른다. 이미 ready 이고 만료 전이면 잡을 만들지 않는다 —
-- 4시간물 스프라이트는 수십 초 걸리므로 재방문마다 다시 뜨면 낭비다.
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
        -- 잔망루피(전용 파이프라인)는 원본 타임라인 개념이 다르다 — 1단계 대상 아님.
        RAISE EXCEPTION '작업지시 없는 카드는 편집실 대상이 아닙니다(잔망루피 등)';
    END IF;

    -- 생성 결과에서 run_id·run_dir·노드를 가져온다. 재료는 그 노드에서만 만들 수 있다
    -- (job 디렉토리가 거기 있다) — 0038 의 scene_rerender 재투입과 같은 규약.
    SELECT j.node_id, j.result->>'run_id' AS run_id, j.result->>'run_dir' AS run_dir
      INTO v_gen
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY coalesce(j.finished_at, j.updated_at) DESC LIMIT 1;
    IF v_gen.run_id IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/node) 없음 — 편집실을 열 수 없습니다';
    END IF;

    SELECT status, expires_at INTO v_ex FROM public.editor_assets WHERE run_id = v_gen.run_id;
    IF FOUND AND v_ex.status = 'ready' AND v_ex.expires_at > now() + interval '1 day' THEN
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
VALUES ('orchestrator','0042','claude (편집실 1단계 — editor_assets 테이블·RPC)')
ON CONFLICT DO NOTHING;
