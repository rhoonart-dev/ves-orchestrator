-- =====================================================================
-- 0039_legacy_usage_pin_source.sql — 레거시 장부를 '영상'에 못박는다 (2026-08-14)
--
-- 왜: source_usage_legacy 는 (작품·채널·회차) 단위다. 레거시는 회차당 영상 하나만
-- 썼는데(가장 긴 것), 0027 부터 한 회차에 영상이 여럿이라 "그 3편을 어느 영상으로
-- 썼는가"가 기록에 없다. planner 는 어쩔 수 없이 **앞선 행부터** 차감한다.
--
-- 그 '앞'이 흔들리면 소진이 엉뚱한 영상에 찍힌다. 실제로 흔들리기 직전이다 —
-- published_ts 백필(deploy/backfill_published_ts.py)을 적용하면 회차 내 순서가
-- 업로드 순으로 뒤집힌다. 도깨비 1회차 실측:
--   · 지금  : RMw9on5u2j0(19:51 하이라이트)에 3편이 찍힌다 — 레거시가 실제로 쓴 영상
--   · 적용 후: Uf5sTr0P5HM(6:47, 07-04)로 옮겨간다 — 레거시가 안 쓴 영상
-- 그러면 이미 쓴 영상이 '미사용'으로 풀려 **같은 소재를 또 만들고**, 안 쓴 영상은
-- '소진'으로 잠겨 **영영 안 만들어진다**.
--
-- 그래서 source_url 을 장부에 적어 그 영상에 정확히 물린다. 비어 있으면(NULL)
-- 종전대로 회차 단위로 앞선 행부터 차감한다 — 기존 작품의 동작은 그대로다.
--
-- 시드(도깨비 10주년 여행): 관제에서 8/13 에 넣은 서수 회차 13·19·33 은 그 뒤 회차
-- 재파싱으로 고아가 됐다. 그 세 행이 가리키던 영상은 각 방송 회차의 **가장 긴 영상**
-- 으로, 레거시 규칙(회차당 최장 1건)과 정확히 일치한다(8/14 대조 확인):
--   EP.1 RMw9on5u2j0 19:51 · EP.2 KRFeF67lkyA 19:33 · EP.3 YVdYrufNq6s 19:59
-- 8/12 '레거시 결산' 행(회차 1·2·3)이 같은 편수(3·3·2)를 담고 있으므로 그쪽에
-- URL 을 박고, 고아가 된 13·19·33 은 지운다 — 둘 다 두면 같은 몫이 두 번 차감된다.
-- EP.4(회차 4, 1편)는 GYiJYX1qtkg(20:25, 그 회차 최장)에 박는다. 편수는 장부값을
-- 그대로 둔다 — clips 기록은 7/24 에 3건을 만든 것으로 보여 값이 다르지만, 무엇이
-- 맞는지는 사람이 정할 일이라 추측으로 올리지 않는다.
-- =====================================================================

ALTER TABLE public.source_usage_legacy
  ADD COLUMN IF NOT EXISTS source_url text;

COMMENT ON COLUMN public.source_usage_legacy.source_url IS
  '이 몫을 어느 영상에 물릴지. NULL 이면 회차 단위로 앞선 행부터 차감(종전 동작). '
  '레거시는 회차당 영상 하나만 썼으므로, 아는 경우 여기에 적어 순서 변화에 흔들리지 않게 한다.';

-- ── 도깨비 10주년 여행: 아는 매핑을 못박는다 ─────────────────────────
UPDATE public.source_usage_legacy l SET source_url = v.url
  FROM (VALUES
    ('도깨비 10주년 여행','TETOCHIP',1,'https://www.youtube.com/watch?v=RMw9on5u2j0'),
    ('도깨비 10주년 여행','TETOCHIP',2,'https://www.youtube.com/watch?v=KRFeF67lkyA'),
    ('도깨비 10주년 여행','TETOCHIP',3,'https://www.youtube.com/watch?v=YVdYrufNq6s'),
    ('도깨비 10주년 여행','TETOCHIP',4,'https://www.youtube.com/watch?v=GYiJYX1qtkg')
  ) AS v(work, ch, ep, url)
 WHERE l.work_title = v.work AND l.channel_slug = v.ch AND l.episode = v.ep
   AND l.source_url IS NULL;

-- 회차 재파싱으로 고아가 된 서수 행(13·19·33) — 같은 몫이 위에 이미 박혔다.
DELETE FROM public.source_usage_legacy
 WHERE work_title = '도깨비 10주년 여행' AND channel_slug = 'TETOCHIP'
   AND episode IN (13, 19, 33) AND source_url IS NULL;

-- ── run_channel_now 도 같은 규칙으로 (0032 판 그대로에 장부 못박기만) ──────
-- planner(pick_from_rows)만 고치면 자동 배정과 관제 '지금 실행'이 서로 다른 영상을
-- 고른다 — 못박힌 몫을 이 RPC 는 여전히 앞선 행부터 흡수시키므로, published_ts 백필로
-- 순서가 바뀌는 순간 레거시가 이미 쓴 영상을 다시 집을 수 있다(도깨비 1회차 실측 구조).
-- 바뀐 곳은 base CTE 하나다: 못박힌 장부(source_url 일치)를 발주(used_wo)에 합산해
-- 그 행에 직접 물리고, legacy_ep 는 못박히지 않은(source_url IS NULL) 몫만 남긴다.
-- (열 수를 유지해 SELECT r.* INTO v_src 의 구조를 0032 와 동일하게 지켰다)
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
                               'source_id', v_src.id, 'localize_level', v_lv));

    RETURN jsonb_build_object('work_order_id', v_wo, 'channel', v_ch.name,
                              'work', v_work, 'episode', v_src.episode,
                              'source_id', v_src.id,
                              'pipeline', v_pipe, 'jobs', v_jobs);
END $$;
REVOKE ALL     ON FUNCTION public.run_channel_now(text, text, integer, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.run_channel_now(text, text, integer, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0039','claude (레거시 장부에 source_url — 순서 변화에도 소진이 안 흔들리게)')
ON CONFLICT DO NOTHING;
