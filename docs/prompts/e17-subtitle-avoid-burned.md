# E17 — 원본 자막 회피 · 제목 회전 차단 · 일레븐랩스 토큰 만료 폴백

발주(2026-08-24, 사용자):

> "제목은 왠만하면 회전은 안되게 해주고, 영상에 원래 자막이 있으면 그 위치 피해서 자막이
> 들어가게 해줘. 물론, 자막이 제목과도 겹치면 안되고. 그리고 일레븐랩스 토큰이 만료되면
> 일레븐랩스 api 가 아니라 기본으로 사용되도록 해줘."

엔진 구현은 ai-video `claude/subtitle-placement-voice-api-a6iqiv`(CLAUDE.md §E17).
이 문서는 **오케스트레이터가 잇는 부분**과 롤아웃 순서만 적는다.

## 1. 오케스트레이터가 잇는 것 — 원본 자막 회피 채널 키

| 층 | 무엇 |
|----|------|
| 엔진 | `--design-subtitle-avoid-burned {auto\|off}` — **기본 auto(켜짐)** |
| 어댑터 | `CHANNEL_DESIGN_FLAGS["subtitle_avoid_burned"]` + `_subtitle_avoid_value`(auto/off 외 즉시 실패) |
| 배포 게이트 | `design_for_job` 이 `params.subtitle_avoid_allowed`(ops_config `channel_subtitle_avoid`) 없이는 키를 걷는다 |
| RPC | `0081_channel_subtitle_avoid_burned.sql` — v_allowed + 값 검증(auto/off) |
| 대시보드 | 채널 설정 모달 `df_subtitle_avoid_burned`(게이트 뒤에서만 뜬다) |

⚠ **다른 채널 키와 방향이 반대다.** 지금까지의 새 기능(E11 전사·E15 스타일)은 '켜는' 키였고
미지정이 종전 동작이었다. 이번 것은 **엔진 기본이 켜짐**이다 — 지시가 "그렇게 되게 해 달라"
였고, 검출이 못 찾으면 아무것도 안 바뀌기 때문이다. 그래서 이 채널 키는 **끄는 통로**이고,
게이트가 꺼져 있어도 회피 자체는 전 채널에서 돈다.

**끄는 것을 검토할 채널**: 사람이 실렌더 픽셀로 자막 위치를 맞춘 채널(한 입 주막 계열 —
`video_y` 만 쓰고 `video_width` 를 안 쓰는 템플릿). 그런 채널은 자막이 밴드 아래 배경에
앉아 있어 대개 겹치지 않지만, 승인된 화면이 조금이라도 움직이면 안 되는 곳이면 `off` 다.

## 2. 회피가 실제로 하는 일 (검수자가 알아야 할 것)

- 렌더 직전에 **영상 밴드 아래 절반**을 표본(4클립×6프레임)으로 재서, 표본의 절반 이상에서
  같은 행에 글자 획이 잡히면 그것을 원본 자막 띠로 본다.
- 우리 대사 자막을 그 띠 **위로만** 올린다(아래는 로고·작품명 스택이라 못 내려간다).
  상한은 **제목 블록 아래 14px** — 발주의 "제목과도 겹치면 안된다"가 이 클램프다.
- 다 못 피하면 제목을 우선하고 로그에 `[SubtitleAvoid/미달]` 로 남긴다.
- 못 찾으면 자막 위치가 **한 픽셀도** 안 바뀐다. 찾은 실행만 run_log
  `steps[{step:"subtitle_avoid_burned"}]` 에 띠 좌표·표본 수가 남는다.
- 검출은 편당 한 번이고 `checkpoint_burned_subtitle.json` 에 남아 **편집실 재렌더에서도
  같은 위치**가 나온다(구간을 고쳐 클립이 바뀌면 다시 잰다).
- 임계값은 초기값이다. 실소재로 다시 잴 때:
  `python -m scripts.e17_burned_subtitle_probe --video … --start … --end …`(ai-video).

## 3. 나머지 둘 — 오케스트레이터가 할 일 없음

- **제목 회전 차단(E17-1)**: E15 AI 연출 플랜에서 `title_rotate` 를 버린다. 채널·편집실이
  보내는 `title_rotate` 는 그대로 살아 있다(어댑터 변경 없음).
- **토큰 만료 폴백(E17-3)**: ElevenLabs 401·403 이면 그 실행은 기본 백엔드로 간다
  (내레이션은 edge-tts, 전사는 내장 Whisper 로 청크 전량 재전사). 어댑터 변경 없음 —
  다만 **검수함에서 보이는 것이 달라진다**: run_log `steps[resources].tts_backend` 가
  `edge-tts` + `tts_fallback_reason: elevenlabs_auth_expired`, 전사 쪽은
  `transcribe_backend` 가 요청값이 아니라 **실제로 쓴** 값이다. 이 두 키가 보이면 그날의
  키를 갱신해야 한다는 뜻이다(그 편은 목소리가 평소와 다르게 나갔다).

## 4. 롤아웃 순서

1. ai-video main 머지 → `deployments.auto_update` 로 6대 노드 갱신 확인.
   **이 시점부터 회피가 전 채널에서 돈다**(게이트와 무관 — 엔진 기본).
   첫 며칠은 검수함에서 자막 위치가 움직인 편이 있는지 본다.
2. `0081_channel_subtitle_avoid_burned.sql` 적용(적용 직전 `SELECT max(version) FROM
   applied_migrations WHERE engine='orchestrator'` 로 번호 확인).
3. 끄고 싶은 채널이 생기면 `ops_config channel_subtitle_avoid = 'on'` → 채널 설정 모달에서
   '끔' 저장. 그 전까지는 어댑터가 키를 걷으므로 구 엔진 노드도 안전하다.
