-- ─────────────────────────────────────────────────────────────────────────────
-- 0063_run_now_direction.sql — 홈 '작업 실행'에 기획 방향(1회성 지시) 추가
--
-- 운영자가 홈에서 잡을 직접 실행할 때 "이번 한 편에만" 얹는 기획 방향을 받는다
-- (예: "특정 인물 중심으로 구성해줘"). generate 잡 params.editorial_run 으로 실려
-- aivideo.build_argv_pure 가 --editorial-run-json 으로 넘긴다. ai-video 가 작품
-- 카드의 상시 지침(--editorial-json)과 병합하며, **avoid·rules(권리사 요구)는
-- 실행 단위로 완화되지 않는다**(ai-video editorial.merge_editorial 이 강제).
-- prefer(랭킹 편향)로만 실린다 — 지시는 방향이지 권리 예외가 아니다.
--
-- 시그니처가 4→5 인자로 바뀌므로 구판을 먼저 지운다 — 남겨두면 named-call 이
-- 두 오버로드에 모두 매칭돼 모호성 에러가 난다. 본문은 적용 시점 라이브 정의
-- (pg_get_functiondef, 2026-08-20)를 베이스로 한 델타 2곳(v_gen 패치·audit)이다
-- (0055 교훈: 옛 파일을 베이스로 쓰면 그 뒤 머지분이 통째로 되돌아간다).
-- 짝: 대시보드 runNow(p_direction) · aivideo.build_argv_pure(editorial_run) ·
--     ai-video --editorial-run-json.
-- ─────────────────────────────────────────────────────────────────────────────

DROP FUNCTION IF EXISTS public.run_channel_now(text, text, integer, text);

CREATE OR REPLACE FUNCTION public.run_channel_now(
    p_slug text, p_work text DEFAULT NULL::text, p_episode integer DEFAULT NULL::integer,
    p_note text DEFAULT NULL::text, p_direction text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
                   -- 0039: 영상에 못박힌 장부(source_url 일치)는 발주처럼 그 행에
                   -- 직접 물린다 — 정렬이 바뀌어도(published_ts 백필) 안 흔들린다.
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
                   -- 못박히지 않은(회차 단위) 몫만 종전대로 앞선 행부터 흡수한다
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
    -- generate params — planner.job_chain 과 1:1. scene_rerender 컷오버(0031):
    -- JP 채널도 기본(완전) 렌더 — 재렌더가 체크포인트에서 일본어판을 새로 그린다.
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

    -- localize params — scene_rerender 컷오버(0031): 생성 노드 재렌더.
    -- 등급·백엔드·목소리는 더 이상 싣지 않는다(그 경로는 zanmang_daily 전용으로 남는다).
    v_loc := v_common || jsonb_build_object('mode', 'scene_rerender');

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
            ('localize',         v_loc,     ARRAY['generate'],  300, 6)
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
                               'direction', p_direction,
                               'source_id', v_src.id, 'localize_level', v_lv));

    RETURN jsonb_build_object('work_order_id', v_wo, 'channel', v_ch.name,
                              'work', v_work, 'episode', v_src.episode,
                              'source_id', v_src.id,
                              'pipeline', v_pipe, 'jobs', v_jobs);
END $function$;

REVOKE ALL ON FUNCTION public.run_channel_now(text, text, integer, text, text) FROM public;
REVOKE ALL ON FUNCTION public.run_channel_now(text, text, integer, text, text) FROM anon;
GRANT EXECUTE ON FUNCTION public.run_channel_now(text, text, integer, text, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0063','claude (홈 기획 방향 — run_channel_now p_direction)');
