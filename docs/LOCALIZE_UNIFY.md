# L 계열 — 현지화 엔진 ai-video 이관 기획 (2026-08-23)

> 사용자 지시(8/23): "ai-video 에 video-localization-project 기능을 이관한다. 잔망루피는
> 이관된 기능만 쓰되 롱폼→쇼츠 추출도 가능하게, 혜미리예채파는 다른 채널과 동일하게 돌되
> 현지화만 이관 기능으로. ves-orchestrator 에서 홈·편집실에 다른 채널처럼 보이고 편집도
> 되게, 일본어 옆에 한국어 원문도 보이게."
>
> 이 문서가 **이관의 정본 기획서**다. 단계별 발주서(`docs/prompts/e15~`)는 여기서 파생된다.
> 코드 한 줄 옮기기 전에 §7(회귀 0 계약)과 §9(위험)을 먼저 읽을 것.

---

## 0. 사용자 결정 (8/23 문답)

| # | 질문 | 결정 |
|---|---|---|
| 1 | OCR·인페인팅·더빙 모델 등 무거운 의존성 | **ai-video 본체 requirements 에 전부 포함** — 6대 어느 노드에서나 어느 채널이든 처리 가능 |
| 2 | 잔망루피 자동화(스캔→채점→자동선별→자동승인→예약업로드) | **사람이 지시하는 방식으로 전환.** 롱폼은 다른 채널과 동일하게, 쇼츠는 원본을 그대로 쓰되 현지화만 |
| 3 | 롱폼 원본 유입 경로 | **유튜브 채널 롱폼 자동 수집** |
| 4 | 편집실 번역 수정 방식 | **줄 단위로 둘 다** — 한국어를 고치면 그 줄만 재번역, 일본어를 직접 고치면 그대로 확정 |

---

## 1. 지금의 지형 (조사 결과 — 사실관계)

### 1-1. 엔진이 셋, 진입점이 넷이다

| 채널 | 오케스트레이터 경로 | 실제로 도는 엔진 | 산출 |
|---|---|---|---|
| 혜미리예채파(SHOTCONE) | planner → `generate` → `localize(mode=scene_rerender)` | vlp `scripts/localize_run.py` (+ ai-video venv 로 재렌더) | `<job>/shorts.mp4` 교체본 · `localize_ja/metadata.json` |
| 잔망루피(LOOPY) | `zanmang_daily`(10:00 KST) → `zanmang_autopilot` 잡 | vlp `src.autopilot daily` → `src/dub.py`(force_route=C) | `outputs/<vid>/final_dubbed_subbed.mp4` |
| (미사용) | `localize(level=B)` | vlp `src.process_video` (OCR→인페인팅→재합성) | — |
| (미사용) | `localize(level=J)` | vlp `src.convert_short` | — |

즉 `localize` 어댑터 하나가 **네 갈래**로 갈라지고, 그 중 둘은 죽은 경로다.
`ORCHESTRATOR_INTEGRATION.md` 가 "이름이 셋"이라 부른 문제가 코드에도 그대로 있다.

### 1-2. 두 채널의 비대칭 — 이관의 진짜 이유

| | 혜미리예채파 | 잔망루피 |
|---|---|---|
| ai-video 런 | **있다** (job 디렉토리·체크포인트) | **없다** (남의 완성 쇼츠를 받아온다) |
| 작업지시(work_order) | 있다 | **없다** — `zanmang_daily` 가 잡만 만든다 |
| 홈 화면 | 다른 채널과 동일 | `EXT_PIPE` 예외 — "오늘의 자동화 잡" 만 보여준다 |
| 편집실 | 0066 로 KR 전체 개방(편집→재렌더→재번역) | **거절**된다 (`submit_editor_render`: "작업지시 없는 카드는 편집실 대상이 아닙니다(잔망루피 등)") |
| 검수 카드 | `localization_qa` | `localization_qa` + `zanmang_video_id`(0026 전용 규약) |
| 원장 | PG(job_queue/review_queue) | **SQLite `outputs/autopilot.db`** + PG 미러(0034/0036) |

