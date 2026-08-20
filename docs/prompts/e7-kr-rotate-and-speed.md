# E7 — KR 편집실: 제목·TTS 회전 + 영상 배속 (ai-video 엔진 발주서)

ai-video(rht-22/ai-video) 엔진 세션용 작업 프롬프트. 기준: 배포 82654ef(전 노드
last_seen 동일). 사용자 요청(8/20): "제목과 tts 도 회전이 가능하게, 영상 배속도
0.8~2.0 으로 설정할 수 있게". 자막 줄 회전(subtitles[].style.rotate, F-410)과
이미지 회전(images[].rotate)은 이미 있다 — 이번엔 **디자인 레벨**(이 편 전체)의
제목·TTS 회전과, 영상 배속이다. TTS **속도**는 발주 대상이 아니다(cue.speed 가
edit_overrides/v2 원계약부터 합성에 적용됨 — 편집실이 8/20 부터 내보낸다).

## 컨텍스트 (먼저 읽기)

- `app/modules/renderer.py` `_build_filtergraph`: 제목 drawtext(:1116 부근,
  split_text_smart 줄별), TTS 자막 drawtext 경로(:1382 부근 주석 — voice/speed 는
  합성 시점 적용), 클립 스케일·패드 체인(:977-1005 — crop_timeline(얼굴 추종) →
  scale=W:scaled_h:force_original_aspect_ratio=increase → crop → pad), concat(:1005-).
- `app/cli.py` --design-* 플래그 → design 객체. 오케스트레이터 짝:
  ves-orchestrator `ves/adapters/aivideo.py` CHANNEL_DESIGN_FLAGS(1:1 미러 규율 —
  모르는 키 즉시 실패). 회전 부호 규약: **시계방향 양수, -180~180**
  (subtitles[].style.rotate·images[].rotate 와 동일 — v3 문서).

## E7-1. 제목·TTS 자막 회전 (중)

- 디자인 키 신설: `title_rotate` · `tts_rotate` (도, -180~180, 시계방향 양수, 0=기본).
  CLI `--design-title-rotate` / `--design-tts-rotate`. 범위 밖·비숫자는 즉시 실패
  (조용한 무시 금지 — v3 검증과 동일 원칙).
- drawtext 는 회전이 없다 — 그 텍스트 블록만 **투명 캔버스에 drawtext → rotate
  필터(rotate=θ:c=none@0.0, 시계방향이면 양수 라디안) → overlay** 로 전환하라.
  제목은 줄 묶음 전체를 한 캔버스에(줄별 개별 회전 아님 — 편집실 도구도 묶음 회전),
  TTS 자막도 같은 방식. `rotate=0`(미지정) 경로는 종전 drawtext 그대로 둔다
  (성능·회귀 없음).
- 회전 원점 = 텍스트 블록 중심(이미지 rotate 와 동일 규약 — 편집실 CSS 미리보기와
  일치해야 한다).
- platform 표기·work 로고 등 다른 drawtext 는 손대지 않는다.

## E7-2. 영상 배속 (중~대 — 타임라인 정합이 본체)

- 디자인 키 신설: `video_speed` (0.8~2.0, 1=기본, 소수 허용). CLI
  `--design-video-speed`. 범위 밖 즉시 실패.
- 렌더: 클립 필터 체인에 `setpts=PTS/S`, 오디오 `atempo=S`(0.8~2.0 은 atempo
  단일 필터 범위 안이다). 얼굴 추종 crop_timeline 의 시각 표현식(t 기준)이
  배속 후 시간축과 어긋나지 않는지 확인하라(크롭이 원본 t 로 계산되면 setpts
  **앞**에 crop 이 오면 된다 — 지금 체인 순서 그대로인지 실측).
- **타임라인 정합(멈춤 지점 후보)**: 출력 길이가 1/S 로 줄면
  자막(subtitle_segments 출력 시각)·TTS cue 창·이미지 오버레이 창·쇼츠 상한
  (59.7s)·edit_plan 길이 검증이 전부 함께 움직여야 한다. 구현 지점을 정하고
  (A: 최종 타임라인 확정 후 출력 시각 전부 ×1/S, B: 클립 길이를 계획 단계에서
  미리 나눔) 근거와 함께 보고하라. 자막·TTS 가 화면과 어긋나면 그 판은 폐기다.
- TTS 내레이션 **오디오는 배속하지 않는다** — 내레이션 속도는 cue.speed(합성
  시점)가 담당한다. 배속은 원본 영상·현장음에만.
- 검증: S=0.8·1.25·2.0 실측 각 1회 — 총길이, 자막 싱크(첫/끝 줄), TTS 창 위치,
  상한 검증 통과 여부.

## 완료 보고에 명시할 것

커밋 sha · 키 이름/검증 범위 그대로 · E7-2 의 구현 지점(A/B)과 크롭 시간축 확인
결과. 오케스트레이터 파트(어댑터 CHANNEL_DESIGN_FLAGS 추가 — brain 미러는 채널
템플릿 개방 시점에, 편집실 UI·플래그 개방)는 전 노드 last_seen_sha 확인 후
ves-orchestrator 쪽에서 잇는다.

시작해라. 먼저 renderer.py 의 제목/TTS drawtext 경로와 클립 체인, cli.py 의
--design-* 처리부를 읽고 계약을 확정한 뒤 구현해라.
