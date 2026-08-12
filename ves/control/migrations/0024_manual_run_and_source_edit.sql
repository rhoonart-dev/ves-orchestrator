-- 0024: 관제에서 작업 실행 + 소스 소진 직접 수정 (2026-08-12 사용자 요청)
--
-- 세 덩어리다.
--
-- ① 홈에서 '작업 실행' — 채널을 눌러 지금 한 편 더 만든다. 오늘 planner 가 만든 것과
--    별개다(사용자 결정: "오늘 것과 별개로 한편 더"). 그런데 wo_uniq 가
--    (service_date, channel_slug, work_title, pipeline) 유일이라 같은 날 같은 작품으로는
--    두 번째 작업지시를 넣을 수 없었다. 그 유일성은 planner 재실행 멱등(R7)을 위한 것이지
--    사람이 손으로 한 편 더 넣는 것을 막으려던 게 아니다.
--    → work_orders.origin 을 두고 유일 제약을 origin='planner' 행에만 건다.
--      planner 는 종전대로 하루 한 번만 만들고, 사람이 만든 건 몇 편이든 들어간다.
--    ⚠ planner.py 가 ON CONFLICT (4컬럼) 을 쓰고 있다 — 부분 인덱스로는 그 추론이 안 된다.
--      이 마이그레이션과 같은 커밋의 planner 변경(WHERE NOT EXISTS)이 짝이다. 순서: 이 SQL 먼저,
--      코드 푸시 다음. 그 사이 09:00 KST 를 넘기지 말 것(넘기면 그날 planner 가 한 번 실패한다).
--
-- ② 소스 창고에서 소진 개수 수정 — 두 숫자를 연다.
--    · 한도(sources.use_limit): 지금은 등록 시 길이로 자동 결정(10분 미만 1·10~30분 2·30분↑ 3).
--      사람이 보고 올리거나 내릴 수 있어야 한다.
--    · 이미 쓴 수: 발주 기록(work_orders)은 정본이라 못 고친다. 고치는 건 레거시 몫
--      (source_usage_legacy)이다. 사람이 입력하는 값은 '이 채널이 이 회차를 실제로 몇 번 썼나'
--      (합계)이고, 함수가 합계 - 발주수 = 레거시로 환산해 저장한다. 인수인계 §3 의
--      '회차체계 상이 18행'을 사람이 관제에서 맞추는 통로다.
--
-- ③ 뷰 보안 복구(발견 사항) — source_usage 는 0010 에서 security_invoker 로 만들었는데
--    0022 의 CREATE OR REPLACE VIEW 가 WITH 절을 빠뜨려 옵션이 날아갔다. 0023 의
--    source_usage_by_channel 도 처음부터 없었다. 그래서 지금 두 뷰는 소유자 권한으로 돌아
--    RLS 를 우회한다 — anon(대시보드에 박혀 공개된 키)으로도 248행이 그대로 읽힌다.
--    실측: `set role anon; select count(*) from source_usage` → 248.
--    설계 원칙은 "로그인 없이는 아무것도 못 읽는다"(0007 머리말)이므로 되돌린다.

-- =====================================================================
-- ① work_orders.origin — planner 멱등은 지키고, 사람 실행은 열어준다
-- =====================================================================
ALTER TABLE public.work_orders
  ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'planner';
COMMENT ON COLUMN public.work_orders.origin IS
  'planner = 매일 09시 자동 계획(하루 채널당 1건, 유일 제약 대상) · manual = 관제에서 사람이 실행';

ALTER TABLE public.work_orders DROP CONSTRAINT IF EXISTS wo_uniq;
CREATE UNIQUE INDEX IF NOT EXISTS wo_uniq_planner
    ON public.work_orders (service_date, channel_slug, work_title, pipeline)
 WHERE origin = 'planner';
COMMENT ON INDEX public.wo_uniq_planner IS
  'R7 — planner 재실행 멱등. 사람이 만든 행(origin=manual)은 제외해 같은 날 추가 생산을 허용한다.';

