# edit_overrides/v3 — 자막 원본 앵커(F-401) + 자막별 스타일(F-407) + images 스키마 선언

(편집실 v2 Phase 4 · 엔진 세션 E1 · ai-video 레포에서 열 것 — 노드 $VES_HOME/engines/ai-video)

## 필독
- ai-video 레포의 edit_overrides 모듈(app/modules/edit_overrides.py 로 추정 — 실제 경로는
  --edit-overrides 플래그 처리부에서 역추적)과 그 검증(validate_overrides), 자막 렌더러.
- 소비자 계약의 정본: ves-orchestrator 레포 ves/control/migrations/0043·0047·0050 머리말과
  ves/adapters/aivideo.py(edit_overrides 는 run_dir/edit_overrides.json + resume 전용).

## 컨텍스트
현행 계약: v1 = title/subtitles/clips/design, v2 = +tts. 전부 전량 교체. tts 의 좌표이자
신원 = source_time_sec(원본 절대초) — 구간(clips)이 바뀌어도 안 흔들려서 함께 보낼 수 있다.
자막은 그 앵커가 없어서 구간을 고치면 편집실이 자막을 아예 안 보낸다(2-pass 강제) —
엔진이 대사에서 재매핑하기 때문. 오케스트레이터의 editor_assets 는 이미 자막마다
source_sec(원본 절대초, 클립 밖이면 null)을 화면에 내려보내고 있다 — 앵커 재료는 있다.

## 작업 범위·결정사항 (결정 완료 — 그대로 구현)
1. **v3 스키마 선언 + validate**: subtitles[] 항목에 선택 필드
   `source_time_sec`(원본 절대초 앵커)·`style`({size, y, color} — 줄 단위 오버라이드),
   그리고 최상위 `images[]`(스키마만: {file, source_time_sec, duration_sec, x, y, w, layer}
   — x·y·w 는 1080×1920 캔버스 대비 0~1 비율, file 은 run_dir 상대 경로).
   subtitles 에 앵커/style 이 하나라도 있거나 images 가 있으면 schema='edit_overrides/v3'.
   v3 렌더 중 images 는 이 세션에서 **명시적 미지원 에러(fail-loud)** — 구현은 다음 세션.
   구 엔진의 v3 거절(미지 스키마 즉시 실패)이 실제로 동작하는지 확인해 문서화.
2. **자막 배치(F-401)**: source_time_sec 있는 자막은 대사 재매핑 대신 tts 와 같은 규칙으로
   최종 타임라인에 변환 배치(담은 클립 오프셋 + 클립 내 상대시각, 포함 판정 슬롭 ±0.5s —
   편집실 UI 와 동일 규약). 앵커가 최종 구간 목록에 없으면 tts 고아와 같은 기존 규칙을
   따르고 그 규칙을 결과 로그에 남겨라. 앵커 없는 항목(신규 줄)은 종전대로 start_sec.
   이로써 clips 와 subtitles 동시 제출이 안전해진다.
3. **자막별 스타일(F-407)**: style.size·y·color 를 채널/편 전역값 위에 줄 단위로 얹는다.
   렌더러가 지원하는 표현 범위로 구현하되 계약 필드명은 위 그대로 못박기.
4. 계약 문서: v3 전체 스키마 예시(JSON)와 배치 규칙을 레포 문서에 남겨라 —
   오케스트레이터 후속 세션(스탬프 전환 마이그레이션)이 이것을 정본으로 쓴다.

## 검증
엔진 테스트 + 실측 1회: 기존 run 을 resume 으로 v3 overrides(앵커 자막 + 줄 스타일) 렌더,
구간을 바꾼 상태에서 자막 시각이 앵커를 따라오는지 확인.

## 멈춤 시점
- 자막 렌더러가 줄 단위 스타일을 구조적으로 지원할 수 없으면(단일 스타일 트랙 등) 멈추고 보고.
- v3 를 전 노드에 배포하기 전까지 오케스트레이터는 v3 스탬프를 보내지 않는다 — 이 세션은
  엔진 구현·배포까지만, 스탬프 전환은 후속 세션 몫임을 완료 보고에 명시.

시작해라. 먼저 --edit-overrides 처리부와 validate, 자막 렌더 경로를 읽고 위 결정과
어긋나는 지점이 있는지 확인한 뒤 구현에 들어가라.
