# E12 — 편집실 내레이션: 일레븐랩스 목소리 (ai-video 엔진 발주서)

ai-video(rht-22/ai-video) 엔진 세션용 작업 프롬프트. 사용자 요청(2026-08-21):
"tts 목소리 더 다양하게 선택할 수 있게 선택지를 일레븐랩스에서 찾아서 넣어줘."

지금 편집실 내레이션 목소리는 `ko_female` · `ko_female_high` · `ko_male` ·
`ko_male_low` 네 프리셋뿐이고 전부 edge-tts 로 합성된다. 목소리 폭이 좁아 채널마다
같은 소리가 난다. **이 저장소(vlp 더빙 경로)는 이미 ElevenLabs 를 쓰고 있다** —
`ops_config.localize_voices` 가 채널별 ElevenLabs `voice_id` 를 들고 있고
`ves/adapters/localize.py` 가 `--voice=<voice_id>` 로 넘긴다. 같은 계정·같은
`voice_id` 어휘를 KR 내레이션에도 연다.

## ⚠ 배포 특성 — 회귀 0 이 안전장치다

ai-video 는 `deployments.auto_update=true` 이고 핀이 없다. **main 에 머지하면 version_watch
(시간당 1회)가 새 sha 를 보고 맥미니 6대가 다음 claim 경계에서 자동으로 갱신한다.**
되돌리는 절차는 RUNBOOK §1 에 있지만, 애초에 안 깨지게 만드는 게 전제다.

**플래그/접두사가 없는 실행은 한 글자도 달라지면 안 된다.** 지금 돌고 있는 모든 작업이
그 경로다. 이건 요청이 아니라 배포 조건이다.

## E12-0. 먼저 확인할 것 (막힘 지점 후보)

⚠ **이 저장소에서 elevenlabs.io 로 나가는 길이 막혀 있어 계정 상태를 못 봤다.**
구현 시작 전에 실키로 `GET /v1/voices` 를 한 번 찍고 보고해라. 이유:

1. ElevenLabs 공지상 **기본(premade) 목소리는 2026-12-31 만료 예정**이고,
   **2026-03 이후에 만든 계정에는 애초에 없다.** 대시보드가 들고 있는 기본 목록이
   이 계정에서 이미 죽어 있을 수 있다.
2. 기본 목소리는 전부 영어권이다 — 다국어 모델이 한국어를 말하긴 하지만
   **영어 억양이 배어난다.** 네이티브 한국어 목소리는 보이스 라이브러리에 있다:
   `GET /v1/shared-voices?language=ko&category=professional` 로 찾아
   `POST /v1/voices/add/{public_user_id}/{voice_id}` 로 계정에 담는다(무료 요금제는
   라이브러리 API 불가). 담은 voice_id 는 **엔진 수정 없이** 오케스트레이터
   `ops_config.editor_tts_voices` 에 넣으면 그대로 목록에 뜬다.
3. 완전 폐기된 legacy 목소리(Rachel·Adam·Josh 등)는 요청이 **성공하는 것처럼 보이면서
   다른 목소리로 갈아치워진다.** 대시보드 기본 목록에서 이미 제외했다 — 엔진에서도
   특별 취급하지 마라, 그냥 쓰지 않으면 된다.

## 🛑 계약 불일치 — 엔진은 이 발주서와 다르게 구현했다 (2026-08-22 확인)

**이 발주서를 그대로 읽지 마라.** 아래 '계약' 절이 정하는 `elevenlabs:{voice_id}` 접두사
규약은 **엔진에 없다.** ai-video 는 이 문서가 쓰이기 전에 이미 다른 설계로 머지했다
(`0271c70`, 294ab98 로 전 노드 배포 완료):

| | 이 발주서 | 실제 엔진(`app/modules/tts.py`) |
|---|---|---|
| voice 값 | `elevenlabs:{voice_id}` 접두사 신설 | **라벨 그대로**(`ko_female` 등) — "라벨 계약은 종전과 동일" |
| voice_id 표 | 대시보드가 든다 | **엔진이 든다** (`EL_VOICE_PRESETS`, 라벨 8종) |
| 모르는 값 | 엔진이 즉시 실패 | `EL_VOICE_PRESETS.get(voice, 기본)` — **조용히 ko_female 로 폴백** |
| 백엔드 선택 | 접두사로 | 키가 있으면 자동 (`elevenlabs > edge-tts > silence`) |

엔진이 아는 라벨은 8종이다 — `ko_female`·`ko_female_high`·`ko_male`·`ko_male_low` +
`chat_emma`·`chat_brian`·`chat_seraphina`·`chat_florian`. 각각 premade voice_id 에 매핑돼
있고, KR 내레이션은 **이미 ElevenLabs 로 합성되고 있다**(294ab98 배포 이후).

