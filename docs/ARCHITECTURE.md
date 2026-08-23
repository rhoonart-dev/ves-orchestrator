# VES 통합 아키텍처 — v3.1 (통합본)

> **이 문서 하나가 정본이다.** v1 · v2 · v3-delta 세 문서를 통합하고, 전체 검토에서 나온
> 결함 9건(🔴5 · 🟡4)을 반영했다. 이전 문서들은 이력으로만 남긴다.
> **작성**: 2026-08-04 · 근거: 3개 레포 실코드 실측 + YouTube Data API v3 / Supabase 공식 문서
>
> **v3.1 변경 요지** — ①지오블락 검증을 스탬프 방식으로(§10-3) ②채널 정본 이원화 해소(§11-5)
> ③마이그레이션 게이트(§11-3) ④엔진별 venv 분리(§11-2) ⑤좀비 워커 펜싱(§6-3)
> ⑥세마포어 레이스 수정(§7) ⑦체크포인트 재개 계약(§6-6) ⑧measure 앵커 교정(§8-3)
> ⑨드리프트 경보 조건 교정(§11-6)

---

## 0. 한 장 요약

| 항목 | 결정 |
|---|---|
| 저장소 | **`ves-orchestrator` 신설.** 기존 3레포는 실행 엔진으로 유지, CLI 계약으로만 호출 |
| 플릿 | **동질 워커 풀 6대.** 채널 고정 배정 폐지, capability 태그로만 제한 |
| 컨트롤 플레인 | **fdidiqd Supabase.** `job_queue` + `FOR UPDATE SKIP LOCKED` claim + lease |
| 아티팩트 스토어 | **Supabase Storage** (같은 프로젝트). private 버킷 3개, 서명 URL |
| 대시보드 | **AWS S3 정적 SPA + CloudFront.** 백엔드 없음 — 규칙은 전부 Postgres RPC/RLS |
| 엔진 버전 | **자동 업데이트** (claim 경계에서). smoke test + 마이그레이션 게이트 + 엔진별 venv |
| 사람 개입 | 3지점(발행 승인 · 승격 승인 · 현지화 QA) — 단일 `review_queue` |
| 불변식 | D1~D6 · R1~R6 전량 계승 + R7~R17 |

한 문장: **오케스트레이터는 *무엇을 언제 어디서*만 알고, *어떻게*는 각 엔진 CLI가 소유한다.**

---

## 1. 외부 제약 — YouTube API (공식 문서 확인분)

설계 전체가 이 두 사실 위에 서 있다. 추측이 아니라 `videos.insert` 문서의 쓰기 가능 속성 목록 실측이다.

**1-1. 지오블락은 API로 설정 불가.** `contentDetails.regionRestriction` 은 쓰기 가능 목록에 없다.
→ 지오블락 필수 작품(laeebly `guide` 기준 21건)은 기계가 `private`/`unlisted` 초과로 절대 올리지 않는다.
Studio 수동이 유일한 공개 경로다. 우리 채널 중 지오블락 가능한 곳은 `재미쇼츠` 뿐.

**1-2. 예약공개는 최초 업로드 시점에만.** `status.publishAt` 은 `privacyStatus=private` 이고
**한 번도 공개된 적 없는** 영상에만 설정 가능. unlisted → 예약공개 사후 전환은 불가.

**업로드 버튼 규칙 (대시보드·워커 공통):**

| 공개 설정 | 지오블락 불필요 작품 | 지오블락 필수 작품 |
|---|---|---|
| 비공개 / 일부공개 | ✅ | ✅ (검수·Studio 마무리용) |
| 예약공개 (`private`+`publishAt`) | ✅ | ⛔ |
| 전체공개 | ✅ | ⛔ |

---

## 2. 왜 이 구조인가 — 기존 문제 요약

| # | 문제 | 근거 | 해소 |
|---|---|---|---|
| C1 | 큐에 claim 없음 — 6대가 같은 잡을 6번 집음 | `autogen.py` SELECT/UPDATE 분리 | §6-1 |
| C2 | 경로 하드코딩 3벌 (`gimsewon`/`steve`/`ves`) | autogen·plist 실측 | §11-2 |
| C3 | 상태 저장소 3곳 분단 (PG / SQLite / json) | 현지화 원장·loop_state | §5 |
| C4 | 스케줄러 부재 (등록물 launchd 1건) | INTEGRATION_PLAN §6 자인 | §8 |
| C5 | 산출물이 노드 로컬에 고립 | autoloop "영상 못찾음" 분기 | §9 |
| C6 | 채널 레지스트리 이중화 (brain vs 현지화) | 발행 경로 2개 | §11-5 |
| C7 | 현지화가 개선 루프 밖 | 적재 경로 없음 | §12 |

---

## 3. 목표 아키텍처 — 3평면

```
                    ┌────────────── 사람 ───────────────┐
                    │ 검수 · 승인 · 소스 등록 · 롤백 핀   │
                    └───────────────┬───────────────────┘
                                    ▼
╔══════════════════════════════════════════════════════════════════╗
║ DASHBOARD — S3 정적 SPA + CloudFront (서버 프로세스 없음)          ║
║ 시크릿 0 · 쓰기는 Postgres RPC 경유만 (R12·R15)                    ║
╚════════════╤═════════════════════════════════╤════════════════════╝
             │ RPC / RLS                       │ createSignedUrl(15분)
             ▼                                 ▼
╔══════════════════════════════════╗ ╔════════════════════════════╗
║ CONTROL PLANE — fdidiqd Supabase ║ ║ STORAGE — Supabase Storage ║
║ work_orders · job_queue          ║ ║ ves-sources   마스터(불변)  ║
║ review_queue · node_registry     ║ ║ ves-outputs   shorts·프리뷰 ║
║ deployments · sources · 미러 등   ║ ║ ves-localized 현지화 결과   ║
╚════════════╤═════════════════════╝ ╚═══════╤════════════════════╝
             │ claim · lease · heartbeat (3초 폴링)   │ GET/PUT (TUS)
   ┌─────────┼─────────┬─────────┬─────────┬─┴───────┐
   ▼         ▼         ▼         ▼         ▼         ▼
 mm-01     mm-02     mm-03     mm-04     mm-05     mm-06(+localize)
   │  ves-agent — 동일 바이너리 · 엔진별 venv · 자동 업데이트  │
   └─────────┴────── subprocess (CLI 계약) ──────┴─────────┘
                          ▼
   ai-video  ·  video-localization-project  ·  brain CLI
   (개선 평면: brain의 loop_controller·판정·통계는 그대로 소유)
```