**잔망루피가 이질적인 근본 원인은 "ai-video 런이 없다"이고, 그건 입력이 남의 완성본이기
때문이다.** 그래서 E9 발주서는 편집실을 여는 대신 vlp 에 컷 기능을 따로 넣었다 —
동등화를 코드 이원화로 산 것이다. 이관은 이 빚을 갚는 일이다.

### 1-3. 실제 운영 라우트 (착각하기 쉬운 지점)

- 잔망루피는 `autopilot.force_route: C` — **precheck(OCR 라우트 판정)를 건너뛴다.**
  8/12 실측에서 paddleocr 초기화 실패로 하루 처리량이 0~1편이 되자 강제로 바꿨다.
  ⇒ **지금 도는 잔망루피 경로에 인페인팅·OCR 은 없다.** 도는 것은
  `src/dub.py`(faster-whisper ASR → 트랜스크리에이션 → ElevenLabs 클론 보이스 →
  Demucs 보컬 분리 → 믹스 → 자막 번인)뿐이다.
- Level B/BJ(인페인팅·병기)와 `convert_short`(등급 J)는 코드는 있으나 운영 부하가 0 이다.
- ⇒ 이관 우선순위는 **① scene_rerender · ② dub** 이고, OCR·인페인팅은 그 다음이다.
  (사용자 결정 1 에 따라 의존성은 처음부터 다 넣되, 검증 순서는 사용량을 따른다.)

---

## 2. 목표 상태 — 한 문장

> **ai-video 가 유일한 생성·현지화 엔진이고, ves-orchestrator 가 유일한 관제이며,
> 채널의 차이는 코드 경로가 아니라 설정(design/localize 키)으로만 표현된다.**

따르는 계(系):
- 엔진 진입점은 `python -m app.cli` 하나. 어댑터는 argv 만 만든다.
- `video-localization-project` 는 이관 완료 후 **동결**(read-only 참조·이력 보존).
  ⚠ 동결 전까지 vlp 를 계속 배포한다 — 컷오버는 플래그 뒤에서 병행한다(§8).
- 채널이 늘어도 코드는 안 늘어난다: `localize` 프로필 한 덩이를 추가할 뿐이다
  (사용자: "물론 이후에 추가될 수도 있어").

---

## 3. ai-video — 새 계층 `app/localize/`

### 3-1. 모듈 지도

```
app/localize/
  __init__.py      계약·모드 상수      (LocalizeSpec / LocalizeResult)
  spec.py          채널 현지화 프로필 파싱·검증 (design.localize → LocalizeSpec)
  collect.py       L0 수집·백업        (localize_backup_ko/ — 재실행해도 이중 번역 없음)
  telop.py         L2·L2b 텔롭 추출·타이밍 프레임 대조 (Gemini Pro 1장=1콜 규약)
  translate.py     L1 문맥 통번역 + 용어집 강제 + response_schema + **줄 단위 캐시**
  apply.py         L3 데이터 계층 교체 (subtitle_segments·checkpoint_story·
                                        checkpoint_resources·edit_plan)
  narration.py     L3t 일본어 내레이션 재합성 (tts.py 재사용 — 아래 3-4)
  rerender.py      L4 재렌더 + 텔롭 ASS 번인 (gen_flags 복원)
  meta.py          L5 유튜브 제목·설명·해시태그 + ko_ja_pairs
  overrides.py     편집실 오버라이드 병합 (줄 단위 ko/ja 선택 — §6)
  external/        완성본 입력 경로(잔망루피 쇼츠)
    detect.py      OCR (paddleocr → rapidocr 폴백)
    mask.py        마스크 기하
    inpaint.py     opencv | lama | sttn | propainter (상업 게이트 유지)
    dub.py         ASR → 트랜스크리에이션 → 클론 TTS → 보컬 분리 → 믹스
    overlay.py     render_mode: subtitle | replace | clean | bilingual
    cuts.py        완성본 시간축 구간 잘라내기 (E9 계약 승계)
  qa.py            역번역 자기검증 · 용어집 위반 · 언어 이탈 검사
  data/
    locales.json   로케일 렌더 자원(폰트·TTS 보이스 맵)
    works.json     작품별 표기·용어집·필수 고지  ⚠ 내부 키는 절대 번역 안 함
    persona.md · font_map.yaml · glossary.yaml
```

