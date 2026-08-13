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
--
-- ★사용량 집계가 (작품, 회차) → 소스 **행**(sha/url) 단위로 바뀐다. 세는 곳이
--  여섯 군데라 하나라도 빠지면 planner 와 관제가 서로 다른 숫자를 본다. 전부 여기서
--  같은 규칙(wo_matches_source)으로 맞춘다:
--    ① planner._pick_source · ② source_watch.REMAIN_SQL  (코드 — 같은 규칙을 SQL 로 씀)
--    ③ source_usage 뷰(0010) · ④ source_usage_by_channel 뷰(0023)
--    ⑤ run_channel_now(0024, 관제 '작업 실행') · ⑥ set_source_limit(0024)
--  set_source_used(0024)는 레거시 장부(source_usage_legacy)가 회차 단위 스키마라
--  그대로 둔다 — pick_from_rows 가 '앞선 행부터 차감'으로 흡수한다.
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

-- =====================================================================
-- 소스 행 ↔ 작업지시 매칭의 **정본**. 회차가 아니라 "같은 영상인가"로 센다.
--   · 드라이브 행(sha 있음)은 sha256 으로 — 같은 회차에 파일이 여럿이어도 각자 한도
--   · 유튜브 행(sha 없음)은 URL 로 — 같은 회차에 영상이 여럿이어도 각자 한도
--   · work_title 을 반드시 함께 본다: 새 멱등키가 (work_title, source_url) 이라
--     같은 URL 이 두 작품에 등록될 수 있고, 그때 한쪽 WO 가 다른 쪽 한도를 먹는다.
-- IMMUTABLE 순수 SQL 이라 플래너가 인라인한다(인덱스 사용 그대로).
-- 세는 곳이 바뀌면 반드시 이 함수만 고친다 — 규칙이 흩어지면 또 어긋난다.
-- =====================================================================
CREATE OR REPLACE FUNCTION public.wo_matches_source(
    w_work text, w_sha text, w_url text,
    s_work text, s_sha text, s_url text)
RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT w_work = s_work
       AND ((s_sha IS NOT NULL AND w_sha = s_sha)
         OR (s_sha IS NULL AND s_url IS NOT NULL AND w_url = s_url));
$$;
COMMENT ON FUNCTION public.wo_matches_source(text,text,text,text,text,text) IS
  '작업지시가 이 소스 행을 쓴 것인가 — 회차가 아니라 sha/URL 로 판정(0027 영상 단위 회차).';

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
           wo.geoblock_required, wo.episode, wo.work_title,
           wo.source_sha256, wo.source_url
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

-- =====================================================================
-- ③ source_usage 뷰(0010) — 전 채널 합계. 회차 조인 → 행 매칭.
--    종전 조인은 같은 회차의 다른 파일이 쓴 WO 까지 이 행의 times_used 로 셌다
--    (혜미리예채파 5화 3행 실측: 한 파일만 써도 세 행 모두 '3번 씀'으로 보였다).
--
-- ⚠ CREATE OR REPLACE VIEW 는 컬럼을 지우지 못한다("cannot drop columns from view").
--   0010 정의만 보고 쓰면 안 되고, 그 뒤 마이그레이션이 덧붙인 컬럼을 **순서까지**
--   그대로 유지해야 한다 — duration_sec 는 0022 가 마지막에 붙였다.
--   security_invoker 도 반드시 명시한다(0024 가 복구한 값). 빠뜨리면 조회자 권한이
--   아니라 뷰 소유자 권한으로 돌아 RLS 를 우회한다.
-- =====================================================================
CREATE OR REPLACE VIEW public.source_usage
WITH (security_invoker = true) AS
SELECT s.id AS source_id, s.work_title, s.episode, s.use_limit, s.is_active,
       s.bytes, s.has_subtitle,
       COUNT(w.id) FILTER (WHERE w.status NOT IN ('cancelled','failed')) AS times_used,
       GREATEST(s.use_limit - COUNT(w.id) FILTER (WHERE w.status NOT IN ('cancelled','failed')), 0) AS remaining,
       s.duration_sec                     -- 0022 추가분 — 순서 유지 필수(맨 뒤)
FROM public.sources s
LEFT JOIN public.work_orders w
  ON public.wo_matches_source(w.work_title, w.source_sha256, w.source_url,
                              s.work_title, s.sha256, s.source_url)
GROUP BY s.id;

GRANT SELECT ON public.source_usage TO authenticated;

