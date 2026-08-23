# E15 — 스타일 구성 단계(Style Compose) 기획서

**상태: 기획 초안 — 발주서 아님.** 확정되면 엔진(ai-video) 발주서와 오케스트레이터
파트로 쪼개서 나간다. 사용자 결정(2026-08-23):

- AI 결정 범위 = 연출 텍스트·자막 강조 + 이미지 오버레이 + 디자인 레벨 일부 + TTS 보이스/속도 (전부)
- 검수 흐름 = **자동 렌더 → 편집실 사후 수정** (현행 검수함·반려-재렌더 루프 그대로)
- 현지화(vlp)는 **이관 기획이 아니다** — 다른 세션에서 진행 중인 작업과
  충돌하지 않게 하는 **제약 조건**으로만 다룬다(§9).
- 모델 정책 = **Pro 는 영상 분석(analyze_chunk)에만**, 그 외 전 호출은 Flash 최신
  (`gemini-3.6-flash`) — E15 와 같이 나가는 정리 작업 포함(§6 모델 사용 정책).

## 1. 배경 — 지금 있는 편집 요소와 빈자리

최근(E7~E14·F-401~F-411)까지 열린 편집 요소 인벤토리. "누가 쓰나" 열이 핵심이다:

| 요소 | 계약 | 누가 쓰나 |
|------|------|-----------|
| 자막 줄 스타일 size·y·color·rotate (F-407/410) | edit_overrides/v3 `subtitles[].style` | 편집실(사람)만 |
| 자막 원본 앵커 (F-401) | `subtitles[].source_time_sec` | 편집실만 |
| 이미지 오버레이+회전 (F-408/410) | `images[]` (run_dir 상대 파일·x/y/w/layer/rotate) | 편집실만 |
| 자유 텍스트 — 의성어·강조·pop/shake (F-411) | `texts[]` (중심좌표·size·color·stroke·fx·rotate·폰트 4종) | 편집실만 |
| 시간대별 제목 (E8) | `title.segments[]` (창 밖 = 제목 없음) | 편집실만 |
| 제목 크기/고정 y (F-409) | `--design-title-size`·`--design-title-y-fixed` | 채널 플래그·편집실 |
| 제목 줄별 박스·굵게 | `--design-title-box(2)`·`-box-color(2)`·`-bold(2)` | 채널 플래그·편집실 |
| 디자인 회전·배속 (E7) | `--design-title-rotate`·`--design-tts-rotate`·`--design-video-speed` | 편집실만 |
| 영상 밴드 레이아웃 (E10) | `aspect_ratio`·`video_width`·`video_y` + 밴드 앵커 자막 기하 | 채널 플래그(editor_e10 게이트) |
| 플랫폼 표기 | `--design-platform-*` (밴드 모서리 앵커) | 채널 플래그 |
| KR 내레이션 ElevenLabs (E11) + 보이스 개방 (E12) | voice 라벨 불변계약 + `elevenlabs:{voice_id}` + cue 합성 캐시 | 백엔드 자동·편집실 |
| 전사 백엔드·다듬기 (E11/E13) | `--transcribe-backend` + keyterms·표기 보정 | 채널 플래그 |
| 자막 노출 하한 (E14) | `_enforce_min_exposure` (전 경로 공통) | 자동 |

빈자리: **편 단위로 이 어휘를 조합하는 AI 단계가 없다.** 채널 플래그는 정적(채널
정체성)이고, v3 오버라이드는 사람 손이다. AI 산출은 스토리 구성(story)에서 끝난다 —
제목 문구·클립·tts cue 까지. F-411 계약 문서가 "AI 효과 텍스트 제안(후속)도 같은
형식으로 채운다"로 예고해 둔 자리가 정확히 여기다.

## 2. 목표 / 비목표

**목표**: 스토리 구성 뒤, 확정된 타임라인·대사·감정 신호를 보고 편 단위 "스타일
플랜"을 AI가 구성하고, 렌더가 그 구성대로 나간다. 산출 어휘는 **기존 계약(v3 +
design 키)을 그대로 재사용** — 새 렌더 경로를 만들지 않는다.

