-- =====================================================================
-- 0053_editor_overrides_carryover.sql — 편집 라운드 누적 승계 (2026-08-19)
--
-- 실측(커리어데이_ae71b530): 1라운드에서 제목+구간을 고쳐 재렌더 → 2라운드에서
-- 내레이션만 고쳐 보냈더니 **제목과 구간이 초기 버전으로 되돌아갔다.**
--
-- 원인: 화면(edCollect)은 '이번에 만진 키만' 보내고(설계 — 안 만진 항목을 보내면
-- 전량 교체로 못박아 버린다), 이 함수는 직전 generate 잡의 params 에 새 오버라이드를
-- `||` 로 얹어 **edit_overrides 키를 통째로 교체**했다. 엔진은 매 라운드 원본
-- 체크포인트(checkpoint_story/silence_cut)에서 다시 시작하므로, 이전 라운드의
-- 제목·구간·자막은 새 오버라이드에 없으면 그대로 초기값으로 돌아간다.
--
-- 수정: 직전 generate 잡의 edit_overrides 를 **키 단위로 승계**한 위에 새 오버라이드를
-- 얹는다(각 키는 전량 교체 규약이므로 최상위 병합이 정확하다). 예외 하나 —
--   · 새 오버라이드에 clips 가 있는데 subtitles 가 없으면, 승계분의 subtitles 는
--     버린다. 자막 좌표는 **편집본 시간축**이라 구간이 바뀌면 통째로 어긋난다.
--     (화면도 같은 이유로 구간을 바꾸면 자막을 안 보낸다 — 엔진이 재매핑한다.)
--   · title/design(스칼라)·clips/tts(원본 절대초 좌표)는 안전하게 승계된다.
-- from_step·스키마 스탬프도 병합 결과(v_ov) 기준 — 승계된 clips/tts 도 resources
-- 재개·v2 스탬프를 받아야 한다.
--
-- (번호 이력: 0049 로 먼저 적용했다가 0049 tts_audio·0050 F-302 와 같은 날 경합 —
--  0050 판 전문 위에 델타를 다시 얹어 0053 으로 확정(0052 는 플랫폼 표기가 선점). F-302 의 재제출 경로·보낸 초안
--  보존·retry_editor_chain 은 그대로다.)
--
-- 짝: dashboard 편집실 edCollect(더티 키만 전송) · ves/adapters/aivideo.py ·
--     ai-video app/modules/edit_overrides.py. 본문은 0050 판 + 위 델타.
-- =====================================================================

CREATE OR REPLACE FUNCTION public.submit_editor_render(
    p_review_id uuid, p_overrides jsonb, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_busy uuid;
    v_prev jsonb; v_ov jsonb; v_step text; v_params jsonb; v_common jsonb; v_acq_params jsonb;
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

    -- ── 라운드 승계(0053) — 머리말 참고 ─────────────────────────────────
    v_prev := coalesce(v_gen.params->'edit_overrides', '{}'::jsonb) - 'schema';
    IF p_overrides ? 'clips' AND NOT p_overrides ? 'subtitles' THEN
        v_prev := v_prev - 'subtitles';   -- 구간이 바뀌면 옛 자막 좌표(편집본 시간축)는 무효
    END IF;
    v_ov := v_prev || p_overrides;
    -- 스키마 스탬프 — 병합 결과에 tts 가 있을 때만 v2 (0047 머리말 참고). 값은 여기서
    -- 못박는다: 화면이 빠뜨리면 엔진이 PermanentError 로 죽고 사람은 "고쳤는데 실패했다"만 본다.
    v_ov := v_ov || jsonb_build_object('schema',
                CASE WHEN v_ov ? 'tts' THEN 'edit_overrides/v2'
                     ELSE 'edit_overrides/v1' END);

    -- 내레이션·구간(승계분 포함)은 resources 부터 — mp3 재합성·구간 재추출이 그 단계다.
    v_step := CASE WHEN v_ov ? 'clips' OR v_ov ? 'tts'
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
                               'carried', (SELECT jsonb_agg(k) FROM jsonb_object_keys(v_prev) k
                                           WHERE NOT p_overrides ? k),
                               'subs', jsonb_array_length(coalesce(v_ov->'subtitles','[]'::jsonb)),
                               'clips', jsonb_array_length(coalesce(v_ov->'clips','[]'::jsonb)),
                               'tts', jsonb_array_length(coalesce(v_ov->'tts','[]'::jsonb))));
    RETURN jsonb_build_object('review_id', p_review_id, 'work_order_id', v_rq.work_order_id,
                              'run_id', v_gen.run_id, 'job_id', v_gen_job,
                              'node', v_gen.node_id, 'from_step', v_step,
                              'chain', jsonb_build_array(v_acq, v_gen_job, v_up, v_in, v_ev));
END $$;

REVOKE ALL     ON FUNCTION public.submit_editor_render(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.submit_editor_render(uuid, jsonb, text) TO authenticated;


INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0053','claude (편집 라운드 누적 승계 — 이전 edit_overrides 키 단위 병합, 0050 재기반)')
ON CONFLICT DO NOTHING;