-- =====================================================================
-- ④ source_usage_by_channel 뷰(0023) — 채널별 소진. 컬럼 구조는 그대로 두고
--    used_wo 집계만 행 단위로. 대시보드가 이 뷰를 그대로 읽는다(하위 호환 유지).
--    used_legacy 는 레거시 장부가 회차 단위라 종전대로 회차로 붙인다 — 회차에 행이
--    여럿이면 같은 레거시 값이 각 행에 보이므로, 화면 합산은 행 단위로 하되
--    레거시는 회차당 한 번만 세야 한다(대시보드 buildEpMap 참조).
-- =====================================================================
CREATE OR REPLACE VIEW public.source_usage_by_channel
WITH (security_invoker = true) AS     -- 0024 복구분 — 생략하면 RLS 를 우회한다
SELECT s.id                AS source_id,
       s.work_title,
       s.episode,
       c.channel_slug,
       s.use_limit,
       s.is_active,
       s.duration_sec,
       c.used_wo,
       c.used_legacy,
       c.used_wo + c.used_legacy                                   AS used_total,
       GREATEST(s.use_limit - (c.used_wo + c.used_legacy), 0)      AS remaining
  FROM public.sources s
  JOIN LATERAL (
        SELECT ch.channel_slug,
               (SELECT count(*) FROM public.work_orders w
                 WHERE public.wo_matches_source(w.work_title, w.source_sha256,
                                                w.source_url, s.work_title,
                                                s.sha256, s.source_url)
                   AND w.channel_slug = ch.channel_slug
                   AND w.status NOT IN ('cancelled','failed'))     AS used_wo,
               coalesce((SELECT l.used FROM public.source_usage_legacy l
                          WHERE l.work_title = s.work_title
                            AND l.episode IS NOT DISTINCT FROM s.episode
                            AND l.channel_slug = ch.channel_slug), 0) AS used_legacy
          FROM (SELECT cm.token_slug AS channel_slug
                  FROM public.channels_mirror cm
                 WHERE cm.works @> ARRAY[s.work_title]) ch
       ) c ON true;

GRANT SELECT ON public.source_usage_by_channel TO authenticated;