**개선 평면(두뇌)과 운영을 분리하는 이유** — 지금 brain은 판정(`loop_controller`)과 운영
(`autogen` subprocess 실행)을 한 레포에서 겸한다. 변경 이유가 다른 둘이다: 판정은 실험 설계가
바뀔 때, 운영은 머신·스케줄·장애가 바뀔 때. 6대로 늘면 운영 변경이 급증하는데 그때마다 판정
코드를 건드리는 건 위험하다. 오케스트레이터는 판정 규칙을 **재구현하지 않고** brain CLI를 호출만
한다 — 규칙이 두 군데 있으면 반드시 갈라진다.

---

## 4. 도메인 모델 (용어 고정)

| 용어 | 정의 | 식별자 |
|---|---|---|
| channel | 발행 대상 채널 (20개) | `token_slug` |
| work | 라이선스 작품 | laeebly `licensed_video.title` **정본** |
| work_order | 하루치 지시서 — "오늘 이 채널에 이 작품 1편" | uuid + `(date, channel, work, pipeline)` unique |
| job | work_order를 실행하는 DAG 노드 | uuid + `idempotency_key` |
| **run** | 엔진 1회 실행 산출 디렉토리 | 엔진 발급 `run_id` (예: `유미의_세포들_시즌3_c7`) |
| clip | 발행(대상) 쇼츠 1편 | `clips.id` / `video_external_id` |
| round | 자가개선 라운드 (config 1개 × 코호트 N편) | `loop_rounds.round` |

> 엔진의 `job_id`(디렉토리명)와 컨트롤 플레인 `job.id`(uuid)는 이름이 겹친다.
> 오케스트레이터 코드에서 전자는 항상 **`run_id`** 로 부른다.

---

## 5. 컨트롤 플레인 스키마 (전체 DDL)

fdidiqd에 **가산적으로만** 추가. 기존 23테이블 불변. `gen_queue` 는 Phase 1에서 흡수 후 호환 뷰.

```sql
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
```

**RLS 방침**: 위 테이블 전부 `ENABLE ROW LEVEL SECURITY` + `authenticated` 읽기 정책만.
쓰기 정책은 만들지 않는다 → 대시보드(anon/authenticated)는 RPC(`security definer`)로만 쓴다(R15).
워커·brain 스크립트는 직결 DB 계정(테이블 소유자)이라 RLS를 우회한다 — **`FORCE ROW LEVEL
SECURITY` 는 절대 걸지 않는다**(기존 스크립트가 죽는다).

---

## 6. 워커 프로토콜

### 6-1. Claim — 설계의 심장

```sql
WITH claimed AS (
  SELECT j.id, j.lease_ttl_sec
    FROM public.job_queue j
   WHERE j.status = 'pending' AND j.run_after <= now()
     AND j.required_caps <@ $2::text[]
     AND NOT EXISTS (SELECT 1 FROM public.job_queue d
                      WHERE d.id = ANY(j.depends_on) AND d.status <> 'succeeded')
   ORDER BY j.priority DESC, j.run_after, j.created_at
   FOR UPDATE SKIP LOCKED LIMIT 1                  -- ★ 6대 동시 폴링의 유일한 방어선
)
UPDATE public.job_queue j
   SET status='running', node_id=$1, attempt=j.attempt+1, started_at=now(),
       lease_expires_at = now() + make_interval(secs => c.lease_ttl_sec),
       updated_at=now()
  FROM claimed c WHERE j.id = c.id
RETURNING j.*;
```

3초 폴링(유휴 시 3→5→10→30초 백오프). 시각 연산은 **전부 DB `now()`** — 노드 로컬 시계를
lease 판정에 절대 쓰지 않는다.

### 6-2. Lease

| 잡 종류 | lease TTL | 갱신 주기 |
|---|---|---|
| generate · localize (장시간) | **300s** | 60s |
| 그 외 | 120s | 30s |

와이파이 수 분 단절이 장시간 잡을 뺏지 않도록 TTL을 종류별로 둔다(`lease_ttl_sec`).
잡 실행 구간 전체를 `caffeinate -i` 로 감싼다 — 슬립 → lease 만료 → 재시도 루프 방지.

### 6-3. ★⑤ 펜싱 — 좀비 워커 방어

lease가 만료돼 잡이 재배정됐는데 **원래 노드가 죽은 게 아니라 계속 돌고 있는** 경우
(네트워크 일시 단절), 둘 다 완료 보고를 하면 뒤가 앞을 덮어쓴다. 모든 상태 전이를
**소유권 조건부**로 강제한다:

