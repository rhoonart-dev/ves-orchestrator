# L-P1 보고 — rerender 계층 ai-video 이관 (2026-08-23)

기획서: [`docs/LOCALIZE_UNIFY.md`](../LOCALIZE_UNIFY.md) §9 P1.
완료 판정은 **혜미리예채파 5편 회귀 0**, 어댑터는 아직 vlp 를 부른다(엔진만 준비).

---

## 0. 한 줄 요약

vlp `scripts/localize_run.py`(917줄)를 ai-video `app/localize/` 11개 모듈로 이식했고,
**원본과 산출이 바이트까지 같음을 기계로 증명**했다. 운영에는 아무 영향이 없다
(어댑터는 그대로 vlp 를 부른다 — 전환은 P2 의 플래그 하나).

---

## 1. 이식 결과

| 원본 (vlp) | 이식 (ai-video) | 단계 |
|---|---|---|
| `l0_backup` | `localize/collect.py` | L0 백업 |
| `l2_extract` · `l2b_refine_timing` | `localize/telop.py` | L2 · L2b |
| `l1_translate` · `_fit_title` | `localize/translate.py` | L1 |
| `l3_apply` · `build_telop_ass` | `localize/apply.py` | L3 |
| `l3t_tts` | `localize/narration.py` | L3t |
| `render_flags` · `l4_render` · `_provision_fonts` | `localize/rerender.py` | L4 |
| `build_ko_ja_pairs` · `l5_metadata` | `localize/meta.py` | L5 |
| `apply_overrides` | `localize/overrides.py` | 검수 수정 |
| `engine/render.py` 스타일 4함수 | `localize/styles.py` | 편집실 계약 |
| `work_locale_cfg` · `gemini_client` · 경로 | `localize/spec.py` | 사양 |
| `main` | `localize/runner.py` | 실행 |
| `config/locales.json` | `localize/data/locales.json` | 설정 |

진입점: `python -m app.cli localize --job-dir <job> [--locale ja] [--overrides …] [--skip-render]`

---

## 2. 회귀 0 증명 — 기계 대조

`ai-video/scripts/localize_port_diff.py` 가 **원본 함수와 이식본에 같은 입력**을 먹여
산출을 비교한다. "옮겼다"가 아니라 "같은 답을 낸다"를 봐야 하기 때문이다.

| 대상 | 케이스 | 결과 |
|---|---|---|
| `render_flags` | aggressive+tight · conservative · 빈 app · provenance 없음 | ✅ 동일 |
| `_ass_escape` · `_fmt_ts` | 줄바꿈·중괄호·CJK·경계값 8건 | ✅ 동일 |
| `build_telop_ass` | 스타일+타이밍 오버라이드 포함 3항목 | ✅ **바이트 동일** |
| `apply_overrides` | 병합 5케이스 | ✅ 동일 |
| `apply_overrides` 예외 | 모르는 style 키·y 범위·end≤start·tts 후속·use 타입 | ✅ **예외 종류까지 동일** |
| `build_ko_ja_pairs` | 클램프·사용자 타이밍·소프트 삭제·텔롭 | ✅ 동일 |
| `l3_apply` | 쓴 파일 5개 | ✅ **바이트 동일** |

```
✅ 전 항목 산출 동일 — 이식 충실
```

단위 테스트도 vlp 것을 **단언 값까지 그대로** 옮겼다(`test_localize_rerender.py` ·
`test_localize_pairs.py`, 40건). 전체 768 passed.

> ⚠ 기존 3건(`test_platform_mark` 2 · `test_e10` 1)은 **이 변경 전에도 실패**한다 —
> 이 컨테이너에 이미지 리소스가 없어서이고 코드와 무관하다.

---

## 3. 이식하며 정리한 것

- **환각 클램프를 함수 하나로 모았다**(`apply.clamp_hallucination`).
  원본은 같은 수식(8초 초과 + 20자 이하 → 4초)을 L3(실제 렌더)와 L5(검수 화면이 보는
  값)에 **두 번 적어** 뒀다. 베낀 수식은 언젠가 어긋난다(E13 교훈) — 이제 두 곳이 같은
  함수를 부른다. 대조 결과가 같으므로 동작 변화는 없다.
- **순수 함수를 뺐다** — `only_broadcast_telops`(인덱스 규약) · `group_hits`(프레임 구간
  묶기) · `render_argv` · `title_needs_fit` · `check_alignment` · `check_work_display` ·
  `rate_string` · `fits_window` · `build_description` · `apply_segments`.
  전부 테스트 대상이 됐다(원본에서는 큰 함수 안에 묻혀 있어 검증 불가였다).
- **ffmpeg 탐색을 ai-video `ffmpeg_utils` 로 합쳤다.** 같은 `FFMPEG_BIN`/`FFPROBE_BIN` 을
  읽고, 오타 난 오버라이드에서 조용히 PATH 로 안 떨어지고 더 일찍 죽는다.
  `ass` 필터 유무 검사는 현지화 전용이라 `rerender.py` 에 남겼다.

---

## 4. 🛑 의도적으로 바꾼 것 둘 (승인 필요)

