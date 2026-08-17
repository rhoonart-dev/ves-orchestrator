-- =====================================================================
-- 0043_editor_render.sql — 검수함 '편집실' 2단계: 고친 제목·자막으로 다시 렌더 (2026-08-17)
--
-- 1단계(0042)는 "이 쇼츠가 원본 어디에서 왔는가"를 보여주기만 했다. 2단계는 그 화면에서
-- 고친 값을 실제 영상에 먹인다. 통로는 ai-video 의 --edit-overrides(edit_overrides/v1) 하나다:
--   · title.top_title  — 영상 안 상단 제목(drawtext)
--   · subtitles[]      — 대사 자막. **편집본 시간축**(쇼츠 0초 시작), 전량 교체
--   · clips[]          — 구간. 원본 절대초, 전량 교체 (3단계에서 화면이 붙는다)
--
-- 왜 0038(reject_and_rerender)을 재사용하지 않는가:
--   0038 은 **일본어 현지화본**을 고치는 경로다 — localize 잡이 localize_ja 를 다시 그린다.
--   편집실은 **한국어 원본 렌더 자체**를 다시 만든다 — generate 를 이어달리기로 재실행해야
--   하고, 그러면 upload_artifacts→ingest→evaluate 후속 체인도 함께 돌아야 새 검수 카드가
--   올라온다. 잡 종류도 체인 모양도 다르므로 별도 RPC 가 맞다.
--
-- 왜 카드를 먼저 rejected 로 닫는가: evaluate 의 카드 생성이 'waiting 이 이미 있으면 skip'
-- 이라(ves/adapters/brain.py) 옛 카드를 닫지 않으면 **새 영상의 카드가 아예 안 올라온다**.
-- 0038 이 같은 이유로 같은 순서를 쓴다.
--
-- 재개 단계(from_step): 구간을 고쳤으면 resources(TTS cue 앵커가 clip_index+offset 이라
-- 구간이 바뀌면 나레이션 위치가 어긋난다), 제목·자막만이면 render. 8/16 실측 — resources
-- 27초 / render 6초, 130분짜리 전체 재생성 대비 300배.
-- 짝: ves/adapters/aivideo.py(edit_overrides_argv) · app/modules/edit_overrides.py · 대시보드 '편집실'.
-- =====================================================================