```sql
-- 완료 보고 (실패 보고도 동일 패턴)
UPDATE public.job_queue
   SET status='succeeded', result=$res, finished_at=now(),
       lease_expires_at=NULL, updated_at=now()
 WHERE id=$job AND node_id=$me AND attempt=$my_attempt AND status='running';
-- 0행 → 소유권 상실. 잡 상태는 건드리지 않는다.
--       로컬 산출물은 artifacts에 kind '…_orphan' 으로 기록만 하고 종료.

-- lease 갱신도 동일 조건부
UPDATE public.job_queue
   SET lease_expires_at = now() + make_interval(secs => lease_ttl_sec)
 WHERE id=$job AND node_id=$me AND attempt=$my_attempt AND status='running'
RETURNING id;
-- 0행 → 즉시 서브프로세스 kill (남의 잡이 된 작업에 컴퓨트 낭비 금지)
```

### 6-4. Reaper (스케줄러, 60초마다)

```sql
UPDATE public.job_queue
   SET status = CASE WHEN attempt >= max_attempts THEN 'dead' ELSE 'pending' END,
       node_id=NULL, lease_expires_at=NULL,
       run_after = now() + (interval '1 minute' * power(3, attempt)),
       error = coalesce(error,'') || ' [lease expired]', error_class='transient'
 WHERE status='running' AND lease_expires_at < now();
```

### 6-5. 상태 전이 · 에러 분류

```
[pending] ─claim→ [running] ─ok→ [succeeded]
    ▲                │ transient/lease만료 → attempt<max → pending(백오프) / ≥max → [dead]🔔
    │                │ permanent → [failed]🔔
    │                │ quota → run_after=쿼터리셋, attempt 증가 안 함 → pending
    │                └ human_required → review_queue 등록 → [blocked]
    └── 사람 approve ──┘        reject → [cancelled]
```

| error_class | 예 | 정책 |
|---|---|---|
| transient | 네트워크, ffmpeg 일시 실패, lease 만료 | 지수 백오프 1m→3m→9m |
| quota | Gemini 429, YT 업로드 쿼터 | `run_after`=리셋 시각. **attempt 미증가** |
| permanent | 소스 없음, 작품명 불일치, argparse | 즉시 failed + 알림 |
| human_required | judge 환각, QA hold, 지오블락 | review_queue → blocked |

### 6-6. 멱등성 + ★⑦ 체크포인트 재개 계약

- 잡 생성 멱등: `idempotency_key = sha256(work_order_id | kind | canonical_json(params))`
- 잡 실행 멱등: 어댑터가 선확인 — generate는 `run_log.json`+`provenance_complete`,
  ingest는 `clip_metadata` 존재, publish는 `video_external_id` non-null → 스킵 succeeded
- **재시도는 이어달리기다.** 어댑터 계약에 `resume_argv()` 를 추가한다:
  - 실패/쿼터 반납 시에도 `result.partial_run_id` 를 반드시 기록
  - `attempt > 1` 이고 `partial_run_id` 가 있으면 `--job-id <run_id> --from-step <최종 체크포인트>`
    로 재개 (ai-video의 checkpoint_*.json 활용)
  - **이게 없으면 청크 8/12에서 429 난 68분짜리가 처음부터 다시 돈다** — 쿼터 보호 장치가
    쿼터를 더 태우는 역설. quota 재시도에서 특히 필수

**어댑터 계약 (엔진별 `adapters/*.py`, 순수 함수 5개):**

```python
def build_argv(job) -> list[str]           # 신규 실행 argv
def resume_argv(job, partial_run_id) -> list[str] | None   # ★⑦ 재개 argv (불가능하면 None=처음부터)
def parse_result(stdout, run_dir) -> dict  # {run_id, provenance_complete, artifacts[]}
def classify_error(rc, stderr) -> str      # transient|permanent|quota|human_required
def is_already_done(job) -> bool           # 멱등 스킵
```

---

## 7. 자원 세마포어 — ★⑥ 레이스 수정

Gemini가 진짜 병목이다(롱폼 1편 = 12청크 × Pro 분석, 6대 동시 = 72청크). GCP 프로젝트
6종(SEAN·VES01·VES03·VES04·CJENM·JMLP)별로 상한을 건다.

v3까지의 `INSERT … WHERE count < max` 는 두 워커가 동시에 count 검사를 통과하면 상한을
초과하는 **check-and-insert 레이스**가 있다. advisory lock으로 직렬화한다:

```sql
BEGIN;
SELECT pg_advisory_xact_lock(hashtext('ves:res:' || $resource));   -- 트랜잭션 종료 시 자동 해제
INSERT INTO public.resource_leases(resource, job_id, node_id, expires_at)
SELECT $resource, $job, $node, now() + interval '90 minutes'
 WHERE (SELECT count(*) FROM public.resource_leases
         WHERE resource=$resource AND expires_at > now())
     < (SELECT max_active FROM public.resource_limits WHERE resource=$resource);
COMMIT;
-- INSERT 0행 = 포화 → 잡을 pending으로 반납(run_after=now()+2min), 다음 잡 봄.
-- 쿼터 대기가 워커 슬롯을 점유하지 않는다.
```

```sql
INSERT INTO public.resource_limits VALUES
  ('gemini:SEAN',2,NULL),('gemini:VES01',2,NULL),('gemini:VES03',2,NULL),
  ('gemini:VES04',2,NULL),('gemini:CJENM',2,NULL),('gemini:JMLP',1,NULL),
  ('yt_upload:_global',3,NULL),('storage_dl',3,'마스터 동시 다운로드')
ON CONFLICT (resource) DO NOTHING;   -- 상한값은 Phase 2 실측 후 튜닝
```

---

## 8. 일일 파이프라인

### 8-1. work_order 1건의 DAG

```
acquire ─▶ generate ─▶ upload_artifacts ─▶ ingest ─▶ evaluate ─▶ (localize) ─▶ ⚑publish_gate
                                                                                    │ 사람①
   measure ◀─(reconcile이 생성)── ⚑Studio공개(사람) ◀── publish(private/unlisted) ◀──┘
      │
      ▼ +7d 판정 → ⚑promotion_gate(사람②) → audit(+14d)
```

