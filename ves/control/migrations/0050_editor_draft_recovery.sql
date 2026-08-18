-- =====================================================================
-- 0050_editor_draft_recovery.sql — 재렌더 실패 복구: 성공하면 지우고 실패하면 남긴다 (2026-08-19, F-302)
--
-- 종전(0047)은 제출 즉시 카드를 rejected 로 닫고 초안을 지웠다 — 체인이 실패하면
-- waiting 카드 0, 초안 0 으로 끝나 "고쳤는데 사라졌다"가 된다(복구 경로 없음).
-- 바꾼다:
--   · 제출은 초안을 지우지 않고 draft_sent_at 만 찍는다(보낸 초안).
--   · 성공 청소는 새 카드를 만드는 지점(brain.Evaluate.post_success)이 한다 —
--     보낸 초안이 남으면 같은 run 의 새 카드에 낡은 편집이 이중 적용된다(P3-a 실측).
--   · 재제출: rejected 카드라도 ①그 카드를 닫은 보낸 초안이 있고 ②같은 작업지시에
--     waiting 발행 카드가 없으면(=체인이 성공하지 못함) 다시 받는다. 카드 닫기는
--     waiting 일 때만 수행(이미 닫힌 카드를 또 닫지 않는다).
--
-- ⚠ 적용 순서: DB 먼저(updater 게이트 ★③) — 특히 이번엔 brain.post_success 가
-- draft_sent_at 컬럼을 UPDATE 하므로, 이 파일이 적용되지 않은 DB 에 신 코드가 돌면
-- evaluate 성공 처리가 죽는다. 게이트가 그 순서를 강제한다.
--
-- 본문은 0047 판(0046 acquire 재가열 포함) 전문 + 위 델타. 짝: ves/adapters/brain.py
-- (post_success 청소) · 대시보드 편집실(재제출 버튼·보낸 초안 표시).
-- =====================================================================

ALTER TABLE public.editor_assets ADD COLUMN IF NOT EXISTS draft_sent_at timestamptz;
COMMENT ON COLUMN public.editor_assets.draft_sent_at IS
  '초안을 재렌더로 보낸 시각(F-302). 있으면 ''보낸 초안'' — 성공 시 post_success 가 지우고, 실패 시 재제출 재료로 남는다.';

