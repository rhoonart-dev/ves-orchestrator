-- =====================================================================
-- 0074_reject_retry_limit_visible.sql — 재생성 상한에 걸린 반려를 화면에 남긴다 (2026-08-23)
--
-- ⚠ 번호 발번: 적용 직전 `SELECT max(version) FROM applied_migrations WHERE engine='orchestrator'`
--    로 확인하고, 그 +1 로 파일명과 아래 INSERT 를 맞춘다.
--    **발번 결과(2026-08-22): 0072 → 0074.** 이 파일은 0071 다음(0072)을 가정했으나, 그 사이
--    0072(채널 자막 전사 백엔드)·0073(편집실 일레븐랩스 목소리)이 **먼저 적용돼**
--    max(version)=0073 이었다. 위 규칙대로 0074 로 재발번한다 — 0072 인 채 적용했다면
--    아래 INSERT 가 기존 0072 행과 충돌해 ON CONFLICT DO NOTHING 에 삼켜져
--    applied_migrations 에 안 남고, updater 마이그레이션 게이트(★③, 파일명 버전 −
--    적용 버전)가 '0072 적용됨'으로 오판해 통과시켰을 것이다(reject_review 는 구판인 채).
--
-- 실사고(2026-08-22 23:12 KST 실측 — 한 입 주막 HANIPJUMAK '가왕쇼' EP1,
-- work_order 333fc58d-f292-466f-a262-6960b31ab72c):
--   reject_review 는 ① review_queue 를 rejected 로 바꾸고 ② rejected_takes 에 한 줄
--   넣은 뒤 ③ 그 개수를 세서 v_tries > 2 면 {regenerated:false, reason:'retry_limit'} 로
--   조기 반환한다. 그 결과 **검수 카드는 사라지는데 후속 잡은 하나도 서지 않는다** —
--   작업지시는 status='open' 인 채 잡 없이 멈춘다. 화면에 남은 신호는 대시보드가 한 번
--   띄우는 토스트뿐이었고, 사용자는 그걸 놓쳐 "카드가 그냥 사라졌다"고 인지했다.
--   상한 자체는 설계대로다(0019 ③ — 2회까지, 그 다음은 사람 판단). 빠진 것은 '사람에게
--   넘겼다'는 사실을 화면에 세우는 자리다.
--
-- 이 마이그레이션이 하는 일 셋:
--  ① reject_review 전문 재정의(0055 본문 기반, 델타 3)
--     · 재생성이 못 서는 사유(busy · no_run_to_resume · no_chain · retry_limit)를 한
--       곳(v_reason)에서 고른다 — 판정 순서·반환 문구는 0055 와 동일하다.
--     · busy 를 뺀 나머지 셋은 **후속 잡이 하나도 안 서는** 상태다. 그 카드
--       payload 에 stalled = {reason,stage,tries,limit,at,by,note} 를 찍는다.
--       카드는 이미 rejected 라 검수함에서 사라지므로, 사라진 자리를 남기는 유일한
--       원장이 이 스탬프다(홈 경고줄·검수함 배지가 여기서 나온다).
--       busy 는 지금 체인이 돌고 있다 = 사람이 할 일이 없다 → 찍지 않는다.
--       p_regenerate=false('기록만 하고 다시 안 만들기')도 찍지 않는다 — 사람이 스스로
--       고른 길이라 '사람 판단 필요' 로 다시 부를 일이 아니다.
--     · 감사 로그에 stall 한 줄(_audit 'reject_stalled') — 토스트를 놓쳐도 원장에 남는다.
--  ② 부수 버그: avoid_spans 집계가 `scene_span IS NOT NULL` 로만 걸러 **jsonb null**
--     (SQL NULL 이 아니라 JSON 리터럴 null)을 통과시켰다. generate 결과에
--     "scene_span": null 이 실린 경로에서 v_span 이 jsonb 'null' 이 되어 들어간
--     행들이 있고, 그 워크오더의 avoid_spans 는 [null,null,null] 로 실린다. 엔진이
--     무시해 실행에 해는 없어 보이나 의도와 다르다 — jsonb_typeof <> 'null' 을 더한다.
--  ③ 뷰 stalled_work_orders — '지금도 멈춰 있는' 스탬프만 남긴다. 스탬프는 사건 기록이라
--     지워지지 않으므로, 해소 판정은 조회 시점에 한다:
--       · 작업지시가 아직 open (취소·완료면 끝난 얘기)
--       · 그 작업지시에 pending/running/blocked 잡이 하나도 없음 (다시 돌기 시작 = 해소)
--       · 그 뒤에 만들어진 검수 카드가 없음 (새 카드 = 사람이 볼 것이 다시 생김)
--     대시보드가 창(잡 150건·카드 120건)에 잘려 오판하지 않도록 DB 에서 센다.
--  ④ 소급 스탬프 — 이미 상한에 걸려 멈춰 있는 건(위 실사고 포함)은 스탬프가 없어 뷰에
--     안 잡힌다. 14일 이내 · 반려 시 재생성을 **요청했던**(감사 로그 regenerate=true)
--     건만 소급한다. 멱등(이미 stalled 가 있으면 건드리지 않는다).
--
-- 짝: 0019(반려 재생성 원판 · 상한 2회) · 0021(단계별 반려) · 0055(체인 스코핑 — 본문 베이스)
--     dashboard/index.html(홈 경고줄 · 검수함 배지 — 같은 커밋)
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
    v_reason text; v_stall jsonb; v_out jsonb;   -- 0074
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

    -- 최신 성공 generate — 이 잡의 체인만 되살린다(0055 ①). 편집 라운드가 있었다면
    -- 이 잡이 editrender 체인이고 params 에 병합 오버라이드(0053)가 실려 있다.
    -- created_at 순(0055 ③) — finished_at 은 재실행에 뒤집힌다.
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

    -- 돌던 체인 위에 얹지 않는다(0055 ②) — 반려 기록은 위에서 이미 남았다.
    SELECT id INTO v_busy FROM public.job_queue
     WHERE work_order_id = v_rq.work_order_id
       AND status IN ('pending','running','blocked')
       AND (kind = 'generate' OR idempotency_key LIKE 'editrender:%')
     LIMIT 1;

    SELECT count(*) INTO v_tries FROM public.rejected_takes
     WHERE work_order_id = v_rq.work_order_id;

    -- ── 0074: 재생성이 못 서는 사유를 한자리에서 고른다 ──────────────────
    -- 판정 순서는 0055 의 조기 반환 넷과 같다(busy → 이어달릴 run 없음 → 체인 없음 → 상한).
    --   · '제작'·'스토리 구성' 은 같은 run 을 이어달리므로 run_id 가 없으면 대상이 없다.
    v_reason := CASE
        WHEN v_busy IS NOT NULL                               THEN 'busy'
        WHEN v_resume AND (v_run IS NULL OR v_gen_id IS NULL) THEN 'no_run_to_resume'
        WHEN v_gen_id IS NULL                                 THEN 'no_chain'
        WHEN v_tries > v_limit                                THEN 'retry_limit'
        END;
    IF v_reason IS NOT NULL THEN
        v_out := jsonb_build_object('regenerated', false, 'reason', v_reason,
                                    'stage', v_stage, 'tries', v_tries);
        IF v_reason = 'busy' THEN
            -- 지금 체인이 돌고 있다 = 사람이 기다리면 된다. 멈춘 게 아니므로 안 찍는다.
            RETURN v_out || jsonb_build_object('job', v_busy);
        END IF;
        -- 여기부터는 후속 잡이 하나도 안 선다. 카드는 이미 rejected 라 검수함에서
        -- 사라졌으니, 사라진 자리를 카드 payload 에 남긴다 — 홈 경고줄·검수함 배지의 원천.
        v_stall := jsonb_build_object(
            'reason', v_reason, 'stage', v_stage, 'tries', v_tries, 'limit', v_limit,
            'at', now(), 'by', coalesce(auth.email(), auth.uid()::text),
            'run_id', v_run, 'note', nullif(btrim(coalesce(p_note,'')),''));
        UPDATE public.review_queue
           SET payload = coalesce(payload,'{}'::jsonb) || jsonb_build_object('stalled', v_stall)
         WHERE id = p_review_id;
        PERFORM public._audit('reject_stalled','review_queue',p_review_id::text,
                v_stall || jsonb_build_object('work_order_id', v_rq.work_order_id));
        RETURN v_out || jsonb_build_object('stalled', true);
    END IF;

    -- 회피 구간: 새로 장면을 고르는 단계에서만 쓴다. '제작' 은 같은 구간을 그대로 다시
    -- 렌더하는 게 목적이라 회피 목록을 주면 자기 자신과 100% 겹쳐 매번 실패한다(0021 ⓐ).
    IF v_stage = '제작' THEN
        v_avoid := NULL;
    ELSE
        -- 0074 ②: jsonb 'null'(SQL NULL 아님)도 거른다 — 안 그러면 avoid_spans 가
        -- [null,null,null] 로 실린다(실측). IS NOT NULL 은 jsonb null 을 못 거른다.
        SELECT coalesce(jsonb_agg(scene_span), '[]'::jsonb) INTO v_avoid
          FROM public.rejected_takes
         WHERE work_order_id = v_rq.work_order_id
           AND scene_span IS NOT NULL AND jsonb_typeof(scene_span) <> 'null';
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
    -- 체인의 succeeded 잡은 건드리지 않는다(0055 ① — 8/19 사고의 직접 원인).
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
COMMENT ON FUNCTION public.reject_review(uuid, text, text, boolean) IS
  '반려 + 재생성(0019·0021·0055). 재생성이 못 서면(상한·체인 없음) 카드 payload.stalled 에
   ''사람 판단 필요'' 를 남긴다(0074) — 카드는 rejected 라 검수함에서 사라지기 때문.';

