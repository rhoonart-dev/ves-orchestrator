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