-- =====================================================================
-- ⑤ run_channel_now(0024) — 관제 '작업 실행'. 소스 고르는 규칙을 planner 와 맞춘다.
--    이걸 안 고치면: 같은 회차 영상 A·B 중 A 만 소진돼도 회차 전체가 소진으로 보여
--    planner 는 B 를 배정하는데 관제는 '쓸 수 있는 소스가 없습니다'로 막힌다.
--    바뀌는 것 — ① 소진 집계를 행 단위로 ② 정렬에 published_ts 반영
--                ③ 레거시(회차 단위)는 그 회차의 앞선 행부터 차감(pick_from_rows 와 동일)
--    나머지(권한·파이프라인·지오블락·잡 체인)는 0024 그대로다.
-- =====================================================================
CREATE OR REPLACE FUNCTION public.run_channel_now(
    p_slug text, p_work text DEFAULT NULL, p_episode integer DEFAULT NULL,
    p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_ch      record;
    v_src     public.sources%ROWTYPE;      -- %ROWTYPE 은 전 필드 NULL 로 초기화된다
    v_try     text;
    v_work    text;
    v_found   boolean := false;
    v_pipe    text;
    v_geo     boolean;
    v_wo      uuid;
    v_prev    uuid := NULL;
    v_common  jsonb;
    v_step    record;
    v_jobs    int := 0;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;

    SELECT m.token_slug, m.name, m.gcp_project, m.country, m.pipeline,
           coalesce(o.works, m.works) AS works
      INTO v_ch
      FROM public.channels_mirror m
      LEFT JOIN public.channel_works_overrides o ON o.token_slug = m.token_slug
     WHERE m.token_slug = p_slug;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 채널: %', p_slug; END IF;

    -- 전용 파이프라인(§10-①)은 작업지시 체인이 아니라 일일 자동화 잡으로 돈다
    IF v_ch.pipeline = 'zanmang_autopilot' THEN
        RAISE EXCEPTION '%: 전용 파이프라인 채널입니다 — zanmang_daily(매일 10시)가 담당합니다',
                        v_ch.name;
    END IF;

    v_pipe := CASE WHEN v_ch.country = 'JP' THEN 'shorts_jp_localized' ELSE 'shorts_kr' END;
    IF v_pipe = 'shorts_jp_localized'
       AND coalesce((SELECT value FROM public.ops_config WHERE key='jp_pipeline'), '') <> 'on' THEN
        RAISE EXCEPTION 'JP 파이프라인 스위치가 꺼져 있습니다 — 구 현지화 autopilot 과 이중 생산이 됩니다';
    END IF;

    -- 권리 안전장치: 그 채널에 배정된 작품만. 배정을 바꾸려면 채널 템플릿에서 먼저 바꾼다
    -- (set_channel_plan 과 같은 규칙).
    IF p_work IS NOT NULL AND NOT (p_work = ANY (v_ch.works)) THEN
        RAISE EXCEPTION '이 채널의 작품이 아닙니다: % (유효 작품: %)',
                        p_work, array_to_string(v_ch.works, ', ');
    END IF;

    -- 소스 고르기 — planner._pick_source · pick_from_rows 와 같은 규칙:
    --   활성 · 3분 초과 · 회차→업로드시각 순 · 소진은 이 채널 몫만, 행 단위로 센다(0027)
    FOREACH v_try IN ARRAY (CASE WHEN p_work IS NULL THEN v_ch.works ELSE ARRAY[p_work] END)
    LOOP
        SELECT s.* INTO v_src
          FROM (
            SELECT s2.*,
                   (SELECT count(*) FROM public.work_orders w
                     WHERE public.wo_matches_source(w.work_title, w.source_sha256,
                                                    w.source_url, s2.work_title,
                                                    s2.sha256, s2.source_url)
                       AND w.channel_slug = p_slug
                       AND w.status NOT IN ('cancelled','failed'))          AS used_wo,
                   -- 레거시(회차 단위)를 그 회차의 앞선 행부터 차감한 누적치.
                   -- 앞 행들이 남긴 여유분을 먼저 먹고, 남은 것만 이 행에 실린다.
                   coalesce((SELECT l.used FROM public.source_usage_legacy l
                              WHERE l.work_title = s2.work_title
                                AND l.episode IS NOT DISTINCT FROM s2.episode
                                AND l.channel_slug = p_slug), 0)            AS legacy_ep,
                   coalesce(sum(GREATEST(s2.use_limit, 0)) OVER (
                       PARTITION BY s2.work_title, s2.episode
                       ORDER BY coalesce(s2.published_ts, s2.created_at), s2.id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS limit_before
              FROM public.sources s2
             WHERE s2.work_title = v_try
               AND s2.is_active
               AND (s2.duration_sec IS NULL OR s2.duration_sec > 180)
               AND (p_episode IS NULL OR s2.episode = p_episode)
          ) s
         WHERE s.used_wo + GREATEST(s.legacy_ep - s.limit_before, 0) < s.use_limit
         ORDER BY s.episode NULLS LAST,
                  coalesce(s.published_ts, s.created_at), s.id
         LIMIT 1;
        IF FOUND THEN
            v_found := true; v_work := v_try; EXIT;
        END IF;
    END LOOP;

    IF NOT v_found THEN
        IF p_work IS NULL THEN
            RAISE EXCEPTION '%: 쓸 수 있는 소스가 없습니다 — 전 회차 소진이거나 미등록입니다. '
                            '소스 창고에서 한도를 올리거나 새 회차를 인입하세요', v_ch.name;
        ELSIF p_episode IS NULL THEN
            RAISE EXCEPTION '% / %: 남은 회차가 없습니다 — 전 회차 소진이거나 미등록입니다',
                            v_ch.name, p_work;
        ELSE
            RAISE EXCEPTION '% / % %회차: 쓸 수 없습니다 — 소진·비활성·3분 이하·미등록 중 하나입니다',
                            v_ch.name, p_work, p_episode;
        END IF;
    END IF;

    -- 지오블락 스탬프(★①): laeebly 는 여기서 못 본다(다른 프로젝트·읽기 전용).
    -- 같은 작품의 최근 작업지시가 이미 laeebly 로 판정받은 값을 물려받고, 없으면 안전측 true.
    v_geo := coalesce((SELECT w.geoblock_required FROM public.work_orders w
                        WHERE w.work_title = v_work
                        ORDER BY w.created_at DESC LIMIT 1), true);

    INSERT INTO public.work_orders
        (service_date, channel_slug, work_title, episode, source_sha256, source_url,
         pipeline, geoblock_required, has_subtitle, origin)
    VALUES ((now() AT TIME ZONE 'Asia/Seoul')::date, p_slug, v_work, v_src.episode,
            v_src.sha256, v_src.source_url, v_pipe, v_geo,
            coalesce(v_src.has_subtitle, false), 'manual')
    RETURNING id INTO v_wo;

    v_common := jsonb_build_object('work_title', v_work, 'episode', v_src.episode,
                                   'channel_slug', p_slug, 'channel_name', v_ch.name);

    -- planner.job_chain 과 1:1. 순서·caps·lease 가 어긋나면 잡이 엉뚱한 맥에서 죽는다.
    FOR v_step IN
        SELECT * FROM (VALUES
            ('acquire'::text,
             (v_common || jsonb_build_object('source_url', v_src.source_url,
                                             'source_sha256', v_src.sha256))::jsonb,
             ARRAY['network']::text[],  120::int, 1::int),
            ('generate',
             v_common || jsonb_build_object(
                 'source_sha256', v_src.sha256, 'source_url', v_src.source_url,
                 'max_shorts', 1, 'no_subtitles', NOT coalesce(v_src.has_subtitle, false),
                 'flags', '{}'::jsonb,
                 'resource', 'gemini:' || coalesce(v_ch.gcp_project, 'DEFAULT'),
                 'outdir', 'outputs'),
             ARRAY['generate'],          300, 2),
            ('upload_artifacts', v_common, ARRAY['analyze'],  120, 3),
            ('ingest',           v_common, ARRAY['analyze'],  120, 4),
            ('evaluate',         v_common, ARRAY['analyze'],  120, 5),
            ('localize',         v_common, ARRAY['localize'], 3600, 6)
        ) AS t(kind, params, caps, ttl, ord)
        WHERE t.kind <> 'localize' OR v_pipe = 'shorts_jp_localized'
        ORDER BY t.ord
    LOOP
        -- 멱등키: 이 작업지시는 방금 만든 새 행이라 충돌 상대가 없다. planner 의 sha256 키와
        -- 형식을 맞출 이유도 없어서, DB 에서 사람이 알아볼 수 있는 문자열을 쓴다.
        INSERT INTO public.job_queue
            (work_order_id, kind, params, idempotency_key, depends_on,
             required_caps, lease_ttl_sec)
        VALUES (v_wo, v_step.kind, v_step.params,
                v_wo::text || ':' || v_step.kind,
                CASE WHEN v_prev IS NULL THEN ARRAY[]::uuid[] ELSE ARRAY[v_prev] END,
                v_step.caps, v_step.ttl)
        RETURNING id INTO v_prev;
        v_jobs := v_jobs + 1;
    END LOOP;

    PERFORM public._audit('run_channel_now','work_orders', v_wo::text,
            jsonb_build_object('channel', p_slug, 'work', v_work,
                               'episode', v_src.episode, 'source_id', v_src.id,
                               'jobs', v_jobs, 'note', p_note));

    RETURN jsonb_build_object('work_order_id', v_wo, 'work', v_work,
                              'episode', v_src.episode, 'source_id', v_src.id,
                              'pipeline', v_pipe, 'jobs', v_jobs);
END $$;
REVOKE ALL     ON FUNCTION public.run_channel_now(text, text, integer, text) FROM public;
GRANT  EXECUTE ON FUNCTION public.run_channel_now(text, text, integer, text) TO authenticated;

-- =====================================================================
-- ⑥ set_source_limit(0024) — 한도 수정. 0024 는 "소진을 (작품, 회차)로 세니 한 행만
--    고치면 사람 기대와 다르게 움직인다"는 이유로 회차 전체에 한도를 걸었다. 0027 이
--    그 전제를 뒤집었다 — 이제 행마다 자기 한도를 쓰므로 고른 그 행만 고친다.
--    (같은 회차를 통째로 올리고 싶으면 행마다 부르면 된다. 반대로 회차 일괄 변경은
--     되돌릴 방법이 없어서, 조용히 남의 영상 한도까지 바꾸는 쪽이 더 위험하다)
-- =====================================================================
CREATE OR REPLACE FUNCTION public.set_source_limit(p_source uuid, p_limit integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_s record;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_limit IS NULL OR p_limit < 0 OR p_limit > 20 THEN
        RAISE EXCEPTION '한도는 0~20 사이여야 합니다 (받은 값: %)', p_limit;
    END IF;

    SELECT work_title, episode INTO v_s FROM public.sources WHERE id = p_source;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 소스: %', p_source; END IF;

    UPDATE public.sources SET use_limit = p_limit WHERE id = p_source;

    PERFORM public._audit('set_source_limit','sources', p_source::text,
            jsonb_build_object('work', v_s.work_title, 'episode', v_s.episode,
                               'use_limit', p_limit, 'rows', 1));
    RETURN jsonb_build_object('source_id', p_source, 'work', v_s.work_title,
                              'episode', v_s.episode, 'use_limit', p_limit, 'rows', 1);
END $$;
REVOKE ALL     ON FUNCTION public.set_source_limit(uuid, integer) FROM public;
GRANT  EXECUTE ON FUNCTION public.set_source_limit(uuid, integer) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0027','claude (영상 단위 회차 — 멱등키 URL 교체·episode_source·published_ts·행 단위 집계 통일)')
ON CONFLICT DO NOTHING;