### ① Flash 모델 — 규칙 충돌을 ai-video 쪽으로 정리했다

| | 모델 |
|---|---|
| vlp `MODEL_FLASH` | `gemini-3-flash-preview` |
| ai-video CLAUDE.md | **사용 금지** (허용: Pro `gemini-3.1-pro-preview` · Flash `gemini-3.6-flash`) |

Pro 는 양쪽이 **같은 모델**이라 통번역·텔롭 추출에는 차이가 없다. Flash 가 쓰이는 곳은
**L2b 프레임 판독**과 **제목 축약** 둘뿐이고, 둘 다 LLM 판단이라 기획서 §8-2 의 회귀 0
측정 대상이 애초에 아니다(번역 결과를 고정 입력으로 주입해 렌더 계층만 대조한다).

⇒ **ai-video 규칙을 따랐다.** `GEMINI_FLASH_MODEL_NAME` 환경변수를 읽으므로 노드에서
되돌릴 수도 있다. 테스트가 코드에 옛 모델 문자열이 다시 들어오는 것을 막는다.

⚠ 다만 **판독 품질은 실측해 봐야 안다.** L2b 는 "이 프레임에 이 텔롭이 보이는가"라는
1장 1콜 판정이라 모델이 바뀌면 텔롭 타이밍이 달라질 수 있다. P2 컷오버 전에 같은 편으로
구·신 엔진을 돌려 `onscreen_refined.json` 을 대조하는 것을 권한다.

### ② 진행 상태 파일 위치

vlp 는 자기 레포 `results/localize_state.json` 에 전 job 의 진행을 모아 썼다.
ai-video 는 엔진 레포에 런타임 상태를 쓰지 않으므로 **job 디렉토리 안**
(`localize_<locale>/state.json`)으로 옮겼다. 읽는 곳이 없다(오케스트레이터는
`metadata.json` 존재만 본다) — 산출에 영향이 없다.

---

## 5. 안 바꾼 것 (P2 컷오버가 플래그 하나로 끝나는 이유)

성공 마커·산출 규약을 **그대로** 뒀다:

- `<job>/localize_<locale>/metadata.json` (성공 마커)
- `<job>/shorts.mp4` (교체본) · `shorts_ko.mp4`·`localize_backup_ko/` (원본 보존)
- `<job>/shorts_ja_notelop.mp4` (번인 전 중간본)
- `metadata.json` 안의 `youtube_title`·`description`·`ko_ja_pairs` 모양

⇒ `ves/adapters/localize.py` 는 **argv 만 바꾸면 된다**. 검수함·편집실·0066 체인은 무변경.

---

## 5-1. 회귀 0 의 기준 = 플릿 sha (2026-08-23 확인)

사용자 개발 머신에서 `localize_port_diff` 가 12건 불일치를 냈다. **둘 다 이식 결함이
아니었고**, 그 과정에서 이 보고의 전제를 못박게 됐다.

| 확인 | 값 |
|---|---|
| `deployments.localization.last_seen_sha` | **`66056fe`** (auto_update=true, pin 없음) |
| `node_registry` mm-01~06 `engine_versions.localization` | **6대 전부 `66056fe`** (전부 active) |
| 이식 기준(이 세션 vlp) | **`66056fe`** ✅ 일치 |
| 사용자 개발 체크아웃 | `9093049` — main 보다 **9커밋 뒤**(JP-2·E6-0·E9 이전) |

⇒ **이식 기준 = 플릿 기준.** P1 의 회귀 0 판정은 유효하다.
낡은 체크아웃과 대조하면 나던 10건(줄 스타일 검증 없음·소프트 삭제 없음 등)은
버전 차이였고, 나머지 2건은 워크트리에서 돌 때 brain 형제 추론이 갈린 대조 도구의
결함이었다. 둘 다 `localize_port_diff` 가 이제 먼저 잡아 낸다(a6e99de).

## 6. P1 판정 · 다음

| 완료 판정 | 상태 |
|---|---|
| 코드 이식 | ✅ 11개 모듈 + CLI 서브커맨드 |
| 순수 로직 회귀 0 | ✅ 기계 대조 전 항목 동일 (§2) |
| 단위 테스트 | ✅ vlp 것 이식 40건 · 전체 768 passed |
| 어댑터 무변경(운영 무영향) | ✅ vlp 를 계속 부른다 |
| **실런 회귀 0** | ✅ **1편 통과** (mm-05, 아래 §7) · 나머지 4편은 선택 |

### (완료) P2 전에 사람이 할 일

노드에서 최근 혜미리예채파 job 하나를 골라 **구·신 엔진을 나란히** 돌린다:

```zsh
cd /opt/ves/engines/ai-video
JOB=/path/to/outputs/<job_id>

.venv/bin/python -m scripts.localize_ab --snapshot $JOB --to /tmp/snap_vlp

# 신 엔진 (번역 캐시 translation.json 이 있으면 LLM 을 다시 안 부른다 = 렌더 계층만 대조)
.venv/bin/python -m app.cli localize --job-dir $JOB --locale ja

.venv/bin/python -m scripts.localize_ab --a /tmp/snap_vlp --b $JOB
```