-- ── ③ 지금도 멈춰 있는 작업지시 — 홈 경고줄·검수함 배지의 정본 ──────────
-- 스탬프는 사건 기록(지우지 않는다). '아직 멈춰 있는가' 는 조회 시점에 판정한다.
CREATE OR REPLACE VIEW public.stalled_work_orders
WITH (security_invoker = true) AS
  SELECT rq.id                                        AS review_id,
         rq.work_order_id,
         coalesce(rq.channel_slug, w.channel_slug)     AS channel_slug,
         w.work_title, w.episode, w.service_date, w.pipeline,
         rq.kind                                       AS review_kind,
         rq.payload->'stalled'->>'reason'              AS reason,
         rq.payload->'stalled'->>'stage'               AS stage,
         (rq.payload->'stalled'->>'tries')::int        AS tries,
         (rq.payload->'stalled'->>'limit')::int        AS retry_limit,
         coalesce((rq.payload->'stalled'->>'at')::timestamptz, rq.decided_at) AS stalled_at,
         rq.payload->'stalled'->>'by'                  AS stalled_by,
         coalesce(rq.payload->'stalled'->>'note', rq.decision_note) AS note,
         (rq.payload->'stalled'->>'backfilled')::boolean AS backfilled,
         rq.decided_at, rq.decision_note
    FROM public.review_queue rq
    JOIN public.work_orders w ON w.id = rq.work_order_id
   WHERE rq.status = 'rejected'
     AND rq.payload ? 'stalled'
     AND w.status = 'open'                       -- 취소되면 끝난 얘기(파이프라인은 open/cancelled 만 쓴다)
     AND NOT EXISTS (                            -- 다시 돌기 시작했으면 해소
           SELECT 1 FROM public.job_queue j
            WHERE j.work_order_id = rq.work_order_id
              AND j.status IN ('pending','running','blocked'))
     AND NOT EXISTS (                            -- 그 뒤 새 카드가 생겼으면 해소
           SELECT 1 FROM public.review_queue n
            WHERE n.work_order_id = rq.work_order_id
              AND n.created_at > rq.created_at);