**원칙: 새 파일로만 들어온다.** 기존 `app/modules/*` 는 재사용만 하고 수정하지 않는다.
수정이 필요하면 그 자체로 별건 발주(E10~E14 가 세운 규약).

### 3-2. 현지화 모드 — 둘뿐이다 (용어 통일)

| 모드 | 입력 | 화면 속 한글 | 컷 재현 | 쓰는 채널 |
|---|---|---|---|---|
| **`rerender`** | ai-video job 디렉토리(체크포인트) | 애초에 안 그린다 | gen_flags 복원 → 프레임 단위 | 혜미리예채파 · 잔망루피 **롱폼** |
| **`overlay`** | 완성 mp4 한 개 (외부 소스) | 인페인팅으로 지우거나(replace) 병기(bilingual)하거나 그대로(subtitle) | 해당 없음(원본 시간축) | 잔망루피 **쇼츠** |

기존 등급 표기 A/B/BJ/C/BC 는 **`overlay` 안의 `route`** 로 강등된다
(`rerender` 에는 등급이 없다 — 등급 J·B 를 `mode` 와 섞어 쓰던 혼선의 근원).

| route | inpaint | render_mode | dub |
|---|---|---|---|
| A | ✗ | subtitle | ✗ |
| B | ✓ | replace | ✗ |
| BJ | ✗ | bilingual | ✗ |
| C | ✓ | replace | ✓ |
| BC | ✓ | clean | ✓ |

### 3-3. CLI 계약

```bash
# ① rerender — 생성이 끝난 job 을 그 자리에서 현지화 (혜미리예채파·잔망루피 롱폼)
python -m app.cli localize --job-dir <job> --locale ja [--overrides <json>]

# ② overlay — 완성본 한 개를 현지화 (잔망루피 쇼츠)
python -m app.cli localize --video <mp4> --video-id <id> --locale ja \
       --mode overlay --route C --voice <elevenlabs_voice_id> [--overrides <json>]

# ③ 생성과 한 번에 (롱폼 → 쇼츠 → 현지화)
python -m app.cli create_shorts … --localize ja
```

- **미지정 = 종전 그대로.** `--localize` 없는 실행은 파일 한 바이트도 안 변한다
  (E11·E13 이 세운 게이트 규약 — KR 채널 20개의 회귀 0 조건).
- 허용값 밖은 argparse `choices` 로 **즉시 실패**. 조용히 기본값으로 떨어지면
  사람은 일본어판을 만든 줄 알고 한국어판을 발행한다.
- 성공 마커·산출 규약은 **지금 것을 그대로 승계**한다 —
  `<job>/localize_ja/metadata.json`, `<job>/shorts.mp4` 교체본,
  한국어 원본은 `localize_backup_ko/`·`shorts_ko.mp4`.
  ⇒ 어댑터·검수함·편집실이 컷오버 순간에 안 깨진다.

### 3-4. 이관하면서 합치는 것 (중복 제거)

| vlp 쪽 | ai-video 쪽 | 이관 후 |
|---|---|---|
| `engine/llm.py` (Gemini 호출) | `app/modules/gemini_client.py` | **ai-video 것으로 합친다** — 모델 규칙(pro/flash 2종 고정)이 CLAUDE.md 에 못박혀 있다 |
| `src/dub.py` 의 ElevenLabs 합성 | `app/modules/tts.py` (E11·E12: 프리셋·speed·캐시·실패 분류) | **ai-video `tts.py` 를 정본으로**, dub 은 보이스·타이밍 로직만 남긴다. `elevenlabs:{voice_id}` 접두사(E12)가 이미 클론 보이스를 받는다 |
| `src/dub.py` 의 faster-whisper 전사 | `app/modules/speech.py` · `stt_elevenlabs.py`(E11·E13) | **ai-video 전사 계층 재사용** — 백엔드 선택(`--transcribe-backend`)·keyterms·표기 보정이 공짜로 따라온다 |
| `engine/render.py` 의 ASS 조립 | `app/modules/subtitle.py` · `subtitle_styles.py`(E5·E14) | **ai-video 것으로.** 단 `style_ass_tags`/`validate_line_style` 는 편집실 계약이라 **동작 동일** 유지 |
| `engine/common.py` ffmpeg 탐색 | `app/modules/ffmpeg_utils.py`(E13 곁다리) | ai-video 것으로 |
| `engine/cuts.py` | (없음) | `localize/external/cuts.py` 로 이관, E9 계약 유지 |

