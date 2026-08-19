# 일본어 자막 줄 스타일·타이밍 (JP-2 엔진 파트 — vlp 세션 E5)

(편집실 JP-2 · video-localization-project 레포 — 기준 9093049 이후 main)

## 컨텍스트
편집실 일본어 화면(ves-orchestrator, KR 편집실과 통일됨)에서 자막의 **줄 단위
스타일(위치 y·크기·색·회전)과 타이밍**을 편집하려 한다. 좌표는 기존 오버라이드의
idx 그대로, 계약 의미는 ai-video edit_overrides/v3 의 style 과 동일(y=0~1 캔버스
비율·하단 기준, size=1080×1920 px, color=#RRGGBB, rotate=시계방향 도 -180~180).
오버라이드 값 dict 는 두 병합 함수 모두 "ja" 외 키를 무시하므로(process_video.py:58,
dub.py:151) 계약 확장은 하위호환 — 단 그 말은 **구 엔진이 style 을 조용히 무시**한다는
뜻이라, 오케스트레이터는 전 노드 배포 확인 후 플래그로 연다. 배포 sha 보고 필수.

## 작업 범위

### A. 오버라이드 계약 확장 (두 경로 공통)
subs/tts/telops 의 dict 값에 선택 키:
`style {size, y, color, rotate}` · `start_sec` · `end_sec`(초, 편집본 시간축).
타입·범위 검증(v3 와 동일), 모르는 style 키 거절. 계약 문서(docs/)에 표로 남겨라.

### B. SHOTCONE(scene_rerender — scripts/localize_run.py)
1. **대사 자막**: l3_apply 의 segments 루프(:465-471)에서 tr 의 style·start_sec·
   end_sec 를 seg 로 전사 → subtitle_segments.json 에 실린다. **ai-video(69e5c06)는
   그 파일의 줄 style 을 이미 렌더에 소비한다**(v3 캐시 규약 — ai-video
   docs/edit_overrides_v3.md 'style 은 남는다') — 렌더 쪽 추가 작업이 없어야 정상이며,
   실측으로 확인해라. 타이밍 전사 시 8s/20자 클램프(:464-471)와의 우선순위:
   **사용자 지정 타이밍이 이기고 클램프는 건너뛴다**(사람이 보고 정한 값이다).
2. **텔롭**: build_telop_ass(:432-459)에 줄별 ASS 오버라이드 태그(\fs·\1c&HBBGGRR&·
   \frz — ASS \frz 는 반시계 양수라 부호 반전은 엔진 책임·문서화, 위치는 MarginV 또는
   \pos, y=하단 비율→PlayResY 1920 환산) + tr 의 start_sec/end_sec 우선. 태그는
   _ass_escape 밖에서 조립(이스케이프가 { } 를 바꾼다).
3. **TTS 자막 스타일은 범위 밖**(ai-video 계약이 cue 단위 스타일을 안 받는다 —
   디자인 레벨은 KR 와 공유). tts 의 start_sec/end_sec 편집도 이번엔 범위 밖
   (재합성 창 재계산이 얽힌다 — 문서에 '후속'으로 명시만).
4. **타이밍·스타일 노출**: build_ko_ja_pairs(:670-709) 확장 —
   subs 에 end(클램프·오버라이드 반영 후의 실표시 값), tts 에 cue start/end,
   telops 는 소스를 onscreen_refined.json 로 바꾸고 **orig_index 를 idx 로**
   + start/end 동봉. ⚠ 이것이 기존 telops 좌표 버그(build_ko_ja_pairs 가 kind
   필터 없이 raw enumerate — :699-707 vs 규약 :381-393)의 수정을 겸한다 —
   수정 전후 좌표가 달라질 수 있으니 계약 문서에 '이 판부터 orig_index' 를 명시.
   현재 스타일 값(있으면)도 각 항목에 동봉해 편집실이 초기값으로 쓴다.

### C. 잔망루피(src/ — 실운영 라우트 C + BJ 폴백만, B replace 는 후순위 제외)
1. **C/BC(더빙 번인)**: apply_dub_overrides(:136-155) 확장 — events 에 style·타이밍
   반영. 타이밍은 ja_dub.srt 1차 기록(:1102-1112) **전**에 넣어야 페이싱 캡에 먹히고,
   retime_events 는 **사용자 지정 end 를 덮어쓰지 않는다**(사용자 값 우선 — 규칙
   신설·문서화). build_ass 에 이벤트별 ASS 태그.
2. **BJ(병기)**: build_bilingual_ass(engine/render.py:107-147)에 동일한 이벤트별 태그.
3. **노출**: ko_ja_pairs.json(C 루트, dub.py:1037-1041)에 end(+retime 후 실측 여부
   구분) 추가. BJ/B 루트 타이밍(detections 기반, 0.5s 양자화)은 render() 가 이벤트를
   JSON 으로 떨궈 review_meta 가 쓸 수 있게(ves 어댑터가 읽는다 — 파일명·스키마 보고).

## 검증
경로별 실측 각 1회: SHOTCONE(대사 style+타이밍+텔롭 회전), 잔망루피 C(자막 style+
end 고정), BJ(style). 프레임 캡처로 위치·크기·색·회전 확인.

## 멈춤 시점
- retime/페이싱과 사용자 타이밍의 우선순위 구현이 더빙 품질을 흔들면(합성이 겹치거나
  잘리면) 수치와 함께 멈추고 보고.
- ai-video 가 subtitle_segments.json 의 style 을 소비하지 않는 것으로 실측되면
  (전사만으로 안 되면) 멈추고 보고 — ai-video 쪽 추가 세션이 필요해진다.

## 완료 보고에 명시할 것
배포 sha · ko_ja_pairs 확장 스키마(필드명 그대로) · telops 좌표 전환 여부 ·
retime 우선순위 규칙 — 오케스트레이터 후속(어댑터 payload·편집실 WYSIWYG·플래그)이
이 넷에 걸려 있다.

시작해라. 먼저 scripts/localize_run.py 의 l3_apply·build_telop_ass·build_ko_ja_pairs
와 src/dub.py 의 오버라이드·retime 경로를 읽고 계약을 확정한 뒤 구현해라.
