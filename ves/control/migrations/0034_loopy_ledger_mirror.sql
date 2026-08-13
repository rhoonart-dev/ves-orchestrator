-- =====================================================================
-- 0034_loopy_ledger_mirror.sql — 잔망루피 원장 미러 (B안 2단계 ①, 2026-08-14)
--
-- 사용자 결정 8/14: "모든 맥에서 나오는 결과물을 supabase 에 저장해서 관리".
-- 원장(autopilot.db sqlite)은 중복 업로드 방지(R10)의 단일 진실 소스라 한 번에
-- 못 바꾼다 — 정석대로 간다: ① 미러(이 파일) → ② 대조 검증 → ③ 소스 전환.
-- 매 daily 후 zanmang.post_success 가 sqlite 전체를 여기로 upsert 한다.
-- 이 단계에서 이 테이블은 **읽기 전용 사본**이다 — 쓰기 주체는 미러 하나뿐이고,
-- 운영 결정(mark·approve)은 여전히 sqlite 가 정본이다.
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.loopy_ledger (
    video_id      text PRIMARY KEY,
    title         text,
    url           text,
    duration      double precision,
    view_count    bigint,
    like_count    bigint,
    comment_count bigint,
    published_at  text,              -- 원본(sqlite) 표기 그대로 — 전환(③) 때 타입 정리
    state         text NOT NULL,
    level_guess   text,
    score         double precision,
    scores        jsonb,
    notes         text,
    discovered_at text,
    updated_at    text,
    publish_at    text,
    youtube_id    text,
    synced_at     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.loopy_ledger IS
  '잔망루피 autopilot 원장 미러(0034) — 정본은 아직 mm-06 sqlite. 매 daily 후 전체 upsert.';
CREATE INDEX IF NOT EXISTS idx_loopy_ledger_state ON public.loopy_ledger(state);

ALTER TABLE public.loopy_ledger ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS loopy_ledger_read ON public.loopy_ledger;
CREATE POLICY loopy_ledger_read ON public.loopy_ledger
    FOR SELECT TO authenticated USING (true);

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0034','claude (잔망루피 원장 미러 테이블 — 매 daily 후 전체 동기화)')
ON CONFLICT DO NOTHING;