-- =====================================================================
-- ② channels_mirror 에 country·pipeline — 파이프라인을 SQL 에서도 판정한다
--    (종전엔 channels.json 만 알고 있어서, RPC 가 JP 인지 전용 파이프라인인지 몰랐다)
-- =====================================================================
ALTER TABLE public.channels_mirror ADD COLUMN IF NOT EXISTS country  text;
ALTER TABLE public.channels_mirror ADD COLUMN IF NOT EXISTS pipeline text;
COMMENT ON COLUMN public.channels_mirror.country  IS 'channels.json 사본 — KR | JP';
COMMENT ON COLUMN public.channels_mirror.pipeline IS
  'channels.json 사본 — zanmang_autopilot 이면 전용 파이프라인(planner·수동 실행 대상 아님)';

-- 다음 channels_sync(08:00)까지 기다리지 않도록 지금 값을 채운다. 파일이 정본이므로
-- 08시에 덮어써진다 — 여기 값은 그때까지의 임시분이다.
UPDATE public.channels_mirror SET country = 'JP' WHERE token_slug IN ('SHOTCONE','LOOPY');
UPDATE public.channels_mirror SET country = 'KR' WHERE country IS NULL;
UPDATE public.channels_mirror SET pipeline = 'zanmang_autopilot' WHERE token_slug = 'LOOPY';

-- =====================================================================
-- ③ run_channel_now — 관제 '작업 실행'
--     p_work NULL  = 채널 정본 작품을 순서대로 훑어 첫 사용 가능 소스
--     p_episode 지정 = 그 회차만 (없으면 실패 — 사람 결정을 조용히 바꾸지 않는다)
--    planner._create_work_order 와 같은 체인·같은 params 를 만든다. 한 곳이 바뀌면 둘 다 본다.
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

    -- 소스 고르기 — planner._pick_source 와 같은 규칙:
    --   활성 · 3분 초과 · 오래된 것(=낮은 회차)부터 · 소진은 이 채널 몫만 센다(0023)
    FOREACH v_try IN ARRAY (CASE WHEN p_work IS NULL THEN v_ch.works ELSE ARRAY[p_work] END)
    LOOP
        SELECT s.* INTO v_src
          FROM public.sources s
         WHERE s.work_title = v_try
           AND s.is_active
           AND (s.duration_sec IS NULL OR s.duration_sec > 180)
           AND (p_episode IS NULL OR s.episode = p_episode)
           AND ( (SELECT count(*) FROM public.work_orders w
                   WHERE w.work_title = s.work_title
                     AND w.episode IS NOT DISTINCT FROM s.episode
                     AND w.channel_slug = p_slug
                     AND w.status NOT IN ('cancelled','failed'))
               + coalesce((SELECT l.used FROM public.source_usage_legacy l
                            WHERE l.work_title = s.work_title
                              AND l.episode IS NOT DISTINCT FROM s.episode
                              AND l.channel_slug = p_slug), 0)
               ) < s.use_limit
         ORDER BY s.episode NULLS LAST, s.created_at, s.id
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
                               'pipeline', v_pipe, 'jobs', v_jobs, 'note', p_note));

    RETURN jsonb_build_object('work_order_id', v_wo, 'channel', v_ch.name,
                              'work', v_work, 'episode', v_src.episode,
                              'pipeline', v_pipe, 'jobs', v_jobs);
END $$;
REVOKE ALL     ON FUNCTION public.run_channel_now(text, text, integer, text) FROM public;
GRANT  EXECUTE ON FUNCTION public.run_channel_now(text, text, integer, text) TO authenticated;