- `acquire`: `sources` 확인 + 캐시 워밍. 미등록이면 `human_required` + 대시보드 [소스 등록] 알림
- `upload_artifacts`: shorts.mp4 → Storage, **preview.mp4(720p, ~6MB) 트랜스코드** → Storage, thumb
- `evaluate`: judge는 **안전게이트 전용**(환각·깨짐). 성과 예측에 쓰지 않는다(D3)
- work_order **간** 배리어 없음 — 채널 A가 생성 중일 때 B는 발행 대기일 수 있다

### 8-2. 하루 리듬 (KST)

| 시각 | 잡 | 비고 |
|---|---|---|
| 09:00 | planner — work_order 20건 생성 | 채널×작품 배정 · **지오블락 스탬프(★①)** · 라운드 config 주입 · 작품명 laeebly 대조(R14) |
| 10:00~ | generate 워크스틸링 | 6대가 큐에서 계속. 롱폼 ~68분/편 |
| 수시 | upload_artifacts → ingest → evaluate | generate 완료 즉시 |
| 매시 | reaper · reconcile · version_watch | §6-4 · §8-3 · §11-1 |
| 17:00 | 검수 다이제스트 Slack | `review_queue.waiting` 요약 |
| 사람 | publish_gate 승인 → publish 자동 | private/unlisted, 예약공개 가능(§1-2 조건 내) |
| 일 1회 | storage_gc · ETL 신선도 감시 · channels_sync 검증 | §9-4 · laeebly 지연 5일 경보 · §11-5 |

### 8-3. ★⑧ measure/audit 앵커 — 업로드 시각이 아니라 공개 시각

기계는 private/unlisted까지만 올리고 공개 전환은 사람이 Studio에서 한다. **비공개 상태로는
도달이 0이라 apv가 쌓이지 않는다.** D+11을 업로드 시각에 걸면 measure가 빈손으로 뜬다.

→ **measure 잡은 publish가 만들지 않는다.** `reconcile`(매시)이 발행분 ↔ youtube_studio를
연결하면서 **실제 공개 시각을 발견한 시점에** measure 잡을 생성한다:

```
reconcile: video_external_id 연결 + published_at(실공개) 확인
  → INSERT job(kind='measure', run_after = published_at + interval '11 days', idem=…)
measure 성공 → INSERT job(kind='audit', run_after = published_at + interval '18 days')
```

커버리지 게이트(laeebly 성숙도 확인)는 loop_controller가 그대로 소유 — run_after는 "그
이전엔 볼 필요도 없다"는 하한일 뿐, 최종 판정 가능 여부는 게이트가 정한다(기존 D2 규율 유지).

---

## 9. 아티팩트 스토어 — Supabase Storage

### 9-1. 한도 (공식 문서 실측)

| 항목 | Pro | 우리 | 판정 |
|---|---|---|---|
| 파일 상한 | 500GB | 마스터 ~2.9GB | 여유 |
| 스토리지 포함 | 100GB | 55(마스터)+20(산출물)=75GB | ✅ |
| Egress 포함 | 캐시 250 + 비캐시 250GB | §9-3 | ⚠ 관리 |

벤더 1개로 수렴 — DB·인증·스토리지가 같은 프로젝트라 "누가 이 영상을 보는가"가 RLS 하나로 정리.

### 9-2. 버킷 (전부 private, 서명 URL만)

```
ves-sources    sha256/<hash>(.srt)     마스터 (불변·content-addressed)
ves-outputs    <run_id>/shorts.mp4 · preview.mp4 · thumb.jpg
ves-localized  <video_id>/final_draft.mp4
```

- 6MB 초과 업로드는 **resumable(TUS) 필수** — 2.9GB 단일 PUT은 끊기면 처음부터
- content-addressed 이점: 중복 제거(SNL·피의게임X는 2채널 공유) + 무결성 공짜 +
  provenance에 `source_sha256` 영구 기록
- **소스 등록**: 대시보드 → 서명 PUT URL(TTL 1h) → 브라우저가 Storage로 직접(서버 경유 금지)
  → sha256 검증 → `sources` 등록. Drive를 여는 빈도가 하루 20번 → **작품·회차당 1번**
- **보호**: fdidiqd에 PITR 활성화 + `ves-sources` 삭제 권한은 admin 역할로 제한
  (마스터는 유일본이다)

### 9-3. Egress 관리 — 노드 캐시가 비용 레버

```
최악(캐시 0): 6노드 × 55GB = 330GB/월 → 초과 ~80GB ≈ $2.4
현실(캐시 有): 작품당 1~2노드만 다운 → 55~110GB/월 → 포함분 내
```

`/opt/ves/cache/sources/<sha256>` LRU 캐시 유지(`disk_free_gb<100` → draining+정리).
planner의 **soft affinity**(같은 작품 → 같은 노드 선호)가 egress를 줄인다 — 단 hard가
아니다: 선호 노드가 바쁘면 다른 노드가 집고 egress 한 번 더 나가는 것으로 끝.

### 9-4. 보관 정책 — `storage_gc` 잡 (일 1회)

Supabase Storage엔 lifecycle rule이 없으므로 우리가 돈다: `artifacts.expires_at < now()` 삭제.

| 대상 | 보관 |
|---|---|
| 마스터 | 작품 운영 종료까지 (수동) |
| shorts.mp4 | 발행 후 90일 |
| preview.mp4 | 검수 완료 후 14일 |
| edit_plan · run_log | **영구** (DB jsonb) |

삭제 전 `artifacts` 상태를 갱신해 대시보드가 "영상 없음"이 아니라 "보관 만료"로 표시.

