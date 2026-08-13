-- =====================================================================
-- 0031_work_card_min_duration.sql — 작품별 소스 길이 하한 (2026-08-13)
--
-- 왜: 레거시 works.json 은 작품마다 다른 하한을 요구했다 — 놀토·도깨비·언더커버셰프
-- 600s, 산지직송·스레파 500s, 커리어데이·B급 300s. 0027 은 3분(180s) 일괄이라
-- 그 규칙이 반영되지 않았고, 실제로 예고편·티저가 소스로 들어와 쇼츠가 만들어졌다
-- (스레파 3화 66초짜리로 3편 실측 · 놀토 430화 80초 예고편).
--
-- ★하한을 보는 곳이 여섯이다. 0027 의 교훈대로 **정본 함수 하나**로 모은다:
--    ① planner._pick_source · ② register_sources.plan_rows  (코드)
--    ③ run_channel_now · ④ source_usage 뷰 · ⑤ source_usage_by_channel 뷰
--    ⑥ 대시보드(뷰의 usable 컬럼을 읽는다 — 더는 JS 가 180 을 알지 않는다)
--  register_drive 는 아직 기본값으로 돈다(드라이브 작품 카드 연결은 후속).
--  코드 쪽 정본은 base.min_duration_for / base.is_usable 이고, 두 규칙은 같아야 한다.
-- =====================================================================

ALTER TABLE public.work_cards
  ADD COLUMN IF NOT EXISTS min_source_duration_sec int
  CHECK (min_source_duration_sec IS NULL OR min_source_duration_sec > 0);
COMMENT ON COLUMN public.work_cards.min_source_duration_sec IS
  '이 작품 소스의 길이 하한(초). NULL 이면 기본 180. 이하는 등록 시 건너뛰고 planner 도 안 쓴다.';

-- 하한 정본 — 카드값이 있으면 그것, 없으면 180. 코드의 base.min_duration_for 와 같은 규칙.
-- STABLE: work_cards 를 읽으므로 IMMUTABLE 이 아니다(같은 트랜잭션 안에서는 안정).
CREATE OR REPLACE FUNCTION public.source_min_duration(p_work text)
RETURNS int LANGUAGE sql STABLE PARALLEL SAFE
SET search_path = pg_catalog, public AS $$
    SELECT coalesce((SELECT wc.min_source_duration_sec FROM public.work_cards wc
                      WHERE wc.work_title = p_work AND wc.min_source_duration_sec > 0), 180);
$$;
COMMENT ON FUNCTION public.source_min_duration(text) IS
  '작품별 소스 길이 하한(초) — 세는 곳이 여섯이라 규칙은 여기 하나뿐이다(0031).';

-- 레거시 works.json 이 요구하던 값 이관. 카드가 이미 값을 가지고 있으면 덮지 않는다.
UPDATE public.work_cards SET min_source_duration_sec = v.sec
  FROM (VALUES ('놀라운 토요일', 600), ('도깨비 10주년 여행', 600), ('언더커버셰프', 600),
               ('언니네 산지직송 in 칼라페', 500), ('스트릿 레스토랑 파이터', 500),
               ('커리어데이', 300), ('B급 스튜디오', 300)
       ) AS v(work, sec)
 WHERE work_cards.work_title = v.work AND work_cards.min_source_duration_sec IS NULL;

-- =====================================================================
-- 뷰 2개 — 컬럼은 **끝에만** 추가한다(CREATE OR REPLACE VIEW 는 컬럼을 못 지운다).
-- usable = planner 가 실제로 고를 수 있는 행인가. 대시보드가 이걸 읽으면
-- JS 가 하한을 따로 알 필요가 없다.
-- security_invoker 는 반드시 명시한다(0024 가 복구해 둔 값 — 빠뜨리면 RLS 우회).
-- =====================================================================
CREATE OR REPLACE VIEW public.source_usage
WITH (security_invoker = true) AS
SELECT s.id AS source_id, s.work_title, s.episode, s.use_limit, s.is_active,
       s.bytes, s.has_subtitle,
       COUNT(w.id) FILTER (WHERE w.status NOT IN ('cancelled','failed')) AS times_used,
       GREATEST(s.use_limit - COUNT(w.id) FILTER (WHERE w.status NOT IN ('cancelled','failed')), 0) AS remaining,
       s.duration_sec,
       (s.is_active AND (s.duration_sec IS NULL
                         OR s.duration_sec > public.source_min_duration(s.work_title))) AS usable
