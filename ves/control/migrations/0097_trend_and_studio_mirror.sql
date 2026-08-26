-- =====================================================================
-- 0097_trend_and_studio_mirror.sql — 일일 트렌드 리포트 1단 (T-P1, 2026-08-26)
--
-- 발주서: docs/TREND_REPORT.md §2·§3.
--
-- 두 테이블을 연다:
--   ① perf_studio_daily — laeebly `youtube_studio` 의 **깔때기** 미러
--   ② trend_snapshot    — 외부(KR/JP/US) 급상승·검색 트렌드
--
-- ## 왜 perf_video_snapshot 에 컬럼을 더하지 않고 새 테이블인가
--
-- 알갱이가 다르다. `perf_video_snapshot` 은 **그 시점의 누적**(조회수 총계)이고
-- `youtube_studio` 는 **그날치 증분**(그날 받은 노출·조회)이다. 한 테이블에 섞으면
-- 같은 컬럼을 어떤 행은 누적으로 어떤 행은 증분으로 읽게 된다 — 합계가 조용히 틀린다.
--
-- ## ⚠ 날짜 축은 upload_at 이다 — created_at 이 아니다
--
-- 원천의 `upload_at` 은 **그 통계가 어느 날짜의 것인지**이고 `created_at` 은 **언제
-- 수집했는지**다. 하루에 여러 날짜분을 몰아 넣는 날이 있어 둘이 갈린다 — 8/15 실측:
-- 06:19 수집분은 8/10 자(노출 107), 16:35 수집분은 8/11 자(노출 135). 같은 날 재보고가
-- 아니라 **서로 다른 날의 증분**이다. `(content_id, upload_at)` 은 유일하다
-- (B급 순삭 8월 파티션 1,779행 = 1,779키 실측).
--
-- 영상 생애 지표는 **날짜별 행의 합**이다. 비율(CTR·완주율)은 단순 평균이 아니라
-- 노출·조회 가중 평균으로 낸다(§5). 조회수가 줄어드는 날도 있다(무효 조회 후보정) —
-- 단조 증가를 가정하지 말 것.
-- =====================================================================

-- ① 깔때기 미러 ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.perf_studio_daily (
    content_id   text NOT NULL,
    stat_date    date NOT NULL,          -- laeebly upload_at 의 KST 날짜(= 통계 대상일)
    channel_id   text NOT NULL,
    work_title   text,                   -- licensed_video_title — **분석의 축**
    video_title  text,
    publish_time timestamptz,
    video_length numeric,                -- 초

    -- 깔때기 3단 (§5 진단 규칙이 이 순서로 읽는다)
    impressions  bigint,                 -- 1단 · 노출
    ctr          numeric,                -- 2단 · impression_click_rate (%)
    views        bigint,
    valid_views  bigint,
    view_pct     numeric,                -- 3단 · average_view_percentage (%, 100 초과 = 재시청)
    kept_rate    numeric,                -- kept_watching_rate (%)
    watch_hours  numeric,

    -- 성공 요인 분석 재료 (§5 후반)
    subscribers  bigint,
    likes        bigint,
    shares       bigint,
    comments     bigint,

    synced_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (content_id, stat_date)
);

CREATE INDEX IF NOT EXISTS perf_studio_daily_ch_date
    ON public.perf_studio_daily (channel_id, stat_date DESC);
CREATE INDEX IF NOT EXISTS perf_studio_daily_work
    ON public.perf_studio_daily (work_title) WHERE work_title IS NOT NULL;
CREATE INDEX IF NOT EXISTS perf_studio_daily_date
    ON public.perf_studio_daily (stat_date DESC);

COMMENT ON TABLE public.perf_studio_daily IS
 'laeebly youtube_studio 깔때기 미러(0097) — **그날치 증분**이다. 영상 생애 지표는 '
 '날짜별 행의 합이고, 비율은 노출·조회 가중 평균으로 낸다. perf_video_snapshot(누적)과 '
 '알갱이가 다르니 섞지 말 것. LOOPY 는 laeebly MCN 밖이라 여기 없다.';

-- ② 외부 트렌드 ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.trend_snapshot (
    collected_date date NOT NULL,
    region         text NOT NULL,        -- KR | JP | US
    source         text NOT NULL,        -- youtube_chart | google_trends
    rank           int  NOT NULL,
    title          text,
    video_id       text,
    channel_title  text,
    category_id    text,
    view_count     bigint,
    published_at   timestamptz,
    raw            jsonb,
    collected_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (collected_date, region, source, rank)
);

CREATE INDEX IF NOT EXISTS trend_snapshot_date ON public.trend_snapshot (collected_date DESC);

COMMENT ON TABLE public.trend_snapshot IS
 '외부 트렌드 일일 스냅샷(0097). chart=mostPopular 는 2025-07-21 이후 통합 Trending Now '
 '가 아니라 Music/Movies/Gaming 카테고리 차트를 돌려준다 — 전량 급상승이 아니다.';

-- ③ RLS ────────────────────────────────────────────────────────────────
-- 0078 과 같은 규율: 켜고 authenticated 읽기만 연다. **켜지 않으면 anon 이 읽는다** —
-- 성과 지표는 공개값이 아니다. 쓰기는 정책이 없으므로 service_role(수집기)만 한다.
ALTER TABLE public.perf_studio_daily ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS perf_studio_daily_read ON public.perf_studio_daily;
CREATE POLICY perf_studio_daily_read ON public.perf_studio_daily
    FOR SELECT TO authenticated USING (true);

ALTER TABLE public.trend_snapshot ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS trend_snapshot_read ON public.trend_snapshot;
CREATE POLICY trend_snapshot_read ON public.trend_snapshot
    FOR SELECT TO authenticated USING (true);

-- ④ 설정 행 ────────────────────────────────────────────────────────────
-- 0080 규율: 코드의 DEFAULTS 와 같은 값으로 행을 열어 둔다. 행이 없으면 사람이 켤 수단이 없다.
INSERT INTO public.ops_config(key, value, note) VALUES
 ('trend_scout',
  '{"enabled": false, "regions": ["KR","JP","US"], "max_per_region": 50}',
  '외부 트렌드 수집기(T-P1) — 매일 03:00 KST. videos.list chart=mostPopular 가 '
  '지역당 1유닛이라 3지역 3유닛(무료 일일 한도의 0.03%). enabled=false 면 수집하지 '
  '않는다 — YOUTUBE_API_KEY 확인 뒤 사람이 켠다'),

 ('algo_constants',
  '{"sweet_spot_sec": [30,45], "retention_min": {"lt30": 65.0, "30to60": 50.0}, '
  '"impression_floor": 100, "ctr_floor": 2.0, '
  '"checked_at": "2026-08-26", "confidence": "역추론", '
  '"source": "크리에이터 매체 종합 — 유튜브 공식 문서 아님"}',
  '리포트 판정 임계값(T-P1 §5) — 여기 한 곳에서만 고친다. 유튜브가 공표하지 않는 값이라 '
  '주 1회 재조사하되 **자동 반영하지 않는다**. 조사 결과는 algo_constants_proposed 에 '
  '쌓이고, 반영은 사람이 한다. 우리 실측이 쌓이면 그 값으로 교정할 것')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0097','claude (0097 트렌드·스튜디오 미러 — T-P1)')
ON CONFLICT DO NOTHING;
