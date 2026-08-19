-- =====================================================================
-- 0055_reject_single_chain.sql — 반려 재생성은 최신 체인만 되살린다 (2026-08-19)
--
-- 실사고(가왕쇼_acfc0ef9, HANIPJUMAK, 08-19 05:14~05:22 UTC): 편집실 재렌더로
-- 제목을 고친 뒤 결과 카드를 '제작' 반려+재생성했더니, 0021 의 되살리기 UPDATE 가
-- work_order 의 **종료된 잡 전부**를 pending 으로 되돌렸다. 0021 당시엔 워크오더당
-- 체인이 하나라 옳았지만, 편집실(0043~) 이후엔 데일리 체인 + 편집 라운드별
-- editrender 체인이 같은 run 디렉토리·preview key 를 공유한다. 셋이 순차 재실행되며
-- **마지막에 끝난 무편집 체인이 편집본 preview 를 덮어썼고**, 새 검수 카드는 옛
-- evaluate 를 가리켰다 — 사용자에겐 '고친 제목이 초기화된' 사고로 보였다.
--
-- 수정 셋:
--   ① 되살리기를 **최신 succeeded generate 의 체인**(그 잡 + depends_on 으로
--      내려가는 후속 잡들)으로 한정한다. 최신 generate 는 편집 라운드가 있었다면
--      editrender 체인이고, params 에 병합된 edit_overrides(0053 승계분)를 이미
--      갖고 있으므로 재렌더에 편집이 그대로 반영된다.
--   ② 체인이 아직 대기·진행 중이면 재생성을 거부한다(반려 기록은 남긴다) —
--      submit_editor_render(0044~0053)의 busy 가드와 같은 이유: 돌던 체인 위에
--      되살리기가 얹히면 같은 run_dir 을 두 체인이 동시에 만진다.
--   ③ '최신 체인'은 finished_at 이 아니라 **created_at** 으로 고른다. 이번 사고처럼
--      옛 체인이 재실행되면 finished_at 이 뒤집혀 데일리 체인이 '최신'으로 잡힌다
--      (가왕쇼 실데이터로 검증 — finished_at 순은 8/18 데일리를 골랐다). 체인의
--      신원은 재실행에도 안 변하는 created_at 이 정본이다. 같은 결함이 0053
--      submit_editor_render 의 승계 소스 선택에도 있어 여기서 함께 교체한다 —
--      안 고치면 이 사고 뒤의 편집실 재렌더가 데일리 체인(오버라이드 없음)에서
--      승계해 편집을 또 잃는다. ★본문은 0053 이 아니라 **라이브(0054) 정의**를 베이스로
--      한다 — 0053 판을 쓰면 0054 의 v3 스탬프·앵커 자막 승계가 되돌아간다(적용 전 실측).
--
-- 본문은 0021 판 + 위 델타. 시그니처 동일(p_review_id, p_note, p_stage,
-- p_regenerate) — CREATE OR REPLACE 로 교체 가능.
-- 짝: 0021_reject_stages(원판) · 0050 retry_editor_chain(체인 스코핑 선례) ·
--     0053 submit_editor_render(busy 가드·승계).
-- =====================================================================

