-- =====================================================================
-- 0054_editor_v3_stamp.sql — edit_overrides/v3 스탬프 전환: 내용 기반 3단 (2026-08-19, F-401·F-407)
--
-- 엔진(ai-video)에 v3 가 구현됐다: subtitles[].source_time_sec(원본 절대초 앵커 — 구간과
-- 자막을 같이 보내도 좌표가 안 흔들린다)·subtitles[].style(줄 단위 크기·위치·색)·images[]
-- (스키마만 — 렌더 미구현, 엔진이 fail-loud 거절). 계약 정본: ai-video docs/edit_overrides_v3.md.
--
-- 스탬프는 **내용 기반**이고, 판정은 0053 규약대로 **병합 결과(v_ov)** 기준이다:
--   · v_ov.subtitles 에 source_time_sec/style 이 하나라도 있거나 images 가 있으면 → v3
--   · 아니고 v_ov 에 tts 가 있으면 → v2 · 그 외 → v1 (종전 그대로)
-- 엔진도 같은 규칙을 양방향으로 강제한다(실측 2026-08-19): 구 엔진은 v3 스키마를 즉시
-- 거절하고, 신 엔진은 v3 전용 필드가 v1/v2 스탬프에 실려 오면 즉시 거절한다.
--
-- 승계 예외도 v3 로 정교해진다(0053 델타): 구간이 바뀌면 옛 자막 좌표(편집본 시간축)는
-- 무효라 승계 자막을 통째로 버렸는데 — **앵커(source_time_sec) 있는 줄은 원본 좌표라
-- 살아남는다.** 앵커 없는 줄만 버린다.
--
-- ⚠ 적용·전환 절차 — 두 단계가 분리돼 있다:
--   ① 이 파일의 적용은 **언제든 안전**하다. 스탬프가 내용 기반이라, 화면이 v3 필드를
--      보내기 전까지는 종전과 똑같이 v1/v2 만 나간다. (updater 게이트 ★③는 '엔진 먼저'
--      방향을 표현할 수 없지만, 이 구조 덕에 표현할 필요가 없다.)
--   ② 실전 전환은 ops_config 'editor_v3' = 'on' 플래그 — 대시보드가 이 플래그를 볼 때만
--      자막 앵커를 실어 보내고 구간·자막 동시 편집 잠금을 푼다. **켜기 전 체크(둘 다)**:
--      ⓐ 이 파일이 applied_migrations 에 있음
--      ⓑ 전 노드의 엔진이 v3 포함 버전:
--         SELECT node_id, engine_versions->>'ai_video' FROM node_registry WHERE status='active';
--         — 6대 모두 v3 머지 커밋 이후 sha 여야 한다. 하나라도 구 sha 면 켜지 말 것
--         (그 노드로 가는 v3 편집이 전부 fail-loud 실패한다 — 조용한 오류보다 낫지만 낭비).
--
-- images 는 여기서 **조기 거절**한다 — 엔진 렌더 미구현이라 어차피 fail-loud 로 죽는데,
-- 검수함까지 가기 전에 화면에서 알리는 편이 낫다(0043 머리말과 같은 원칙). 엔진의 images
-- 렌더가 구현되는 세션에서 이 거절을 함께 푼다(스탬프의 images 분기는 그때를 위해 남겨둔다).
--
-- from_step 규칙은 불변: clips/tts(승계 포함) → resources, 제목·자막(앵커·style 포함)만
-- → render — 앵커 변환·줄 스타일은 render 단계에서 굽는다(계약 문서 실측 참조).
--
-- 본문은 0053 판(라운드 승계 + F-302) 전문 + 위 델타. retry_editor_chain 은 불변이라
-- 재정의하지 않는다. 짝: ai-video docs/edit_overrides_v3.md · 대시보드 편집실(editor_v3 플래그).
-- =====================================================================

CREATE OR REPLACE FUNCTION public.submit_editor_render(
    p_review_id uuid, p_overrides jsonb, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_busy uuid;
    v_prev jsonb; v_subs jsonb; v_v3 boolean;
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
    -- 이미지 오버레이(0054) — 엔진 렌더 미구현. 검수함에서 fail-loud 로 죽기 전에
    -- 여기서 알린다. 엔진 구현 세션에서 이 거절을 푼다.
    IF p_overrides ? 'images' THEN
        RAISE EXCEPTION '이미지 오버레이는 아직 렌더 미구현입니다 — 엔진 구현 후 열립니다';
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
        -- 구간이 바뀌면 옛 자막 좌표(편집본 시간축)는 무효 — 단 v3 앵커(source_time_sec)
        -- 있는 줄은 원본 좌표라 살아남는다(0054). 앵커 없는 줄만 버린다.
        IF jsonb_typeof(v_prev->'subtitles') = 'array' THEN
            SELECT coalesce(jsonb_agg(s), '[]'::jsonb) INTO v_subs
              FROM jsonb_array_elements(v_prev->'subtitles') s
             WHERE s ? 'source_time_sec';
            IF jsonb_array_length(v_subs) > 0 THEN
                v_prev := jsonb_set(v_prev, '{subtitles}', v_subs);
            ELSE
                v_prev := v_prev - 'subtitles';
            END IF;
        ELSE
            v_prev := v_prev - 'subtitles';
        END IF;
    END IF;
    v_ov := v_prev || p_overrides;
    -- 스키마 스탬프(0054) — 병합 결과 기준 내용 기반 3단. 정본: ai-video
    -- docs/edit_overrides_v3.md. 값은 여기서 못박는다: 화면이 빠뜨리면 엔진이 즉시
    -- 거절하고 사람은 "고쳤는데 실패했다"만 본다(스탬프-내용 불일치는 양방향 거절).
    v_v3 := (v_ov ? 'images')
         OR (jsonb_typeof(v_ov->'subtitles') = 'array' AND EXISTS (
                SELECT 1 FROM jsonb_array_elements(v_ov->'subtitles') s
                 WHERE s ? 'source_time_sec' OR s ? 'style'));
    v_ov := v_ov || jsonb_build_object('schema',
                CASE WHEN v_v3 THEN 'edit_overrides/v3'
                     WHEN v_ov ? 'tts' THEN 'edit_overrides/v2'
                     ELSE 'edit_overrides/v1' END);

    -- 내레이션·구간(승계분 포함)은 resources 부터 — mp3 재합성·구간 재추출이 그 단계다.
    -- 앵커·줄 스타일은 render 단계에서 굽는다(0054 확인 — from_step 불변).
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
                               'schema', v_ov->>'schema',
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
VALUES ('orchestrator','0054','claude (편집실 v3 스탬프 — 병합 결과 기반 3단, 앵커 자막 승계, images 조기 거절)')
ON CONFLICT DO NOTHING;
