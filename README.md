# ves-orchestrator

맥미니 6대 동질 워커 풀 + fdidiqd Supabase 컨트롤 플레인으로 VES 3개 프로젝트
(ai-video · video-localization-project · ai-improvement-edit-video)를 반자동 운행하는
오케스트레이션 레이어. **무엇을 언제 어디서만 안다 — 어떻게는 각 엔진 CLI 소유.**

- 설계 정본: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (v3.1 통합본)
- 머신 셋업: [docs/MACHINE_SETUP.md](docs/MACHINE_SETUP.md) · 장애 대응: [docs/RUNBOOK.md](docs/RUNBOOK.md)
- 유튜브 자동 업로드 설명서(화면 포함): [docs/YOUTUBE_UPLOAD_GUIDE.md](docs/YOUTUBE_UPLOAD_GUIDE.md)
- 어댑터 계약: [docs/CONTRACTS.md](docs/CONTRACTS.md)

## 구조

```
ves/agent/       worker(메인 루프) · claim(SKIP LOCKED) · lease(펜싱★⑤) · executor · updater(자동 업데이트§11)
ves/scheduler/   main(advisory lock) · planner(09:00, 지오블락 스탬프★①) · reaper · version_watch
                 · reconcile(measure 앵커★⑧) · channels_sync(★②) · storage_gc
ves/adapters/    aivideo(재개★⑦) · brain(ingest/evaluate/publish) · acquire · upload_artifacts · localize
ves/storage/     Supabase Storage (서명 URL·다운로드)
ves/control/     migrations/0006(스키마) · 0006_seed · 0007(RLS·RPC — 대시보드 규칙 전부 여기)
deploy/          bootstrap.sh · launchd plist · secrets.env.example
dashboard/       Phase 2 — S3 정적 SPA (스텁만, RPC 는 0007 에 이미 있음)
```

## 시작 순서

1. **§0 1회성 작업** — [docs/MACHINE_SETUP.md](docs/MACHINE_SETUP.md) §0 (마이그레이션 적용은 확인 후)
2. **mm-01 카나리아** — bootstrap → 3일 무인 주행 (Phase 1)
3. **6대 확장** (Phase 2)

## 테스트

```bash
python -m pytest tests/ -q     # 순수 로직 — DB/네트워크 불필요 (14 passed)
```

## 상태 한눈에 (대시보드 전 임시)

```sql
SELECT node_id, status, engine_versions, now()-last_seen_at AS silent FROM node_registry;
SELECT kind, status, count(*) FROM job_queue GROUP BY 1,2 ORDER BY 1,2;
SELECT kind, channel_slug, created_at FROM review_queue WHERE status='waiting';
```