CREATE OR REPLACE FUNCTION public.submit_editor_render(
    p_review_id uuid, p_overrides jsonb, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_busy uuid;
    v_ov jsonb; v_step text; v_params jsonb; v_common jsonb;
    v_gen_job uuid; v_up uuid; v_in uuid; v_ev uuid;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;

    -- ① 오버라이드 계약 — 고칠 게 없으면 렌더를 돌릴 이유가 없다
    IF p_overrides IS NULL OR p_overrides = '{}'::jsonb THEN
        RAISE EXCEPTION '고친 내용이 없습니다';
    END IF;
    IF NOT (p_overrides ? 'title' OR p_overrides ? 'subtitles' OR p_overrides ? 'clips') THEN
        RAISE EXCEPTION '편집 항목(title/subtitles/clips) 이 하나도 없습니다';
    END IF;
    -- 스키마는 여기서 못박는다 — 화면이 빠뜨리면 엔진이 PermanentError 로 죽고,
    -- 사람은 "고쳤는데 실패했다"만 본다. 값은 v1 하나뿐이라 주입이 안전하다.
    v_ov := p_overrides || jsonb_build_object('schema', 'edit_overrides/v1');

    -- ② 카드 — 한국어 발행 게이트만. 일본어 카드(localization_qa)는 0038 '수정 재렌더'가
    --    담당한다. 그쪽에서 원본 구간을 고치려면 KR 렌더부터 다시 도는데, 그러면 이미 만든
    --    일본어판까지 버려야 해서 결정 단위가 달라진다(3단계 이후 과제).
    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.kind = 'publish_gate' AND rq.status = 'waiting'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION '편집 재렌더 대상이 아닙니다 — 대기중인 발행 검수 카드만 가능합니다';
    END IF;

    -- ③ 이 작업지시에 이미 도는 렌더가 있으면 막는다. 같은 run_dir 을 두 프로세스가
    --    쓰면 체크포인트가 섞인다(어느 쪽 결과인지 알 수 없는 영상이 나온다).
    SELECT id INTO v_busy FROM public.job_queue
     WHERE work_order_id = v_rq.work_order_id AND kind = 'generate'
       AND status IN ('pending','running','blocked') LIMIT 1;
    IF v_busy IS NOT NULL THEN
        RAISE EXCEPTION '이미 렌더가 대기·진행 중입니다(job %) — 끝난 뒤 다시 시도하세요', v_busy;
    END IF;

    -- ④ 생성 결과 — run_id/run_dir/노드. 재렌더는 job 디렉토리가 있는 그 맥에서만 된다.
    SELECT j.node_id, j.result->>'run_id' AS run_id, j.result->>'run_dir' AS run_dir,
           j.params AS params
      INTO v_gen
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY coalesce(j.finished_at, j.updated_at) DESC LIMIT 1;
    IF v_gen.run_id IS NULL OR v_gen.run_dir IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/run_dir/node) 없음 — 편집 재렌더 불가';
    END IF;

    v_step := CASE WHEN p_overrides ? 'clips' THEN 'resources' ELSE 'render' END;

    -- ⑤ 옛 카드를 닫는다(위 머리말 참고). 반려로 기록되지만 사유가 '편집'임을 남긴다.
    UPDATE public.review_queue
       SET status = 'rejected',
           decided_by = coalesce(auth.email(), auth.uid()::text),
           decided_at = now(),
           decision_note = '[편집실 재렌더] ' || coalesce(p_note, '')
     WHERE id = p_review_id;

    -- ⑥ 렌더 체인 재투입: generate → upload_artifacts → ingest → evaluate.
    --    planner 의 job_chain 과 같은 모양이다(acquire 는 소스가 이미 캐시에 있으니 뺀다).
    --    후속 잡의 node 핀은 executor._pin_dependents 가 generate 완료 시 박는다.
    v_params := coalesce(v_gen.params, '{}'::jsonb) || jsonb_build_object(
                    'resume_run_id', v_gen.run_id, 'from_step', v_step,
                    'edit_overrides', v_ov,
                    'run_id', v_gen.run_id, 'run_dir', v_gen.run_dir,
                    'review_id', p_review_id);
    v_common := jsonb_build_object(
                    'work_title',   v_gen.params->>'work_title',
                    'episode',      v_gen.params->'episode',
                    'channel_slug', coalesce(v_gen.params->>'channel_slug', v_rq.channel_slug),
                    'channel_name', v_gen.params->>'channel_name',
                    'outdir',       coalesce(v_gen.params->>'outdir', 'outputs'),
                    'run_id',       v_gen.run_id, 'run_dir', v_gen.run_dir);

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('generate', v_rq.work_order_id, v_params,
            'editrender:' || p_review_id,
            ARRAY[]::uuid[], ARRAY['generate', 'node:' || v_gen.node_id], 300, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            params=excluded.params, updated_at=now()
    RETURNING id INTO v_gen_job;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('upload_artifacts', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':up',
            ARRAY[v_gen_job], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_up;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('ingest', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':in',
            ARRAY[v_up], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_in;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('evaluate', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':ev',
            ARRAY[v_in], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_ev;

    -- ⑦ 편집실 재료는 낡았다 — 구간·자막이 바뀌었으므로 다음에 열 때 다시 뜨게 한다.
    --    (0042 의 캐시 분기가 status='ready' 를 보고 재사용하기 때문)
    UPDATE public.editor_assets SET status='pending', updated_at=now()
     WHERE run_id = v_gen.run_id;

    PERFORM public._audit('editor_render','review_queue', p_review_id::text,
            jsonb_build_object('run_id', v_gen.run_id, 'job', v_gen_job,
                               'node', v_gen.node_id, 'from_step', v_step,
                               'note', p_note,
                               'keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(p_overrides) k),
                               'subs', jsonb_array_length(coalesce(p_overrides->'subtitles','[]'::jsonb)),
                               'clips', jsonb_array_length(coalesce(p_overrides->'clips','[]'::jsonb))));
    RETURN jsonb_build_object('review_id', p_review_id, 'work_order_id', v_rq.work_order_id,
                              'run_id', v_gen.run_id, 'job_id', v_gen_job,
                              'node', v_gen.node_id, 'from_step', v_step,
                              'chain', jsonb_build_array(v_gen_job, v_up, v_in, v_ev));
END $$;

REVOKE ALL     ON FUNCTION public.submit_editor_render(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.submit_editor_render(uuid, jsonb, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0043','claude (편집실 2단계 — 제목·자막 수정 재렌더 RPC)')
ON CONFLICT DO NOTHING;
