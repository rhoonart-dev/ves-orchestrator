-- =====================================================================
-- 0036_loopy_ledger_pg.sql — 잔망루피 원장 중앙(정본 후보) 스키마 (B안 2단계 ②, 2026-08-14)
--
-- vlp ledger 의 postgres 백엔드가 쓰는 실테이블. sqlite 스키마와 컬럼·타입 의미를
-- 1:1 로 맞춘다(타임스탬프는 sqlite 그대로 text — 코드가 ISO 문자열을 읽고 쓴다).
-- search_path=loopy 로 접속해 raw SQL 의 "videos" 가 여기를 가리킨다.
-- ⚠ 이 시점엔 비어 있다 — 컷오버(§순서: 미러 대조 검증 → migrate-to-pg 1회 →
--   config ledger.backend=postgres) 전까지 정본은 여전히 mm-06 sqlite 다.
--   0034 의 loopy_ledger(미러)와 별개: 미러는 관제 열람용 사본, 이건 전환 후 정본.
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS loopy;

CREATE TABLE IF NOT EXISTS loopy.videos (
    video_id      text PRIMARY KEY,
    title         text,
    url           text,
    duration      double precision,
    view_count    bigint,
    like_count    bigint,
    comment_count bigint,
    published_at  text,
    state         text NOT NULL DEFAULT 'discovered',
    level_guess   text,
    score         double precision,
    scores        text,              -- sqlite 와 동일하게 JSON 문자열(코드가 json.dumps)
    notes         text,
    discovered_at text NOT NULL,
    updated_at    text NOT NULL,
    publish_at    text,
    youtube_id    text
);
CREATE INDEX IF NOT EXISTS idx_loopy_videos_state ON loopy.videos(state);

CREATE TABLE IF NOT EXISTS loopy.kpi_snapshots (
    video_id    text NOT NULL,
    youtube_id  text NOT NULL,
    taken_at    text NOT NULL,
    views       bigint,
    likes       bigint,
    comments    bigint,
    PRIMARY KEY (video_id, taken_at)
);

-- PostgREST(api) 노출 스키마가 아니다 — 대시보드 열람은 0034 미러가 담당.
-- 접속 주체는 워커의 PIPELINE_DB_URL 롤 하나뿐이라 별도 GRANT 불필요.

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0036','claude (잔망루피 중앙 원장 스키마 — vlp postgres 백엔드용, 컷오버 전 빈 테이블)')
ON CONFLICT DO NOTHING;