COMMENT ON VIEW public.stalled_work_orders IS
  '재생성이 못 서서 사람 판단으로 넘어간 채 아직 멈춰 있는 작업지시(0074).
   해소 조건: 작업지시 취소·완료 / 대기·실행 잡이 다시 섬 / 뒤에 새 검수 카드가 생김.';
GRANT SELECT ON public.stalled_work_orders TO authenticated;

-- ── ④ 소급 스탬프 — 이미 멈춰 있는 건(실사고 포함)을 뷰에 태운다 ────────
-- 조건은 뷰의 해소 판정과 같고, 여기에 '상한 초과(rejected_takes > 2)' 와
-- '반려 시 재생성을 요청했었다(감사 로그 regenerate=true)' 를 더한다 —
-- p_regenerate=false 로 사람이 스스로 멈춘 건까지 '사람 판단 필요' 로 부르지 않기 위해서다.
-- 14일 컷: 그보다 오래된 건은 이미 다른 방식으로 정리됐다고 본다(대시보드 unpublished 와 동일 컷).
UPDATE public.review_queue rq
   SET payload = rq.payload || jsonb_build_object('stalled', jsonb_build_object(
         'reason', 'retry_limit',
         'stage',  coalesce((SELECT t.stage FROM public.rejected_takes t
                              WHERE t.work_order_id = rq.work_order_id
                              ORDER BY t.rejected_at DESC LIMIT 1), '영상 분석'),
         'tries',  (SELECT count(*) FROM public.rejected_takes t
                     WHERE t.work_order_id = rq.work_order_id),
         'limit',  2,
         'at',     rq.decided_at,
         'by',     rq.decided_by,
         'run_id', rq.payload->>'run_id',
         'note',   nullif(btrim(coalesce(rq.decision_note,'')),''),
         'backfilled', true))
  FROM public.work_orders w
 WHERE w.id = rq.work_order_id
   AND rq.status = 'rejected'
   AND NOT (rq.payload ? 'stalled')
   AND w.status = 'open'
   AND rq.decided_at > now() - interval '14 days'
   AND (SELECT count(*) FROM public.rejected_takes t
         WHERE t.work_order_id = rq.work_order_id) > 2
   AND EXISTS (SELECT 1 FROM public.dashboard_actions a
                WHERE a.action = 'reject' AND a.target_kind = 'review_queue'
                  AND a.target_id = rq.id::text
                  AND coalesce(a.payload->>'regenerate','true') = 'true')
   AND NOT EXISTS (SELECT 1 FROM public.job_queue j
                    WHERE j.work_order_id = rq.work_order_id
                      AND j.status IN ('pending','running','blocked'))
   AND NOT EXISTS (SELECT 1 FROM public.review_queue n
                    WHERE n.work_order_id = rq.work_order_id
                      AND n.created_at > rq.created_at);

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0074','claude (재생성 상한 반려를 홈 경고줄·검수함에 세운다 — HANIPJUMAK 가왕쇼 8/22 · avoid_spans jsonb null 필터)')
ON CONFLICT DO NOTHING;
