-- 0021: 단계별 반려 + 사유 반영 재실행 (2026-08-12 사용자 결정)
--
-- 0019 는 반려 유형이 '장면'(처음부터) / '제작'(렌더만) 둘뿐이었다. 실사용에서 드러난 것:
--   ① 사람이 보는 불만은 세 가지로 갈린다 — 영상을 잘못 봤다 / 이야기를 잘못 짰다 / 화면이 별로다
--   ② 왜 반려했는지를 적어도 엔진이 못 읽어서, 재실행이 같은 실수를 되풀이했다
-- 그래서 ai-video 13단계에 맞춰 세 단계로 나누고, 사유를 --reject-note 로 엔진에 넘긴다.
--   영상 분석   → 새 run (처음부터)            · 40~70분 · 사유를 분석·스토리 프롬프트에 주입
--   스토리 구성 → 같은 run 의 story 단계부터    · 15~25분 · 사유를 스토리 프롬프트에 주입
--   제작        → 같은 run 의 render 단계부터   · 수 분   · 프롬프트를 안 쓰므로 사유 미주입
--
-- 함께 고치는 결함 두 가지(실측 근거):
--   ⓐ '제작' 반려는 같은 구간을 그대로 다시 렌더하는 게 정상인데, 0019 는 회피 구간까지 물려줬다.
--      → parse_result 의 중복 판정에 100% 걸려 매번 실패, 재생성이 영원히 성공할 수 없었다.
--      이제 '제작' 에는 avoid_spans 를 주지 않는다.
--   ⓑ 되돌리는 후속 잡(ingest/evaluate 등)의 params 에 옛 run_id·run_dir 이 남아 있으면
--      새 run 이 아니라 옛 run 을 읽는다(8/12 숏테토칩 실측: 6일 전 run 을 물고 dead).
--      → 되돌릴 때 그 두 키를 지운다.

ALTER TABLE public.rejected_takes ADD COLUMN IF NOT EXISTS stage text;
COMMENT ON COLUMN public.rejected_takes.stage IS '반려 단계: 영상 분석 | 스토리 구성 | 제작';

-- 0019 의 (uuid, text, text, boolean) 을 대체한다. 인자 이름이 p_kind → p_stage 로 바뀌므로
-- CREATE OR REPLACE 로는 못 바꾼다(인자명 변경 불가) — 지우고 새로 만든다.
-- ⚠ 열어둔 옛 관제 탭은 이 시점부터 반려가 실패한다. 새로고침하면 된다.
DROP FUNCTION IF EXISTS public.reject_review(uuid, text, text, boolean);

CREATE FUNCTION public.reject_review(
    p_review_id uuid, p_note text DEFAULT NULL, p_stage text DEFAULT NULL,
    p_regenerate boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public'
AS $function$
DECLARE
    v_rq record; v_stage text; v_run text; v_span jsonb; v_node text;
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

    SELECT j.result->>'run_id', j.result->'scene_span', j.node_id
      INTO v_run, v_span, v_node
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id AND j.kind='generate'
       AND j.status='succeeded'
     ORDER BY j.finished_at DESC NULLS LAST LIMIT 1;
    v_run := coalesce(v_run, v_rq.payload->>'run_id');

    INSERT INTO public.rejected_takes(work_order_id, run_id, kind, stage, scene_span,
                                      note, rejected_by)
    VALUES (v_rq.work_order_id, v_run, v_stage, v_stage, v_span, p_note, auth.uid()::text);

    PERFORM public._audit('reject','review_queue',p_review_id::text,
            jsonb_build_object('note',p_note,'stage',v_stage,'run_id',v_run,
                               'regenerate',p_regenerate,'from_step',v_step));

    IF NOT coalesce(p_regenerate, true) THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'user_declined',
                                  'stage', v_stage);
    END IF;

    -- '제작' 은 같은 run 을 이어달리므로 run_id 가 없으면 이어갈 대상이 없다.
    IF v_resume AND v_run IS NULL THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'no_run_to_resume',
                                  'stage', v_stage);
    END IF;

    SELECT count(*) INTO v_tries FROM public.rejected_takes
     WHERE work_order_id = v_rq.work_order_id;
    IF v_tries > v_limit THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'retry_limit',
                                  'tries', v_tries, 'stage', v_stage);
    END IF;

    -- 회피 구간: 새로 장면을 고르는 단계에서만 쓴다. '제작' 은 같은 구간을 그대로 다시
    -- 렌더하는 게 목적이라 회피 목록을 주면 자기 자신과 100% 겹쳐 매번 실패한다(결함 ⓐ).
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

    UPDATE public.job_queue j
       SET status='pending', node_id=NULL, error=NULL, error_class=NULL, attempt=0,
           lease_expires_at=NULL, finished_at=NULL, result=NULL,
           run_after=now(), updated_at=now(),
           params = CASE
                      WHEN j.kind='generate' THEN
                        (j.params - 'resume_run_id' - 'from_step' - 'avoid_spans'
                                  - 'reject_note') || v_patch
                      -- 후속 잡은 옛 run 을 물고 있으면 안 된다(결함 ⓑ) — 선행 결과에서 새로 받는다
                      ELSE j.params - 'run_id' - 'run_dir' END,
           required_caps = CASE WHEN v_node IS NULL THEN j.required_caps
                                WHEN j.required_caps @> ARRAY['node:'||v_node] THEN j.required_caps
                                ELSE array_remove(array_remove(array_remove(array_remove(
                                       array_remove(array_remove(j.required_caps,'node:mm-01'),
                                       'node:mm-02'),'node:mm-03'),'node:mm-04'),'node:mm-05'),'node:mm-06')
                                     || ARRAY['node:'||v_node] END
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind IN ('generate','upload_artifacts','ingest','evaluate','localize')
       AND j.status IN ('succeeded','failed','dead','cancelled');
    GET DIAGNOSTICS v_gen = ROW_COUNT;

    RETURN jsonb_build_object('regenerated', true, 'stage', v_stage, 'tries', v_tries,
                              'node', v_node, 'from_step', v_step, 'jobs', v_gen,
                              'avoid', v_avoid, 'note_applied', v_use_note,
                              'mode', CASE WHEN v_resume THEN 'resume' ELSE 'fresh' END);
END $function$;
REVOKE ALL ON FUNCTION public.reject_review(uuid, text, text, boolean) FROM public;
GRANT EXECUTE ON FUNCTION public.reject_review(uuid, text, text, boolean) TO authenticated;