**비목표**:
- 스토리 구성 결과(클립·구간·제목 문구·tts 문구)를 바꾸지 않는다 — 스타일 단계는
  **연출 레이어**다. 문구를 고치고 싶으면 story 반려가 맞다.
- 채널 정체성(폰트·색 체계·밴드 레이아웃·플랫폼 표기)은 건드리지 않는다(§5 우선순위).
- vlp 이관은 이 기획 범위 밖(§9는 충돌 회피만).

## 3. 파이프라인 위치와 단계 정의

```
… → story → silence_cut → 【style】 → resources → render → validate
```

- **silence_cut 뒤**: 무음 컷·클램프까지 끝난 **확정 클립 목록**이 있어야 앵커 좌표
  (원본 절대초)와 편집본 시각을 오갈 수 있다. tts_plan 이 무음 컷 전 clips 를 받아
  cue 가 영상 길이를 넘던 옛 사고(라운드 6a-2)와 같은 함정을 피한다.
- **resources 앞**: TTS voice/speed 연출이 합성에 반영되려면 synthesize 전이어야
  한다. 자막 스타일은 resources 의 재매핑 뒤 병합(§5).
- `--from-step style` 재개 지원. 산출은 `checkpoint_style.json` — 편집실 재렌더
  (`from_step=resources|render`)는 이 체크포인트를 **재호출 없이 그대로 재적용**
  (재개 산출 불변 원칙, E13 사이드카와 같은 이유).
- variant(최대 3편) **각각** 플랜 하나. v3 오버라이드의 '첫 variant 한정'과 다르다 —
  오버라이드는 사람이 그 한 편을 고친 것이고, 스타일 플랜은 편마다의 연출이다.
- 게이트: **CLI `--style-compose` (기본 미지정 = 단계 자체가 없음 = 종전과 동일,
  회귀 0).** E11 `--transcribe-backend` 와 같은 규약 — 미지정 실행은 체크포인트를
  쓰지도 읽지도 않는다. 오케스트레이터는 채널 design 키 `style_compose` 를 이
  플래그로 넘긴다(§10).

## 4. style_plan/v1 스키마 (계약 초안)

v3 어휘의 부분집합 + design 부분집합. **좌표는 전부 원본 절대초(source_time_sec)
앵커** — 이후 어떤 타임라인 변형(편집실 구간 수정 포함)에도 v3 와 같은 배치 규칙
(`place_anchored_*`, 슬롭 ±0.5s, 고아 드롭+로그)으로 견딘다.

```json
{
  "schema": "style_plan/v1",
  "texts":  [ { "text": "쿵!", "source_time_sec": 743.2, "duration_sec": 1.2,
                "x": 0.7, "y": 0.25, "size": 96, "color": "#FFDD00",
                "stroke": "dark", "fx": "pop", "rotate": -8,
                "reason": "문이 넘어지는 순간 — 타격감" } ],
  "subtitle_styles": [ { "source_time_sec": 745.0,
                         "style": { "size": 78, "color": "#FF4444" },
                         "reason": "핵심 대사 강조" } ],
  "images": [ { "sticker": "arrow_red_down", "source_time_sec": 748.0,
                "duration_sec": 1.5, "x": 0.55, "y": 0.30, "w": 0.2,
                "layer": 0, "rotate": 0, "reason": "시선 유도" } ],
  "title_segments": [ { "text": "이게 되네?\n반전 주의", "from_anchor": 743.0,
                        "to_anchor": 756.0 } ],
  "tts": [ { "source_time_sec": 743.0, "voice": "ko_male_low", "speed": "slow",
             "reason": "진지한 회상 톤" } ],
  "design": { "video_speed": 1.1, "title_rotate": -3.0 },
  "notes": "전체 연출 컨셉 한 줄"
}
```

- `texts`/`images` 는 v3 `TEXT_KEYS`/`IMAGE_KEYS` 그대로 + `reason`(플랜 전용,
  적용 시 제거 — 검수 카드·run_log 표시용). 모르는 키 즉시 거절(v3 검증기 재사용).