FROM public.sources s
LEFT JOIN public.work_orders w
  ON public.wo_matches_source(w.work_title, w.source_sha256, w.source_url,
                              s.work_title, s.sha256, s.source_url)
GROUP BY s.id;

GRANT SELECT ON public.source_usage TO authenticated;

CREATE OR REPLACE VIEW public.source_usage_by_channel
WITH (security_invoker = true) AS
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
       GREATEST(s.use_limit - (c.used_wo + c.used_legacy), 0)      AS remaining,
       (s.is_active AND (s.duration_sec IS NULL
                         OR s.duration_sec > public.source_min_duration(s.work_title))) AS usable
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
-- run_channel_now — 0029 판 그대로에 하한만 정본 함수로 바꾼다.
-- (0029 가 복구한 priority 150 · 멱등키 'manual:' · 반환 'channel' · 현지화 level ·
--  free_before 차감은 손대지 않았다 — 생성 시 자동 대조했다)
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

    -- 현지화 설정(0029) — planner._load_localize_cfg + localize_level_for 와 같은 규칙.
    -- 설정이 깨졌으면 조용히 기본값 B 로 간다(설정 오류가 실행을 막지 않는다 — planner 동일).
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
    v_jp := (v_lv = 'J');     -- planner.job_chain 의 jp_convert 와 같은 판정(등급만 본다)

    -- 소스 고르기 — planner._pick_source · pick_from_rows 와 같은 규칙:
    --   활성 · 3분 초과 · 회차→업로드시각 순 · 소진은 이 채널 몫만, 행 단위로 센다(0027)
    --   레거시(회차 단위)는 그 회차의 앞선 행이 남긴 **여유**부터 차감한다(0029 교정).
    FOREACH v_try IN ARRAY (CASE WHEN p_work IS NULL THEN v_ch.works ELSE ARRAY[p_work] END)
    LOOP
        WITH base AS (
            SELECT s2.*,
                   (SELECT count(*) FROM public.work_orders w
                     WHERE public.wo_matches_source(w.work_title, w.source_sha256,
                                                    w.source_url, s2.work_title,
                                                    s2.sha256, s2.source_url)
                       AND w.channel_slug = p_slug
                       AND w.status NOT IN ('cancelled','failed'))          AS used_wo,
                   coalesce((SELECT l.used FROM public.source_usage_legacy l
                              WHERE l.work_title = s2.work_title
                                AND l.episode IS NOT DISTINCT FROM s2.episode
                                AND l.channel_slug = p_slug), 0)            AS legacy_ep
              FROM public.sources s2
             WHERE s2.work_title = v_try
               AND s2.is_active
               AND (s2.duration_sec IS NULL
                    OR s2.duration_sec > public.source_min_duration(s2.work_title))
               AND (p_episode IS NULL OR s2.episode = p_episode)
        ), ranked AS (
            SELECT b.*,
                   -- 앞선 행들이 흡수하고 남긴 여유의 누적 — pick_from_rows 의 take 와 동치.
                   -- (한도 합이 아니다: 이미 발주가 물린 몫은 레거시를 흡수하지 못한다)
                   coalesce(sum(GREATEST(b.use_limit - b.used_wo, 0)) OVER (
                       PARTITION BY b.work_title, b.episode
                       ORDER BY coalesce(b.published_ts, b.created_at), b.id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS free_before
              FROM base b
        )
        SELECT r.* INTO v_src
          FROM ranked r
         WHERE r.used_wo + GREATEST(r.legacy_ep - r.free_before, 0) < r.use_limit
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

    -- generate params — planner.job_chain 의 gen 과 1:1.
    -- 등급 J(8/13): ai-video 는 텍스트를 얹기 직전까지만. 한국어 자막을 만들었다 지우는 게
    -- 아니라 처음부터 안 그린다 — 번역·렌더는 vlp 가 한다.
    v_gen := v_common || jsonb_build_object(
                 'source_sha256', v_src.sha256, 'source_url', v_src.source_url,
                 'max_shorts', 1,
                 'no_subtitles', CASE WHEN v_jp THEN true
                                      ELSE NOT coalesce(v_src.has_subtitle, false) END,
                 'flags', '{}'::jsonb,
                 'resource', 'gemini:' || coalesce(v_ch.gcp_project, 'DEFAULT'),
                 'outdir', 'outputs')
             || CASE WHEN v_jp THEN jsonb_build_object('no_tts_subtitles', true,
                                                       'no_title_overlay', true,
                                                       'no_tts_audio', true)
                     ELSE '{}'::jsonb END;

    -- localize params — 등급·백엔드·목소리를 실어야 한다. 안 실으면 B 로 떨어지고
    -- mm-06 에 LaMa 가중치가 없어 즉사한다(0026 실측).
    v_loc := v_common || jsonb_build_object('level', v_lv);
    IF v_bk IS NOT NULL AND v_bk <> '' THEN
        v_loc := v_loc || jsonb_build_object('backend', v_bk);
    END IF;
    IF v_vo IS NOT NULL AND v_vo <> '' THEN
        v_loc := v_loc || jsonb_build_object('voice_id', v_vo);
    END IF;

    -- planner.job_chain 과 1:1. 순서·caps·lease 가 어긋나면 잡이 엉뚱한 맥에서 죽는다.
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
            ('localize',         v_loc,     ARRAY['localize'], 3600, 6)
        ) AS t(kind, params, caps, ttl, ord)
        WHERE t.kind <> 'localize' OR v_pipe = 'shorts_jp_localized'
        ORDER BY t.ord
    LOOP
        -- 멱등키: 이 작업지시는 방금 만든 새 행이라 충돌 상대가 없다. planner 의 sha256 키와
        -- 형식을 맞출 이유도 없어서, DB 에서 사람이 알아볼 수 있는 문자열을 쓴다.
        INSERT INTO public.job_queue
            (work_order_id, kind, params, idempotency_key, depends_on,
             required_caps, lease_ttl_sec, priority)
        VALUES (v_wo, v_step.kind, v_step.params,
                'manual:' || v_wo::text || ':' || v_step.kind,
                CASE WHEN v_prev IS NULL THEN '{}'::uuid[] ELSE ARRAY[v_prev] END,
                v_step.caps, v_step.ttl,
                150)   -- 보충 인입과 같은 급. 사람이 눌러 기다리는 일이라 일상 잡보다 앞세운다
        RETURNING id INTO v_prev;
        v_jobs := v_jobs + 1;
    END LOOP;

    PERFORM public._audit('run_channel_now','work_orders', v_wo::text,
            jsonb_build_object('slug', p_slug, 'work', v_work, 'episode', v_src.episode,
                               'pipeline', v_pipe, 'jobs', v_jobs, 'note', p_note,
                               'source_id', v_src.id, 'localize_level', v_lv));

    RETURN jsonb_build_object('work_order_id', v_wo, 'channel', v_ch.name,
                              'work', v_work, 'episode', v_src.episode,
                              'source_id', v_src.id,
                              'pipeline', v_pipe, 'jobs', v_jobs);
END $$;
REVOKE ALL     ON FUNCTION public.run_channel_now(text, text, integer, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.run_channel_now(text, text, integer, text) TO authenticated;
-- =====================================================================
-- set_work_card — 하한을 관제에서 넣을 수 있게 인자 추가.
-- 인자 규약은 0028 그대로: NULL=미변경 · ''=지움 · p_clear=카드 삭제.
-- p_min_duration 은 정수라 '' 가 없다 — 0 을 주면 지움(기본값 180 으로 되돌림)으로 본다.
-- =====================================================================
CREATE OR REPLACE FUNCTION public.set_work_card(
    p_work text, p_regex text DEFAULT NULL, p_filter text DEFAULT NULL,
    p_playlist text DEFAULT NULL, p_note text DEFAULT NULL,
    p_clear boolean DEFAULT false, p_min_duration int DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_role text; v_n int;
BEGIN
    SELECT role INTO v_role FROM public.user_roles WHERE user_id = auth.uid();
    IF v_role IS NULL OR v_role NOT IN ('operator','admin') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_work IS NULL OR btrim(p_work) = '' THEN
        RAISE EXCEPTION '작품명 필요';
    END IF;

    IF p_clear THEN
        DELETE FROM public.work_cards WHERE work_title = p_work;
        GET DIAGNOSTICS v_n = ROW_COUNT;
        RETURN jsonb_build_object('work', p_work, 'cleared', v_n > 0);
    END IF;

    IF p_min_duration IS NOT NULL AND p_min_duration < 0 THEN
        RAISE EXCEPTION '길이 하한은 0 이상이어야 합니다 (0 = 기본값 180 으로 되돌림)';
    END IF;

    -- 정규식 검증: 빈 문자('' = 지우기)는 통과, 그 외에는 실제로 써 본다.
    -- ⚠ 여기서 도는 것은 Postgres ARE 이고 실제 파싱은 Python re 다 — 최종 안전망은
    --   등록 어댑터 쪽 base.compile_episode_regex 의 PermanentError 다.
    IF p_regex IS NOT NULL AND p_regex <> '' THEN
        IF position('(' in p_regex) = 0 THEN
            RAISE EXCEPTION '정규식에 캡처그룹 ( ) 이 필요합니다 — 예: EP\.?(\d+)';
        END IF;
        BEGIN
            PERFORM regexp_match('회차 확인용 표본 EP.410', p_regex);
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION '정규식 문법 오류입니다: % — 저장하지 않았습니다', SQLERRM;
        END;
    END IF;

    IF p_regex IS NULL AND p_filter IS NULL AND p_playlist IS NULL AND p_note IS NULL
       AND p_min_duration IS NULL THEN
        RETURN jsonb_build_object('work', p_work, 'saved', false,
                                  'note', '바꿀 값이 없습니다 — 카드를 지우려면 p_clear => true');
    END IF;

    INSERT INTO public.work_cards AS wc
        (work_title, title_episode_regex, title_filter, playlist_url, note,
         min_source_duration_sec, updated_by, updated_at)
    VALUES (p_work, nullif(p_regex,''), nullif(p_filter,''), nullif(p_playlist,''),
            nullif(p_note,''), nullif(p_min_duration, 0),
            coalesce(auth.uid()::text,'system'), now())
    ON CONFLICT (work_title) DO UPDATE SET
        -- 안 넘긴 인자(NULL)는 기존 값 유지, ''(정수는 0)는 지우기
        title_episode_regex = CASE WHEN p_regex    IS NULL THEN wc.title_episode_regex
                                   ELSE nullif(p_regex,'')    END,
        title_filter        = CASE WHEN p_filter   IS NULL THEN wc.title_filter
                                   ELSE nullif(p_filter,'')   END,
        playlist_url        = CASE WHEN p_playlist IS NULL THEN wc.playlist_url
                                   ELSE nullif(p_playlist,'') END,
        note                = CASE WHEN p_note     IS NULL THEN wc.note
                                   ELSE nullif(p_note,'')     END,
        min_source_duration_sec = CASE WHEN p_min_duration IS NULL
                                       THEN wc.min_source_duration_sec
                                       ELSE nullif(p_min_duration, 0) END,
        updated_by          = excluded.updated_by,
        updated_at          = now();
    RETURN jsonb_build_object('work', p_work, 'saved', true);
END $$;

-- 0028/0030 판(6인자)이 남아 있으면 기본값이 겹쳐 호출이 모호해진다 — 지운다.
DROP FUNCTION IF EXISTS public.set_work_card(text, text, text, text, text, boolean);
REVOKE ALL     ON FUNCTION public.set_work_card(text,text,text,text,text,boolean,int) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.set_work_card(text,text,text,text,text,boolean,int) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0031','claude (작품별 소스 길이 하한 — source_min_duration 정본 + 뷰 usable 컬럼)')
ON CONFLICT DO NOTHING;