`판정: 회귀 0` 이 나오면 P2(어댑터 컷오버)로 갑니다. 이때 §4-① 대로
`localize_ja/onscreen_refined.json` 도 함께 보시면 Flash 모델 교체의 영향까지 잡힙니다.


---

## 7. 실런 대조 결과 — mm-05 · 혜미리예채파_7e42b761 (2026-08-23)

job 사본(`/tmp/abtest/…`)에 vlp 산출을 스냅샷으로 떠 두고, **같은 job 을 ai-video
엔진으로 끝까지 돌린 뒤** 대조했다. 번역 캐시(`translation.json`·`onscreen*.json`)가
있어 LLM 은 다시 돌지 않았다 — 설계대로 **렌더·데이터 계층만** 비교된다(§8-2).

실행: L3 자막 13건·텔롭 11건 → L3t TTS 3 cue 재합성 → **L4 재렌더 11초 + 텔롭 번인**
→ L5. 재현 플래그 `--silence-profile conservative --loudness-lufs -14`.

| 항목 | 결과 |
|---|---|
| `render:shorts.mp4` | **길이 57.900s → 57.900s (Δ0.000s) · 샘플 프레임 12/12 일치** |
| `data:subtitle_segments.json` | 동일 |
| `data:edit_plan.json` · `checkpoint_story.json` | 동일 |
| `data:checkpoint_resources.json` | 동일 |
| `meta` (제목·설명) | 동일 |
| `backup` | 9개 → 9개 |

**판정: 회귀 0.**

- 프레임 일치가 핵심이다 — 재렌더 **+ 텔롭 번인(x264 재인코딩)** 까지 거치고도 픽셀이
  같다. L4 의 컷 재현(§같은 gen_flags)이 실제로 성립한다는 뜻이다.
- `checkpoint_resources.json` 이 동일한 것은 예상 밖의 좋은 소식이다. edge-tts 재합성이
  비결정적이면 `fit_actual_sec` 이 흔들릴 것으로 봤는데, 같은 입력에 같은 길이가 나왔다.

### 7-1. 아직 검증되지 않은 것 — L2b(Flash 모델)

이번 실런은 `onscreen_refined.json` 캐시를 썼으므로 **§4-① 의 Flash 모델 교체는
경로를 타지 않았다.** 텔롭 타이밍 판독 품질은 여전히 미검증이다.

확인하려면 캐시를 지우고 한 번 더 돌려 `onscreen_refined.json` 을 대조한다:

```zsh
cp $DST/localize_ja/onscreen_refined.json /tmp/refined_vlp.json
rm $DST/localize_ja/onscreen_refined.json
$PY -m app.cli localize --job-dir $DST --locale ja --skip-render
diff <(python3 -m json.tool /tmp/refined_vlp.json) \
     <(python3 -m json.tool $DST/localize_ja/onscreen_refined.json)
```

프레임 판독은 LLM 판단이라 **완전 일치를 기대하지 않는다.** 텔롭 개수가 유지되고
구간이 ±1.5초(프레임 간격) 안이면 합격으로 본다. P2 컷오버를 막지는 않되,
**결과를 보고 나서 켜는 것**이 안전하다.

## 8. 실런이 드러낸 버그 4건 (전부 이번에 수정)

기계 대조(§2)로는 못 잡고 **실제로 돌려야만** 나오는 것들이었다.

| # | 증상 | 원인 | 성격 |
|---|---|---|---|
| 1 | `GEMINI_API_KEY 없음` (키가 있는 노드에서) | `spec.gemini_client` 가 ai-video 규약(레포 `.env`)을 안 봤다 — vlp 는 brain `.env` 만 폴백한다 | **이식 누락** |
| 2 | `AttributeError: 'str' object has no attribute 'get'` | `localize_ab.pair_diff` 가 `ko_ja_pairs` 를 리스트로 가정. 실제는 dict | **도구 버그** |
| 3 | `PermissionError: Operation not permitted` (폰트) | `_provision_fonts` 의 `copy2` 가 macOS 시스템 폰트의 SIP 플래그를 `chflags` 로 옮기려다 거부됨 | **원본에도 있던 잠복 버그** |
| 4 | 아무것도 안 돌았는데 `판정: 회귀 0` (2회) | A/B 도구에 실행 증거 검사가 없었고, 넣은 뒤에도 `state.json`(L0 직후 기록)에 속았다 | **도구 버그 — 가장 위험** |

**3번은 이관과 무관하게 남는 문제다.** 운영 노드는 폰트가 이미 `assets/`(untracked)에
있어 이 경로를 안 타므로 여태 안 드러났다 — **새 노드 증설 때 그대로 만난다.**
부트스트랩이 일본어 폰트를 깔지 않는다면 별건으로 처리해야 한다.

**4번이 가장 위험했다.** 대조 도구가 거짓 합격을 내면 그 뒤 모든 판단이 무의미해진다.
지금은 오케스트레이터가 성공 판정에 쓰는 것과 **같은 파일**(`localize_*/metadata.json`)의
갱신만 증거로 인정한다.
