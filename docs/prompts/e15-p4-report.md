# L-P4 보고 — overlay 계층 이관 (2026-08-24)

발주서: [`docs/LOCALIZE_UNIFY.md`](../LOCALIZE_UNIFY.md) §3-2 · §8-3 · §8-7 · §8-8.
이관본: ai-video `app/localize/overlay/` (main `00a764a`).

---

## 0. 한 줄 요약

vlp 의 overlay 파이프라인(**3,275줄**)을 ai-video 로 옮겼고 **250개 함수·상수가 AST
동일**하다. **지금 동작은 하나도 안 바뀐다** — `--mode overlay` 를 주는 코드가 아직 없다.

---

## 1. 무엇을 옮겼나

| vlp | ai-video | 줄 |
|---|---|---|
| `engine/common.py` | `overlay/common.py` | 410 |
| `engine/detect.py` | `overlay/detect.py` | 331 |
| `engine/render.py` | `overlay/render.py` | 595 |
| `engine/inpaint.py` · `mask.py` · `cuts.py` · `schemas.py` · `qa*.py` · `translate.py` · `llm.py` | 같은 이름 | ~840 |
| `src/process_video.py` | `overlay/pipeline.py` | 258 |
| `src/dub.py` | `overlay/dub.py` | 1,469 |
| `src/refbank.py` · `src/precheck.py` | 같은 이름 | 442 |
| — | `overlay/runner.py` (신설) | 51 |

route 정본은 `overlay/data/pipeline.config.yaml` 의 `levels` 다 — 구 '등급'을 이름만
강등했고 값은 그대로다(A·B·BJ·C·BC).

## 2. 이식 충실도 — 기계 대조

`python -m scripts.overlay_port_diff`

```
동일          250
의도된 차이     7
예상 밖 차이    0
```

| 갈라진 것 | 사유 |
|---|---|
| `llm.resolve_model` | vlp config 의 `gemini-3.5-flash`·`gemini-pro-latest` 는 이 레포 **사용 금지 모델**이다. config 를 안 읽고 env 기본값을 따른다(P1 과 같은 규약) |
| `common.PROJECT_ROOT` · `load_config` | 경로 기준이 ai-video 레포 루트, 설정은 `overlay/data/` |
| `pipeline._parse_args` · `main` | 이 레포 진입점은 `app.cli` 하나 |
| `pipeline.process_video` | 로그가 안내하는 더빙 실행 경로를 이식 위치로(없는 파일로 보내면 안 된다) |
| `dub.dub_from_video` | self-ref 프로브의 자기 호출 모듈 경로를 `_SELF_MODULE` 로 |

⚠ 도구는 **함수 안 임포트의 패키지 이름 변경을 정규화**한다. 안 하면 멀쩡한 이식 16건이
전부 '예상 밖 차이'로 뜬다 — 도구가 늘 울면 사람이 도구를 안 본다.

## 3. 🛑 회귀 가드가 잡은 이식 결함 3건

파일 단위 복사는 **함수 안 지연 임포트**를 놓친다. 셋 다 문법·임포트 검사를 통과하면서
런타임에 죽는 것이었다:

1. `dub.py` 의 `from engine import render` — 재배선 누락
2. `dub.py` 가 self-ref 프로브를 **`-m src.dub`** 로 다시 부르던 것. 모델 캐시 오염을
   피하려 자기를 서브프로세스로 부르는데(2026-07-08 vlp 실측 주석) 이 레포엔 없는 모듈이다
3. **`src/refbank.py`·`src/precheck.py` 를 아예 안 옮긴 것** — dub 이 지연 임포트로 써서
   드러나지 않았다

⇒ **지연 임포트가 많은 코드는 문법이 통과해도 이식이 끝난 게 아니다.**

## 4. 계획서 §8 회귀 0 계약 대조

| # | 대상 | 상태 |
|---|---|---|
| 1 | KR 채널 20개 | ✅ `--mode` 미지정이면 종전 rerender — 새 코드가 안 돈다 |
| 7 | 라이선스 게이트 | ✅ propainter `commercial_ack` 게이트 그대로. 가드가 라이선스 벽과 가중치 벽을 **구분해** 고정 |
| 8 | 자막 하한(E14) | ✅ overlay 자막은 `overlay/render.py` 가 조립하고 `merge_subtitle_segments` 를 안 지난다 — 계약대로 꺼진 채다 |
| 3 | 잔망루피 10편 CER·라우드니스·정렬 | ⏳ **아직** — §5 |
| §10-1 | 의존성(최대 위험) | ✅ **requirements 무변경.** OCR 3·인페인트 4·TTS 3·전사·보컬분리가 전부 지연 임포트 + 폴백. 임포트로 하나도 안 끌려오는 것을 가드가 서브프로세스로 실측 |