⚠ **합치기가 곧 회귀 위험이다.** 특히 자막 조립: ai-video `merge_subtitle_segments` 에는
E14 노출 하한이 붙어 있고 vlp `render.py` 에는 없다. 잔망루피 자막 타이밍이 조용히
움직이면 안 되므로, `overlay` 경로는 **E14 후처리를 명시적으로 끄고 시작**해
A/B 로 확인한 뒤 켠다(§7).

### 3-5. 채널 현지화 프로필 (design 키 확장)

오케스트레이터 `channel_design_overrides`(0014) 에 `localize` 한 덩이를 추가한다.
어댑터는 이 값을 그대로 CLI 플래그로 옮긴다 — 판단은 하지 않는다.

```json
"localize": {
  "locale": "ja",
  "mode": "rerender",              // rerender | overlay
  "route": "C",                    // overlay 전용
  "work": "혜미리예채파",           // works.json 조회 키 — ⚠ 내부 키, 절대 번역 안 함
  "voice": "elevenlabs:<voice_id>",
  "narration": "ja",               // ja | keep — 내레이션 TTS 를 일본어로 재합성할지
  "audio": "keep",                 // keep | dub — 원본 대사 오디오 처리
  "subtitle_font": "…", "title_font": "…", "telop_font": "…"
}
```

기존 `ops_config.localize_levels/backends/voices` 3종은 이 한 키로 흡수한다
(채널 설정이 세 군데 흩어져 있어 "어느 값이 이겼는지" 를 사람이 못 읽는다).

---

## 4. 채널별 동작

### 4-1. 혜미리예채파 — 결과는 그대로, 엔진만 바뀐다

- 파이프라인 `shorts_jp_localized` 유지. 체인 `generate → … → localize(rerender)` 유지.
- 편집실 0066 체인(편집 → ai-video 재렌더 → 재번역) 그대로. **호출 대상만** vlp
  `localize_run.py` → ai-video `app.cli localize` 로 바뀐다.
- **완료 판정 = 회귀 0.** 같은 job 디렉토리에 구·신 엔진을 돌려
  ① 최종 mp4 길이·프레임 해시 ② `subtitle_segments.json` 바이트 ③ `metadata.json`
  (youtube_title·description·ko_ja_pairs) 를 대조한다. 번역문은 LLM 이라 비결정적이므로
  **캐시된 translation.json 을 고정 입력으로 넣어** 렌더 계층만 대조한다.

### 4-2. 잔망루피 — 두 갈래, 둘 다 사람이 지시한다

**(a) 쇼츠 현지화** — 기본. 원본은 그대로 쓰고 현지화만.

```
사람이 쇼츠 지정(유튜브 URL) → work_order(pipeline=shorts_jp_overlay)
  → acquire(yt-dlp 다운로드) → localize(mode=overlay, route=C)
  → upload_artifacts → localization_qa 검수 카드 → 편집실 → 발행
```
- ai-video 생성 파이프라인(분석·스토리·클립 선정)을 **안 탄다.** 사용자 지시대로
  "ai-video 기능은 거의 안 쓰고 이관된 기능만" 이 그대로 성립한다.
- 그럼에도 **작업지시(work_order)가 생긴다** — 이것이 홈·편집실 동등화의 열쇠다(§5-2).
- 폐기: `autopilot.auto_select`·`auto_approve`·`force_route`·SQLite 원장·
  `zanmang_daily`·`zanmang_autopilot` 잡·`scan`/`score`/`report`.
  ⚠ 원장의 **발행 이력(uploaded/url/published_at)은 PG 로 이관**한다 — 지우면
  같은 영상을 두 번 올린다.