### 지금 무엇이 위험한가

오케스트레이터 대시보드는 `elevenlabs:<20자 id>` 값 20종을 내보내도록 이미 머지돼 있다
(0073 + `ED_EL_VOICES_DEFAULT`). 게이트 `ops_config.editor_tts_elevenlabs` 가 `off` 라
지금은 아무도 그 값을 못 고르지만, **켜는 순간 모든 선택이 조용히 ko_female 로 떨어진다** —
이 발주서가 가장 경계한 실패 모드 그대로다. **게이트를 켜기 전에 아래 중 하나를 정해야 한다.**

1. **오케스트레이터를 엔진에 맞춘다** — 대시보드 목록을 엔진의 8라벨로 바꾸고 0073 의
   `elevenlabs:` 형태 검증을 걷어낸다. 목소리 폭은 8종으로 제한되고, 늘리려면 엔진을 고쳐야 한다.
2. **엔진이 접두사를 받게 한다** — `elevenlabs:{voice_id}` 를 라벨 조회보다 먼저 처리하고,
   모르는 라벨은 폴백 대신 즉시 실패로 바꾼다. 목록의 정본이 대시보드로 오고
   `ops_config.editor_tts_voices` 로 계정 라이브러리(한국어 네이티브 목소리)까지 열린다.
3. **둘 다** — 8라벨은 그대로 두고 접두사를 추가 어휘로 받는다(하위호환 + 확장 둘 다).

**선택 전까지 `editor_tts_elevenlabs` 를 켜지 마라.** 아래 절들은 3안(또는 2안)을 전제로
쓰였으므로, 1안으로 가면 이 문서는 폐기하고 오케스트레이터 쪽을 고치는 것이 작업이 된다.

## 계약 (오케스트레이터가 이 형태로 보낸다)

`edit_overrides.tts[].voice` 는 지금도 **불투명 문자열 통과**다 — RPC·어댑터 어디에도
검증이 없고(`submit_editor_render` 의 tts 검증은 배열 타입 한 줄뿐), 화면은 모르는
프리셋을 현재값으로 보존한다(`chat_*` 계열이 그렇게 살아 있다). 그래서 **새 어휘를
접두사로 연다** — 기존 이름은 한 글자도 안 바뀐다.

```
voice = "ko_female" | "ko_male" | … (지금 그대로, edge-tts)
      | "elevenlabs:<voice_id>"     (신설 — ElevenLabs TTS)
```

- 접두사 `elevenlabs:` 가 붙은 값만 새 경로다. 나머지는 **종전 코드 그대로** 흐른다
  (회귀 0 — 접두사 없는 실행은 한 줄도 안 달라져야 한다).
- `<voice_id>` 는 ElevenLabs 의 voice id 문자열을 그대로 싣는다. 엔진이 이름표를
  들 필요가 없다 — 사람이 읽는 이름은 대시보드가 들고 있다.
- 오케스트레이터 RPC 가 형태(`elevenlabs:` + 영숫자 16~32자)를 먼저 거른다. 엔진은
  **없는 voice_id·권한 없음**을 즉시 실패로 다뤄라 — 조용히 기본 목소리로 떨어지면
  사람은 바꿨다고 믿은 채 종전 소리로 발행된다.
- `speed`(`very_slow`…`very_fast`)는 두 백엔드 모두에서 살아야 한다. edge-tts 는
  `tts.SPEED_TO_RATE`(rate −25%~+25%), ElevenLabs 는 `voice_settings.speed` 로
  **같은 체감**이 나게 맞추고, 매핑 표를 보고에 실어라. 편집실의 발화 길이 게이지
  (`ED_SPEED_FACTOR` = 0.75/0.9/1/1.1/1.25)가 그 근사를 쓴다 — 크게 어긋나면
  게이지가 거짓말을 한다.
  ⚠ **`voice_settings.speed` 의 범위는 0.7~1.2 다**(0~2 아님). 편집실의 다섯 단은
  그 안으로 눌러 담아야 하고, `very_slow` 0.75 · `very_fast` 1.2 가 자연스러운
  대응이다 — 끝단이 edge-tts 만큼 안 벌어지면 그 사실을 보고해라(게이지 배율을
  이쪽에서 고쳐야 한다).

## E12-1. 합성 경로 분기 (중)