---

## 10. 대시보드 — S3 정적 SPA

### 10-1. 구조

```
S3 (정적 SPA) + CloudFront ──supabase-js(anon key)──▶ Supabase
                                                       Auth · RLS · RPC · Storage 서명 URL
```

- **서버 프로세스가 없다** → R12(시크릿 미접촉)가 규율이 아니라 물리적 보장이 된다
- 예외는 **엣지 함수**(`supabase/functions/`) 하나뿐이고, R12 의 예외가 아니라 그 반대다:
  브라우저에 둘 수 없는 키가 필요한 일만 거기서 한다. 현재 `tts-preview`(편집실 내레이션
  미리듣기 — ElevenLabs 키). 함수도 **호출자 JWT 로 권한을 다시 보고** 게이트를 다시 읽는다
  (규칙은 여전히 컨트롤 플레인에 있다). 노드를 거치지 않는 이유는 지연이다 — claim 은
  빈 큐에서 180초 뒤라 '미리듣기'가 성립하지 않는다
- ⚠ S3 웹사이트 엔드포인트는 HTTP 전용 — **CloudFront + ACM 필수** (HTTPS 없이 JWT를 흘리게 된다)
- ⚠ SPA 라우팅: CloudFront 커스텀 에러 응답 403/404 → `/index.html`(200). 없으면 새로고침 404
- 대시보드가 죽어도 워커는 계속 돈다 — 승인된 잡은 큐에 있고 워커는 Supabase만 본다

### 10-2. 원칙 — 규칙은 전부 Postgres 안에

anon key는 공개값이다. DevTools로 `supabase.from('job_queue').insert(…)` 를 직접 칠 수
있으므로 **JS 검증은 UX일 뿐 방어선이 아니다.** 쓰기는 전부 `security definer` RPC:

| RPC | 검증 |
|---|---|
| `approve_and_publish` | 권한 · R9-a/b/c · R10 (아래 전문) |
| `reject_review` / `retry_job` / `set_node_status` | 권한 · 상태 전이 유효성 |
| `pin_engine` / `unpin_engine` | operator · 롤백 핀(부록 C) |
| `register_source` | admin · **작품명 laeebly 정본 대조는 워커 잡으로 위임**(RPC는 laeebly를 못 본다) |
| `request_signed_url` | 열람 권한 → `createSignedUrl(path, 900)` |

### 10-3. ★① `approve_and_publish` 수정본 — 지오블락은 스탬프로 검증

**v3의 결함**: RPC가 `work_requires_geoblock()` 으로 laeebly를 조회하게 설계했는데, laeebly는
**별개 Supabase 프로젝트**라 fdidiqd의 함수가 닿을 수 없다(FDW 없음). 컴파일조차 안 된다.

**수정**: 판정 시점을 옮긴다. **planner가 work_order 생성 시**(laeebly 접근 가능한 쪽)
`geoblock_required` 를 스탬프하고, RPC는 그 스탬프만 검증한다. 기본값 `true` = 안전측
(스탬프 실패 시 공개가 차단될 뿐, 잘못 공개되지 않는다). 가이드가 사후 변경되는 경우는
워커의 `publish_youtube.py` 가 발행 직전 laeebly를 실조회하는 **기존 게이트가 최종 방어선**
으로 잡는다 — RPC는 조기 차단(UX), 워커는 최종 차단. 이중 방어이며 정본은 워커 쪽이다.

```sql
CREATE OR REPLACE FUNCTION public.approve_and_publish(
    p_review_id uuid, p_privacy text,
    p_publish_at timestamptz DEFAULT NULL, p_note text DEFAULT NULL
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_rq record; v_job uuid;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'permission denied'; END IF;

    SELECT rq.*, wo.geoblock_required INTO v_rq
      FROM review_queue rq JOIN work_orders wo ON wo.id = rq.work_order_id
     WHERE rq.id = p_review_id AND rq.status = 'waiting' FOR UPDATE OF rq;
    IF NOT FOUND THEN RAISE EXCEPTION 'review not waiting'; END IF;

    -- R9-a: 지오블락 필수 → private/unlisted만 (★① 스탬프 검증)
    IF v_rq.geoblock_required AND p_privacy NOT IN ('private','unlisted') THEN
        RAISE EXCEPTION 'R9-a: geoblock-required work — Studio manual only'; END IF;
    -- R9-c: publishAt은 private에만 (YouTube API 제약, §1-2)
    IF p_publish_at IS NOT NULL AND p_privacy <> 'private' THEN
        RAISE EXCEPTION 'R9-c: publish_at requires privacy=private'; END IF;
    -- R10: 등록 채널 검증 (★② 미러 참조)
    IF NOT EXISTS (SELECT 1 FROM channels_mirror WHERE token_slug = v_rq.channel_slug) THEN
        RAISE EXCEPTION 'R10: unknown channel %', v_rq.channel_slug; END IF;

    UPDATE review_queue SET status='approved', decided_by=auth.uid()::text,
           decided_at=now(), decision_note=p_note WHERE id=p_review_id;

    INSERT INTO job_queue(work_order_id, kind, params, idempotency_key, required_caps)
    VALUES (v_rq.work_order_id, 'publish',
            jsonb_build_object('clip_id',v_rq.clip_id,'channel_slug',v_rq.channel_slug,
                               'privacy',p_privacy,'publish_at',p_publish_at),
            encode(digest(v_rq.work_order_id::text||'publish'||v_rq.clip_id::text,'sha256'),'hex'),
            '{publish}')
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_job;

    INSERT INTO dashboard_actions(actor,action,target_kind,target_id,payload)
    VALUES (auth.uid()::text,'approve_publish','review_queue',p_review_id::text,
            jsonb_build_object('privacy',p_privacy,'publish_at',p_publish_at));
    RETURN v_job;
END $$;
REVOKE ALL ON FUNCTION public.approve_and_publish FROM public;
GRANT EXECUTE ON FUNCTION public.approve_and_publish TO authenticated;
```

