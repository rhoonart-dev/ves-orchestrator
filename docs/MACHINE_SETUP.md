# 머신별 셋업 — 맥미니 6대

> 순서: **§0(1회성 콘솔 작업) → §1(6대 공통) → §2(머신별)**. 소요: §0 반나절 · 노드당 ~30분.

---

## §0. 머신 아님 — 먼저 끝내야 하는 1회성 작업

| # | 작업 | 어디서 | 비고 |
|---|---|---|---|
| 0-1 | `0006_orchestration.sql` 적용 | Supabase(fdidiqd) | ⚠ 공유 DB — 적용 전 확인 규율 유지 |
| 0-2 | `0007_rpc_dashboard.sql` 적용 | 〃 | RLS·RPC. 0006 선행 |
| 0-3 | `0006_seed.sql` 실행 | 〃 | deployments repo_url **실제 값으로 수정 후** |
| 0-4 | Storage 버킷 3개 생성(**전부 private**) | Supabase 콘솔 | `ves-sources` `ves-outputs` `ves-localized` |
| 0-5 | PITR 활성 + `ves-sources` 삭제 제한 | 〃 | 마스터는 유일본(§9-2) |
| 0-6 | 시크릿 파일 작성 → sops/age 암호화 | 로컬 | `deploy/secrets.env.example` 참조 |
| 0-7 | 채널 refresh token 발급 상태 점검 | `get_youtube_token.py` | **미발급 채널은 발행 하드실패(R10)** — 20슬러그 대조 |
| 0-8 | 사설 레포 접근 수단 결정 | GitHub | PAT(https) 또는 노드별 deploy key — 자동 업데이트 fetch 용 |
| 0-9 | brain `requirements.txt` 자급자족화 | brain 레포 | 현재 ai-video venv 에 기생(psycopg 등) — venv 분리(★④) 전제 |
| 0-10 | laeebly `licensed_video.guide` 스키마 실측 | laeebly | planner 지오블락 스탬프(★①)의 컬럼명 검증 |

## §1. 6대 공통 (모든 노드에서 동일)

```bash
# 1) macOS 설정 (1회, GUI/sudo)
#    - 자동 로그인 켜기  ← LaunchAgent 는 로그인 세션에서 동작 (FileVault 와 상충 — 정책 결정)
#    - sudo pmset -a sleep 0 displaysleep 10   (전원 연결 상시 가동)
# 2) 기존 잔재 정리 — 옛 cron/launchd 가 새 agent 와 겹치지 않게
launchctl list | grep -i -E "rhoonart|loopy|autopilot"   # 있으면 bootout
crontab -l                                                # 있으면 정리
# 3) 시크릿 복호화본 준비 후 부트스트랩 (레포 clone·venv·plist·env 전부 자동)
export VES_SECRETS_SRC=~/Downloads/ves.env.decrypted
bash bootstrap.sh --node-id <mm-0X> --caps <아래 표>
# 4) 검증
tail -f /opt/ves/logs/agent.log        # "mm-0X 기동" + heartbeat
#    대시보드(또는 SQL)에서 node_registry 에 노드 표시 확인
```

## §2. 머신별

| 노드 | `--caps` | 추가 작업 |
|---|---|---|
| **mm-01** | `generate,analyze,publish,network,scheduler` | scheduler plist 자동 설치됨. 시계 확인(NTP) |
| **mm-02** | `generate,analyze,publish,network,scheduler` | scheduler **백업** — advisory lock 이라 중복 안전(자동 승계) |
| **mm-03** | `generate,analyze,publish,network` | — |
| **mm-04** | `generate,analyze,publish,network` | — |
| **mm-05** | `generate,analyze,publish,network` | — |
| **mm-06** | `generate,analyze,publish,network,localize,gpu_mps` | 현지화 전담: `weights/` 가중치(4GB+, 라이선스 확인) · `fonts/NotoSansJP` · 루피 레퍼런스 음성 — video-localization README 절차 |

> 디스크 여유 확인: 노드당 마스터 캐시 최대 ~55GB + 생성 중간파일. **200GB 미만이면 증설 검토.**
> `disk_free_gb < 100` 이면 노드가 스스로 draining 된다(§9-3).

## §3. 스모크 시나리오 (Phase 1 완료 기준)

```bash
# ① 소스 1건 등록(임시로 SQL 직접 — 대시보드 소스 등록 화면은 Phase 2)
#    Storage 에 마스터 업로드 후 sources INSERT (sha256 일치 확인)
# ② work_order 수동 1건 → planner 없이 잡 체인만 검증
#    (또는 09:00 planner 를 기다림)
# ③ 관찰: acquire → generate(~68분) → upload_artifacts → ingest → evaluate
#    → review_queue 에 publish_gate 1건
# ④ 2대에서 agent 동시 기동 → 같은 잡이 두 번 안 도는 것 확인 (Phase 0 완료 기준)
# ⑤ 노드 1대 전원 차단 → 5분 내 reaper 가 잡 회수·재배정 (Phase 2 완료 기준)
```