- 내레이션 합성부(`tts.py`)를 백엔드 인터페이스로 감싼다: 입력 = 문구·voice·speed,
  출력 = **지금과 같은 mp3 파일**(같은 샘플레이트·같은 라우드니스 정책).
  `checkpoint_resources.tts_cue_files` 의 모양은 바뀌면 안 된다 — 오케스트레이터
  `ves/adapters/editor_assets.py` 가 그 파일을 편집실 미리듣기로 올린다.
- 자격증명은 환경변수(예: `ELEVENLABS_API_KEY`). 키 없이 `elevenlabs:` 목소리가
  오면 즉시 실패 + "무엇을 어디에 넣어야 하는지" 메시지(vlp `dub_argv` 규율).
- 캐시: 같은 (문구, voice, speed) 는 재합성하지 마라. 편집실 재렌더는
  `from_step=resources` 로 오므로 한 줄만 고쳐도 전 cue 가 다시 돈다 —
  요금이 그대로 곱해진다.
- 모델은 **`eleven_multilingual_v2`** 로 고정해라 — 2026-08-21 조사 기준 한국어가
  명시적으로 지원 목록에 있고 장문 내레이션에 권장되는 모델이다.
  · `eleven_v3` 는 더 표현력이 좋지만 **`speed`·`similarity_boost`·`use_speaker_boost`
    를 지원하지 않는다** — 편집실 속도 프리셋이 죽으므로 쓰지 마라.
  · ⚠ `language_code` 파라미터는 `eleven_multilingual_v2` 에서 **무시된다**. 언어는
    문장 자체로 정해지므로 넣어도 소용없다(넣지 마라 — 넣고 되는 줄 알면 위험하다).
  · 기본 `voice_settings`: stability 0.5 · similarity_boost 0.75 · style 0.0.
    같은 문구를 재렌더할 때 소리가 미묘하게 달라지는 게 문제면 `seed` 를 고정해라.
  · 엔드포인트: `POST /v1/text-to-speech/{voice_id}`, 헤더 `xi-api-key`.
- 실패 분류: 401·403·없는 voice_id = permanent, 429·5xx·네트워크 = transient.

## E12-2. 목소리 목록의 정본은 어디인가 (소)

대시보드가 사람이 읽는 이름표를 들고, 엔진은 `voice_id` 만 받는다. 엔진이 목록을
들지 마라 — 두 곳에 목록이 생기면 반드시 어긋난다(1:1 미러 규율을 지킬 수 없는
어휘다. ElevenLabs 라이브러리는 계정마다 다르다).

## E12-3. 실측 검증 (필수)

한국어 내레이션 3줄로 다음을 보고하라.

1. `elevenlabs:` 목소리 1종 × speed 3단(slow·normal·fast) — 실제 발화 길이가
   편집실 게이지 근사(0.9/1/1.1)와 얼마나 벌어지는가.
2. 같은 cue 를 두 번 렌더 — 캐시가 두 번째 합성을 막는가(요금 0).
3. 접두사 없는 종전 프리셋 실행이 **완전히 같은지**(회귀 0).
4. 잘못된 voice_id 를 넣었을 때 즉시 실패하는가(조용한 폴백 없음).
5. 한국어 발음·억양 체감 — 영어권 목소리로 한국어를 읽혔을 때 쓸 만한 수준인가.
   이 기능의 핵심 리스크가 여기다(E12-0 ②: premade 는 전부 영어권이고 다국어 모델이
   한국어를 말하긴 하지만 억양이 배어난다). 못 쓸 수준이면 **그게 가장 중요한 보고다** —
   그 경우 보이스 라이브러리에서 한국어 네이티브 목소리를 담는 경로로 간다.

## 완료 보고에 명시할 것

커밋 sha · 접두사 규약 그대로 · 자격증명 환경변수 이름 · 쓰는 모델 id ·
speed 매핑 표 · 캐시 키 · 실패 분류 표 · E12-3 실측 5항목.

오케스트레이터 파트는 이미 나갔다:

- `dashboard/index.html` — `ED_EL_VOICES_DEFAULT`(검증된 현행 premade 20종) +
  `edElVoices()`(운영자 목록 `ops_config.editor_tts_voices` 가 이긴다) +
  `edVoiceSel` 그룹 select (게이트 `ops_config.editor_tts_elevenlabs`)
- `ves/control/migrations/0073_editor_tts_voice_vocab.sql` —
  `submit_editor_render` 의 `tts[].voice` 형태 검증 + 게이트 시드

전 노드 `last_seen_sha` 확인 후 `editor_tts_elevenlabs = on` 만 남는다.

먼저 `tts.py` 의 합성·캐시 경로와 `SPEED_TO_RATE`, `checkpoint_resources` 의
`tts_cue_files` 생성부를 읽고 계약을 확정한 뒤 구현해라.
