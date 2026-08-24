-- =====================================================================
-- 0078_external_shorts_archive.sql — 외부 쇼츠 아카이브 (L-P3, 2026-08-23)
--
-- 발주서: docs/LOCALIZE_UNIFY.md §5-4·§5-5. 사용자 지시(8/23): "잔망루피 쇼츠는
-- 옛날 것부터 최신 것까지 주기적으로 자동 수집해서 가지고 있다가 사용할 수 있게".
--
-- 2층 구조 중 **① 메타 카탈로그**다. 전량(~1,100편) 영구 보관 — 행당 ~1KB 라 1MB 다.
-- ② 원본 파일은 여기 없다(고른 편만 acquire 가 받는다).
--
-- 이 테이블은 vlp `src/ledger.py` 의 videos 를 **승격**한 것이다(폐기가 아니라).
-- 그 원장이 '중복 업로드 방지(R10)의 단일 진실 소스'였고, 그 성질을 여기서도 지킨다:
--   · state='uploaded' 는 **종착**이다 — 트리거가 역행을 막는다(원장 TRANSITIONS 이식)
--   · 발행 이력(youtube_id·published_at)이 있으면 다시 고를 수 없다
-- ⚠ 이관 검증 전에는 선별기를 켜지 않는다(§8-5b).
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.external_shorts (
    video_id      text PRIMARY KEY,           -- 원 채널의 유튜브 영상 id
    channel_slug  text NOT NULL,              -- 우리 발행 채널(LOOPY 등)
    source_handle text,                       -- 원 채널 핸들(@zanmangloopy)
    title         text,
    url           text,
    thumbnail_url text,
    duration_sec  double precision,
    view_count    bigint,
    like_count    bigint,
    comment_count bigint,
    published_at  timestamptz,                -- 원본 공개일 — 다양성 순위의 재료(§5-6)
    kind          text NOT NULL DEFAULT 'short',   -- short | longform (길이로 분류)

    -- 상태 (vlp 원장 STATES 이식). uploaded 는 종착.
    state         text NOT NULL DEFAULT 'discovered',
    -- 선별기(§5-6) 판정 — P3b 가 채운다. 여기서는 열만 연다.
    score         double precision,
    scores        jsonb,
    flags         jsonb,                      -- LLM 심사 플래그(collab·sponsored·…)
    block_reason  text,                       -- 게이트 0/1 에서 걸린 사유(사람이 읽는다)
    allowed_by    text,                       -- 사람이 차단을 뒤집었으면 누가
    dup_of        text REFERENCES public.external_shorts(video_id),  -- 내용 중복 판정(§5-7)

    -- 발행 이력 (구 원장 이관 대상 — 지우면 같은 영상을 두 번 올린다)
    youtube_id    text,                       -- 우리 채널에 올라간 영상 id
    publish_at    timestamptz,
    work_order_id uuid,                       -- 작업을 걸었으면 그 작업지시

    notes         text,
    discovered_at timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT external_shorts_state_chk CHECK (state IN
        ('discovered','scored','selected','processing','pending_approval',
         'approved','uploaded','failed','skipped')),
    CONSTRAINT external_shorts_kind_chk CHECK (kind IN ('short','longform'))
);

COMMENT ON TABLE public.external_shorts IS
  '외부 쇼츠 아카이브(L-P3) — 원 채널 전량 메타. vlp ledger.videos 승격본. '
  'state=uploaded 는 종착(중복 발행 방지 R10).';

CREATE INDEX IF NOT EXISTS idx_ext_shorts_channel_state
    ON public.external_shorts(channel_slug, state);
CREATE INDEX IF NOT EXISTS idx_ext_shorts_pick
    ON public.external_shorts(channel_slug, kind, state, score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_ext_shorts_published
    ON public.external_shorts(channel_slug, published_at DESC NULLS LAST);

-- ── uploaded 는 종착 ─────────────────────────────────────────────────────
-- vlp 원장의 TRANSITIONS 가 코드로 막던 것을 DB 제약으로 옮긴다. 이관하면서
-- 이 성질을 잃으면 아카이브가 '단일 진실 소스'이기를 그만둔다(§8-5).
CREATE OR REPLACE FUNCTION public._external_shorts_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state = 'uploaded' AND NEW.state <> 'uploaded' THEN
        RAISE EXCEPTION 'uploaded 는 종착 상태입니다 — 되돌리면 같은 영상을 두 번 올립니다 (video %)',
            OLD.video_id;
    END IF;
    IF OLD.youtube_id IS NOT NULL AND NEW.youtube_id IS DISTINCT FROM OLD.youtube_id THEN
        RAISE EXCEPTION '발행 이력(youtube_id)은 덮어쓸 수 없습니다 (video %)', OLD.video_id;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS external_shorts_guard ON public.external_shorts;
CREATE TRIGGER external_shorts_guard BEFORE UPDATE ON public.external_shorts
    FOR EACH ROW EXECUTE FUNCTION public._external_shorts_guard();

ALTER TABLE public.external_shorts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS external_shorts_read ON public.external_shorts;
CREATE POLICY external_shorts_read ON public.external_shorts
    FOR SELECT TO authenticated USING (true);

-- ── 구 원장 미러(0034 loopy_ledger) → 아카이브 이관 ──────────────────────
-- 발행 이력을 잃으면 같은 영상을 두 번 올린다(§8-5). 미러가 없으면 0행 — 무해.
INSERT INTO public.external_shorts
    (video_id, channel_slug, source_handle, title, url, duration_sec,
     view_count, like_count, comment_count, published_at, kind, state,
     score, scores, notes, youtube_id, publish_at, discovered_at, updated_at)
SELECT l.video_id, 'LOOPY', '@zanmangloopy', l.title, l.url, l.duration,
       l.view_count, l.like_count, l.comment_count,
       NULLIF(l.published_at,'')::timestamptz,
       CASE WHEN coalesce(l.duration, 0) > 61 THEN 'longform' ELSE 'short' END,
       CASE WHEN l.state IN ('discovered','scored','selected','processing',
                             'pending_approval','approved','uploaded','failed','skipped')
            THEN l.state ELSE 'discovered' END,
       l.score, l.scores, l.notes, l.youtube_id,
       NULLIF(l.publish_at,'')::timestamptz,
       coalesce(NULLIF(l.discovered_at,'')::timestamptz, now()),
       coalesce(NULLIF(l.updated_at,'')::timestamptz, now())
  FROM public.loopy_ledger l
ON CONFLICT (video_id) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0078','claude (0078 외부 쇼츠 아카이브 — L-P3)')
ON CONFLICT DO NOTHING;
