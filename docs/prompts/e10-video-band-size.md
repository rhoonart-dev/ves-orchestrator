# E10 — 영상 밴드 가로 크기 (design.video_width) 구현

ves-orchestrator 발주서(docs/prompts/e10-video-band-size.md)에 따른 엔진 작업이다. 기준: bd58078(E8 머지본). 사용자 요청(8/21): "쇼츠 화면 크기 안에서 영상의 비율 및 크기를 조절할 수 있게". 비율(aspect_ratio)·세로 위치(video_y)는 이미 있다 — 이번엔 **밴드의 가로 크기**다. 지금 렌더는 폭이 항상 W(1080) 고정이라(_build_filtergraph `scaled_w = W`) 밴드 직사각형의 '크기'를 줄일 방법이 없다.

## 컨텍스트 (먼저 읽기)

- `app/modules/renderer.py` `_build_filtergraph` [2]~[3] (:985-1046): `scaled_w = W` · `scaled_h = int(W * r_h / r_w)` · `overlay_y`(video_y/중앙 클램프) · 클립 체인 `crop_timeline → scale=scaled_w:scaled_h:force_original_aspect_ratio=increase → setsar=1 → crop=W:scaled_h → pad=W:H:0:overlay_y`.
- [5] 제목 동적 배치(:1131-1143 — overlay_y 기준), [5.5] 플랫폼 표기(:1258-1267 — "영상영역 왼쪽 상단" 계약), 작품명/로고 클램프(:1310-1316 — overlay_y+scaled_h 기준).
- `app/cli.py` `_CLI_TO_DESIGN_FIELD` · `_build_design_config`(E7 범위 검증 패턴).
- ⚠ `app/config.py` DesignConfig 에 **레거시 `video_width: int = 800`** 이 이미 있다(렌더러는 안 읽음, `app/api/videoApi.py` 만 씀 — width 기본 800). 렌더러가 이 필드를 그대로 읽기 시작하면 **아무 플래그도 안 준 기존 채널 전부가 800px 로 줄어든다.** 권고: DesignConfig 기본값을 1080 으로 바꾸고 videoApi 의 `video_config.get("width", 800)` 기본 인자도 1080 으로 맞춘 뒤, videoApi 경로의 실사용 여부를 확인해 보고하라. 다른 처리를 택하면 근거와 함께 보고.
- 오케스트레이터 짝: ves-orchestrator 어댑터에 `video_width → --design-video-width` 미러 완료(1:1 규율). 편집실 미리보기도 아래 수식 그대로 배선 완료 — **이 계약과 다르게 구현하면 미리보기가 거짓말을 하게 된다**(8/21 aspect_ratio 기본값 16:9/1:1 어긋남 사고의 재발). 계약을 바꿔야 한다고 판단되면 구현하지 말고 완료 보고에 사유를 남겨라.

## 작업 (중)

- 디자인 키(레거시 필드 재정의): `video_width` (캔버스 px, **320~1080**, 미지정/1080 = 종전과 동일한 꽉 찬 폭). CLI `--design-video-width`. 범위 밖·비숫자는 즉시 실패(E7 검증 패턴 — CLI 와 렌더 경계 양쪽). 홀수는 짝수 보정(scaled_w -= scaled_w % 2).
- 렌더 수식(편집실 미리보기와 합의된 계약):
  - `scaled_w = video_width` (기본 1080)
  - `scaled_h = int(scaled_w * r_h / r_w)` — **밴드 폭 기준**이다. 화면비는 밴드 직사각형의 모양을 정의하고, 크기는 video_width 하나로 정해진다.
  - `pad_x = (W - scaled_w) // 2` — **가로 중앙**. `pad=W:H:{pad_x}:{overlay_y}`.
  - overlay_y 클램프(`H - scaled_h`)·세로 중앙 기본값은 종전 그대로(scaled_h 만 작아짐).
  - 클립 체인의 cover 목표도 `scale=scaled_w:scaled_h:…increase → crop=scaled_w:scaled_h` 로 폭을 따라간다(얼굴 추종 crop_timeline 은 체인 앞이라 무영향).
- 따라 움직여야 하는 것들(계약이 "영상영역 기준"인 것):
  - 플랫폼 표기: left 앵커 `pf_x = pad_x + platform_x`, right 앵커는 영상영역 오른쪽 가장자리(`pad_x + scaled_w`) 기준으로 — 캔버스 모서리가 아니라 밴드 모서리를 따라야 aspect_ratio·video_width 를 바꿔도 표기가 영상 위에 남는다(기존 계약 주석).
  - 제목 동적 배치·작품명/로고 클램프는 overlay_y·scaled_h 파생이라 수식 변경 없음 — 테스트로만 확인.
- 하지 않는 것: 가로 위치(video_x)는 이번 범위 밖(항상 중앙). brain 채널 템플릿 개방도 범위 밖.

## 검증

- 기존 테스트 전체 통과 + 신규 테스트(test_e7_rotate_speed.py·test_platform_mark.py 의 필터그래프 문자열 검증 패턴을 따라라):
  - `--design-video-width` 미지정: 종전과 **동일한 필터그래프**(회귀 0 — 기존 채널 전부).
  - 800×16:9 · 800×1:1 · 320(하한) · 801(홀수→800): scale/crop/pad 문자열, pad_x 중앙, overlay_y 클램프.
  - 플랫폼 표기 left/right 가 pad_x 를 따라오는지.
  - 범위 밖(319·1081·비숫자) 즉시 실패 — CLI 와 렌더 경계 양쪽.
- ffmpeg 가 이 컨테이너에 있으면 합성 입력(testsrc)으로 실렌더 1회 스모크, 없으면 문자열 검증만으로 간다(있고 없음을 보고에 명시).

## 세션 운영

- 이 세션의 outcome 브랜치(claude/e10-video-band-width)로 커밋·푸시해라. main 머지는 사람이 한다. PR 은 만들지 마라.
- 커밋 메시지는 이 저장소 관례(한국어 서술 + 검증 결과 명시)를 따르되 모델명은 넣지 마라.
- 마지막 메시지에 완료 보고를 남겨라: 커밋 sha · 레거시 video_width 기본값 충돌의 처리와 근거(videoApi 실사용 여부 포함) · 신규/기존 테스트 결과 · ffmpeg 스모크 여부와 결과 · 계약에서 벗어난 점(있다면).

시작해라. 먼저 renderer.py 의 [2]~[3] 클립 체인과 [5.5] 플랫폼 표기, cli.py 의 --design-* 처리부, config.py 의 레거시 필드를 읽고 계약을 확정한 뒤 구현해라.
