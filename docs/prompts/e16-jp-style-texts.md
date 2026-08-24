# E16 — JP 화면 텍스트 현지화: 효과 텍스트·시간대별 제목 : vlp 엔진 발주서

vlp(video-localization-project) 엔진 세션용 작업 프롬프트. 기준: `5f8c3e3`(main).
짝 변경: ai-video E15 스타일 구성(머지됨 `80dc5a6`) · 관제 `style_compose` 채널 스위치(`9bd2164`).

## 한 줄

**JP 재렌더가 화면에 그리는 한국어 글자를 일본어로 바꾼다.** 지금은 `texts[]`(효과 텍스트)가
한국어 그대로 번인되고, E15 가 그 소스를 하나 더 얹었다(AI 연출).

## 왜 지금인가 — 이미 있는 구멍 + 새 소스

**이건 E15 가 만든 문제가 아니다.** `localize_run.py:694 visual_only_overrides` 가 편집실
`texts`·`images` 를 JP 재렌더로 넘기는데, 그 주석이 스스로 적고 있다 — "안 넘기면 사람이
올린 이미지·문구가 일본어판에서 조용히 사라진다". 넘기는 것은 맞지만 **번역을 안 한다**.
즉 편집실에서 "쿵!" 을 넣은 편은 지금도 일본어판에 한국어로 박힌다.

E15(2026-08-23)가 여기에 두 번째 소스를 더했다: 스토리 구성 뒤 AI 가 편 단위 연출을
`checkpoint_style.json` 에 저장하고, 렌더가 그것으로 `texts.ass`·시간대별 제목을 그린다.
`--from-step render` 재개에서는 **LLM 재호출 없이 그 체크포인트를 그대로 재적용**한다 —
즉 vlp 의 L4 재렌더도 자동으로 그 연출을 다시 그린다.

운영 조치(2026-08-24): SHOTCONE 은 이 발주가 끝날 때까지 `style_compose` 를 **꺼 뒀다**
(채널 design `_note` 에 사유 기재). KR 19 채널은 켜져 있다.

## 무엇을 번역하고 무엇을 두는가

측정해서 갈랐다 — **언어 중립인 것은 건드리지 마라.**

| 대상 | 어디에 | 번역? | 근거 |
|------|--------|-------|------|
| `texts[].text` | `checkpoint_style.json`(AI) · `edit_overrides.json`(사람) | **필요** | 한국어 문구가 화면에 번인 |
| `title_segments[].text` | `checkpoint_style.json` | **필요** | L4 가 `--no-title-overlay` 를 안 붙여 JP 재렌더에도 제목이 그려진다 |
| `images[]`(스티커) | 위 두 곳 | 불필요 | 그림이다 |
| `subtitle_styles[]` | `checkpoint_style.json` | 불필요 | `size`·`color` 뿐. L3 가 이미 일본어로 바꾼 줄에 얹히므로 **지금도 정상 동작** |
| `tts` 톤(voice/speed) | `checkpoint_style.json` | 불필요 | L3t 가 일본어로 재합성하고 오디오는 체크포인트에서 온다 |

## 계약 — `checkpoint_style.json` (ai-video E15)

읽기만 하면 되는 부분만 적는다. 정본: ai-video `CLAUDE.md`(스타일 구성 단계 계약) ·
`app/modules/style_compose.py`.

```json
{ "schema": "style_plan/v1",
  "texts": [ { "text": "쿵!", "source_time_sec": 743.2, "duration_sec": 1.2,
               "x": 0.7, "y": 0.25, "size": 96, "color": "#FFDD00",
               "stroke": "dark", "fx": "pop", "rotate": -8, "font": "Jalnan" } ],
  "title_segments": [ { "text": "이게 되네?\n반전 주의",
                        "from_anchor": 743.0, "to_anchor": 756.0 } ],
  "subtitle_styles": [ … ], "images": [ … ], "tts": [ … ], "design": { … } }
```

- `text` 는 **줄바꿈 `\n` 포함 60자 이내**(엔진 `TEXT_MAX_CHARS`). 번역이 이 상한을 넘으면
  엔진이 그 판을 거절한다 — L1 프롬프트에 글자수 제약을 명시하고, 넘으면 줄여라.
- `font` 는 번들 4종(`Jalnan`/`JalnanGothic`/`mulmaru`/`Griun`) 화이트리스트다. **일본어
  글리프가 없을 수 있다** — 아래 §폰트 참고. 모르는 폰트명은 엔진이 거절한다.
- 나머지 키(좌표·크기·색·fx·rotate)는 **손대지 마라**. 연출 의도이고 언어와 무관하다.
- 파일이 없으면(=그 채널이 `style_compose` 를 안 켰거나 구 런) **아무것도 하지 않는다** —
  종전과 완전히 동일하게 동작해야 한다(회귀 0).

## 작업

### E16-1. L0 백업에 `checkpoint_style.json` 추가 (필수·선행)

`BACKUP_FILES`(:103)에 `"checkpoint_style.json"` 을 넣는다.

**이게 빠지면 멱등성이 깨진다.** L3 는 항상 `localize_backup_ko/` 의 한국어 원본을 읽어
일본어를 만든다(`l3_apply` :522 주석 "항상 KO 백업 기준으로 교체(멱등)"). 백업에 없으면
두 번째 L3 실행이 **이미 일본어인 텍스트를 다시 번역**한다.

### E16-2. L1 번역 스키마 확장

`l1_translate`(:411) 요청/응답에 항목을 추가한다 — 기존 `segments`·`tts_cues`·`telops`·
`top_title` 과 같은 모양:

```json
"style_texts":  [ { "index": 0, "ko": "쿵!" } ],
"style_titles": [ { "index": 0, "ko": "이게 되네?\n반전 주의" } ]
```

