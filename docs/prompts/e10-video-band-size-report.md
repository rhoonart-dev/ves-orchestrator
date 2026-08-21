# E10 — 영상 밴드 가로 크기 : 엔진 완료 보고 (2026-08-21)

ai-video 엔진 세션 → ves-orchestrator. 발주서: e10-video-band-size.md (세션 프롬프트로
전달분 — 이 레포 main 에는 아직 미푸시 상태라 본 보고가 참조용 기록을 겸한다).
기준 bd58078(E8 머지본), 작업 브랜치 `claude/e10-video-band-width` (main 머지는 사람 몫).

## 커밋

| sha | 내용 |
|-----|------|
| `f4bb16b` | E10 본편 — video_width 키·`--design-video-width`·렌더 수식·플랫폼 표기 밴드 앵커 |
| `6c28d9c` | 후속 1 — 메인 자막 margin_v 밴드 폭 반영 (`_compute_subtitle_margin_v`) |
| `4bd8528` | 후속 2 — 메인 자막 margin_v 에 video_y 반영 |
| `ac67a90` | 후속 3 — TTS 자막 margin_v 밴드 델타 앵커 (`_compute_tts_margin_v`) |
| `c2ed100` | CLAUDE.md 에 E10 계약 정리 |

## 계약 이행 — 발주 수식 그대로, 이탈 없음

- `scaled_w = video_width`(320~1080, 기본 1080 = 종전 꽉 찬 폭) ·
  `scaled_h = int(scaled_w * r_h / r_w)`(밴드 폭 기준) · `pad_x = (W - scaled_w) // 2`
  가로 중앙 · overlay_y 클램프/세로 중앙 종전 그대로 · 홀수 짝수 보정 ·
  cover 체인 `scale=…increase → crop=scaled_w:scaled_h`(crop_timeline 무영향).
- 범위 밖·비숫자는 CLI(`_build_design_config`, E7 패턴)와 렌더 경계(`_build_filtergraph`,
  `int(str(…))` 라 800.5 도 거절) 양쪽 즉시 실패.
- 플랫폼 표기: left `pad_x + platform_x`, right 는 밴드 오른쪽 가장자리 앵커 —
  right 오프셋을 "캔버스 오른쪽에서의 여백"으로 환산해 기본 폭에서 종전 필터그래프
  문자열이 바이트 단위로 유지된다.
- video_x·brain 채널 템플릿 개방은 발주대로 범위 밖.

## 레거시 video_width 기본값 충돌 — 권고안대로

DesignConfig 기본 800→**1080**, videoApi `video_config.get("width", 800)`→**1080**.
videoApi 실사용: `app/main.py` 가 라우터를 등록해 도달 가능하지만 레포 내 호출부가
없고, 렌더러가 안 읽는 레거시 필드(video_height·video_y_pos)를 여전히 쓰는 미정비
경로다. 주의 — API 호출자가 명시적으로 `width: 800` 을 보내고 있었다면 이제 실제로
800px 밴드가 된다(E10 의 의도된 의미 부여).

## 발주 범위 밖 후속 3건 (사용자 지시, 같은 세션)

자막 계열이 캔버스 기준 고정이라 밴드를 줄이거나(video_width) 올리면(video_y) 옛
밴드 위치에 남던 것을 정리했다. **편집실 미리보기가 자막·TTS 위치까지 그린다면
아래 수식을 미러해야 한다**:

- 메인 자막 MarginV = `H − 밴드 하단 + 10` (항상 밴드 하단 10px 위).
  밴드 하단 = `pipeline._video_band_bottom`(렌더러 [2]와 같은 수식 — video_width·
  video_y·짝수 보정 반영)이 단일 소스.
- TTS 자막 MarginV = `tts_line_y_margin + (종전 기하 밴드 하단 − 실제 밴드 하단)`,
  0 하한 — 사용자 노브를 유지하는 **델타 앵커**(밴드 하단으로부터의 오프셋 상수).
  video_width·video_y 미지정이면 델타 0 = 종전 값 그대로.

## 검증

- 테스트: 기존 488 + 신규 30(`tests/test_e10_video_band_width.py`) = **518 전체 통과**.
- 회귀 0 직접 증명: bd58078 렌더러를 로드해 video_width 미지정 6개 구성(기본·16:9·
  13:9+video_y+플랫폼·right 앵커·회전+배속·9:16)의 필터그래프 문자열 대조 — 완전 동일.
- ffmpeg 실렌더 스모크: 컨테이너에 ffmpeg 가 없어 apt 설치 후 진행. 합성 입력
  (testsrc·color)으로 기본·800×16:9 렌더 성공(출력 1080×1920), 픽셀 실측 밴드
  x=140~939(pad_x=140)·y=735~1184(overlay_y=735) 일치.
- 작품명/로고 클램프 실렌더 실측(문자열 테스트 외 추가 확인): 로고가 밴드 하단
  이동(1262↔1185)을 픽셀 단위로 추종(y 1526↔1487), 작품명 work_title_y=1400 이
  800×9:16 밴드 하단+20(1691)으로 밀림 — "영상영역 기준" 계약대로.

## 오케스트레이터 후속 확인 사항

- 어댑터 `video_width → --design-video-width` 미러는 발주 시점 완료로 안다 — 범위
  (320~1080)·홀수 보정 규약이 엔진과 같은지만 재확인.
- 편집실 미리보기: 밴드 수식은 합의 계약 그대로 구현했다. 자막·TTS 위치 미리보기가
  있다면 위 margin 수식(후속 3건) 미러 여부 결정 필요.
- 엔진 CLAUDE.md(`c2ed100`)에 같은 계약을 기록해 뒀다 — 이후 엔진 세션의 기준 문서.
