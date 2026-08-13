-- =====================================================================
-- 0027_episode_per_video.sql — 유튜브 소스 영상 단위 회차 체계 (운영 합의 2026-08-13)
--
-- 배경: 유튜브 소스의 "회차"가 목록 위치 순번이라 ① 설명란에 방송 회차가 아닌
-- 순번이 박히고(놀라운 토요일 23·25 실측) ② 3분 이하 영상이 번호만 소비하고
-- ③ 영상 분량과 무관하게 일괄 3편이었다. 개편:
--   · episode = 원본 방송 회차(제목 파싱). 같은 회차에 영상 여러 개 허용
--   · 멱등키를 (작품, 회차) → (작품, 영상 URL)로 — "같은 영상인가"는 URL 이 판단
--   · episode_source('parsed'|'ordinal') — 서수 폴백 여부. 설명란 표기 생략의 근거
--   · published_ts — 업로드 시각. 회차 안에서의 소비 순서(등록시각은 재실행 순서에
--     따라 어긋날 수 있어 원본 시각을 남긴다)
-- 사용량 집계는 planner 가 소스 행(sha/url) 단위로 전환 — 코드 쪽 참조.
-- =====================================================================

ALTER TABLE public.sources ADD COLUMN IF NOT EXISTS episode_source text
  CHECK (episode_source IN ('parsed','ordinal'));
ALTER TABLE public.sources ADD COLUMN IF NOT EXISTS published_ts timestamptz;

-- 멱등키 교체: 같은 회차에 두 번째 영상을 등록할 수 있어야 한다.
-- (0012 의 (work_title, episode) 부분 유니크는 "회차가 같으면 같은 영상"으로 오인했다)
DROP INDEX IF EXISTS public.sources_url_uniq;
CREATE UNIQUE INDEX IF NOT EXISTS sources_video_uniq
  ON public.sources (work_title, source_url) WHERE source_url IS NOT NULL;

-- 백필: 기존 유튜브 행의 episode 는 전부 목록 위치 순번이었다 — ordinal 로 표시해
-- 설명란 'N화' 오표기를 막는다(재파싱 이행은 별도 결정 — 사용 이력 있는 행 주의).
UPDATE public.sources SET episode_source = 'ordinal'
 WHERE source_url IS NOT NULL AND episode IS NOT NULL AND episode_source IS NULL;
-- 드라이브 행은 파일명에서 파싱된 회차
UPDATE public.sources SET episode_source = 'parsed'
 WHERE source_url IS NULL AND episode IS NOT NULL AND episode_source IS NULL;

-- approve_and_publish: 서수 회차(episode_source='ordinal')는 설명란 'N화' 줄을 넣지
-- 않는다 — 방송 회차가 아닌 숫자를 공개 영상에 박지 않기 위해. 그 외는 0018 그대로.
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
           wo.geoblock_required, wo.episode, wo.source_sha256, wo.source_url
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

    -- 0027: 이 WO 의 소스 행이 서수 회차인지 — 서수면 설명란 표기를 생략한다
    SELECT EXISTS (
        SELECT 1 FROM public.sources s
         WHERE ((v_rq.source_sha256 IS NOT NULL AND s.sha256 = v_rq.source_sha256)
             OR (v_rq.source_sha256 IS NULL AND v_rq.source_url IS NOT NULL
                 AND s.source_url = v_rq.source_url))
           AND s.episode_source = 'ordinal') INTO v_ep_ordinal;

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
VALUES ('orchestrator','0027','claude (영상 단위 회차 — 멱등키 URL 교체·episode_source·published_ts)')
ON CONFLICT DO NOTHING;
