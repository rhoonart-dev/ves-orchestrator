-- =====================================================================
-- 0029_run_channel_now_fix.sql — 0027 이 run_channel_now 를 다시 쓰며 흘린 것 복구
--                                 + 레거시 차감식 교정 + 현지화 등급 전달 (2026-08-13)
--
-- 왜 0027 을 고치지 않고 0029 인가: 0027 은 이미 운영 DB 에 적용됐다. 적용된 파일을
-- 사후 편집하면 다음 사람이 파일만 보고 DB 상태를 오판한다. 새 번호로 남긴다.
--
-- ① 0027 이 0024 에서 흘린 것 세 가지 — 운영 DB 에 이미 실려 있던 회귀다.
--    · job_queue.priority = 150 이 통째로 빠져 기본값 100 으로 들어갔다.
--      claim 은 ORDER BY priority DESC 다(0024 주석: "사람이 눌러 기다리는 일이라
--      일상 잡보다 앞세운다"). 관제 '작업 실행'이 일상 잡 뒤로 밀렸다.
--    · 멱등키의 'manual:' 접두사가 빠져 잡 큐에서 planner/manual 구분이 사라졌다.
--    · 반환 jsonb 의 'channel' 키가 빠져 대시보드 토스트가 "undefined" 를 찍었다
--      (dashboard/index.html 의 작업 실행 성공 토스트가 r.channel 을 읽는다).
--    _audit 페이로드도 0024 형태('slug'·'pipeline')로 되돌리고 source_id 만 더한다.
--
-- ② 레거시 차감식 교정 — 0027 이 새로 만든 결함.
--    limit_before 는 앞 행의 **한도 합**을 뺐는데, planner.pick_from_rows 는 앞 행이
--    실제로 흡수한 **남은 여유 합**만 뺀다. SQL 이 늘 더 느슨해서 회차 총한도를 넘겨
--    한 편 더 만든다. 반례: legacy 2 · 행1(limit 2, used 1) · 행2(limit 1, used 0)
--      - python: 행1 free=1 → take 1, 남은 legacy 1 → 행2 free=1 → take 1 → 소진(None)
--      - 종전 SQL: 행2 의 limit_before=2 → GREATEST(2-2,0)=0 → 0+0 < 1 → 행2 채택(오답)
--    free_before(앞 행들의 GREATEST(use_limit - used_wo, 0) 누적)로 바꾼다.
--
-- ③ 현지화 파라미터 전달 — 0024 부터 있던 구멍(0027 이 만든 것은 아니다).
--    localize 잡에 level/backend/voice_id 를 안 실어 등급이 늘 B 로 떨어졌다.
--    운영 실측 ops_config.localize_levels={"SHOTCONE":"J"} 인데 B 로 가면 mm-06 에
--    LaMa 가중치가 없어 make_inpainter 가 즉사한다(0026 이 기록한 그 사고).
--    planner.job_chain 과 1:1 로 맞춘다 — 등급 J 는 generate 단계에서 텍스트를
--    처음부터 안 그리게 하는 플래그 네 개가 함께 붙는다.
--
-- ④ advisor 정리 — 0027·0028 이 남긴 경고 두 건(실악용 경로는 함수 내부 권한 가드가
--    막고 있어 긴급하지는 않다).
-- =====================================================================

-- ── ④ advisor: 순수 비교 함수의 search_path 고정 + PUBLIC 실행 회수 ──
ALTER FUNCTION public.wo_matches_source(text,text,text,text,text,text)
  SET search_path = pg_catalog, public;
REVOKE ALL ON FUNCTION public.wo_matches_source(text,text,text,text,text,text) FROM public;
GRANT EXECUTE ON FUNCTION public.wo_matches_source(text,text,text,text,text,text) TO authenticated;

-- ── ④ advisor: SECURITY DEFINER 함수에서 anon 직접 grant 회수 ──
-- 0008_rpc_grants_fix.sql 이 문서화한 함정: REVOKE FROM public 으로는 Supabase 가
-- 걸어 둔 anon 직접 grant 가 안 걷힌다. anon 을 명시해야 한다.
REVOKE ALL ON FUNCTION public.set_work_card(text,text,text,text,text,boolean) FROM anon;
REVOKE ALL ON FUNCTION public.run_channel_now(text,text,integer,text)          FROM anon;
REVOKE ALL ON FUNCTION public.set_source_limit(uuid,integer)                   FROM anon;
REVOKE ALL ON FUNCTION public.set_source_used(uuid,text,integer)               FROM anon;
REVOKE ALL ON TABLE public.work_cards FROM anon;

-- =====================================================================
-- run_channel_now — 관제 '작업 실행'
--   0027 판에서 바뀌는 것: priority·멱등키 접두사·반환 channel 복구,
--                          free_before 차감, 현지화 파라미터 전달.
--   그대로인 것: 권한·전용 파이프라인 차단·JP 스위치·작품 배정 가드·행 단위 집계.
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
               AND (s2.duration_sec IS NULL OR s2.duration_sec > 180)
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

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0029','claude (run_channel_now 복구 — priority·manual 키·channel 반환 + 레거시 차감 교정 + 현지화 등급 전달)')
ON CONFLICT DO NOTHING;