-- =====================================================================
-- ④ set_source_limit — 회차별 '만들 편수 한도'
--    ⚠ 한 회차에 파일 행이 여러 개인 경우가 실제로 있다(실측: 혜미리예채파 5화 3행,
--      샤먼:미신전 회차 NULL 6행 — sha 가 다른 별개 파일들이다). 소진은 (작품, 회차)로
--      세므로 한 행만 고치면 사람이 기대한 대로 안 움직인다. 그래서 회차 단위로 건다.
-- =====================================================================
CREATE OR REPLACE FUNCTION public.set_source_limit(p_source uuid, p_limit integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_s record; v_n int;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_limit IS NULL OR p_limit < 0 OR p_limit > 20 THEN
        RAISE EXCEPTION '한도는 0~20 사이여야 합니다 (받은 값: %)', p_limit;
    END IF;

    SELECT work_title, episode INTO v_s FROM public.sources WHERE id = p_source;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 소스: %', p_source; END IF;

    UPDATE public.sources s SET use_limit = p_limit
     WHERE s.work_title = v_s.work_title
       AND s.episode IS NOT DISTINCT FROM v_s.episode;
    GET DIAGNOSTICS v_n = ROW_COUNT;

    PERFORM public._audit('set_source_limit','sources', p_source::text,
            jsonb_build_object('work', v_s.work_title, 'episode', v_s.episode,
                               'use_limit', p_limit, 'rows', v_n));
    RETURN jsonb_build_object('source_id', p_source, 'work', v_s.work_title,
                              'episode', v_s.episode, 'use_limit', p_limit, 'rows', v_n);
END $$;
REVOKE ALL     ON FUNCTION public.set_source_limit(uuid, integer) FROM public;
GRANT  EXECUTE ON FUNCTION public.set_source_limit(uuid, integer) TO authenticated;

-- =====================================================================
-- ⑤ set_source_used — 회차별·채널별 '이미 쓴 수'
--    p_used 는 합계다. 발주 기록(work_orders)은 정본이라 건드리지 않고, 차액만 레거시에 담는다.
--    발주수보다 낮게는 못 내린다 — 내리려면 그 작업지시를 취소해야 한다(이중장부 방지).
-- =====================================================================
CREATE OR REPLACE FUNCTION public.set_source_used(
    p_source uuid, p_channel text, p_used integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_s record; v_wo int; v_legacy int; v_who text;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_used IS NULL OR p_used < 0 THEN
        RAISE EXCEPTION '쓴 수는 0 이상이어야 합니다 (받은 값: %)', p_used;
    END IF;

    SELECT work_title, episode INTO v_s FROM public.sources WHERE id = p_source;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 소스: %', p_source; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_channel) THEN
        RAISE EXCEPTION '없는 채널: %', p_channel;
    END IF;

    SELECT count(*) INTO v_wo FROM public.work_orders w
     WHERE w.work_title = v_s.work_title
       AND w.episode IS NOT DISTINCT FROM v_s.episode
       AND w.channel_slug = p_channel
       AND w.status NOT IN ('cancelled','failed');

    IF p_used < v_wo THEN
        RAISE EXCEPTION '발주 기록이 이미 %건입니다 — 그 아래로는 내릴 수 없습니다. '
                        '작업 내역에서 해당 작업지시를 취소하세요', v_wo;
    END IF;

    v_legacy := p_used - v_wo;
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
                               'used_wo', v_wo, 'used_legacy', v_legacy));
    RETURN jsonb_build_object('source_id', p_source, 'channel', p_channel,
                              'used_total', p_used, 'used_wo', v_wo,
                              'used_legacy', v_legacy);
END $$;
REVOKE ALL     ON FUNCTION public.set_source_used(uuid, text, integer) FROM public;
GRANT  EXECUTE ON FUNCTION public.set_source_used(uuid, text, integer) TO authenticated;

-- =====================================================================
-- ⑥ 뷰 보안 복구 — 로그인 없이는 아무것도 못 읽는다(0007 머리말)
--    ALTER VIEW ... SET 을 쓴다. CREATE OR REPLACE 로 다시 쓰면 컬럼 순서 함정(§5)에 걸린다.
-- =====================================================================
ALTER VIEW public.source_usage            SET (security_invoker = true);
ALTER VIEW public.source_usage_by_channel SET (security_invoker = true);

REVOKE ALL ON public.source_usage            FROM anon;
REVOKE ALL ON public.source_usage_by_channel FROM anon;
REVOKE ALL ON public.source_usage_legacy     FROM anon;

GRANT SELECT ON public.source_usage            TO authenticated;
GRANT SELECT ON public.source_usage_by_channel TO authenticated;
GRANT SELECT ON public.source_usage_legacy     TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0024',
        'claude-cloud (0024 관제 작업 실행 + 소스 소진 수정 + 뷰 security_invoker 복구)')
ON CONFLICT DO NOTHING;