**(b) 롱폼 → 쇼츠** — 확장.

```
yt_longform_watch(신설) → 채널 롱폼 자동 수집 → sources 등록
  → 사람이 작업카드로 지시 → 일반 채널과 완전 동일한 generate
  → localize(mode=rerender) → 검수 → 발행
```
- 이 갈래에서는 잔망루피가 **혜미리예채파와 같은 코드 경로**를 탄다.
  화면에 한국어가 애초에 안 그려지므로 인페인팅이 불필요하다(품질도 더 낫다).
- 자동 수집은 **소스 등록까지만**이다. 무엇을 만들지는 사람이 정한다(결정 2).

### 4-3. 다른 KR 채널 20여 개

**아무것도 바뀌지 않는다.** `localize` 키가 없으면 코드 경로가 종전과 동일하다.
이것이 이 이관의 최상위 제약이다.

---

## 5. ves-orchestrator

### 5-1. 파이프라인 3종으로 정리

| pipeline | 체인 | 채널 |
|---|---|---|
| `shorts_kr` | acquire → generate → upload_artifacts → ingest → evaluate → publish_gate | KR 채널 |
| `shorts_jp_localized` | 위 + `localize(rerender)` | 혜미리예채파 · 잔망루피 롱폼 |
| `shorts_jp_overlay` **(신설)** | acquire → localize(overlay) → upload_artifacts → localization_qa | 잔망루피 쇼츠 |

`zanmang_autopilot` 은퇴. `ves/adapters/zanmang.py`·`zanmang_decision.py`·
`ves/scheduler/zanmang_daily.py` 는 컷오버 완료 후 삭제.

### 5-2. 잔망루피에 작업지시를 준다 = 홈·편집실 동등화

한 줄 요약: **`work_order_id` 가 없어서 막히던 것이 전부 열린다.**

- 홈: `EXT_PIPE` 예외 삭제 → 다른 채널과 같은 카드(작품·회차·라운드·소스)로 그려진다.
- 편집실: `submit_editor_render` 의 "작업지시 없는 카드는 편집실 대상이 아닙니다" 거절이
  자연히 사라진다. `overlay` 카드는 KR 타임라인이 없으므로 **편집 가능 항목이 다르다**:

  | 편집 항목 | rerender(혜미리예채파·잔망 롱폼) | overlay(잔망 쇼츠) |
  |---|---|---|
  | 구간(clips) | ✓ 원본 타임라인 | △ 완성본 컷 잘라내기(E9 `cuts`) |
  | 자막·대사 문구 | ✓ | ✓ |
  | 번역문(ja) | ✓ | ✓ |
  | 제목 | ✓ 번인 + 유튜브 | 유튜브 제목만(번인 제목이 없다) |
  | TTS 내레이션 | ✓ | ✓(더빙 라인) |
  | 이미지 오버레이·디자인 | ✓ | ✗ |

  화면은 **같은 편집실**을 쓰고 지원 안 되는 탭만 감춘다(지금처럼 별도 JP 화면을 두지 않는다).

### 5-3. 롱폼 자동 수집 — `ves/scheduler/yt_longform_watch.py` (신설)

- 기존 `source_watch`·`drive_watch` 와 같은 자리. 채널별 유튜브 채널ID를 받아
  신규 롱폼을 `sources` 에 등록한다(내용주소 sha256 캐시 규약 §9-2 준수).
- 다운로드는 스케줄러가 아니라 `acquire` 잡이 한다(디스크·네트워크 캡).
- 보관: 롱폼은 편당 수 GB 다 — `storage_gc`·`diskgc` 정책에 롱폼 전용 보존 기간을 넣는다.
- ⚠ 저작권: 잔망루피 원본은 라이선스 확보 전제(© ICONIX 등). 자동 수집은
  **수집까지만**이고 발행은 사람이 승인한다 — 지금의 유예 창 정책을 그대로 유지한다.