CREATE OR REPLACE FUNCTION public.reject_review(
    p_review_id uuid, p_note text DEFAULT NULL, p_stage text DEFAULT NULL,
    p_regenerate boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public'
AS $function$
DECLARE
    v_rq record; v_stage text; v_run text; v_span jsonb; v_node text;
    v_gen_id uuid; v_busy uuid;
    v_tries int; v_avoid jsonb; v_gen int; v_limit int := 2;
    v_step text; v_resume boolean; v_use_note boolean; v_patch jsonb;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'permission denied'; END IF;

    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload
      INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.status = 'waiting'
     FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'review not waiting'; END IF;

    -- 반려 단계: 명시 인자 > 메모 접두사 > 기본 '영상 분석'. 0019 의 '장면' 도 받아준다.
    v_stage := coalesce(nullif(btrim(p_stage), ''),
        CASE WHEN p_note LIKE '[제작]%'        THEN '제작'
             WHEN p_note LIKE '[스토리 구성]%' THEN '스토리 구성'
             WHEN p_note LIKE '[영상 분석]%'   THEN '영상 분석'
             WHEN p_note LIKE '[장면]%'        THEN '영상 분석' END, '영상 분석');
    IF v_stage = '장면' THEN v_stage := '영상 분석'; END IF;
    IF v_stage NOT IN ('영상 분석','스토리 구성','제작') THEN
        RAISE EXCEPTION '알 수 없는 반려 단계: %', v_stage; END IF;

    v_step     := CASE v_stage WHEN '스토리 구성' THEN 'story'
                               WHEN '제작'        THEN 'render' ELSE NULL END;
    v_resume   := v_stage IN ('스토리 구성','제작');   -- 같은 run 을 이어달린다
    v_use_note := v_stage IN ('영상 분석','스토리 구성'); -- 렌더는 프롬프트를 쓰지 않는다

    UPDATE public.review_queue
       SET status='rejected', decided_by=auth.uid()::text, decided_at=now(),
           decision_note=p_note
     WHERE id = p_review_id;

    -- 최신 성공 generate — 이 잡의 체인만 되살린다(수정 ①). 편집 라운드가 있었다면
    -- 이 잡이 editrender 체인이고 params 에 병합 오버라이드(0053)가 실려 있다.
    -- created_at 순(수정 ③) — finished_at 은 재실행에 뒤집힌다.
    SELECT j.id, j.result->>'run_id', j.result->'scene_span', j.node_id
      INTO v_gen_id, v_run, v_span, v_node
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id AND j.kind='generate'
       AND j.status='succeeded'
     ORDER BY j.created_at DESC LIMIT 1;
    v_run := coalesce(v_run, v_rq.payload->>'run_id');

    INSERT INTO public.rejected_takes(work_order_id, run_id, kind, stage, scene_span,
                                      note, rejected_by)
    VALUES (v_rq.work_order_id, v_run, v_stage, v_stage, v_span, p_note, auth.uid()::text);

    PERFORM public._audit('reject','review_queue',p_review_id::text,
            jsonb_build_object('note',p_note,'stage',v_stage,'run_id',v_run,
                               'regenerate',p_regenerate,'from_step',v_step,
                               'gen_job',v_gen_id));

    IF NOT coalesce(p_regenerate, true) THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'user_declined',
                                  'stage', v_stage);
    END IF;

    -- 돌던 체인 위에 얹지 않는다(수정 ②) — 반려 기록은 위에서 이미 남았다.
    SELECT id INTO v_busy FROM public.job_queue
     WHERE work_order_id = v_rq.work_order_id
       AND status IN ('pending','running','blocked')
       AND (kind = 'generate' OR idempotency_key LIKE 'editrender:%')
     LIMIT 1;
    IF v_busy IS NOT NULL THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'busy',
                                  'job', v_busy, 'stage', v_stage);
    END IF;

    -- '제작' 은 같은 run 을 이어달리므로 run_id 가 없으면 이어갈 대상이 없다.
    IF v_resume AND (v_run IS NULL OR v_gen_id IS NULL) THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'no_run_to_resume',
                                  'stage', v_stage);
    END IF;
    IF v_gen_id IS NULL THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'no_chain',
                                  'stage', v_stage);
    END IF;

    SELECT count(*) INTO v_tries FROM public.rejected_takes
     WHERE work_order_id = v_rq.work_order_id;
    IF v_tries > v_limit THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'retry_limit',
                                  'tries', v_tries, 'stage', v_stage);
    END IF;

    -- 회피 구간: 새로 장면을 고르는 단계에서만 쓴다. '제작' 은 같은 구간을 그대로 다시
    -- 렌더하는 게 목적이라 회피 목록을 주면 자기 자신과 100% 겹쳐 매번 실패한다(0021 ⓐ).
    IF v_stage = '제작' THEN
        v_avoid := NULL;
    ELSE
        SELECT coalesce(jsonb_agg(scene_span), '[]'::jsonb) INTO v_avoid
          FROM public.rejected_takes
         WHERE work_order_id = v_rq.work_order_id AND scene_span IS NOT NULL;
    END IF;

    -- generate 잡에 실을 재실행 지시
    v_patch := '{}'::jsonb;
    IF v_avoid IS NOT NULL THEN
        v_patch := v_patch || jsonb_build_object('avoid_spans', v_avoid); END IF;
    IF v_use_note AND nullif(btrim(coalesce(p_note,'')),'') IS NOT NULL THEN
        v_patch := v_patch || jsonb_build_object('reject_note', btrim(p_note)); END IF;
    IF v_resume THEN
        v_patch := v_patch || jsonb_build_object('resume_run_id', v_run, 'from_step', v_step);
    END IF;

    -- 되살리기 — 최신 generate 와 그 후속(depends_on 폐포)만. 다른 라운드·데일리
    -- 체인의 succeeded 잡은 건드리지 않는다(수정 ① — 사고의 직접 원인).
    WITH RECURSIVE chain AS (
        SELECT v_gen_id AS id
        UNION
        SELECT j.id FROM public.job_queue j JOIN chain c ON j.depends_on @> ARRAY[c.id]
         WHERE j.work_order_id = v_rq.work_order_id
    )
    UPDATE public.job_queue j
       SET status='pending', node_id=NULL, error=NULL, error_class=NULL, attempt=0,
           lease_expires_at=NULL, finished_at=NULL, result=NULL,
           run_after=now(), updated_at=now(),
           params = CASE
                      WHEN j.kind='generate' THEN
                        (j.params - 'resume_run_id' - 'from_step' - 'avoid_spans'
                                  - 'reject_note') || v_patch
                      -- 후속 잡은 옛 run 을 물고 있으면 안 된다(0021 ⓑ) — 선행 결과에서 새로 받는다
                      ELSE j.params - 'run_id' - 'run_dir' END,
           required_caps = CASE WHEN v_node IS NULL THEN j.required_caps
                                WHEN j.required_caps @> ARRAY['node:'||v_node] THEN j.required_caps
                                ELSE array_remove(array_remove(array_remove(array_remove(
                                       array_remove(array_remove(j.required_caps,'node:mm-01'),
                                       'node:mm-02'),'node:mm-03'),'node:mm-04'),'node:mm-05'),'node:mm-06')
                                     || ARRAY['node:'||v_node] END
     WHERE j.id IN (SELECT id FROM chain)
       AND j.kind IN ('generate','upload_artifacts','ingest','evaluate','localize')
       AND j.status IN ('succeeded','failed','dead','cancelled');
    GET DIAGNOSTICS v_gen = ROW_COUNT;

    RETURN jsonb_build_object('regenerated', true, 'stage', v_stage, 'tries', v_tries,
                              'node', v_node, 'from_step', v_step, 'jobs', v_gen,
                              'gen_job', v_gen_id,
                              'avoid', v_avoid, 'note_applied', v_use_note,
                              'mode', CASE WHEN v_resume THEN 'resume' ELSE 'fresh' END);
