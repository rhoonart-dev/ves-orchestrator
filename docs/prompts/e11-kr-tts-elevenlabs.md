# E11 — KR 내레이션 TTS ElevenLabs 전환 (ai-video 엔진 발주서)

> **구현 패치 동봉(2026-08-21)**: 이 디렉토리의 `e11-kr-tts-elevenlabs.patch.txt`
> (d195cb9 기준 format-patch, 로컬 검증: 신규 11개 + 인접 114개 테스트 통과).
> 엔진 세션은 패치를 검토·적용(`git am`)하고 테스트 재확인 후 브랜치로 푸시한다 —
> 발주 본문은 아래 원문 그대로(패치가 곧 그 구현이다).

ai-video(rht-22/ai-video) 엔진 세션용 작업 프롬프트. 기준: d195cb9(전 노드
last_seen 동일 — node_registry 2026-08-21 실측). 사용자 요청(8/21): "tts 는
일레븐랩스를 사용하게 해줘" + "tts 속도 조절이 안 먹히는 것 같다".

## 진단 (오케스트레이터 쪽에서 실측 완료 — 재조사 불필요)

- cue 단위 speed 체인 자체는 온전하다: 편집실 → edit_overrides.tts[].speed →
  `overrides_tts`(edit_overrides.py:743 승계 포함) → resources 재합성
  (`_tts_override` 가 checkpoint_resources 무효화, pipeline.py:3353-3356) →
  `synthesize_tts_with_fit(speed=cue["speed"])` → `SPEED_TO_RATE` rate.
- 다만 **2026-08-21 이전까지 normal 아닌 speed 가 제출된 적이 단 한 번도 없다**
  (job_queue 전수 조회 25건 중 0건 — 속도 UI 는 8/20 출시). 첫 non-normal 제출
  (8/21 06:55Z, fast×5)은 현행 edge-tts 로도 반영된다.
- 남는 실제 결함 두 가지가 이번 발주의 배경이다:
  1. edge-tts 프리셋 fast/slow 가 ±10% 라 **체감이 거의 없다**(±25% 만 들린다).
  2. `_synthesize_edge_tts` 의 예외 폴백(tts.py:144-151)이 rate/pitch 를 빼고
     **조용히** 재시도한다 — 실패하면 속도·피치가 소리 없이 무시되는 유일한
     지점이고, 렌더는 성공하므로 아무도 모른다(2026-07-29 폰트 사고와 같은 계열).
- vlp(더빙·JP 변환)는 이미 ElevenLabs 를 쓴다 — 이번 대상은 **ai-video 의 KR
  내레이션 합성만**이다. vlp·잔망루피는 무변경.

## 컨텍스트 (먼저 읽기)

- `app/modules/tts.py` — VOICE_PRESETS(edge voice+pitch 8종) · SPEED_TO_RATE ·
  `synthesize_tts` · `synthesize_tts_with_fit`(fit 루프 — 창 초과 시 Flash 축약) ·
  `get_audio_duration`.
- `app/pipeline.py` resources 합성 루프(:3474-3502 — cue.voice/speed 전달,
  E7-2 배속 반영 target_sec) · 체크포인트 무효화(:3331-3356).
- `scripts/verify_tts_planner.py` — voice×speed 매트릭스 검증 스크립트.
- 오케스트레이터 짝: 신 design 키·CLI 플래그 **없음**(어댑터·게이트 무변경).
  ELEVENLABS_API_KEY 는 `/opt/ves/secrets/ves.env` 에서 job_env 로 서브프로세스에
  주입된다(ves-orchestrator deploy/secrets.env.example 에 항목 추가됨).

## E11-1. ElevenLabs 백엔드 (중)

- `ELEVENLABS_API_KEY` 가 있으면 ElevenLabs, 없으면 edge-tts 폴백. 폴백은
  **stdout 에 한 줄 명시**(`[TTS] backend=edge-tts — ELEVENLABS_API_KEY 없음`) —
  조용한 대체 금지. run_log(provenance 또는 steps)에 `tts_backend` 를 기록해
  검수함에서 어느 백엔드로 나갔는지 추적 가능하게.