### 5-4. 편집실 통일 (§6 에서 계약 상술)

- `edJpMode`(loopy/shotcone 분기) 흡수 → 카드 종류가 아니라 **`localize.mode`** 로 갈린다.
- 모든 자막·제목·내레이션 줄에 **KO 원문 병기**(사용자 지시).
- 줄 단위 `ko`/`ja` 선택 편집(결정 4).

### 5-5. 마이그레이션 (0075~)

| # | 내용 |
|---|---|
| 0075 | `channel_design_overrides.localize` 키 개방 + 검증(mode/route/locale 화이트리스트) |
| 0076 | `shorts_jp_overlay` 파이프라인 수용 — `run_channel_now`·planner RPC |
| 0077 | 잔망루피 work_order 발급 경로(쇼츠 지정 RPC `enqueue_localize_short`) |
| 0078 | `submit_editor_render` — overlay 카드 수용, 지원 항목 화이트리스트 |
| 0079 | `localize_lines` 오버라이드 계약(줄 단위 ko/ja) + 검증 |
| 0080 | 잔망루피 원장(0034/0036 미러) → 정본 테이블 승격 · 발행 이력 이관 |
| 0081 | 컷오버 후 정리 — `zanmang_*` RPC·`EXT_PIPE`·`ops_config.zanmang_pipeline` 제거 |

### 5-6. 어댑터 정리

- `ves/adapters/localize.py`: 네 갈래 → **두 갈래(rerender/overlay)**, 둘 다 ai-video CLI.
  `scene_rerender_argv`·`localize_argv`·`dub_argv`·`convert_argv` → `localize_argv` 하나.
- `_restore_run_dir`(번들 복원)은 rerender 전용으로 유지 — overlay 는 job 디렉토리가 없다.
- 노드 어피니티: rerender 는 지금처럼 생성 노드 핀. overlay 는 **캡 불필요**
  (의존성이 전 노드에 깔리므로 `localize` 캡=mm-06 전담이 사라진다 — 결정 1의 이득).

### 5-7. brain 리포 (이 세션 범위 밖 — 확인 필요)

채널 정본 `channels.json` 은 brain(`ai-improvement-edit-video`)에 있고 planner 가 읽는다.
잔망루피의 `pipeline` 값 변경은 **brain 수정**이 필요하다. 이 리포는 현재 세션에
붙어 있지 않으므로 §10 미결로 남긴다.

---

## 6. 편집실 계약 — KO/JA 병기 + 줄 단위 선택 (결정 4)

### 6-1. 자료: `ko_ja_pairs` 를 편집실 정본으로 승격

지금은 검수 카드의 참고 표시용(40건 상한)이다. 이관 후에는 편집 대상 자료가 된다.

```json
{ "i": 12, "kind": "subtitle|telop|tts|title",
  "start": 34.2, "end": 36.0,
  "ko": "이거 진짜 미쳤다",
  "ja": "これマジでヤバい",
  "src": "engine|ko_edited|ja_edited",     // 이 줄이 어디서 확정됐는가
  "use": true }
```

- `src` 가 화면에 보인다 — 검수자가 "이 줄은 내가 일본어를 직접 고친 줄" 을 안다.
- 상한 40건 해제(편집 자료이므로 전량). 크면 `editor_assets` 처럼 별 테이블로.

### 6-2. 제출 오버라이드

`edit_overrides.localize.lines[]` — 기존 `edit_overrides` 스키마에 **새 키로만** 얹는다
(구 엔진은 모르는 최상위 키를 무시한다 — E6-0·E9 와 같은 구도).

```json
{"localize": {"locale": "ja", "lines": [
  {"i": 12, "ko": "이거 진짜 미쳤다니까"},    // 한국어 수정 → 그 줄만 재번역
  {"i": 15, "ja": "これはヤバすぎる"},        // 일본어 확정 → 재번역 건너뜀(pin)
  {"i": 18, "use": false}                      // 그 줄 제외
]}}
```

