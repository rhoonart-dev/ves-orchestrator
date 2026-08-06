-- =====================================================================
-- 0006_orchestration.sql — v3.1 통합 (⚠ 적용은 사용자 확인 후. 전량 가산적)
-- =====================================================================

-- ── 노드 등록·심박 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.node_registry (
    node_id         text PRIMARY KEY,              -- 'mm-01'…'mm-06' (논리명)
    hostname        text,
    capabilities    text[] NOT NULL DEFAULT '{}',  -- {generate,analyze,publish,localize,scheduler,gpu_mps,network}
    max_concurrency int  NOT NULL DEFAULT 1,
    agent_version   text,
    engine_versions jsonb NOT NULL DEFAULT '{}',   -- {ai_video:'b935d20', brain:'…', …}
    updating_since  timestamptz,                   -- 업데이트 중이면 non-null (경보 제외용)
    status          text NOT NULL DEFAULT 'active',-- active/draining/disabled
    disk_free_gb    numeric,
    last_seen_at    timestamptz NOT NULL DEFAULT now(),
    meta            jsonb NOT NULL DEFAULT '{}',
    CONSTRAINT node_status_chk CHECK (status IN ('active','draining','disabled'))
);

-- ── 하루치 지시서 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.work_orders (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service_date      date NOT NULL,               -- KST 운영일
    channel_slug      text NOT NULL,
    work_title        text NOT NULL,               -- laeebly 정본과 일치 (R14)
    episode           int,
    source_sha256     text,                        -- sources 참조 (R14)
    pipeline          text NOT NULL DEFAULT 'shorts_kr',  -- shorts_kr | shorts_jp_localized
    round_id          int,
    knob_config       jsonb NOT NULL DEFAULT '{}',
    geoblock_required boolean NOT NULL DEFAULT true,  -- ★①: planner가 laeebly guide로 스탬프.
                                                      --   기본 true = 안전측(미확인이면 공개 차단)
    has_subtitle      boolean NOT NULL DEFAULT false, -- sources에서 복사 → --no-subtitles 자동화
    status            text NOT NULL DEFAULT 'open',
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT wo_uniq UNIQUE (service_date, channel_slug, work_title, pipeline),
    CONSTRAINT wo_status_chk CHECK (status IN ('open','done','cancelled','failed'))
);

-- ── 잡 큐 ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.job_queue (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id    uuid REFERENCES public.work_orders(id) ON DELETE CASCADE,
    kind             text NOT NULL,                -- acquire/generate/upload_artifacts/ingest/
                                                   -- evaluate/localize/publish/measure/audit/
                                                   -- reconcile/storage_gc/channels_sync
    params           jsonb NOT NULL DEFAULT '{}',
    idempotency_key  text NOT NULL,
    depends_on       uuid[] NOT NULL DEFAULT '{}',
    required_caps    text[] NOT NULL DEFAULT '{}',
    priority         int  NOT NULL DEFAULT 100,
    lease_ttl_sec    int  NOT NULL DEFAULT 120,    -- ★⑤: generate/localize는 planner가 300으로
    status           text NOT NULL DEFAULT 'pending',
    attempt          int  NOT NULL DEFAULT 0,
    max_attempts     int  NOT NULL DEFAULT 3,
    node_id          text REFERENCES public.node_registry(node_id),
    lease_expires_at timestamptz,
    run_after        timestamptz NOT NULL DEFAULT now(),
    result           jsonb,                        -- {run_id, engine_sha{}, artifact_ids[], …}
    error            text,
    error_class      text,                         -- transient/permanent/quota/human_required
    started_at       timestamptz, finished_at timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT job_idem_uniq  UNIQUE (idempotency_key),
    CONSTRAINT job_status_chk CHECK (status IN
        ('pending','running','succeeded','failed','dead','blocked','cancelled'))
);
CREATE INDEX IF NOT EXISTS idx_job_claimable ON public.job_queue (priority DESC, run_after)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_job_lease ON public.job_queue (lease_expires_at)
    WHERE status = 'running';
CREATE INDEX IF NOT EXISTS idx_job_wo ON public.job_queue(work_order_id);

