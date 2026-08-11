-- 0019: 반려 → 자동 재생성 (2026-08-11, 컷오버 후 필수)
-- 배경: 구 시스템(scene_loop)에는 검증된 반려 정책이 있었다(2026-07-30) —
--   ① 반려는 회차 슬롯을 돌려준다(교착 방지)
--   ② 반려 구간은 회피 목록에 남겨 같은 장면을 다시 만들지 않는다
--   ③ 중복이면 최대 2회 재생성, 그래도 겹치면 사람에게
-- VES 의 reject_review 는 '기록만' 했다 — 컷오버 이후엔 반려 = 그날 그 채널 공백.
-- 사용자 결정(8/11): 2회까지 · 즉시 · 원본을 만든 같은 맥에서.
-- 추가(8/11): 반려 시 재생성 여부를 사람에게 묻는다 — p_regenerate=false 면 기록만 한다.

-- 반려 이력(회피 구간의 원장). work_order 단위로 쌓인다.
CREATE TABLE IF NOT EXISTS public.rejected_takes (
    id           bigserial PRIMARY KEY,
    work_order_id uuid NOT NULL REFERENCES public.work_orders(id) ON DELETE CASCADE,
    run_id       text,
    kind         text NOT NULL DEFAULT '장면',     -- 장면 | 제작
    scene_span   jsonb,                            -- [start, end] 초
    note         text,
    rejected_by  text,
    rejected_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rejected_takes_wo ON public.rejected_takes(work_order_id);
ALTER TABLE public.rejected_takes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rt_read ON public.rejected_takes;
CREATE POLICY rt_read ON public.rejected_takes FOR SELECT TO authenticated USING (true);

CREATE OR REPLACE FUNCTION public.reject_review(
    p_review_id uuid, p_note text DEFAULT NULL, p_kind text DEFAULT NULL,
    p_regenerate boolean DEFAULT true)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public'
AS $function$
DECLARE
    v_rq record; v_kind text; v_run text; v_span jsonb; v_node text;
    v_tries int; v_avoid jsonb; v_gen uuid; v_limit int := 2;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'permission denied'; END IF;

    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload
      INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.status = 'waiting'
     FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'review not waiting'; END IF;

    -- 반려 유형: 명시 인자 > 메모 접두사('[장면] …') > 기본 '장면'
    v_kind := coalesce(p_kind,
        CASE WHEN p_note LIKE '[제작]%' THEN '제작'
             WHEN p_note LIKE '[장면]%' THEN '장면' ELSE NULL END, '장면');

    UPDATE public.review_queue
       SET status='rejected', decided_by=auth.uid()::text, decided_at=now(),
           decision_note=p_note
     WHERE id = p_review_id;

    -- 이 반려의 근거(run_id·구간·실행 노드)를 제작 잡에서 가져온다
    SELECT j.result->>'run_id', j.result->'scene_span', j.node_id
      INTO v_run, v_span, v_node
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id AND j.kind='generate'
       AND j.status='succeeded'
     ORDER BY j.finished_at DESC NULLS LAST LIMIT 1;
    v_run := coalesce(v_run, v_rq.payload->>'run_id');

    INSERT INTO public.rejected_takes(work_order_id, run_id, kind, scene_span, note, rejected_by)
    VALUES (v_rq.work_order_id, v_run, v_kind, v_span, p_note, auth.uid()::text);

    PERFORM public._audit('reject','review_queue',p_review_id::text,
            jsonb_build_object('note',p_note,'kind',v_kind,'run_id',v_run,
                               'regenerate',p_regenerate));

    -- 사람이 '재생성 안 함'을 고르면 여기서 끝(8/11 사용자 요청: 반려 시 재실행 여부를 묻는다).
    -- 구간은 회피 목록에 남는다 — 나중에 그 회차를 다시 돌려도 같은 장면을 피한다.
    IF NOT coalesce(p_regenerate, true) THEN
        RETURN jsonb_build_object('regenerated', false, 'reason', 'user_declined',
                                  'kind', v_kind);
    END IF;

    SELECT count(*) INTO v_tries FROM public.rejected_takes
     WHERE work_order_id = v_rq.work_order_id;
    IF v_tries > v_limit THEN     -- ③ 상한 초과 — 사람 몫으로 남긴다(자동 재생성 중단)
        RETURN jsonb_build_object('regenerated', false, 'reason', 'retry_limit',
                                  'tries', v_tries, 'kind', v_kind);
    END IF;

    -- ② 회피 구간 누적(같은 장면 재생산 금지)
    SELECT coalesce(jsonb_agg(scene_span), '[]'::jsonb) INTO v_avoid
      FROM public.rejected_takes
     WHERE work_order_id = v_rq.work_order_id AND scene_span IS NOT NULL;

    -- ① 같은 work_order 의 제작~검사 잡을 되돌린다 — 새 WO 를 만들지 않으므로
    --    회차 사용 횟수를 추가로 쓰지 않는다(=슬롯을 돌려준다). acquire 는 그대로 둔다(캐시 재사용).
    UPDATE public.job_queue j
       SET status='pending', node_id=NULL, error=NULL, error_class=NULL, attempt=0,
           lease_expires_at=NULL, finished_at=NULL, result=NULL,
           run_after=now(), updated_at=now(),
           params = CASE WHEN j.kind='generate' THEN
                      (j.params - 'resume_run_id' - 'from_step')
                      || jsonb_build_object('avoid_spans', v_avoid)
                      || CASE WHEN v_kind='제작' AND v_run IS NOT NULL
                              THEN jsonb_build_object('resume_run_id', v_run, 'from_step', 'render')
                              ELSE '{}'::jsonb END
                    ELSE j.params END,
           -- 즉시·같은 맥(사용자 결정): 원본을 만든 노드로 고정
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

    RETURN jsonb_build_object('regenerated', true, 'kind', v_kind, 'tries', v_tries,
                              'node', v_node, 'avoid', v_avoid,
                              'mode', CASE WHEN v_kind='제작' THEN 'resume_render' ELSE 'fresh_scene' END);
END $function$;
REVOKE ALL ON FUNCTION public.reject_review(uuid, text, text, boolean) FROM public;
GRANT EXECUTE ON FUNCTION public.reject_review(uuid, text, text, boolean) TO authenticated;