**규칙(엔진·화면 공통 계약):**
1. `ja` 가 오면 그 줄은 **번역하지 않는다.** 사람 확정이 LLM 을 이긴다.
2. `ko` 만 오면 그 줄만 재번역한다. 다른 줄은 캐시에서 그대로 온다.
3. 둘 다 오면 `ja` 가 이기고, 화면이 "한국어 수정은 원문에만 반영됩니다" 라고 알린다.
4. **`ko` 수정은 한국어판 산출물도 바꾼다** — 자막·내레이션이 함께 바뀌므로
   ai-video 재렌더가 필요하다(0066 체인). `ja` 만 고친 라운드는 **localize 단계만**
   다시 돌면 된다. 비용·시간이 한 자릿수 배 차이라 화면이 소요 시간을 다르게 안내한다.
   - overlay(잔망 쇼츠)는 `ko` 수정도 더빙 재합성을 부르므로 어느 쪽이든 전체 재실행이다.

### 6-3. 줄 단위 번역 캐시 (요금)

`sha1(ko + glossary_ver + model + 문맥키)` → `<job>/localize_<locale>/tcache/{key}.json`.
안 고친 줄은 재번역하지 않는다. E12 가 TTS 에서 같은 이유로 캐시를 넣었고,
편집 라운드가 반복되는 구조라 캐시가 없으면 요금이 라운드 수만큼 곱해진다.
⚠ **문맥 통번역과 충돌**한다 — 줄 단위 캐시는 앞뒤 문맥이 바뀌면 무효여야 한다.
문맥키 = 인접 ±2 줄의 ko 해시. 이 규칙은 실측으로 검증하고 실패하면 전량 재번역으로 후퇴한다.

---

## 7. 회귀 0 계약 — 절대 안 변해야 하는 것

| # | 대상 | 판정 방법 |
|---|---|---|
| 1 | KR 채널 20여 개 | `localize` 키 없는 실행은 필터그래프 문자열·자막 바이트가 종전과 동일. 기존 `tests/test_e1*` 가 이미 고정한 값을 그대로 쓴다 |
| 2 | 혜미리예채파 최근 5편 | 같은 job + 고정 translation.json → mp4 길이·프레임 해시·SRT 바이트 동일 |
| 3 | 잔망루피 최근 10편 | 구·신 더빙 산출의 **CER·라우드니스(-16 LUFS)·세그먼트 정렬 리포트** 대조. 목소리는 같은 voice_id 라 동일해야 한다 |
| 4 | 내부 키 | `works.json` 키·`channels.json works`·DB `works.title` 은 한국어 유지. **laeebly 완전일치 조회 키** — 일본어로 바꾸면 권리 조회가 통째로 실패한다 |
| 5 | 발행 안전장치 | 자동 공개 없음. 업로드는 비공개/미등록, 공개는 사람. `qa=hold` 자동 승인 금지 |
| 6 | 라이선스 게이트 | `propainter` 는 `propainter_commercial_ack=true` 없으면 차단. XTTS 가중치(비상업)는 상업 채널 기본값에서 제외 |
| 7 | 자막 하한(E14) | overlay 경로는 처음에 **끄고** 시작 — 잔망루피 자막 타이밍이 조용히 움직이면 안 된다. A/B 후 켠다 |

A/B 하네스: `scripts/localize_ab.py --job A --job B --diff` (E11 `e11_transcribe_ab` 와 같은 형).

---

## 8. 단계 (완료 판정 포함)

