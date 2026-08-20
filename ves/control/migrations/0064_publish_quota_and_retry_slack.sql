-- =====================================================================
-- 0064_publish_quota_and_retry_slack.sql — 한도는 '발행', 시도는 따로 (2026-08-20)
--
-- 왜: 한도(use_limit) 하나로 두 가지를 동시에 통제하려다 어긋났다. 지금은 **작업지시
-- 수**를 세므로 검수에서 반려한 시도도, 생성이 취소돼 결과물이 없는 건도 한 편으로
-- 친다. 커리어데이 실측(8/20):
--   · 6회차 한도 2 — 8/15 반려 · 8/16 발행 → 유튜브엔 1편인데 창고는 2/2 소진
--   · 7회차 한도 1 — 아직 검수 대기(미발행)인데 1/1 소진
--   · 8회차 한도 2 — generate 가 cancelled 라 결과물 자체가 없는데 1편 사용
-- 그래서 발행 한 편 없이 원본이 죽는다. 반대로 '발행만 센다' 로 뒤집으면 반려가
-- 반복될 때 같은 원본으로 생성이 무한정 돌아 비용이 샌다.
--
-- 그래서 둘로 나눈다(사용자 결정 8/20):
--   · 한도(use_limit)  = **발행된 편수**    — 같은 원본을 너무 많이 올리는 것을 막는다
--   · 시도 상한        = 한도 + 시도 여유   — 반려가 반복될 때 비용을 막는다
--   · 시도 여유 기본 3 (작품 카드 work_cards.retry_slack 으로 작품별 재정의)
-- 고르는 조건: 발행 < 한도  AND  시도 < 한도 + 여유.
-- 예) 한도 2 · 여유 3 → 최대 5번 시도, 그 안에 2편 발행되면 거기서 닫힌다.
--
-- 레거시 장부(source_usage_legacy)는 구 루프가 **공개까지 마친** 몫이라 발행·시도 양쪽에
-- 모두 더한다.
--
-- 세는 곳이 여섯이라(0027 주석) 이 마이그레이션이 SQL 쪽 넷을 함께 갱신하고,
-- 파이썬 둘(planner._pick_source · source_watch.REMAIN_SQL)은 같은 커밋에서 고친다.
--
-- 함께 넣는 것 — cancel_work_order(작업지시 취소):
--   set_source_used 는 '발주 기록 아래로는 못 내린다' 며 "작업 내역에서 작업지시를
--   취소하세요" 라고 안내하는데, 관제에는 잡 취소(cancel_job)만 있고 **작업지시를
--   취소하는 경로가 없었다**(취소된 12건은 전부 사람이 DB 에서 직접 바꾼 것). 막다른
--   길이라 정식 경로를 만든다. 발행까지 간 작업지시는 취소를 거부한다 — 올라간 영상의
--   사용 이력을 지우는 셈이라서다.
-- =====================================================================

-- ── ① 작품 카드에 시도 여유 ─────────────────────────────────────────
ALTER TABLE public.work_cards ADD COLUMN IF NOT EXISTS retry_slack integer;
COMMENT ON COLUMN public.work_cards.retry_slack IS
  '이 작품의 시도 여유(발행 한도 위에 얹는 재시도 허용치). NULL 이면 기본 3.';

CREATE OR REPLACE FUNCTION public.source_retry_slack(p_work text)
RETURNS integer LANGUAGE sql STABLE PARALLEL SAFE
SET search_path TO 'pg_catalog','public' AS $$
    SELECT coalesce((SELECT wc.retry_slack FROM public.work_cards wc
                      WHERE wc.work_title = p_work AND wc.retry_slack >= 0), 3);
$$;
COMMENT ON FUNCTION public.source_retry_slack(text) IS
  '작품별 시도 여유 — 정본은 이 함수 하나다(작품 카드 > 기본 3).';

