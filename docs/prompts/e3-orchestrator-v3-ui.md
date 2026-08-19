# v3 스탬프 전환 + 자막 잠금 해제 + 자막별 스타일·이미지 UI + 업로드 RPC (F-401·407·408 오케스트레이터 파트)

(편집실 v2 Phase 4 · 오케스트레이터 세션 E3 · ves-orchestrator 레포 — E1·E2 전 노드 배포 후에 열 것)

## 필독
- ves/control/migrations/0047·0050 머리말(스키마 스탬프는 RPC 가 못박는다 — fail-loud 규약),
  0044(초안)·0051, dashboard/index.html 의 편집실 구획(edCollect 의 자막 잠금 로직,
  F-203 오버레이 edOvPaint, 출력 타임라인 edOutHtml), ves/adapters/aivideo.py.
- E1 이 남긴 v3 계약 문서가 스키마 정본.

## 선행 조건 (하나라도 아니면 멈추고 보고)
전 노드의 ai-video 가 E1(+E2) 포함 버전인지 node_registry.engine_versions 로 확인 —
구 엔진에 v3 를 보내면 fail-loud 로 죽는 것이 계약이다(그게 정상 동작).

## 작업 범위
1. 마이그레이션(최신 번호+1): submit_editor_render 전문 재정의 — 스탬프 규칙을
   "subtitles 에 source_time_sec/style 있음 또는 images 있음 → v3, tts 만 → v2, 그 외 v1"
   로. images 검증(배열·필드). 서명 업로드 URL RPC 신설(reviewer 검증, ves-outputs 의
   편집 에셋 prefix 한정, 확장자·크기 제한) — 스토리지 쓰기 표면 최초 신설이므로 R12·RLS
   관점 주석을 머리말에 남겨라.
2. aivideo 어댑터: edit_overrides 의 images[].key 를 다운로드해 run_dir 파일로 바꿔
   file 로 치환(엔진은 로컬 파일만 받는다).
3. 대시보드: ① 구간 변경 시 자막 잠금 해제 — edCollect 가 자막에 source_time_sec(화면의
   s.src)을 실어 clips 와 함께 보낸다(앵커 없는 신규 줄은 종전대로) ② 자막별 스타일 —
   F-203 오버레이에서 자막 박스 드래그(y)·핸들(size) WYSIWYG, 값은 subtitles[].style 로
   ③ 이미지 — 업로드(서명 URL), 출력 타임라인 이미지 트랙, 오버레이 드래그 배치,
   초안(edCollect(true))에 이미지 포함.
4. 편집실 재료의 GC prefix 문제(별도 세션 진행 중)와 에셋 prefix 가 겹치지 않게 확인.

## 멈춤 시점
- 마이그레이션 작성까지 하고 적용 직전 멈춰 보고(운영 DB).
- 업로드 RPC 의 스토리지 정책 설계가 기존 '브라우저는 읽기 전용' 규율과 충돌하는 지점이
  발견되면(정책 신설 없이 불가능하면) 멈추고 대안과 함께 보고.

시작해라. 먼저 E1 계약 문서와 edCollect·edOvPaint 를 읽고 스키마 매핑을 확정한 뒤
마이그레이션 → 어댑터 → UI 순서로 진행해라.