| P | 내용 | 완료 판정 |
|---|---|---|
| **P0** | 이관 인벤토리 확정 + A/B 하네스 + 의존성 실측 | vlp 파일별 이관/합치기/폐기 판정표. 6대 pip sync 용량·소요·실패 복구 실측치 |
| **P1** | `rerender` 계층 이관 (§3-1 상단 9개 모듈) | 혜미리예채파 5편 회귀 0(§7-2). 어댑터는 아직 vlp 를 부른다(엔진만 준비) |
| **P2** | 어댑터 컷오버(rerender) | `ops_config.localize_engine='ai-video'` 플래그로 전환. 되돌리기 1줄 |
| **P3** | `overlay` 계층 이관 (external/*) | 잔망루피 10편 회귀 0(§7-3). route C·BC 우선, B·BJ·A 는 그 다음 |
| **P4** | 오케스트레이터 통일 (0075~0078) | 잔망루피가 홈에서 다른 채널과 같은 카드로 보이고, 편집실이 열린다 |
| **P5** | 편집실 KO/JA 통일 + 줄 단위 재번역 (0079) | 한 줄만 고친 라운드가 그 줄만 재번역하고 요금이 그만큼만 나온다 |
| **P6** | 롱폼 자동 수집 + 잔망루피 롱폼 모드 | 롱폼 1편이 사람 지시 → 쇼츠 → 현지화 → 발행까지 완주 |
| **P7** | 구 경로 폐기 (0080·0081) | `autopilot.db` 쓰기 0. vlp 동결. `zanmang_*` 코드 삭제 |

각 P 는 **독립 배포 가능**하고 이전 단계로 되돌릴 수 있어야 한다
(`deployments.auto_update=true` — main 머지 = 맥미니 6대 즉시 갱신).

---

## 9. 위험

### 9-1. 의존성 (결정 1의 대가) — 가장 큰 위험

`paddlepaddle`·`torch`·`torchaudio`·`demucs`·`coqui-tts` 를 본체 requirements 에 넣으면
**6대 전부**가 받는다. 지금 실패하면 **전 채널이 멈춘다**(현재는 mm-06 만 멈춘다).

완충책(발주에 반드시 포함):
1. `updater` 의 pip sync 실패 시 **이전 venv 를 유지**하는지 먼저 확인·보강한다.
   (부분 설치된 venv 로 계속 도는 것이 최악이다)
2. 한 번에 넣지 않는다 — P1(추가 의존성 0) → P3(무거운 것) 순서.
3. 노드 1대(카나리아)에 먼저 pin 하고 3일 주행 후 확대.
4. paddlepaddle 은 macOS arm64 에서 이력이 나쁘다(8/12 초기화 실패로 하루 처리량 0).
   실측 실패 시 **OCR 백엔드를 rapidocr 기본 + paddleocr 선택**으로 뒤집는다.

### 9-2. LLM 비결정성
번역·텔롭 추출은 런마다 다르다. 회귀 대조는 **번역 결과를 고정 입력으로 주입**해
렌더 계층만 본다. 번역 품질은 별도로 사람 검수·역번역 QA 로 본다.

### 9-3. 시간축
컷·오프셋 수식을 베끼지 않는다. E13 이 남긴 교훈대로 **같은 함수**
(`remap_transcript_to_edited_timeline`)를 다시 태운다. E9 `cuts` 도 같은 규칙으로 흡수.

### 9-4. 이름
이관 후 "video-localization-project" 라는 이름이 가리키는 것이 하나여야 한다.
README 에 동결 선언과 이관처를 못박는다.

---

## 10. 미결 — 사람 확인 필요

| # | 항목 | 기본값(확인 전) |
|---|---|---|
| 1 | brain(`ai-improvement-edit-video`) 리포 접근 — `channels.json` 의 잔망루피 pipeline 변경이 필요하다. 이 세션에 미연결 | P4 착수 전 리포 추가 |
| 2 | 잔망루피 쇼츠 "지정" UI — 유튜브 URL 붙여넣기 / 채널 최신 목록에서 고르기 | URL 붙여넣기(가장 단순) + 목록은 P6 |
| 3 | 잔망루피 유튜브 업로드 토큰·예약 공개(19:00 JST) 정책 유지 여부 | 유지. 단 자동 승인은 폐기 |
| 4 | 일본어 폰트 정본 — 현재 `ArialUnicode`(macOS 복사본, untracked) | 정식 선정 후 `app/assets/fonts` 에 커밋. 그 전까지 부트스트랩 프로비저닝 유지 |
| 5 | 롱폼 자동 수집 대상 채널ID·주기·보관 기간 | 일 1회, 신규분만, 30일 보관 |
| 6 | 멤버명 일본어 공식 표기(리정·채원) | 현행 잠정 표기 유지(PLAN §9-4 미결 승계) |