- 모델: **한국어 지원 + voice_settings.speed 지원**이 필수 조건. 후보
  eleven_multilingual_v2(품질) vs eleven_flash_v2_5(단가 절반·저지연) — 최신
  문서를 확인해 결정하고 근거를 완료 보고에 적어라.
- **voice/speed 라벨 계약은 그대로 둔다** — ko_female·ko_female_high·ko_male·
  ko_male_low·chat_* 라벨은 편집실(edVoiceSel)·edit_overrides/v2·체크포인트
  cue 에 이미 실려 있는 값이라 바꾸면 하위호환이 깨진다. 라벨 → ElevenLabs
  voice_id(+voice_settings) 매핑 테이블을 신설하라. ElevenLabs 에는 pitch
  파라미터가 없으므로 high/low 피치 변형은 **다른 voice 선정**으로 재현하고
  매핑 표(라벨 → voice_id·이름)를 완료 보고에 명시하라.
- speed 매핑(라벨 유지): very_slow 0.7 · slow 0.85 · normal 1.0 · fast 1.1 ·
  very_fast 1.2 — ElevenLabs voice_settings.speed 허용 범위(0.7~1.2)를 문서로
  재확인하고 범위가 다르면 근거와 함께 조정하라. edge-tts 폴백 경로는 현행
  SPEED_TO_RATE 를 그대로 쓴다.
- `synthesize_tts` / `synthesize_tts_with_fit` 시그니처·fit 루프·
  `get_audio_duration` 계약은 유지 — 호출부(pipeline.py)는 무변경이 목표다.
  합성 시점·캐시 무효화 규칙(_tts_override → resources 재합성)도 그대로.
- API 호출 실패(4xx/5xx·쿼터 소진)는 짧은 재시도 후 **즉시 실패**시켜라 —
  edge-tts 로 조용히 넘어가면 채널 목소리가 편마다 달라진다(fail-loud 원칙).
  폴백은 '키 없음' 한 경우뿐이다. 기존 '예외 → rate/pitch 빼고 재시도' 무성
  폴백은 제거하라(위 진단 2).

## E11-2. 검증 (실측)

- `scripts/verify_tts_planner.py` 확장: 같은 문장을 voice 4종(ko_*) × speed
  5종으로 합성, mp3 길이가 speed 에 단조(0.7 이 가장 길고 1.2 가 가장 짧게)인지
  실측 — edge-tts ±10% 와 달리 차이가 뚜렷해야 한다.
- 편집실 경로 1회: edit_overrides.tts 로 speed 만 바꾼 재렌더(--from-step
  resources)에서 tts_cue_*.mp3 길이가 실제로 달라지는지.
- 키 없는 환경 1회: edge-tts 폴백 + stdout 명시 로그 확인.
- 비용: cue 당 문자 단가 + fit 재합성(최대 3회) 몫이 있다 — 편당 대략 비용과
  쿼터 상한을 완료 보고에 명시하라.

## 완료 보고에 명시할 것

커밋 sha · 선택한 모델과 근거 · 라벨 → voice_id 매핑 표 · speed 매핑(허용 범위
확인 결과) · 폴백/실패 동작 · 검증 실측 결과 · 편당 비용 추정. 오케스트레이터
파트는 시크릿 배치뿐이다: 전 노드 `/opt/ves/secrets/ves.env` 에
ELEVENLABS_API_KEY 를 넣은 뒤 엔진 배포(§11 자동 업데이트) — 키가 먼저 깔려야
배포 직후부터 ElevenLabs 로 나간다(키 없는 노드는 edge-tts 폴백 로그가 남는다).

시작해라. 먼저 tts.py 전문과 pipeline.py 의 resources 합성 루프를 읽고,
ElevenLabs 문서(모델별 언어·voice_settings.speed)를 확인해 계약을 확정한 뒤
구현해라.