-- ── ② '이 작업지시가 발행까지 갔나' 정본 ────────────────────────────
CREATE OR REPLACE FUNCTION public.wo_published(p_wo uuid)
RETURNS boolean LANGUAGE sql STABLE PARALLEL SAFE
SET search_path TO 'pg_catalog','public' AS $$
    SELECT EXISTS (SELECT 1 FROM public.job_queue j
                    WHERE j.work_order_id = p_wo
                      AND j.kind = 'publish' AND j.status = 'succeeded');
$$;
COMMENT ON FUNCTION public.wo_published(uuid) IS
  '발행 잡이 성공했는가 — 한도(use_limit)에 세는 기준(0064). 예약 업로드도 성공이면 발행으로 본다.';

-- ── ③ source_usage 뷰 — times_used 는 '시도', remaining 은 '발행' 기준 ──
-- CREATE OR REPLACE VIEW 는 컬럼을 못 지우고 순서도 못 바꾼다 — 기존 15개를 그대로 두고
-- 뒤에 used_pub·attempts_cap 을 덧붙인다(0027 주석의 사고 재발 방지).
CREATE OR REPLACE VIEW public.source_usage
WITH (security_invoker = true) AS
  SELECT s.id AS source_id, s.work_title, s.episode, s.use_limit, s.is_active,
         s.bytes, s.has_subtitle,
         count(w.id) FILTER (WHERE w.status <> ALL (ARRAY['cancelled','failed'])) AS times_used,
         GREATEST(s.use_limit - count(w.id) FILTER (
                    WHERE w.status <> ALL (ARRAY['cancelled','failed'])
                      AND public.wo_published(w.id)), 0::bigint) AS remaining,
         s.duration_sec,
         s.is_active AND (s.duration_sec IS NULL
              OR s.duration_sec > public.source_min_duration(s.work_title)::numeric) AS usable,
         s.source_url, s.title, s.published_ts, s.created_at,
         count(w.id) FILTER (WHERE w.status <> ALL (ARRAY['cancelled','failed'])
                               AND public.wo_published(w.id)) AS used_pub,
         (s.use_limit + public.source_retry_slack(s.work_title)) AS attempts_cap
    FROM public.sources s
    LEFT JOIN public.work_orders w
      ON public.wo_matches_source(w.work_title, w.source_sha256, w.source_url,
                                  s.work_title, s.sha256, s.source_url)
   GROUP BY s.id;

-- ── ④ source_usage_by_channel 뷰 — 채널별. used_wo 는 '시도'(이름 그대로 작업지시 수),
--      used_total·remaining 은 '발행' 기준으로 바뀐다. 뒤에 발행·시도 상한을 덧붙인다.
CREATE OR REPLACE VIEW public.source_usage_by_channel
WITH (security_invoker = true) AS
  SELECT s.id AS source_id, s.work_title, s.episode, c.channel_slug,
         s.use_limit, s.is_active, s.duration_sec,
         c.used_wo, c.used_legacy,
         c.used_pub + c.used_legacy_pin + c.used_legacy AS used_total,
         GREATEST(s.use_limit - (c.used_pub + c.used_legacy_pin + c.used_legacy), 0::bigint) AS remaining,
         s.is_active AND (s.duration_sec IS NULL
              OR s.duration_sec > public.source_min_duration(s.work_title)::numeric) AS usable,
         c.used_legacy_pin, s.source_url, s.title, s.published_ts, s.created_at,
         c.used_pub,
         (s.use_limit + public.source_retry_slack(s.work_title)) AS attempts_cap,
         GREATEST(s.use_limit + public.source_retry_slack(s.work_title)
                  - (c.used_wo + c.used_legacy_pin + c.used_legacy), 0::bigint) AS attempts_left
    FROM public.sources s
    JOIN LATERAL (
      SELECT ch.channel_slug,
             (SELECT count(*) FROM public.work_orders w
               WHERE public.wo_matches_source(w.work_title, w.source_sha256, w.source_url,
                                              s.work_title, s.sha256, s.source_url)
                 AND w.channel_slug = ch.channel_slug
                 AND w.status <> ALL (ARRAY['cancelled','failed'])) AS used_wo,
             (SELECT count(*) FROM public.work_orders w
               WHERE public.wo_matches_source(w.work_title, w.source_sha256, w.source_url,
                                              s.work_title, s.sha256, s.source_url)
                 AND w.channel_slug = ch.channel_slug
                 AND w.status <> ALL (ARRAY['cancelled','failed'])
                 AND public.wo_published(w.id)) AS used_pub,
             COALESCE((SELECT sum(l.used) FROM public.source_usage_legacy l
                        WHERE l.work_title = s.work_title
                          AND NOT l.episode IS DISTINCT FROM s.episode
                          AND l.channel_slug = ch.channel_slug
                          AND l.source_url IS NULL), 0::bigint)::integer AS used_legacy,
             COALESCE((SELECT sum(l.used) FROM public.source_usage_legacy l
                        WHERE l.work_title = s.work_title
                          AND l.channel_slug = ch.channel_slug
                          AND l.source_url = s.source_url), 0::bigint)::integer AS used_legacy_pin
        FROM (SELECT cm.token_slug AS channel_slug FROM public.channels_mirror cm
               WHERE cm.works @> ARRAY[s.work_title]) ch) c ON true;