-- ── 감사 로그 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.job_events (
    id bigserial PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES public.job_queue(id) ON DELETE CASCADE,
    at timestamptz NOT NULL DEFAULT now(),
    node_id text, from_status text, to_status text,
    detail jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_job_events_job ON public.job_events(job_id, at);

-- ── 산출물 카탈로그 ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.artifacts (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id        uuid REFERENCES public.job_queue(id) ON DELETE SET NULL,
    work_order_id uuid REFERENCES public.work_orders(id) ON DELETE CASCADE,
    kind          text NOT NULL,        -- shorts_mp4/preview_mp4/thumb/edit_plan/run_log/
                                        -- final_draft_mp4/…/  '_orphan' 접미사 = 소유권 상실분(§6-3)
    sha256        text NOT NULL,
    bytes         bigint,
    bucket        text NOT NULL,        -- ves-sources | ves-outputs | ves-localized
    object_key    text NOT NULL,
    expires_at    timestamptz,          -- storage_gc 가 이 시각 후 삭제 (§9-4)
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT artifact_sha_kind_uniq UNIQUE (sha256, kind)
);

-- ── 사람 검수 대기열 (3지점 통합) ──────────────────────────────
CREATE TABLE IF NOT EXISTS public.review_queue (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind          text NOT NULL,        -- publish_gate | promotion_gate | localization_qa
    work_order_id uuid REFERENCES public.work_orders(id) ON DELETE CASCADE,
    job_id        uuid REFERENCES public.job_queue(id) ON DELETE SET NULL,
    clip_id       uuid,
    channel_slug  text,
    round_id      int,
    payload       jsonb NOT NULL DEFAULT '{}',   -- preview object_key · judge 사유 · 수치 근거
    status        text NOT NULL DEFAULT 'waiting',
    decided_by    text, decided_at timestamptz, decision_note text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT rq_kind_chk   CHECK (kind IN ('publish_gate','promotion_gate','localization_qa')),
    CONSTRAINT rq_status_chk CHECK (status IN ('waiting','approved','rejected','expired'))
);
CREATE INDEX IF NOT EXISTS idx_rq_waiting ON public.review_queue(status, created_at)
    WHERE status = 'waiting';

-- ── 자원 세마포어 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.resource_limits (
    resource   text PRIMARY KEY,        -- 'gemini:VES01' | 'yt_upload:_global' | 'storage_dl'
    max_active int NOT NULL,
    note       text
);
CREATE TABLE IF NOT EXISTS public.resource_leases (
    resource   text NOT NULL,
    job_id     uuid NOT NULL REFERENCES public.job_queue(id) ON DELETE CASCADE,
    node_id    text,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (resource, job_id)
);

-- ── 소스 원장 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.sources (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    work_title    text NOT NULL,        -- laeebly 정본 (등록 RPC가 대조, R14)
    episode       int,
    sha256        text NOT NULL UNIQUE,
    object_key    text NOT NULL,        -- ves-sources/sha256/<hash>
    bytes         bigint, duration_sec numeric,
    has_subtitle  boolean NOT NULL DEFAULT false,
    subtitle_key  text,
    origin        text,                 -- drive | youtube | upload
    registered_by text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sources_work ON public.sources(work_title, episode);

-- ── 배포·버전 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.deployments (
    engine        text PRIMARY KEY,     -- ai_video | localization | brain | orchestrator
    repo_url      text NOT NULL,
    track_ref     text NOT NULL DEFAULT 'main',
    auto_update   boolean NOT NULL DEFAULT true,
    pinned_sha    text,                 -- auto_update=false 일 때만 (롤백 핀, 부록 C)
    last_seen_sha text,                 -- version_watch(시간당 1회)가 갱신
    updated_at    timestamptz NOT NULL DEFAULT now()
);

-- ★③ 마이그레이션 게이트 원장 — "이 DB에 어느 마이그레이션이 적용됐나"
CREATE TABLE IF NOT EXISTS public.applied_migrations (
    engine     text NOT NULL,           -- brain | orchestrator
    version    text NOT NULL,           -- '0006' 등 (파일명 접두)
    applied_at timestamptz NOT NULL DEFAULT now(),
    applied_by text,
    PRIMARY KEY (engine, version)
);

-- ★② 채널 미러 — 정본은 channels.json(파일). RPC 검증용 읽기 사본
CREATE TABLE IF NOT EXISTS public.channels_mirror (
    token_slug       text PRIMARY KEY,
    name             text NOT NULL,
    channel_id       text,
    gcp_project      text,
    geoblock_capable boolean NOT NULL DEFAULT false,
    works            text[] NOT NULL DEFAULT '{}',
    synced_sha       text NOT NULL,     -- 어느 커밋의 channels.json에서 왔나
    synced_at        timestamptz NOT NULL DEFAULT now()
);

-- ── 대시보드 행위 감사 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.dashboard_actions (
    id bigserial PRIMARY KEY,
    at timestamptz NOT NULL DEFAULT now(),
    actor text NOT NULL,
    action text NOT NULL,               -- approve_publish/reject/retry/drain/pin/register_source/…
    target_kind text, target_id text,
    payload jsonb NOT NULL DEFAULT '{}'
);

-- ── loop_state.json → DB 이관 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS public.loop_rounds (
    round int PRIMARY KEY,
    config jsonb NOT NULL,
    cohort_ids text[],
    status text NOT NULL DEFAULT 'proposed',
    pct numeric, ci_lo numeric, ci_hi numeric,
    n int, n_works int, watchsec_pct numeric, guardrail text, window_days int,
    audit jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
