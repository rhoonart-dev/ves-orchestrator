# supabase/functions — 컨트롤 플레인 엣지 함수

이 저장소가 **정본**이다. 배포는 Supabase(프로젝트 `fdidiqdhcyctdbogxkdu`) 쪽에 있고,
여기 파일과 배포본이 갈라지면 배포본이 이긴다 — 고칠 때는 **여기서 고치고 배포**한다.

```bash
supabase functions deploy tts-preview --project-ref fdidiqdhcyctdbogxkdu
```

## 왜 서버가 없다더니 함수가 있나

ARCHITECTURE §10-1 의 "서버 프로세스가 없다"는 **대시보드에** 서버가 없다는 뜻이다
(anon key 는 공개값이고 규칙은 전부 Postgres 안에 있다 — R12·R15). 엣지 함수는 그
규율의 예외가 아니라 **키를 브라우저에 두지 않기 위한 자리**다: 함수는 호출자의 JWT 로
권한을 다시 보고, 시크릿은 Supabase 시크릿에만 있다.

## tts-preview — 편집실 내레이션 미리듣기

| | |
|---|---|
| 호출 | `dashboard/index.html` 의 `edTtsSynth()` (supabase-js `functions.invoke`) |
| 입력 | `{ text, voice: "elevenlabs:<voice_id>", speed }` |
| 출력 | `{ audio: <base64 mp3>, mime, chars, truncated, voice_id, model_id, speed }` |
| 권한 | 호출자 JWT + `user_roles.role ∈ (reviewer, operator, admin)` |
| 게이트 | `ops_config.editor_tts_elevenlabs = on` (꺼져 있으면 409 — 화면에 없는 기능에 돈이 나가면 안 된다) |
| 시크릿 | `ELEVENLABS_API_KEY` (없으면 503 + 어디에 넣는지 알린다 — 조용한 폴백 없음) |
| 선택 시크릿 | `ELEVENLABS_MODEL_ID` (기본 `eleven_multilingual_v2`) |

### 지켜야 할 것 둘

1. **합성 파라미터는 엔진(ai-video `app/modules/tts.py`)의 복제본이다.** 모델 id·
   `voice_settings`·speed 매핑이 어긋나면 **미리듣기가 완성본과 다른 소리**를 낸다 —
   이 기능이 있으나 마나가 아니라, 사람을 잘못된 결정으로 이끈다.
   `tests/test_pure.py::test_tts_preview_fn_mirrors_engine_contract` 가 값을 못박아
   두었으니, 엔진이 바꾸면 **여기와 그 테스트를 함께** 고친다.
2. **라벨 목소리(`ko_female` 등)는 여기서 합성하지 않는다.** 라벨→voice_id 표는 엔진이
   들고 있고, 그걸 복제하면 정본이 둘이 된다. 라벨 목소리는 화면이 저장된 mp3(구본)를
   튼다 — 새 소리는 재렌더 후에만 존재한다.

### CORS

대시보드는 CloudFront 에서 오므로 **다른 오리진**이다. `functions.invoke` 는
`authorization`·`apikey`·`content-type` 을 실어 보내 브라우저가 먼저 OPTIONS
(프리플라이트)를 친다 — 그 응답에 허용 헤더가 없으면 본 요청은 아예 나가지 않고
**함수 로그에도 아무것도 안 남는다**. 2026-08-23 판이 그 구멍(OPTIONS → 405)을 메웠다.
