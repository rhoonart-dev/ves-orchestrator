-- 0018: 발행 잡 파라미터 결손 수정 (2026-08-11 실측 — 몰입도둑 SNL8 발행 실패)
-- 증상: publish 가 "영상 파일 못 찾음 (run=None)" 로 permanent 사망.
-- 원인 3겹: ① approve_and_publish 가 run_id/run_dir 를 params 에 넣지 않음
--          ② review_queue.clip_id 가 NULL(evaluate 가 payload 에만 run_id 를 넣었다)
--          ③ 노드 고정 없음 — 산출물이 있는 노드(generate 실행 노드)가 아닌 곳에 떨어질 수 있다
-- 처방: RPC 가 generate/evaluate 결과에서 정본을 끌어와 params 를 완성하고 node 를 고정한다.
--       (어댑터에도 Storage 폴백을 넣어 노드 의존 자체를 없앴다 — 이중 방어)

CREATE OR REPLACE FUNCTION public.approve_and_publish(
    p_review_id uuid, p_privacy text,
    p_publish_at timestamptz DEFAULT NULL, p_note text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public','extensions'
AS $function$
DECLARE
    v_rq record; v_job uuid;
    v_run_id text; v_run_dir text; v_node text; v_clip uuid; v_caps text[];
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    IF p_privacy NOT IN ('private','unlisted','public') THEN
        RAISE EXCEPTION 'invalid privacy %', p_privacy; END IF;

    SELECT rq.id, rq.work_order_id, rq.clip_id, rq.channel_slug, rq.payload,
           wo.geoblock_required, wo.episode
      INTO v_rq
      FROM public.review_queue rq
      JOIN public.work_orders wo ON wo.id = rq.work_order_id
     WHERE rq.id = p_review_id AND rq.kind = 'publish_gate' AND rq.status = 'waiting'
     FOR UPDATE OF rq;
    IF NOT FOUND THEN RAISE EXCEPTION 'review not waiting'; END IF;

    IF v_rq.geoblock_required AND p_privacy NOT IN ('private','unlisted') THEN
        RAISE EXCEPTION 'R9-a: geoblock-required work — Studio manual only'; END IF;
    IF p_publish_at IS NOT NULL AND p_privacy <> 'private' THEN
        RAISE EXCEPTION 'R9-c: publish_at requires privacy=private'; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.channels_mirror
                    WHERE token_slug = v_rq.channel_slug) THEN
        RAISE EXCEPTION 'R10: unknown channel %', v_rq.channel_slug; END IF;

    -- ① 산출물 정본: generate 결과(run_id·run_dir·실행 노드)
    SELECT j.result->>'run_id', j.result->>'run_dir', j.node_id
      INTO v_run_id, v_run_dir, v_node
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id AND j.kind = 'generate'
       AND j.status = 'succeeded'
     ORDER BY j.finished_at DESC NULLS LAST LIMIT 1;
    v_run_id := coalesce(v_run_id, v_rq.payload->>'run_id');   -- 검수 카드 폴백
    IF v_run_id IS NULL THEN
        RAISE EXCEPTION '발행 불가: run_id 를 찾을 수 없습니다(generate 결과·검수 payload 모두 없음)';
    END IF;

    -- ② clip_id: 검수행 → evaluate 결과 → clip_metadata(정본) 순
    v_clip := v_rq.clip_id;
    IF v_clip IS NULL THEN
        SELECT (j.result->>'clip_id')::uuid INTO v_clip
          FROM public.job_queue j
         WHERE j.work_order_id = v_rq.work_order_id AND j.kind = 'evaluate'
           AND j.status = 'succeeded' AND j.result ? 'clip_id'
         ORDER BY j.finished_at DESC NULLS LAST LIMIT 1;
    END IF;
    IF v_clip IS NULL THEN
        SELECT m.clip_id INTO v_clip
          FROM public.clip_metadata m WHERE m.ai_video_run_id = v_run_id LIMIT 1;
    END IF;
    IF v_clip IS NULL THEN
        RAISE EXCEPTION '발행 불가: clip_id 를 찾을 수 없습니다(run=%) — ingest/evaluate 확인', v_run_id;
    END IF;

    UPDATE public.review_queue
       SET status='approved', decided_by=auth.uid()::text, decided_at=now(),
           decision_note=p_note, clip_id=coalesce(clip_id, v_clip)
     WHERE id = p_review_id;

    -- ③ 산출물이 있는 노드로 고정(어댑터 Storage 폴백이 있어도 로컬이 빠르고 안전)
    v_caps := CASE WHEN v_node IS NULL THEN ARRAY['publish']
                   ELSE ARRAY['publish', 'node:' || v_node] END;

    INSERT INTO public.job_queue(work_order_id, kind, params, idempotency_key, required_caps)
    VALUES (v_rq.work_order_id, 'publish',
            jsonb_build_object('clip_id', v_clip, 'channel_slug', v_rq.channel_slug,
                               'channel_name', (SELECT name FROM public.channels_mirror
                                                 WHERE token_slug = v_rq.channel_slug),
                               'run_id', v_run_id, 'run_dir', v_run_dir,
                               'episode', v_rq.episode,   -- 설명란 'N화' 줄(실측 경고 방지)
                               'privacy', p_privacy, 'publish_at', p_publish_at),
            encode(digest(v_rq.work_order_id::text||'publish'||coalesce(v_clip::text,''),
                          'sha256'),'hex'),
            v_caps)
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_job;

    PERFORM public._audit('approve_publish','review_queue',p_review_id::text,
            jsonb_build_object('privacy',p_privacy,'publish_at',p_publish_at,
                               'run_id',v_run_id,'clip_id',v_clip,'node',v_node));
    RETURN v_job;
END $function$;