END $function$;
REVOKE ALL ON FUNCTION public.reject_review(uuid, text, text, boolean) FROM public;
GRANT EXECUTE ON FUNCTION public.reject_review(uuid, text, text, boolean) TO authenticated;

-- ── submit_editor_render — **라이브(0054) 전문** + 승계 소스 정렬만 교체(수정 ③) ──
-- ⚠ 0053 본문을 베이스로 쓰면 그 뒤 머지된 0054(edit_overrides/v3 스탬프 · 앵커
--   source_time_sec 자막 승계)가 통째로 되돌아간다. 그래서 여기 본문은 pg_get_functiondef
--   로 뜬 **적용 시점 라이브 정의**이고, 델타는 ORDER BY 한 줄뿐이다.
CREATE OR REPLACE FUNCTION public.submit_editor_render(p_review_id uuid, p_overrides jsonb, p_note text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
     ORDER BY j.created_at DESC LIMIT 1;   -- 0055 수정 ③: finished_at 은 재실행에 뒤집힌다
                                           -- (0054 판 그대로 + 이 줄만 교체)
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
    -- 스키마 스탬프(0054) — 병합 결과 기준 내용 기반 3단.
    v_v3 := (v_ov ? 'images')
         OR (jsonb_typeof(v_ov->'subtitles') = 'array' AND EXISTS (
                SELECT 1 FROM jsonb_array_elements(v_ov->'subtitles') s
                 WHERE s ? 'source_time_sec' OR s ? 'style'));
    v_ov := v_ov || jsonb_build_object('schema',
                CASE WHEN v_v3 THEN 'edit_overrides/v3'
                     WHEN v_ov ? 'tts' THEN 'edit_overrides/v2'
                     ELSE 'edit_overrides/v1' END);

    v_step := CASE WHEN v_ov ? 'clips' OR v_ov ? 'tts'
                   THEN 'resources' ELSE 'render' END;

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
END $function$;

REVOKE ALL     ON FUNCTION public.submit_editor_render(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.submit_editor_render(uuid, jsonb, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0055','claude (반려 재생성 체인 스코핑 — 가왕쇼_acfc0ef9 사고)')
ON CONFLICT DO NOTHING;
