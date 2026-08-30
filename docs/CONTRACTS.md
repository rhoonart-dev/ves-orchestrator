# CONTRACTS — 어댑터 계약 · 에러 분류 · 자원 명명

## 어댑터 계약 (ves/adapters/base.py)

| 함수 | 필수 | 설명 |
|---|---|---|
| `build_argv(cfg, job) -> list` | subprocess형 ✔ | 신규 실행 argv |
| `resume_argv(cfg, job, partial_run_id) -> list\|None` | 권장 ★⑦ | 체크포인트 재개. None=처음부터 |
| `parse_result(cfg, job, stdout) -> dict` | subprocess형 ✔ | rc=0 일 때 결과 추출. **R8 검증 포함**(generate) |
| `classify_error(rc, stderr, stdout) -> str` | 권장 | 미구현 시 `classify_by_patterns` 폴백 |
| `run(cfg, conn, job, deps) -> dict` | 네이티브형 ✔ | subprocess 불필요한 잡(acquire 등) |
| `is_already_done(cfg, job) -> bool` | 선택 | 멱등 스킵 |
| `resource(cfg, job) -> str\|None` | 선택 | 세마포어 자원명(§7) |
| `post_success(cfg, conn, job, result)` | 선택 | 성공 후 훅(review_queue 등록 등). 실패해도 성공 유지 |
| `cwd(cfg, job)` / `env(cfg, job)` | 선택 | subprocess 실행 환경 |

원칙: **전부 순수 함수**(부수효과는 run/post_success 만) — tests/test_pure.py 대상.
실패 시에도 `extract_partial_run_id(stdout)` 가 있으면 `result.partial_run_id` 가 남아
다음 attempt 가 이어달린다(재시도는 이어달리기 — quota 에서 특히 필수).

## error_class → 정책 (§6-5)

| class | 상태 전이 | attempt | run_after |
|---|---|---|---|
| `transient` | pending(상한 도달 시 dead) | 유지 | +1m→3m→9m |
| `quota` | pending | **-1 (미차감)** | 쿼터 리셋 시각(기본 +1h) |
| `permanent` | failed | — | — |
| `human_required` | blocked | — | 사람 approve 로 재개 |

## 자원 명명 (resource_limits.resource)

`gemini:<GCP_PROJECT>` (channels.json gcp_project 6종) · `yt_upload:_global` · `storage_dl`

## 잡 params 핵심 키

공통: `work_title`(laeebly 정본) · `episode` · `channel_slug` · `channel_name`
generate: `source_sha256`|`source_url` · `flags{silence,length,loudness}` · `no_subtitles` · `resource` · `outdir`
publish: `clip_id` · `privacy(private|unlisted)` · `publish_at`(예약 — §1 규칙, RPC가 검증)

## V3 경계면 동결 (ai-video pipeline v3, 2026-08-31 합의)

정본: `ai-premiere-pro/orders/v3-m2-adapter-contract.md` (사용자 승인 2026-08-31).
원칙 — **경계면 동결, 내부 표현만 교체**: v3 의 meaning/span 은 내부 표현이고,
편집실·어댑터가 만지는 스키마는 기존 그대로다. v3 는 additive 필드만 추가한다.

| 접점 | 계약 |
|---|---|
| `edit_plan.timeline[]` | `clip_start_sec/clip_end_sec`(원본 절대초)·`role`·`use_original_audio`·`subtitle` 필드 호환 유지 |
| TTS cue | `source_time_sec` = 좌표이자 신원(edit_overrides/v2) 유지 · voice/speed 라벨 E11 불변 |
| 체크포인트 | `checkpoint_<step>.json` 네이밍 유지 (v3 스텝명은 M2 완료 시 부록 고지) |
| `edit_overrides` | 키·의미 무변경. v3 는 경계 이동을 grid 스냅으로 정착(오차 run_log 기록) |
| `edit_overrides.design` | 무변경 — v3 style.json 은 design-* 어휘만 사용 |
| additive | `edit_plan.schema="edit_plan/v3"` · `timeline[].span_ids` · `grid_marks`(예약, UI 활용은 별도 발주) |

M2~M4 동안 v3 run 은 오케스트레이터 밖(수동/스모크)에서만 돈다. `aivideo` 어댑터의
v3 엔트리(`python -m app.v3`) 분기는 M5 전환 때 채널 게이트 뒤로 들어온다.

### V3 스텝명 부록 (C3 고지 — M5, 2026-08-31)

v3 잡의 `checkpoint_<step>.json` → 재개 스텝 매핑(어댑터 `pick_resume_step_v3`):
`grid_words→grid · chunk_split · chunk_analyze · story · resources · style`.
v3 `--from-step` 어휘: `grid seq_analyze chunk_split chunk_analyze story resources
draft_render style render validate` — **v1 스텝명(silence_cut 등)은 어댑터가 거절**한다.

게이트: `ops_config aivideo_v3`(전역, 기본 off) ∧ 채널 design `pipeline_v3: true`
둘 다 켜져야 v3 (`python -m app.v3`). 꺼진 채널은 기존 경로 바이트 동일.
**채널 전환은 건별 사용자 승인 — 자동 전환 금지**(기획 멈춤 ③). brain
CHANNEL_DESIGN_SWITCHES 미러는 채널 템플릿 승격 시점에(1:1 규율 — 이번 범위 아님).
편집실 edit_overrides 는 v3 에서도 같은 파일·같은 플래그(`--edit-overrides`)로 가며,
clip 경계는 엔진이 최근접 grid span 경계로 정착한다(C4 — 오차는 run_log 기록).