- `images.sticker` 는 **번들 스티커 id 만**(§7). 임의 경로 금지 — 엔진이 스토리지
  자격을 갖지 않는 현행 규율 그대로, AI 에게도 파일 시스템을 열지 않는다. 적용 시
  run_dir `style_assets/` 로 복사해 v3 `file`(run_dir 상대) 계약으로 변환 —
  이렇게 하면 배치·렌더·편집실 재렌더가 기존 코드 그대로다.
- `subtitle_styles` 는 v3 subtitles 와 달리 **텍스트를 싣지 않는다** — 기존 자막
  줄에 스타일만 얹는 패치다. 매칭은 앵커가 그 자막 cue 의 원본 구간 안이면 적중,
  매칭 실패는 드롭+로그. 키는 F-407/410 넷(size·y·color·rotate)뿐.
- `title_segments` 는 앵커 쌍(from/to)으로 받고, 엔진이 확정 타임라인에서 편집본
  시각으로 변환해 E8 `title.segments` 계약(겹침 거절·최대 20개·창 밖=제목 없음)으로
  넘긴다. 편집실에 보이는 어휘는 E8 그대로 — 계약이 늘지 않는다.
- `tts` 는 cue 신원 = source_time_sec(v2 규약)으로 기존 cue 를 찾아 voice/speed 만
  바꾼다. **불변 라벨만 허용**(`ko_female`~`chat_*`, `very_slow`~`very_fast`) —
  `elevenlabs:` 접두사는 계정 종속(E12)이라 AI 산출에 금지, `_normalize_storyline_tts_cues`
  화이트리스트("LLM 산 cue")가 이미 지키는 경계와 같다. 문구(text)는 못 바꾼다.
- `design` 개방 키는 **편 단위 연출로 의미가 있는 것만**: `video_speed`(0.8~2.0)·
  `title_rotate`·`tts_rotate`(-180~180)·`title_box(2)`·`title_box_color(2)`·
  `title_bold(2)`. 밴드 레이아웃(aspect_ratio·video_width·video_y)·폰트·자막
  색 체계·플랫폼 표기는 **비개방**(채널 정체성).
- 항목 하드캡(과연출 방지): texts ≤ 8 · images ≤ 4 · subtitle_styles ≤ 10 ·
  title_segments ≤ 5 · tts 는 기존 cue 수 이내. 초과는 앞에서부터 자르고 로그.

## 5. 적용·병합 규칙 — 우선순위 한 줄

```
편집실 edit_overrides  >  채널 design 플래그(명시 키)  >  AI 스타일 플랜  >  코드 기본값
```

- **사람이 이긴다**: 편집실이 어떤 카테고리(texts·images·subtitles·title·tts·design
  키)를 보내면 그 카테고리의 AI 항목은 **전량 진다** — v3 '전량 교체' 규약과 정합.
  항목 단위 병합은 안 한다(사람이 지운 연출이 살아 돌아오면 안 된다).
- **채널 정체성이 이긴다**: CLI 로 명시된 design 키는 AI 가 못 덮는다. 구현 메모:
  DesignConfig 는 frozen 이고 기본값 비교로는 명시 여부를 알 수 없으므로(None 기본
  키), cli 가 **명시 키 집합**을 PipelineInput 으로 넘겨야 한다.