### 10-4. 화면

① **오늘**: 노드 심박·현재 잡·디스크·버전 / 큐 재고·최고 체류 ② **검수**: preview 재생 +
judge 사유 + 공개 설정(§1 규칙으로 비활성 처리) + [승인 후 업로드][반려][재생성]
③ **버전**: §11-6 매트릭스 ④ **라운드**: 라운드 보드 + **코호트 sha 다양성 배지**(§12) +
승격 승인 ⑤ **소스**: 작품×회차 등록 현황 + 업로드

역할: `viewer < reviewer < operator < admin` (`user_roles` 테이블, 미결정 §17-②).

---

## 11. 버전·배포 — 자동 업데이트

### 11-1. 흐름

```
version_watch(스케줄러, 시간당 1회): git ls-remote → deployments.last_seen_sha 갱신
워커(claim 직전, 매번): DB의 last_seen_sha vs 로컬 sha 문자열 비교  ← 원격 조회 아님, 비용 0
  다르면: draining → 하던 잡만 마침 → checkout → pip sync → 게이트(§11-3) → smoke → active
```

- 워커가 직접 `git ls-remote` 를 치지 않는다 — 6대×분당 20회 = 시간당 7,200회 원격 조회가 된다
- 반영 지연 최대 1시간. 급하면 대시보드 [지금 확인] 버튼이 version_watch를 수동 트리거
- **실행 중인 잡 밑에서 절대 코드를 갈지 않는다** (draining 후)
- smoke test = import + `--help` + **엔진 단위테스트 축약 세트**. 실패 → 직전 sha 롤백 +
  그 노드만 `disabled` + 경보
- 잡마다 실행 시점 sha를 `result.engine_sha` 에 기록 — 판정용이 아니라 디버깅용
  ("이 실패가 어제 커밋 이후인가"를 3초에)
- `auto_update=false + pinned_sha` 스위치 유지 — 자가개선 로직 개편 때 "이 라운드만 고정"이
  필요해지면 재설계 없이 플래그만 내린다

### 11-2. ★④ 엔진별 venv — 공용 venv 폐지

기존 관행(ai-video venv를 brain이 공용)은 자동 업데이트와 상극이다 — ai-video의
requirements 변경 한 번이 **pip sync 한 방으로 brain·현지화를 조용히 깨뜨린다.**

```
/opt/ves/
  orchestrator/            .venv/
  engines/
    ai-video/              .venv/     ← 각자 requirements.txt만 sync
    video-localization/    .venv/
    brain/                 .venv/     ← requirements.txt 자급자족화 필요 (Phase 1 작업)
  cache/sources/<sha256>/
  secrets/ves.env          (chmod 600, sops 배포)
```

디스크 몇 GB로 격리를 산다. brain의 requirements.txt가 현재 ai-video venv에 기대고
있으므로(psycopg 등) **자급자족화가 Phase 1 선행 작업**이다. 경로 하드코딩(C2)은 전부
`VES_HOME=/opt/ves` 기준으로 치환.

### 11-3. ★③ 마이그레이션 게이트 — 자동 코드 vs 수동 스키마

코드는 자동 최신인데 DB 마이그레이션은 수동(공유 DB — 기존 규율 유지)이다. 게이트가 없으면
0007을 전제한 커밋이 푸시된 뒤 1시간 안에 **6대 전부가 옛 스키마 위의 새 코드**가 되고,
순수 함수 위주인 단위테스트로는 안 잡힌다.

```
업데이트 절차에 삽입:
  required = 새 sha의 레포 migrations/ 디렉토리 최대 버전   ← 자동 유도, 선언 파일 불필요
  applied  = SELECT max(version) FROM applied_migrations WHERE engine=$e
  required > applied →
      이전 sha 유지(체크아웃 롤백) + 경보 + 대시보드에
      "brain 0007 대기 — 6대 구버전 유지 중 [SQL 보기]"
      last_seen_sha가 다시 바뀌거나 마이그레이션 적용 전까지 재시도 안 함
```

보수적 방향으로만 튄다 — 최악이 "업데이트 지연 + 경보"지 "깨진 배포"가 아니다.
운영 규칙 2개를 함께 명문화: **마이그레이션은 가산적·하위호환**(기존 규율), **적용자는
적용 직후 `applied_migrations` 에 원장 기록**(대시보드 [SQL 보기]에 INSERT문 동봉).

### 11-4. 오케스트레이터 자기 업데이트

돌고 있는 프로세스가 자길 갈아끼울 수 없다. launchd `KeepAlive` 패턴:
ves-agent가 자기 드리프트를 감지하면 **pull 후 스스로 종료** → launchd가 새 코드로 재기동.

### 11-5. ★② 채널 레지스트리 — 정본은 파일, DB는 미러

RPC의 R10 검증이 DB를 봐야 하는데 정본은 `channels.json`(파일)이다. 테이블을 정본으로
올리면 `channel_registry.py` 가 없애려던 드리프트를 우리가 재생산하는 꼴이다.

→ **`channels_mirror` 는 읽기 사본이다.** `channels_sync` 잡(brain 버전 업데이트 직후 +
일 1회 검증)이 channels.json → 미러로 upsert하고 파일에 없는 행을 지운다. `synced_sha` 로
"어느 커밋의 파일인가"를 남기고, `deployments.last_seen_sha` 와 어긋난 채 1일 초과 시 경보.
워커·발행(`publish_youtube.py`)·토큰 발급은 **계속 파일만 읽는다** — 기존 코드 무변경.
현지화의 자체 OAuth 토큰도 Phase 3에서 이 파일 체계로 흡수한다(C6 해소).