- 응답 정렬 검증도 기존 패턴 그대로(:449~ `len(data["segments"]) != len(segments)` → RuntimeError).
- 입력이 비면 그 키를 아예 안 보낸다 — 프롬프트가 종전과 같아야 연출 없는 편의 번역
  결과가 안 흔들린다.
- 번역 톤은 **효과 텍스트**임을 프롬프트에 명시하라. 대사가 아니라 의성어·감탄·강조라
  직역보다 그 나라 관용 표현이 맞다(`쿵!` → `ドンッ!`). 길이도 화면 물건이라 짧아야 한다.

### E16-3. L3 적용

`l3_apply`(:519) 꼬리에 추가 — 다른 파일들과 **같은 방식**(백업에서 읽어 job 에 쓴다):

1. `backup/checkpoint_style.json` 이 있으면 로드.
2. `texts[i].text` ← `translation["style_texts"][i]["ja"]`,
   `title_segments[i].text` ← `translation["style_titles"][i]["ja"]`.
3. `job/checkpoint_style.json` 으로 쓴다.
4. 한 줄 로그 — `[L3] 연출 텍스트 n건 · 제목 창 m건 일본어 적용`.

### E16-4. 편집실 texts 도 같이 (기존 구멍 수리)

`l4_render`(:760~)가 만드는 `edit_overrides_visual.json` 의 `texts[].text` 도 같은 번역을
태운다. 사람이 넣은 문구와 AI 가 넣은 문구가 **한 화면에서 한쪽만 일본어면** 더 이상하다.

- 좌표계가 다르니 주의: 편집실 `texts` 는 `edit_overrides.json` 에, AI `texts` 는
  `checkpoint_style.json` 에 있다. L1 에 보낼 때 **둘을 한 배열로 합치지 말고** 각각
  `style_texts`·`editor_texts` 로 나눠라(인덱스 정렬이 어긋나면 다른 문구가 들어간다).

### E16-5. 검수 카드 노출

`build_ko_ja_pairs`(:824)에 `style_texts` 항목을 더해 대시보드가 한↔일 대역을 보여 주게
한다 — 다른 항목과 같은 모양(`{idx, ko, ja, start, end}`). 검수자가 "쿵!" 이 무엇으로
바뀌었는지 카드에서 봐야 한다. 40건 상한 규약은 그대로.

## 폰트 (선확인 1건 — 여기서 막히면 보고)

효과 텍스트는 `font` 키가 번들 4종 중 하나이고 **전부 한글 폰트**다. 일본어 가나/한자
글리프가 없으면 두부(□)가 되거나 폴백된다.

- **먼저 실측하라**: 번들 4종에 가나가 있는가(`fc-list`/PIL 로 확인).
- 없으면 선택지 둘 — (a) L3 가 `font` 를 현지화 폰트(`locale_cfg["telop_font"]` 계열)로
  바꿔 쓴다, (b) ai-video 의 `TEXT_FONTS` 화이트리스트에 일본어 폰트를 추가한다(그쪽 변경 필요).
  **(a) 를 먼저 시도**하되, ai-video 화이트리스트에 없는 이름을 넣으면 엔진이 거절하니
  실제 허용값을 확인하고 정하라. (b) 가 필요하다고 판단되면 **멈추고 보고**하라 —
  ai-video 쪽 짝 발주가 필요하다.

## 검증

1. SHOTCONE 실물 1편으로 L0~L5 완주. `texts` 가 있는 편을 골라라(없으면 편집실에서 하나 넣거나
   `checkpoint_style.json` 을 손으로 적어 넣어도 된다 — 측정 대상은 번역·재렌더 경로다).
2. **프레임 캡처**로 확인: 효과 텍스트가 일본어인가 · 두부(□)가 아닌가 · 위치·크기·회전이
   한국어판과 같은가(좌표는 안 건드렸으니 같아야 한다).
3. **멱등성**: 같은 job 에 L3 를 두 번 돌려 `checkpoint_style.json` 이 두 번째에도 같은
   일본어인지(재번역 안 되는지) 확인 — E16-1 이 실제로 먹었는지 보는 시험이다.
4. **회귀 0**: `checkpoint_style.json` 이 **없는** 편으로 한 번 — 번역 프롬프트·산출물·
   완성본이 종전과 동일해야 한다.
5. 스티커·자막 강조는 손대지 않았음을 확인(스티커가 그대로 뜨고, 강조 줄이 일본어 위에 얹힌다).

## 멈춤 시점

- 번들 폰트에 일본어 글리프가 없고 `locale_cfg` 폰트로 바꿔도 엔진 화이트리스트에 막히면
  → 멈추고 보고(ai-video 짝 발주 필요).
- 번역이 60자 상한을 상시 넘겨 엔진이 판을 거절하면 → 수치와 함께 보고.
- L1 프롬프트 확장이 기존 자막·텔롭 번역 품질을 흔들면(대역 비교로 확인) → 멈추고 보고.

## 완료 보고에 명시할 것

배포 sha · `ko_ja_pairs` 확장 필드명 · 폰트 처리 방식((a)/(b) 중 무엇) · 멱등성 시험 결과 ·
회귀 0 확인. 오케스트레이터 후속(SHOTCONE `style_compose` 재개방)이 이 넷에 걸려 있다.

## 되돌리기

이 작업 전체가 실패해도 운영은 지금 상태로 안전하다 — SHOTCONE 은 `style_compose` 가 꺼져
있고, 나머지 JP 채널(LOOPY)은 ai-video 런 자체가 없어 무효과다. 배포 후 SHOTCONE 을 다시
켜는 것은 **채널 design `style_compose: true` 한 줄**(대시보드 채널 템플릿 탭)이다.