CREATE OR REPLACE FUNCTION public.submit_editor_render(
    p_review_id uuid, p_overrides jsonb, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_busy uuid;
    v_ov jsonb; v_step text; v_params jsonb; v_common jsonb; v_acq_params jsonb;
    v_acq uuid; v_gen_job uuid; v_up uuid; v_in uuid; v_ev uuid;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;

    IF p_overrides IS NULL OR p_overrides = '{}'::jsonb THEN
        RAISE EXCEPTION '고친 내용이 없습니다';
    END IF;
    IF NOT (p_overrides ? 'title' OR p_overrides ? 'subtitles' OR p_overrides ? 'clips'
            OR p_overrides ? 'design' OR p_overrides ? 'tts') THEN
        RAISE EXCEPTION '편집 항목(title/subtitles/clips/design/tts) 이 하나도 없습니다';
    END IF;
    IF p_overrides ? 'tts' AND jsonb_typeof(p_overrides->'tts') <> 'array' THEN
        RAISE EXCEPTION 'tts 는 배열이어야 합니다 (빈 배열 = 내레이션 전부 삭제)';
    END IF;
    -- 스키마 스탬프 — tts 가 있을 때만 v2 (0047 머리말 참고). 값은 여기서 못박는다:
    -- 화면이 빠뜨리면 엔진이 PermanentError 로 죽고 사람은 "고쳤는데 실패했다"만 본다.
    v_ov := p_overrides || jsonb_build_object('schema',
                CASE WHEN p_overrides ? 'tts' THEN 'edit_overrides/v2'
                     ELSE 'edit_overrides/v1' END);

    -- waiting = 통상 경로 · rejected = 재제출 경로(F-302, 아래 가드)
    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload, rq.status INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.kind = 'publish_gate'
       AND rq.status IN ('waiting','rejected')
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION '편집 재렌더 대상이 아닙니다 — 발행 검수 카드만 가능합니다';
    END IF;
    IF v_rq.status = 'rejected' THEN
        -- 재제출은 '편집 재렌더가 성공하지 못한' 카드만: 새 waiting 카드가 있으면 그쪽이
        -- 정본이고, 보낸 초안이 없으면 이 카드는 사람이 반려한 것이다(재제출 아님).
        PERFORM 1 FROM public.review_queue w
         WHERE w.work_order_id = v_rq.work_order_id
           AND w.kind = 'publish_gate' AND w.status = 'waiting';
        IF FOUND THEN
            RAISE EXCEPTION '이미 새 검수 카드가 있습니다 — 그 카드에서 고치세요';
        END IF;
        PERFORM 1 FROM public.editor_assets ea
         WHERE ea.review_id = p_review_id AND ea.draft_sent_at IS NOT NULL;
        IF NOT FOUND THEN
            RAISE EXCEPTION '재제출 대상이 아닙니다 — 이 카드로 보낸 초안이 없습니다';
        END IF;
    END IF;

    -- generate 만 보면 안 된다 — generate 성공 후 upload/ingest/evaluate 가 도는 창
    -- (evaluate 는 수십 분 가능)에서 재제출이 통과하면 ON CONFLICT 리셋이 돌던 체인을
    -- 죽이고 처음부터 다시 돌린다.
    SELECT id INTO v_busy FROM public.job_queue
     WHERE work_order_id = v_rq.work_order_id
       AND status IN ('pending','running','blocked')
       AND (kind = 'generate' OR idempotency_key LIKE 'editrender:%')
     LIMIT 1;
    IF v_busy IS NOT NULL THEN
        RAISE EXCEPTION '이미 렌더 체인이 대기·진행 중입니다(job %) — 끝난 뒤 다시 시도하세요', v_busy;
    END IF;

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

    -- 내레이션도 resources 부터 — mp3 재합성이 그 단계다 (구간과 같은 라우팅).
    v_step := CASE WHEN p_overrides ? 'clips' OR p_overrides ? 'tts'
                   THEN 'resources' ELSE 'render' END;

    -- 카드 닫기는 waiting 일 때만 — 재제출 경로는 이미 닫혀 있다
    UPDATE public.review_queue
       SET status = 'rejected',
           decided_by = coalesce(auth.email(), auth.uid()::text),
           decided_at = now(),
           decision_note = '[편집실 재렌더] ' || coalesce(p_note, '')
     WHERE id = p_review_id AND status = 'waiting';

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

    v_acq_params := v_common || jsonb_build_object(
                        'source_url',    v_gen.params->>'source_url',
                        'source_sha256', v_gen.params->>'source_sha256');

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('acquire', v_rq.work_order_id, v_acq_params,
            'editrender:' || p_review_id || ':acq',
            ARRAY[]::uuid[], ARRAY['network', 'node:' || v_gen.node_id], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            required_caps=excluded.required_caps,
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_acq;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('generate', v_rq.work_order_id, v_params,
            'editrender:' || p_review_id,
            ARRAY[v_acq], ARRAY['generate', 'node:' || v_gen.node_id], 300, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
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

    -- 초안은 지우지 않는다(F-302) — 보낸 표시만. 성공 청소는 post_success 가 한다.
    -- review_id 도 여기서 갱신 — 캐시 히트로 열린 화면은 request_editor_assets 가
    -- review_id 를 안 고치므로, 안 찍으면 재제출 가드(ea.review_id 대조)가 어긋난다.
    UPDATE public.editor_assets
       SET status='pending', draft_sent_at=now(), review_id=p_review_id, updated_at=now()
     WHERE run_id = v_gen.run_id;

    PERFORM public._audit('editor_render','review_queue', p_review_id::text,
            jsonb_build_object('run_id', v_gen.run_id, 'job', v_gen_job,
                               'node', v_gen.node_id, 'from_step', v_step,
                               'note', p_note, 'resubmit', v_rq.status = 'rejected',
                               'keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(p_overrides) k),
                               'subs', jsonb_array_length(coalesce(p_overrides->'subtitles','[]'::jsonb)),
                               'clips', jsonb_array_length(coalesce(p_overrides->'clips','[]'::jsonb)),
                               'tts', jsonb_array_length(coalesce(p_overrides->'tts','[]'::jsonb))));
    RETURN jsonb_build_object('review_id', p_review_id, 'work_order_id', v_rq.work_order_id,
                              'run_id', v_gen.run_id, 'job_id', v_gen_job,
                              'node', v_gen.node_id, 'from_step', v_step,
                              'chain', jsonb_build_array(v_acq, v_gen_job, v_up, v_in, v_ev));
END $$;

REVOKE ALL     ON FUNCTION public.submit_editor_render(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.submit_editor_render(uuid, jsonb, text) TO authenticated;

-- ── 실패 지점부터 재시도 — 인프라 실패(upload/ingest/evaluate dead 등)의 정석 복구 ──
-- 재제출(전량 오버라이드)은 실패 체인이 run_dir 을 이미 변형한 경우 diff 가 붕괴한다
-- (generate 성공 후 실패면 재료가 이미 고친 본 — 보낼 diff 가 없다). 그런 실패군은
-- 오버라이드를 다시 보내는 게 아니라 **멈춘 잡을 되살리는** 것이 맞다.
CREATE OR REPLACE FUNCTION public.retry_editor_chain(p_review_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_n int;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;
    UPDATE public.job_queue
       SET status='pending', attempt=0, error=NULL, error_class=NULL,
           node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
     WHERE idempotency_key LIKE 'editrender:' || p_review_id || '%'
       AND status IN ('failed','dead','cancelled');
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n = 0 THEN
        RAISE EXCEPTION '재시도할 실패 잡이 없습니다 — 체인이 진행 중이거나 이미 끝났습니다';
    END IF;
    PERFORM public._audit('editor_chain_retry','review_queue', p_review_id::text,
            jsonb_build_object('reset', v_n));
    RETURN jsonb_build_object('reset', v_n);
END $$;

REVOKE ALL     ON FUNCTION public.retry_editor_chain(uuid) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.retry_editor_chain(uuid) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0050','claude (편집실 실패 복구 — 보낸 초안 보존·재제출)')
ON CONFLICT DO NOTHING;