- 적용 지점(엔진 변경 최소):
  - tts voice/speed → resources 합성 직전 cue 병합 (편집실 tts 오버라이드가 있으면
    그 카테고리 스킵). E12 합성 캐시 키에 voice/speed 가 이미 들어 있어 재렌더 요금
    구조는 그대로.
  - subtitle_styles → 재매핑 뒤 `final_segments` 에 앵커 매칭으로 style 부여, 결과는
    `subtitle_segments.json` 에 **v3 와 동일한 style 키**로 저장(캐시 규약 'style 은
    남는다' 그대로 — 새 키를 이 파일에 추가하지 않는다, §9-3).
  - texts/images/title_segments → 렌더 인풋 조립 시 v3 와 **같은 배치 함수**
    (`place_anchored_texts`/`place_anchored_images` — 시그니처 불변, §9-2)로.
  - design → 렌더 직전 `dataclasses.replace` 로 파생 DesignConfig.

## 6. LLM 실행 설계

- **모델: Flash 최신** — 스토리 구성과 같은 축(창작 조합, 정밀 분석 아님). 아래
  모델 사용 정책을 따른다.

### 모델 사용 정책 (사용자 결정 8/23 — E15 와 같이 나가는 정리)

**원칙: Pro 는 영상을 실제로 보는 호출 = `analyze_chunk`(청크 영상 분석) 하나뿐.
나머지 텍스트-온리 호출은 전부 Flash 최신(`gemini-3.6-flash`).**

코드 실측(2026-08-23) — 지금 Pro(`model_name`)를 쓰는 곳이 영상 분석 외 2곳 더 있다:

| 호출 | 단계 | 지금 | 앞으로 |
|------|------|------|--------|
| `analyze_chunk` — 청크 영상 분석 | gemini | Pro | **Pro (유일)** |
| `extract_relationships` — 후보 관계 추출 | graph | Pro | **Flash 로 전환** |
| `research_work` / `_search_with_grounding` — 작품 리서치(구글 검색 그라운딩) | research | Pro | **Flash 로 전환** |
| `analyze_video_intent` — 스크리닝 | story 계열 | Flash | Flash |
| `compose_story_with_context` — 스토리 구성 | story | Flash | Flash |
| `shorten_text` — 제목 단축·TTS fit 재작성 | story·resources | Flash | Flash |
| `choose_beat_drops` — 비트 컷 선택 | story 후처리 | Flash | Flash |
| 스타일 구성 (E15 신설) | style | — | Flash |

- 구현은 `gemini_client.py`·`work_researcher.py` 의 `model_name` → `flash_model_name`
  참조 교체 — 분기 없이 참조만 바꾼다. `GEMINI_MODEL_NAME` 은 이후 **영상 분석 전용**
  노브가 된다. CLAUDE.md 모델 표(Pro=정밀 분석 / Flash=스크리닝·스토리)도
  **Pro=영상 분석 전용 / Flash=그 외 전부**로 갱신.
- **모델명 정본 확인(§13-1 해소)**: `gemini-3.6-flash` 는 이미 main 에 커밋돼 있다
  (5178b11) — auto_update 로 전 노드가 이 기본값으로 돈다. CLAUDE.md 의
  "이 머신 로컬 변경·미푸시" 각주가 낡았으니 같은 커밋에서 지운다.
- 곁다리: `GeminiConfig` dataclass 기본값이 `model_name="gemini-3.5-flash"` 로
  남아 있다(금지 모델·팩토리가 늘 덮어써서 무해했지만) — env 기본값과 같은 값으로
  정리한다.
- **검증**: ① 리서치는 google_search 그라운딩 경로라 Flash 전환 후 그라운딩 동작·
  출처 품질을 실측 1회 확인(안 되면 리서치만 Pro 잔류 + 사유 기록). ② 관계 추출은
  같은 에피소드 Pro/Flash A/B 1회 — edge 수·품질이 크게 무너지면 보고 후 결정.
  ③ 전환분은 run_log `steps[].models` (provenance 기록)로 편별 추적 가능.
- 입력: storyline(클립·role·pacing_note·character_focus) · 확정 타임라인(클립별
  원본 구간↔편집 시각 표) · 선택 구간 전사(대사+시각) · 청크 분석의 감정/하이라이트
  신호 · tts cue 목록 · editorial(권리사 지침 — avoid 는 하드 필터로도) · 채널 스타일
  프로파일(§13) · 스티커 manifest 요약(§7).
- 출력: style_plan/v1 JSON. JSON 강제·재시도·max_tokens 절단 처리는 compose_story
  패턴 재사용.
- 호출 수: variant 당 1회(+검증 실패 재시도 ≤ 2). Flash 라 비용·시간 영향 미미.
- 반려 루프: `--reject-note` 가 story 처럼 style 프롬프트에도 주입된다 — "과한 연출"
  반려가 다음 판에 반영되는 통로.

## 7. 스티커 라이브러리 (신규 자산)

- `assets/stickers/` 번들 + `manifest.json`: `{ id, file, tags, desc, 권장 w }`.
  프롬프트에는 manifest 요약만 들어가고 산출은 id 만 허용 — 없는 id 는 그 항목
  드롭+로그(스티커 하나 때문에 편이 죽으면 안 된다 — E13 keyterms 필터와 같은 결).
- 초기 세트는 범용 연출(화살표·동그라미·집중선·땀·물음표·느낌표 류) 10~20개.
  **소싱·라이선스 확정 필요**(§13) — 권리사 콘텐츠 위에 얹는 자산이라 상용 가능
  라이선스가 조건.
- 폰트 REMOTE_FONTS 처럼 원격 다운로드는 하지 않는다 — 레포 번들(용량 작음)이
  단순하고 6대 auto_update 로 같이 배포된다.

## 8. 검증·기록·실패 처리

- 코드 검증: v3 검증기 전면 재사용(모르는 키·범위 밖 즉시 거절) + 앵커가 선택 클립
  구간 밖이면 드롭+로그(배치 규칙과 동일). 검증 실패 재시도 후에도 플랜 전체가
  불량이면 **스타일 없이 진행 + stdout·run_log 명시** — 연출은 부가물이라 본편
  발행을 막지 않되, 조용한 대체 금지 원칙대로 크게 남긴다.
- 겹침 가드(코드): texts/images 가 메인 자막 밴드(`pipeline._video_band_bottom`
  파생 y 영역)와 겹치면 **경고 로그**(거절 아님 — 연출 자유). 제목 창 겹침은 E8
  검증이 이미 거절한다.
- run_log `steps[{step:"style"}]`: 모델·항목 수·드롭 수·하드캡 절단 수·항목별
  reason 요약. 검수 카드 노출은 ves 몫(§10).
- 회귀 가드: `tests/test_e15_style_compose.py` — ① `--style-compose` 미지정이면
  필터그래프·subtitle_segments.json·cue 가 종전과 문자열/수치 동일(회귀 0),
  ② 우선순위(편집실>채널>AI) 카테고리별, ③ 앵커 변환·고아 드롭, ④ 스티커 id 해석.

## 9. 현지화(vlp) 충돌 회피 — 제약 조건 ★

이관 기획이 아니다. 다른 세션(vlp·JP 편집실 E5/E6/E9 진행 중)과 **부딪히지 않기
위한 규칙**만 박는다:

1. **JP 파이프라인 런은 게이트 오프가 기본.** `shorts_jp_localized` 체인
   (`show_title_overlay=False`·`include_tts_audio=False`)에는 오케스트레이터가
   `--style-compose` 를 넘기지 않는다. 이유: texts[]·스티커·자막 강조는 **한국어
   기준으로 번인**되는데 vlp 는 제목·자막·TTS 만 일본어로 교체한다 — 번인된 한국어
   연출 텍스트는 vlp 가 지울 수 없다. 배속(video_speed)도 `tts_subtitles.ass`
   (현지화 타이밍 원료) 좌표를 움직여 vlp scene_rerender 와 좌표 합의가 선행돼야
   한다. JP 개방은 현지화 세션과 계약 합의 후 별도 건.
2. **공유 함수 시그니처 불변.** vlp 세션이 같은 시기에 ai-video 의
   `--from-step render` 경로·`place_anchored_*`·`edit_overrides.py` 를 읽고 있다
   (E6-4 이미지 오버레이 선확인 항목). E15 구현은 이 함수들에 **추가만** 하고
   시그니처·기존 동작을 바꾸지 않는다. 충돌 나기 쉬운 파일(edit_overrides.py·
   renderer.py)의 리팩터링 금지.
3. **파일 계약 동결.** `subtitle_segments.json` 에는 v3 와 동일한 키만 쓴다(E5 가
   이 파일의 style 을 그대로 소비 — 새 키를 넣으면 vlp 병합 코드와 합의 필요).
   `edit_plan.json`·`tts_subtitles.ass` 산출 모양도 불변(등급 J convert 의 원료).
   AI 플랜 자체 정보는 전부 `checkpoint_style.json` 사이드카에만.
4. **scene_rerender 재개 안전.** vlp 가 ai-video 를 `--from-step render` 로 다시
   돌릴 때: JP 런은 게이트 오프라 checkpoint_style 자체가 없다 = 경로 무변화.
   KR 런을 나중에 JP 로 전환하는 흐름이 생기면 그때 checkpoint_style 처리 규약을
   현지화 세션과 정한다(지금은 그런 흐름이 없다).
5. **배포 독립.** main 머지 = 6대 auto_update 이므로, E15 는 게이트 뒤에서만 도는
   상태로 머지한다(vlp 세션 배포 타이밍과 무관하게 안전).

## 10. 오케스트레이터 파트 (별도 커밋 계열)

- 어댑터: `CHANNEL_DESIGN_FLAGS` 에 `style_compose` 추가 → `--style-compose`.
  개방은 **엔진 전 노드 배포(last_seen) 확인 후 ops_config 게이트** — E7·E10 과
  같은 롤아웃 규율.
- 검수 카드: run_log `steps[{step:"style"}]` 요약(항목 수 + reason 목록) 표시 —
  검수자가 "왜 이 스티커가 떴는지"를 카드에서 본다.
- 편집실: AI 플랜이 적용된 상태가 editor_assets 초기값으로 이미 보인다
  (subtitle_segments.json 의 style·배치된 texts/images 가 기존 통로로 내려간다) —
  0070 editor_baselines(AI 원안 스냅샷) 규약 덕에 "AI 연출 대비 사람이 고친 것"
  구분도 유지된다. 편집실이 고치면 §5 규칙대로 그 카테고리는 사람 것으로 전량 교체.
- 스티커를 편집실 이미지 탭에서도 고르게 하려면 manifest 를 대시보드로 내려보내는
  통로가 필요 — 후속(이번 범위 밖).

## 11. 롤아웃 순서

1. ai-video: 스키마·검증·배치 + 게이트 + 테스트 → main 머지 → 전 노드 확인.
2. 스티커 초기 세트 번들(라이선스 확정 후).
3. ves: 어댑터 플래그 + ops_config 게이트 + 검수 카드 표시.
4. KR 채널 1곳 파일럿 → 실측(연출 적중/과연출 반려율·렌더 시간) → 확대.
   JP 채널은 오프 유지(§9-1).

## 12. 실측 계획

- 합성 run(F-408/410 방식 재사용): 앵커 변환·레이어·회전·배속 프레임 캡처 확인.
- 실물 1편: 스타일 on/off 이중 렌더(`--from-step render` 재렌더 = 깨끗한 A/B,
  loudness A/B 패턴) — 편집실에서 나란히 검수.
- 미지정 회귀 0: `--diff` 성 대조(E11 도구 패턴)로 종전 산출과 바이트 대조.

## 13. 발주 전 확정할 것 (열린 질문)

~~1. Flash 모델명 정본~~ — **해소(8/23)**: `gemini-3.6-flash` 가 main 에 이미
커밋돼 있음을 코드 실측으로 확인, 모델 정책은 §6 으로 확정(Pro=영상 분석 전용).

1. **스티커 초기 세트** — 소싱(자체 제작? 무료 라이선스팩?)·수량·목록. 라이선스
   확인 없이는 번들 금지.
2. **채널 스타일 프로파일 어휘** — 초기엔 연출 강도(`low/mid/high`) 한 키만
   제안(ops_config → design 키 `style_profile`). 세분화(이모지 허용·색 취향)는
   실측 후.
3. **subtitle_styles 의 y·rotate 개방 여부** — 강조가 size·color 만으로 충분하면
   위치·회전은 사람 전용으로 남기는 쪽이 안전(자막 가독성). 파일럿에서 결정 제안.
