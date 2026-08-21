# E8 — 시간대별 제목(타임드 제목) : ai-video 엔진 발주서

ai-video(rht-22/ai-video) 엔진 세션용 작업 프롬프트. 기준: 2a087eb(E7 머지,
전 노드 last_seen 동일). 사용자 요청(8/20): "제목도 시간에 따라 다르게 변경되게 —
자막처럼". 지금 제목(top_title)은 영상 전체에 한 벌이다.

## 컨텍스트 (먼저 읽기)

- `app/modules/renderer.py` `_build_filtergraph`: 제목 drawtext 경로(:1116 부근,
  split_text_smart 줄별 — 활성 코드, 상단 주석 블록 아님)와 E7 회전 경로
  (:1141-1170 — 투명 캔버스 → rotate → overlay, `_title_specs`).
- `app/modules/edit_overrides.py`: `"title": {"top_title": "…"}` 계약(:14),
  subtitles 좌표계 규약(:74-76 — **편집본 시간축**, 쇼츠 0초 시작).
- 오케스트레이터 짝: ves-orchestrator 0043 계열 submit_editor_render 가
  p_overrides.title 을 그대로 넘긴다(내용 무검증 통과) — 스키마 확장은 하위호환.

## 계약 (edit_overrides 확장 — v3 스탬프 그대로)

`title` 값에 선택 키 `segments` 를 추가한다:

```json
{ "title": { "top_title": "기본 제목",
             "segments": [ { "text": "첫 제목\n둘째 줄", "start_sec": 0,  "end_sec": 12.5 },
                           { "text": "반전!",            "start_sec": 12.5, "end_sec": 30 } ] } }
```

- 좌표계는 subtitles 와 동일(**편집본 시간축**, 초). `text` 는 top_title 과 같은
  규약(줄바꿈 = 2줄 위계·title_color/title_color2).
- `segments` 가 있으면 그 창들만 그린다 — 창 밖 시간은 제목 없음(빈 화면이 유효값:
  '뒤에는 제목을 끄고 싶다'가 이 기능의 절반이다). `top_title` 은 세그먼트가 없거나
  구 대시보드가 보낼 때의 종전 경로(전체 상영) 그대로.
- 검증(즉시 실패 — 조용한 무시 금지): text 비면 거절 · start_sec≥0 ·
  end_sec>start_sec · 창끼리 겹침 거절(제목은 한 벌 자리라 겹치면 포개진다) ·
  세그먼트 최대 20개.
- **title_y_fixed/title_y·title_size·title_rotate(E7)는 전 세그먼트 공통**(디자인
  레벨 유지 — 세그먼트별 스타일은 이번 판 범위 밖, 문서에 '후속' 명시).

## 구현

- drawtext 에 `enable='between(t,S,E)'` 를 세그먼트별로 단다(줄별 drawtext ×
  세그먼트 수). E7 회전 경로(투명 캔버스 rotate overlay)는 **세그먼트별 캔버스**로
  같은 창을 단다 — overlay 의 enable 파라미터.
- 자동 배치(title_y_fixed 아님)의 기준 y 는 종전 계산 그대로 한 벌 — 세그먼트마다
  줄 수가 달라도 기준선은 고정(첫 세그먼트 줄 수 기준이 아니라 **최대 줄 수** 기준
  이면 겹침·튐이 없다 — 구현 후 실측으로 확정·보고).
- 배속(video_speed, E7-2 지점 A)과의 정합: segments 의 창도 다른 출력 시각과
  같이 ×1/S 대상인지 확인 — subtitles 와 같은 지점에서 함께 나누면 된다.
- `edit_plan.layout` 에 적용된 segments 기록(하류 검산·검수 노출용).

## 검증

실측 1회: 세그먼트 2개(중간 3초 공백 포함) + title_rotate 8° + video_speed 1.25 —
프레임 캡처로 창 경계 ±1프레임, 공백 구간 제목 없음, 회전·중심 유지 확인.
기존 top_title-만 경로 회귀 없음(테스트).

## 완료 보고에 명시할 것

커밋 sha · 겹침/범위 검증 문구 그대로 · 자동 배치 기준선 결정(최대 줄 수 여부) ·
배속 정합 지점. 오케스트레이터 파트(편집실 제목 타임라인 UI — 자막처럼 행 추가·
시각 편집·미리보기)는 전 노드 last_seen_sha 확인 후 ves-orchestrator 쪽에서 잇는다.

시작해라. 먼저 renderer.py 의 제목 drawtext·E7 회전 경로와 edit_overrides.py 의
title 처리·검증부를 읽고 계약을 확정한 뒤 구현해라.