ALTER VIEW public.source_usage             SET (security_invoker = true);
ALTER VIEW public.source_usage_by_channel  SET (security_invoker = true);
REVOKE ALL ON public.source_usage            FROM anon;
REVOKE ALL ON public.source_usage_by_channel FROM anon;
GRANT SELECT ON public.source_usage            TO authenticated;
GRANT SELECT ON public.source_usage_by_channel TO authenticated;

-- ── ⑤ run_channel_now(관제 '작업 실행') — planner 와 같은 조건으로 고른다 ────
-- 0063 판을 그대로 가져와 소스 선택부만 고쳤다(발행/시도 분리). 여기가 어긋나면
-- planner 는 배정하는데 관제는 '쓸 수 있는 소스가 없습니다' 로 막힌다(0027 주석).
CREATE OR REPLACE FUNCTION public.run_channel_now(p_slug text, p_work text DEFAULT NULL::text, p_episode integer DEFAULT NULL::integer, p_note text DEFAULT NULL::text, p_direction text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_ch      record;
    v_src     public.sources%ROWTYPE;
    v_try     text;
    v_work    text;
    v_found   boolean := false;
    v_pipe    text;
    v_geo     boolean;
    v_wo      uuid;
    v_prev    uuid := NULL;
    v_common  jsonb;
    v_gen     jsonb;
    v_loc     jsonb;
    v_lv      text := 'B';
    v_bk      text;
    v_vo      text;
    v_jp      boolean;
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

    IF v_ch.pipeline = 'zanmang_autopilot' THEN
        RAISE EXCEPTION '%: 전용 파이프라인 채널입니다 — zanmang_daily(매일 10시)가 담당합니다',
                        v_ch.name;
    END IF;

    v_pipe := CASE WHEN v_ch.country = 'JP' THEN 'shorts_jp_localized' ELSE 'shorts_kr' END;
    IF v_pipe = 'shorts_jp_localized'
       AND coalesce((SELECT value FROM public.ops_config WHERE key='jp_pipeline'), '') <> 'on' THEN
        RAISE EXCEPTION 'JP 파이프라인 스위치가 꺼져 있습니다 — 구 현지화 autopilot 과 이중 생산이 됩니다';
    END IF;

    IF p_work IS NOT NULL AND NOT (p_work = ANY (v_ch.works)) THEN
        RAISE EXCEPTION '이 채널의 작품이 아닙니다: % (유효 작품: %)',
                        p_work, array_to_string(v_ch.works, ', ');
    END IF;

    BEGIN
        v_lv := upper(coalesce((SELECT value::jsonb ->> p_slug FROM public.ops_config
                                 WHERE key='localize_levels'), 'B'));
        v_bk := (SELECT value::jsonb ->> p_slug FROM public.ops_config
                  WHERE key='localize_backends');
        v_vo := (SELECT value::jsonb ->> p_slug FROM public.ops_config
                  WHERE key='localize_voices');
    EXCEPTION WHEN OTHERS THEN
        v_lv := 'B'; v_bk := NULL; v_vo := NULL;
    END;
    IF v_lv IS NULL OR v_lv NOT IN ('A','B','BJ','C','BC','J') THEN v_lv := 'B'; END IF;
    v_jp := (v_lv = 'J');

    FOREACH v_try IN ARRAY (CASE WHEN p_work IS NULL THEN v_ch.works ELSE ARRAY[p_work] END)
    LOOP
        WITH base AS (
            SELECT s2.*,
                   (SELECT count(*) FROM public.work_orders w
                     WHERE public.wo_matches_source(w.work_title, w.source_sha256,
                                                    w.source_url, s2.work_title,
                                                    s2.sha256, s2.source_url)
                       AND w.channel_slug = p_slug
                       AND w.status NOT IN ('cancelled','failed'))
                   + coalesce((SELECT sum(l.used) FROM public.source_usage_legacy l
                                WHERE l.work_title = s2.work_title
                                  AND l.channel_slug = p_slug
                                  AND l.source_url = s2.source_url), 0)     AS used_wo,
                   -- 0064: 한도는 발행 기준으로 센다(used_pub), 시도는 used_wo 그대로
                   (SELECT count(*) FROM public.work_orders w
                     WHERE public.wo_matches_source(w.work_title, w.source_sha256,
                                                    w.source_url, s2.work_title,
                                                    s2.sha256, s2.source_url)
                       AND w.channel_slug = p_slug
                       AND w.status NOT IN ('cancelled','failed')
                       AND public.wo_published(w.id))
                   + coalesce((SELECT sum(l.used) FROM public.source_usage_legacy l
                                WHERE l.work_title = s2.work_title
                                  AND l.channel_slug = p_slug
                                  AND l.source_url = s2.source_url), 0)     AS used_pub,
                   coalesce((SELECT sum(l.used) FROM public.source_usage_legacy l
                              WHERE l.work_title = s2.work_title
                                AND l.episode IS NOT DISTINCT FROM s2.episode
                                AND l.channel_slug = p_slug
                                AND l.source_url IS NULL), 0)               AS legacy_ep
              FROM public.sources s2
             WHERE s2.work_title = v_try
               AND s2.is_active
               AND (s2.duration_sec IS NULL
                    OR s2.duration_sec > public.source_min_duration(s2.work_title))
               AND (p_episode IS NULL OR s2.episode = p_episode)
        ), ranked AS (
            SELECT b.*,
                   coalesce(sum(GREATEST(b.use_limit - b.used_pub, 0)) OVER (
                       PARTITION BY b.work_title, b.episode
                       ORDER BY coalesce(b.published_ts, b.created_at), b.id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS free_before
              FROM base b
        )
        SELECT r.* INTO v_src
          FROM ranked r
         WHERE r.used_pub + GREATEST(r.legacy_ep - r.free_before, 0) < r.use_limit
           AND r.used_wo + GREATEST(r.legacy_ep - r.free_before, 0)
               < r.use_limit + public.source_retry_slack(r.work_title)
         ORDER BY r.episode NULLS LAST,
                  coalesce(r.published_ts, r.created_at), r.id
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

    v_gen := v_common || jsonb_build_object(
                 'source_sha256', v_src.sha256, 'source_url', v_src.source_url,
                 'max_shorts', 1,
                 'no_subtitles', NOT coalesce(v_src.has_subtitle, false),
                 'flags', '{}'::jsonb,
                 'resource', 'gemini:' || coalesce(v_ch.gcp_project, 'DEFAULT'),
                 'outdir', 'outputs');

    -- 기획 방향(0063) — 이번 한 편에만 얹는 지시 → --editorial-run-json.
    -- prefer(랭킹 편향)로만 실린다 — 권리 제약(avoid·rules)은 실행 단위로 완화 불가.
    IF nullif(btrim(coalesce(p_direction, '')), '') IS NOT NULL THEN
        v_gen := v_gen || jsonb_build_object(
                     'editorial_run', jsonb_build_object(
                         'prefer', jsonb_build_array(btrim(p_direction))));
    END IF;

    v_loc := v_common || jsonb_build_object('mode', 'scene_rerender');

    FOR v_step IN
        SELECT * FROM (VALUES
            ('acquire'::text,
             (v_common || jsonb_build_object('source_url', v_src.source_url,
                                             'source_sha256', v_src.sha256))::jsonb,
             ARRAY['network']::text[],  120::int, 1::int),
            ('generate',         v_gen,     ARRAY['generate'],  300, 2),
            ('upload_artifacts', v_common,  ARRAY['analyze'],   120, 3),
            ('ingest',           v_common,  ARRAY['analyze'],   120, 4),
            ('evaluate',         v_common,  ARRAY['analyze'],   120, 5),
            ('localize',         v_loc,     ARRAY['generate'],  300, 6)
        ) AS t(kind, params, caps, ttl, ord)
        WHERE t.kind <> 'localize' OR v_pipe = 'shorts_jp_localized'
        ORDER BY t.ord
    LOOP
        INSERT INTO public.job_queue
            (work_order_id, kind, params, idempotency_key, depends_on,
             required_caps, lease_ttl_sec, priority)
        VALUES (v_wo, v_step.kind, v_step.params,
                'manual:' || v_wo::text || ':' || v_step.kind,
                CASE WHEN v_prev IS NULL THEN '{}'::uuid[] ELSE ARRAY[v_prev] END,
                v_step.caps, v_step.ttl,
                150)
        RETURNING id INTO v_prev;
        v_jobs := v_jobs + 1;
    END LOOP;

    PERFORM public._audit('run_channel_now','work_orders', v_wo::text,
            jsonb_build_object('slug', p_slug, 'work', v_work, 'episode', v_src.episode,
                               'pipeline', v_pipe, 'jobs', v_jobs, 'note', p_note,
                               'direction', p_direction,
                               'source_id', v_src.id, 'localize_level', v_lv));

    RETURN jsonb_build_object('work_order_id', v_wo, 'channel', v_ch.name,
                              'work', v_work, 'episode', v_src.episode,
                              'source_id', v_src.id,
                              'pipeline', v_pipe, 'jobs', v_jobs);
END $function$;

REVOKE ALL ON FUNCTION public.run_channel_now(text, text, integer, text, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.run_channel_now(text, text, integer, text, text) TO authenticated;

-- ── ⑥ set_source_used — 바닥이 '발주' 가 아니라 '발행' 이 된다 ──────────
-- 한도가 발행 기준이 됐으니 관제 입력칸도 발행 아래로만 못 내린다. 반려·취소로 끝난
-- 시도는 이제 이 숫자에 안 들어가므로 사람이 0 으로 되돌릴 수 있다.
CREATE OR REPLACE FUNCTION public.set_source_used(p_source uuid, p_channel text, p_used integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public' AS $function$
DECLARE v_s record; v_pub int; v_legacy int; v_who text;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_used IS NULL OR p_used < 0 THEN
        RAISE EXCEPTION '쓴 수는 0 이상이어야 합니다 (받은 값: %)', p_used;
    END IF;

    SELECT work_title, episode, sha256, source_url INTO v_s
      FROM public.sources WHERE id = p_source;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 소스: %', p_source; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_channel) THEN
        RAISE EXCEPTION '없는 채널: %', p_channel;
    END IF;

    -- 발행까지 간 작업지시 수 — 이 소스 행에 물린 것만(0027 행 단위 · 0062 sha 또는 URL)
    SELECT count(*) INTO v_pub FROM public.work_orders w
     WHERE public.wo_matches_source(w.work_title, w.source_sha256, w.source_url,
                                    v_s.work_title, v_s.sha256, v_s.source_url)
       AND w.channel_slug = p_channel
       AND w.status NOT IN ('cancelled','failed')
       AND public.wo_published(w.id);

    IF p_used < v_pub THEN
        RAISE EXCEPTION '이미 발행된 편수가 %건입니다 — 그 아래로는 내릴 수 없습니다. 올라간 영상을 지우려면 유튜브에서 내리고 작업 내역에서 해당 작업지시를 취소하세요', v_pub;
    END IF;

    v_legacy := p_used - v_pub;
    v_who    := coalesce(auth.email(), auth.uid()::text);

    IF v_legacy = 0 THEN
        DELETE FROM public.source_usage_legacy l
         WHERE l.work_title = v_s.work_title
           AND l.episode IS NOT DISTINCT FROM v_s.episode
           AND l.channel_slug = p_channel;
    ELSE
        UPDATE public.source_usage_legacy l
           SET used = v_legacy, note = '관제 수정 · ' || v_who, recorded_at = now()
         WHERE l.work_title = v_s.work_title
           AND l.episode IS NOT DISTINCT FROM v_s.episode
           AND l.channel_slug = p_channel;
        IF NOT FOUND THEN
            INSERT INTO public.source_usage_legacy
                (work_title, episode, channel_slug, used, note)
            VALUES (v_s.work_title, v_s.episode, p_channel, v_legacy,
                    '관제 수정 · ' || v_who);
        END IF;
    END IF;

    PERFORM public._audit('set_source_used','sources', p_source::text,
            jsonb_build_object('work', v_s.work_title, 'episode', v_s.episode,
                               'channel', p_channel, 'used_total', p_used,
                               'used_pub', v_pub, 'used_legacy', v_legacy));
    RETURN jsonb_build_object('source_id', p_source, 'channel', p_channel,
                              'used_total', p_used, 'used_pub', v_pub,
                              'used_legacy', v_legacy);
END $function$;
REVOKE ALL     ON FUNCTION public.set_source_used(uuid, text, integer) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.set_source_used(uuid, text, integer) TO authenticated;

-- ── ⑦ cancel_work_order — 관제에서 작업지시를 취소하는 정식 경로 ──────
CREATE OR REPLACE FUNCTION public.cancel_work_order(p_wo uuid, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public' AS $function$
DECLARE v_w record; v_jobs int;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    SELECT id, channel_slug, work_title, episode, status INTO v_w
      FROM public.work_orders WHERE id = p_wo FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 작업지시: %', p_wo; END IF;
    IF v_w.status = 'cancelled' THEN
        RETURN jsonb_build_object('work_order_id', p_wo, 'already', true);
    END IF;
    -- 발행까지 간 건은 취소하지 않는다 — 올라간 영상의 사용 이력을 지우는 셈이다.
    IF public.wo_published(p_wo) THEN
        RAISE EXCEPTION '이미 발행된 작업지시는 취소할 수 없습니다 — 유튜브에서 영상을 먼저 내리세요';
    END IF;

    UPDATE public.job_queue
       SET status='cancelled', lease_expires_at=NULL, updated_at=now(),
           error=coalesce(p_note,'작업지시 취소')
     WHERE work_order_id = p_wo AND status IN ('pending','running','blocked');
    GET DIAGNOSTICS v_jobs = ROW_COUNT;

    -- 대기 중인 검수 카드도 함께 닫는다 — 취소된 작업지시의 카드가 검수함에 남으면
    -- 사람이 합격시킬 수 있고, 그러면 취소한 건이 발행된다.
    UPDATE public.review_queue
       SET status='rejected', decided_by=coalesce(auth.email(), auth.uid()::text),
           decided_at=now(), decision_note=coalesce(p_note,'작업지시 취소')
     WHERE work_order_id = p_wo AND status='waiting';

    UPDATE public.work_orders SET status='cancelled' WHERE id = p_wo;

    PERFORM public._audit('cancel_work_order','work_orders', p_wo::text,
            jsonb_build_object('note', p_note, 'channel', v_w.channel_slug,
                               'work', v_w.work_title, 'episode', v_w.episode,
                               'jobs_cancelled', v_jobs));
    RETURN jsonb_build_object('work_order_id', p_wo, 'jobs_cancelled', v_jobs);
END $function$;
REVOKE ALL     ON FUNCTION public.cancel_work_order(uuid, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.cancel_work_order(uuid, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0064','claude (한도=발행 · 시도 상한=한도+여유(기본3) · 작업지시 취소 RPC)')
ON CONFLICT DO NOTHING;
