-- =====================================================================
-- 0033_publish_from_localization_qa.sql — 일본어 카드에서 바로 발행 (2026-08-14)
--
-- 사용자 결정 8/14: JP 채널 검수함에는 일본어판(localization_qa) 카드 하나만 —
-- 한국어 publish_gate 는 brain.Evaluate 가 더 이상 만들지 않는다(코드 532f131 후속).
-- 그런데 발행 RPC 가 kind='publish_gate' 만 받아, 일본어 카드의 '합격 · 발행' 버튼이
-- 'review not waiting' 으로 죽는다. 0027 판 그대로에 두 가지만 바꾼다:
--   ① 대상 kind 를 ('publish_gate','localization_qa') 로.
--   ② 승인 시 같은 작업지시의 다른 waiting 게이트 카드를 자동 종결 —
--      과도기 잔재(한국어 카드)가 이중 발행 버튼이 되는 것을 막는다.
-- 발행 산출물은 무변경: generate 의 run_dir/shorts.mp4 — scene_rerender 가 이미
-- 일본어판으로 교체해 두었다(vlp scripts/localize_run.py L4).
-- =====================================================================

CREATE OR REPLACE FUNCTION public.approve_and_publish(
    p_review_id uuid, p_privacy text,
    p_publish_at timestamptz DEFAULT NULL, p_note text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public','extensions'
AS $function$
DECLARE
    v_rq record; v_job uuid;
    v_run_id text; v_run_dir text; v_node text; v_clip uuid; v_caps text[];
    v_ep_ordinal boolean;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    IF p_privacy NOT IN ('private','unlisted','public') THEN
        RAISE EXCEPTION 'invalid privacy %', p_privacy; END IF;

    SELECT rq.id, rq.work_order_id, rq.clip_id, rq.channel_slug, rq.payload,
           wo.geoblock_required, wo.episode, wo.work_title,
           wo.source_sha256, wo.source_url
      INTO v_rq
      FROM public.review_queue rq
      JOIN public.work_orders wo ON wo.id = rq.work_order_id
     WHERE rq.id = p_review_id AND rq.status = 'waiting'
       -- 0033: JP 파이프라인은 일본어판 카드(localization_qa)가 유일한 게이트다
       -- (사용자 결정 8/14: 한국어 publish_gate 는 만들지도, 보여주지도 않는다)
       AND rq.kind IN ('publish_gate','localization_qa')
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

    -- 0027: 이 WO 의 소스 행이 서수 회차인지 — 서수면 설명란 표기를 생략한다.
    -- 매칭은 wo_matches_source 정본을 쓴다(work_title 포함) — 같은 URL 이 다른 작품에도
    -- 등록돼 있으면 그쪽 행의 episode_source 가 판정을 뒤집는다.
    SELECT EXISTS (
        SELECT 1 FROM public.sources s
         WHERE public.wo_matches_source(v_rq.work_title, v_rq.source_sha256,
                                        v_rq.source_url, s.work_title, s.sha256,
                                        s.source_url)
           AND s.episode_source = 'ordinal') INTO v_ep_ordinal;

    UPDATE public.review_queue
       SET status='approved', decided_by=auth.uid()::text, decided_at=now(),
           decision_note=p_note, clip_id=coalesce(clip_id, v_clip)
     WHERE id = p_review_id;

    -- 0033: 같은 작업지시의 자매 게이트 카드 자동 종결 — 발행 결정은 하나면 된다.
    -- (JP 컷오버 이전에 만들어진 한국어 publish_gate 잔재가 waiting 으로 남아
    --  이중 발행 버튼이 되는 것을 막는다. LOOPY 카드는 work_order_id 가 NULL 이라 무관)
    UPDATE public.review_queue
       SET status='approved', decided_by=auth.uid()::text, decided_at=now(),
           decision_note='0033: 자매 카드 자동 종결(같은 작업지시의 발행 승인에 수반)'
     WHERE work_order_id = v_rq.work_order_id AND id <> p_review_id
       AND kind IN ('publish_gate','localization_qa') AND status = 'waiting';

    -- ③ 산출물이 있는 노드로 고정(어댑터 Storage 폴백이 있어도 로컬이 빠르고 안전)
    v_caps := CASE WHEN v_node IS NULL THEN ARRAY['publish']
                   ELSE ARRAY['publish', 'node:' || v_node] END;

    INSERT INTO public.job_queue(work_order_id, kind, params, idempotency_key, required_caps)
    VALUES (v_rq.work_order_id, 'publish',
            jsonb_build_object('clip_id', v_clip, 'channel_slug', v_rq.channel_slug,
                               'channel_name', (SELECT name FROM public.channels_mirror
                                                 WHERE token_slug = v_rq.channel_slug),
                               'run_id', v_run_id, 'run_dir', v_run_dir,
                               -- 설명란 'N화' 줄 — 서수 회차는 생략(0027)
                               'episode', CASE WHEN v_ep_ordinal THEN NULL
                                               ELSE v_rq.episode END,
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

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0033','claude (approve_and_publish 가 localization_qa 를 받는다 — JP 일본어 카드 단일 게이트)')
ON CONFLICT DO NOTHING;
