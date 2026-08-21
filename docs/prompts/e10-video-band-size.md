# E10 — 영상 밴드 가로 크기 (design.video_width, ai-video 엔진 발주서)

ai-video(rht-22/ai-video) 엔진 세션용 작업 프롬프트. 기준: bd58078(E8 머지본).
사용자 요청(8/21): "쇼츠 화면 크기 안에서 영상의 비율 및 크기를 조절할 수 있게".
비율(aspect_ratio)·세로 위치(video_y)는 이미 있다 — 이번엔 **밴드의 가로 크기**다.
지금 렌더는 폭이 항상 W(1080) 고정이라(_build_filtergraph `scaled_w = W`) 밴드
직사각형의 '크기'를 줄일 방법이 없다.

## 컨텍스트 (먼저 읽기)

- `app/modules/renderer.py` `_build_filtergraph` [2]~[3] (:985-1046):
  `scaled_w = W` · `scaled_h = int(W * r_h / r_w)` · `overlay_y`(video_y/중앙 클램프) ·
  클립 체인 `crop_timeline → scale=scaled_w:scaled_h:force_original_aspect_ratio=increase
  → setsar=1 → crop=W:scaled_h → pad=W:H:0:overlay_y`.
- [5] 제목 동적 배치(:1131-1143 — overlay_y 기준), [5.5] 플랫폼 표기(:1258-1267 —
  "영상영역 왼쪽 상단" 계약), 작품명/로고 클램프(:1310-1316 — overlay_y+scaled_h 기준).
- `app/cli.py` `_CLI_TO_DESIGN_FIELD` · `_build_design_config`(E7 범위 검증 패턴).
- ⚠ `app/config.py` DesignConfig 에 **레거시 `video_width: int = 800`** 이 이미 있다
  (렌더러는 안 읽음, `app/api/videoApi.py` 만 씀 — width 기본 800). 렌더러가 이 필드를
  그대로 읽기 시작하면 **아무 플래그도 안 준 기존 채널 전부가 800px 로 줄어든다.**
  기본값을 1080 으로 바꾸고 videoApi 쪽 영향(기본 800 인자)을 함께 확정하든지,
  충돌을 피할 다른 처리를 하든지 — 결정과 근거를 완료 보고에 명시하라.
- 오케스트레이터 짝: ves-orchestrator `ves/adapters/aivideo.py` CHANNEL_DESIGN_FLAGS 에
  `video_width → --design-video-width` 미러 완료(1:1 규율). 편집실 미리보기도 아래
  수식 그대로 배선 완료 — **엔진이 이 계약과 다르게 구현하면 미리보기가 또 거짓말을
  하게 된다**(8/21 aspect_ratio 기본값 16:9/1:1 어긋남 사고의 재발). 계약을 바꿔야
  한다면 먼저 알려라.

## 작업 (중)

- 디자인 키 신설(레거시 필드 재정의): `video_width` (캔버스 px, **320~1080**,
  미지정/1080 = 종전과 동일한 꽉 찬 폭). CLI `--design-video-width`. 범위 밖·비숫자는
  즉시 실패(E7 검증 패턴 — CLI 와 렌더 경계 양쪽). 홀수는 짝수 보정(scaled_w -= %2).
- 렌더 수식(편집실 미리보기와 합의된 계약):
  - `scaled_w = video_width` (기본 1080)
  - `scaled_h = int(scaled_w * r_h / r_w)` — **밴드 폭 기준**이다. 화면비는 밴드
    직사각형의 모양을 정의하고, 크기는 video_width 하나로 정해진다.
  - `pad_x = (W - scaled_w) // 2` — **가로 중앙**. `pad=W:H:{pad_x}:{overlay_y}`.
  - overlay_y 클램프(`H - scaled_h`)·세로 중앙 기본값은 종전 그대로(scaled_h 만 작아짐).
  - 클립 체인의 cover 목표도 `scale=scaled_w:scaled_h:…increase → crop=scaled_w:scaled_h`
    로 폭을 따라간다(얼굴 추종 crop_timeline 은 체인 앞이라 무영향).
- 따라 움직여야 하는 것들(계약이 "영상영역 기준"인 것):
  - 플랫폼 표기: left 앵커 `pf_x = pad_x + platform_x`, right 앵커는 영상영역 오른쪽
    가장자리(`pad_x + scaled_w`) 기준으로 — 캔버스 모서리가 아니라 밴드 모서리를
    따라야 aspect_ratio·video_width 를 바꿔도 표기가 영상 위에 남는다(기존 계약 주석).
  - 제목 동적 배치·작품명/로고 클램프는 overlay_y·scaled_h 파생이라 수식 변경 없음 —
    실측으로만 확인.
- 하지 않는 것: 가로 위치(video_x)는 이번 범위 밖(항상 중앙). 채널 템플릿
  (channels.json) 개방은 brain CHANNEL_DESIGN_FLAGS 미러 선행 — 지금은 편집실
  (edit_overrides.design) 경로 전용.

## 검증 (실측)

- `--design-video-width` 미지정: 종전과 **동일한 필터그래프**(회귀 0 — 기존 채널 전부).
- 800 × 16:9 · 800 × 1:1 · 320(하한) 각 1회: 밴드 크기·가로 중앙·세로 중앙/video_y,
  제목이 밴드 바로 위, 작품명이 밴드 바로 아래, 플랫폼 표기 left/right 가 밴드
  모서리를 따라오는지.
- 범위 밖(319·1081·비숫자) 즉시 실패.

## 완료 보고에 명시할 것

커밋 sha · 레거시 video_width 기본값 충돌의 처리와 근거(videoApi 영향 포함) ·
검증 범위 그대로의 실측 결과. 오케스트레이터 파트(어댑터 미러·편집실 UI ⇔ 핸들·
스타일 탭 입력·미리보기 밴드)는 배선 완료 — 전 노드 배포 확인 후 ops_config
`editor_e10=on` 으로 개방한다(그 전까지 대시보드가 신 키를 걷어낸다, H2 이중 안전).

시작해라. 먼저 renderer.py 의 [2]~[3] 클립 체인과 [5.5] 플랫폼 표기, cli.py 의
--design-* 처리부, config.py 의 레거시 필드를 읽고 계약을 확정한 뒤 구현해라.