## 5. ⏳ 실측 회귀 0 — 대조 기준이 job_queue 가 아니다

**여기서 착각하기 쉽다.** DB 실측:

```
VES 를 통한 overlay 잡  총 3건 · 마지막 2026-08-13 · 등급 J 2건 · B 1건
route C·BC             VES 를 통해 한 번도 안 돌았다
LOOPY 의 VES 활동      zanmang_decision 8건 (승인·업로드 결정만)
```

⇒ 잔망루피 실운영은 **mm-06 의 vlp autopilot**(자체 SQLite 원장)이고, 대조 기준은
그 산출물이다. 이 컨테이너에는 소재도 OCR 백엔드도 없어 실측을 못 한다.

### 노드에서 재는 법 (mm-06)

정본은 ai-video **`docs/overlay_ab_runbook.md`** 다.

🛑 **이 보고서 초판에 적었던 명령은 틀렸다.** 두 가지가 잘못됐다:

1. `localize_ab` 의 플래그는 `--job/--job2` 가 아니라 **`--a/--b`** 다.
2. 애초에 **`localize_ab` 를 쓰면 안 된다** — rerender 전용이라 `shorts_ko.mp4`·
   `localize_backup_ko/`·`metadata.json` 을 찾는데 overlay 산출에는 그 파일들이
   **아예 없다.** 하나도 못 찾은 채 '차이 없음'을 내는 **거짓 합격**이 된다
   (P1 노드 실측에서 두 번 당한 그 실패 모드다).

그래서 overlay 전용 도구를 만들었다 — `scripts/overlay_ab.py`.

```zsh
R=/opt/ves/engines; AIV=$R/ai-video/.venv/bin/python
cd $R/ai-video && git pull

# ① 이식이 vlp 를 따라잡고 있는지부터 (P2b·E16 때 두 번 앞서갔다)
VLP_ROOT=$R/video-localization-project $AIV -m scripts.overlay_port_diff --verbose
#   → '예상 밖 차이 0' 이 아니면 여기서 멈춘다

# ② 같은 소재로 신 엔진
VID=<autopilot 이 이미 처리한 video_id>;  SRC=<그 원본 mp4>
$AIV -m app.cli localize --mode overlay --video "$SRC" --video-id "${VID}_new" --route B

# ③ 대조
$AIV -m scripts.overlay_ab --a $R/video-localization-project/outputs/$VID \
                           --b $R/ai-video/outputs/${VID}_new
```

판정 항목(§8-3):

| 줄 | 판정 |
|---|---|
| 원문(OCR·탐지) | **회귀 대상** — 달라지면 번역보다 상류가 흔들린 것 |
| 세그먼트 정렬 | **회귀 대상** — 어긋나면 자막이 딴 장면에 뜬다(허용 0.05s) |
| 최종본 길이 · 라우드니스 | **회귀 대상**(허용 ±1.0 LUFS) |
| 번역문 CER | 판정에서 뺀다 — LLM 비결정성. 크기만 본다 |

⚠ `⚠ 못 쟀다` 가 뜨면 그 항목은 **판정에 안 들어간 것**이다(ffmpeg 이 비대화형 SSH 의
PATH 에 없을 때). `FFMPEG_BIN`·`FFPROBE_BIN` 을 지정하고 다시 돌린다 — 라우드니스는
판정 항목이라 빠지면 판정이 반쪽이다.

⚠ **OCR 백엔드가 양쪽에서 같아야 한다**(config `detect.ocr_backend`, 기본 paddleocr).
갈리면 대조가 무의미하다.

route C(더빙)는 ②를 `--route C` 로 돌린 뒤 별도 실행이다 — 더빙은 overlay 파이프라인이
부르지 않는다(검수 게이트 뒤 단계). `voice_id` 를 반드시 준다(안 주면 잔망루피 클론
보이스로 떨어진다).

## 6. 남은 것

| | 무엇 | 막고 있는 것 |
|---|---|---|
| a | 실측 회귀 0 (§5) | mm-06 접근 |
| b | 어댑터 컷오버 | (a) — P2 와 같은 스위치 한 값으로 |
| c | `tts.py` 합치기(§3-4) | (a) — 충실 이식 → 회귀 0 → 합치기 순서 |
| d | 등급 J (`convert_short.py`, 314줄) | 휴면이지만 코드 경로는 산다 |

(b) 가 끝나면 vlp 는 **통째로 동결 가능**하다(P8) — rerender 는 이미 컷오버됐고 overlay 가
마지막 산 경로였다.