### 11-6. ★⑨ 버전 화면과 드리프트 경보

```
엔진                 origin 최신   mm-01 02   03   04   05   06
ai-video             b935d20        ✓   ✓    ⟳    ✓    ●    ✓
brain                7e4d10b        ✓   ✓    ✓    ✓    ✓    ✗ ⚠
✓ 최신  ⟳ 업데이트 중  ● 장시간 잡 실행 중(경계 대기 — 정상)  ✗ 실패
```

낮에 푸시하면 몇 시간 동안 sha가 갈려 보이는 것은 **정상이다** — 68분 잡을 돌던 노드는
잡 경계에서 갱신한다. 따라서 경보 조건은 "불일치"가 아니라:

> **유휴 상태**(실행 중 잡 없음 · `updating_since` null)로 불일치가 **20분** 초과 → 🔔
> `✗` 는 항상 "업데이트 실패"를 뜻한다(자동이므로 '반영 안 함'이란 상태가 없다).

---

## 12. 자가개선 루프 접합

- `loop_controller propose` → `loop_rounds` INSERT → planner가 다음 09:00에 work_order로
  전개(knob_config 주입) → 발행 후 reconcile이 `cohort_ids` 자동 수집 → measure/audit 자동
  (§8-3) → `promotion_gate` 승인은 사람
- 사라지는 수작업: `ids_RN.txt` 수기 작성, record/measure/audit 시점 기억
- **전량 계승**: D1(검증 2방식) · D3(지표 역할 고정 — judge는 안전게이트 전용) · D5(사람 2지점) ·
  R5(쌍 48h) · R6(1클립 1실험) · provenance 없으면 코호트 등록 거부 · 자사 채널 시장 제외
- **혼합 sha 코호트(감수하는 리스크)**: 자동 업데이트라 한 라운드 코호트에 여러 sha가 섞일 수
  있다. 차단하지 않는다(사용자 결정 — 자가개선 로직 개편 예정). 대신 라운드 보드에
  **"sha N종" 배지**를 상시 표시하고, `engine_sha` 기록으로 사후 분리 판단이 가능하게 남긴다.
  개편 시점에 이 문단을 다시 본다.
- 현지화(C7): `pipeline='shorts_jp_localized'` 도 같은 DAG를 탄다. 단 일본 시장 비교군이
  laeebly에 있는지 먼저 검증(§17-⑤) — 없으면 운영만 통합, 판정은 별도

---

## 13. 관측성 — 침묵 감지

| # | 지표 | 경보 |
|---|---|---|
| 1 | 노드 심박 | `last_seen_at` 5분 초과 🔔 |
| 2 | 단계별 재고·최고 체류 | kind별 pending 수·최고 대기시간 |
| 3 | dead 잡 | 1건이라도 🔔 (자동 업데이트의 악성 커밋 탐지기이기도 하다) |
| 4 | 검수 적체 | waiting 48h 초과 🔔 |
| 5 | ETL 신선도 | laeebly 지연 5일 🔔 |
| 6 | 쿼터 포화율 | resource_leases 점유율 |
| 7 | 디스크 | `disk_free_gb<100` → draining |
| 8 | 라운드 보드 | 상태·경과일·백분위 추이 + **sha 다양성 배지** |
| 9 | Goodhart 카나리아 | 주입 점수 vs 백분위 상관 |
| 10 | 조용한 0건 | planner 실행 자체 감시 — 어제 work_order 0건이면 🔔 |
| 11 | 버전 드리프트 | **유휴 상태** 불일치 20분 🔔 (★⑨) |
| 12 | 업데이트/게이트 실패 | smoke 실패 disabled 노드 · 마이그레이션 대기 🔔 |
| 13 | Storage egress | 월 200GB(포함분 80%) 초과 🔔 |
| 14 | 소스 미등록 | work_order 있는데 sources 없음 (R14의 관측 짝) |
| 15 | 캐시 적중률 | 마스터 재다운로드 / 생성 잡 수 |
| 16 | orphan 산출물 | `_orphan` 발생 수 — 잦으면 lease TTL 재조정 신호 (★⑤) |
| 17 | 미러 신선도 | channels_mirror.synced_sha 어긋남 1일 🔔 (★②) |

---

## 14. 불변식 (최종)

기존 **D1~D6 · R1~R6** 전량 계승(brain 코드·DB 트리거가 계속 소유). 추가·개정분:

| # | 불변식 | 강제 지점 |
|---|---|---|
| R7 | `(date, channel, work, pipeline)` 당 work_order 1건 | UNIQUE |
| R8 | generate는 `provenance_complete=true` 없이 succeeded 불가 | 어댑터 |
| R9-a | 지오블락 필수 작품은 기계가 private/unlisted 초과 업로드 금지 | **스탬프+RPC(조기) + publish_youtube 실조회(최종)** ★① |
| R9-b | public·예약공개는 지오블락 불필요 작품 + 사람 승인 선행 시만 | RPC |
| R9-c | publishAt은 최초 업로드 시점·private에만 | RPC + 워커 |
| R10 | 미등록 채널로 어떤 잡도 실행 금지 | RPC(미러) + 워커(파일) |
| R11 | 워커는 smoke + 마이그레이션 게이트 통과 코드로만 claim | agent 루프 ★③ |
| R12 | 대시보드는 시크릿 미접촉 | 정적 배포 — 구조적 보장 |
| R14 | sources에 없는 소스로 generate 금지 · 작품명은 laeebly 정본 | planner |
| R15 | 대시보드 쓰기는 RPC 경유만 (직접 INSERT/UPDATE 불가) | RLS(쓰기 정책 부재) |
| R16 | 잡 상태 전이는 소유권 조건부(`node_id`+`attempt`)로만 | 전이 SQL ★⑤ |
| R17 | 채널 정본은 channels.json — DB는 미러, 워커는 파일만 읽음 | channels_sync ★② |

(R13 "라운드 중 버전 고정"은 v3에서 삭제됨 — 자동 업데이트 결정에 따름)

---

## 15. 용량 (요약)

20편/일 × 롱폼 68분 = **~22.7h/일** ÷ 6대 = 노드당 3.8h → 야간 8h 창 대비 **2.1배 여유**.
병목은 CPU가 아니라 Gemini(§7). 디스크: 고유 작품 19개 × 2.9GB ≈ 55GB, content-addressed
캐시 + LRU로 관리. 검수 부하: 20건/일 × 2~3분 ≈ 1h/일(사람).

---

## 16. 로드맵

| Phase | 내용 | 기간 | 완료 기준 (관찰 가능) |
|---|---|---|---|
| **0** | claim `SKIP LOCKED` · `VES_HOME` 경로 치환 · 작품명 대조 스크립트 | 1~2일 | 2대 동시 실행에도 잡 중복 0 |
| **1** | 스키마 0006 적용 · Storage 버킷 3개+RLS · ves-agent(펜싱·재개 포함) · **venv 분리 + brain requirements 자급자족** · `applied_migrations` 원장 소급 기록(0001~0005) · mm-01 카나리아 | 1.5주 | 1대가 3일 무인 주행, dead 0 · shorts가 Storage에 올라가 서명 URL 재생 확인 |
| **2** | 6대 확장 · sops 시크릿 · 자동 업데이트(version_watch+게이트) · **channels_sync** · 대시보드 v1(검수+업로드+노드/큐) · 세마포어 실측 튜닝 | 2주 | 노드 1대 끄면 5분 내 재배정 관찰 · 대시보드 업로드 1건 성공 · 악성 커밋 모의 → smoke가 막고 경보 |
| **3** | 현지화 통합(원장→큐 · OAuth→파일 체계) · 대시보드 v2(버전·소스·라운드) | 1~2주 | 잔망루피 1편이 큐 잡으로만 발행 · `autopilot.db` 쓰기 0 |
| **4** | 자가개선 자동 접합(propose→work_order · cohort 자동수집 · measure/audit 자동) · 침묵 감지 완성 | 1~2주 | 라운드 1회가 사람 승인 2번 외 전자동 완주 |

---

## 17. 미결정

| # | 항목 | 막는 것 |
|---|---|---|
| ① | 대시보드 인증 주체 — Supabase Auth 자체 vs Google Workspace SSO. 정적 배포라 RLS가 유일한 방어선 → 더 중요해짐 | **Phase 2** |
| ② | `user_roles` 설계 (`has_role` 의 기반) | Phase 2 |
| ③ | 재생성 정책 — 반려 클립 자동 재생성 여부. 라운드 소속 클립은 비활성 권장(선택 편향) | — |
| ④ | 발행 페이스 — 20채널 동시 살포의 YPP 리스크. publishAt으로 채널별 시각 분산 권장 | planner 정책 |
| ⑤ | 일본 채널 판정 기준 — laeebly에 일본 시장 비교군 존재 여부 | Phase 3 판정 편입 |
| ⑥ | 현지화 가중치 4GB×6대 배포 vs mm-06 전담 유지 | — |
| ⑦ | Egress 실측 — 캐시 적중률 낮으면 상한 재검토 | Phase 2 실측 |

---

## 부록 A. ves-orchestrator 레포 구조

```
ves-orchestrator/
  ves/
    agent/       worker.py · claim.py · lease.py(펜싱) · executor.py · updater.py(게이트)
    scheduler/   planner.py(지오블락 스탬프) · reaper.py · version_watch.py · reconcile.py
    adapters/    aivideo.py · localize.py · brain.py   ← 순수 함수 5개 계약(§6-6)
    control/     models.py · queries.py · migrations/
    storage/     supabase_storage.py (TUS · 서명 URL · gc)
    dashboard/   web/ (정적 SPA) · sql/ (RPC·RLS 정의 — 마이그레이션으로 배포)
    obs/         metrics.py · notify.py
  deploy/        bootstrap.sh · node.env.example · launchd/*.plist (KeepAlive)
  docs/          ARCHITECTURE.md(이 문서) · RUNBOOK.md · CONTRACTS.md
  tests/         claim 경합 · lease 만료 · 펜싱 · 멱등 · 재개 argv · 게이트 · 미러 sync
```

## 부록 B. 이 설계가 하지 않는 것

엔진 내부 알고리즘 변경 없음 · 판정 규칙 재구현 없음 · 쿠버네티스/도커 없음 ·
메시지 브로커 없음(하루 수백 잡에 Postgres SKIP LOCKED로 충분) · 완전 무인 공개 없음(D5 유지).

## 부록 C. 런북 — 악성 커밋 대응 (자동 업데이트의 안전핀)

```
증상: dead 잡 급증(지표3) 또는 smoke 실패로 노드 disabled(지표12)

1) 핀 고정 (대시보드 [핀] 또는 SQL):
   UPDATE deployments SET auto_update=false, pinned_sha='<직전 정상 sha>'
    WHERE engine='<엔진>';
2) 노드들이 다음 claim 경계에서 자동으로 pinned_sha로 롤백된다 (재기동 불필요)
3) disabled 노드는 원인 확인 후 node_registry.status='active' 복귀
4) 원인 커밋 revert/수정 push → 확인 후 auto_update=true 복귀
5) 그 시간대 생성분은 engine_sha로 식별해 필요 시 재생성/코호트 제외 판단
```
