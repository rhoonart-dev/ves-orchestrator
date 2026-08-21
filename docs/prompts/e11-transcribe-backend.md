# E11 — 자막 전사 백엔드 선택: 기본 / 일레븐랩스 (ai-video 엔진 발주서)

ai-video(rht-22/ai-video) 엔진 세션용 작업 프롬프트. 사용자 요청(2026-08-21):
"자막 전사를 기본과 일레븐랩스 둘 중에 선택할 수 있게 해줘."

지금 대사 자막의 원본은 엔진 `chunk_transcribe` 단계의 받아쓰기 하나뿐이다(편집실
자막 탭이 "아래는 전사된 대사 원본"이라 부르는 그것). 사람이 고를 통로가 없다.
채널 디자인 키 하나로 그 통로를 만든다.

**오케스트레이터 쪽은 이미 나갔다** — 엔진이 플래그를 받는 순간 켜진다:

- `ves/adapters/aivideo.py` `CHANNEL_DESIGN_FLAGS["transcribe_backend"] =
  "--transcribe-backend"` · `TRANSCRIBE_BACKENDS = ("default","elevenlabs")` ·
  `_transcribe_value`(허용값 밖 즉시 실패)
- `ves/control/migrations/0072_channel_transcribe_backend.sql` —
  `set_channel_design` v_allowed + 값 검증 + `ops_config.channel_transcribe='off'` 시드
- 대시보드 채널 설정 모달 '자막 전사' 선택칸 (게이트 `channel_transcribe` 뒤)

## 계약 (이대로 구현해라 — 오케스트레이터가 이미 이 형태로 보낸다)

```
--transcribe-backend {default|elevenlabs}
```

- **미지정 = 지금 그대로**. 플래그가 없는 실행은 한 글자도 안 바뀌어야 한다(회귀 0).
- `default` = 지금의 내장 전사 경로(무엇을 쓰는지는 엔진 소유 —
  오케스트레이터는 이름만 안다). 명시해도 미지정과 같은 결과.
- `elevenlabs` = ElevenLabs Scribe STT.
- 허용값 밖은 **argparse `choices` 로 즉시 실패**. 조용히 기본값으로 떨어지면
  사람은 일레븐랩스로 바꿨다고 믿은 채 종전 전사로 발행된다(registry 원칙).

## E11-1. 백엔드 분기 (중)

- `chunk_transcribe` 단계의 받아쓰기 호출부를 백엔드 인터페이스 하나로 감싼다:
  입력 = 오디오(또는 청크) 경로 + 언어, 출력 = **지금 내부 표현 그대로**
  (segment: `text` · `start` · `end`, 필요하면 word 단위). 분기는 그 뒤에서 끝나야
  하고, `subtitle_segments.json` 이하 downstream 은 백엔드를 몰라야 한다.
- 청크 분할·병합·타임코드 오프셋 규칙은 지금 것을 그대로 쓴다 — 두 백엔드가 같은
  좌표계로 돌아와야 편집실 앵커(`source_time_sec` 역산)가 두 경로에서 같이 산다.

## E11-2. ElevenLabs Scribe 어댑터 (중)

아래는 2026-08-21 조사분이다. **구현 전에 살아 있는 값인지 한 번 확인해라** —
이 저장소에서 elevenlabs.io 로 나가는 길이 막혀 있어 공식 문서 미러·SDK 소스에서
확인한 것이고, 이 API 는 올해 두 번 갈아엎였다.

```
POST https://api.elevenlabs.io/v1/speech-to-text
Header:  xi-api-key: $ELEVENLABS_API_KEY
Body:    multipart/form-data
  model_id=scribe_v2            # ← v2 다. scribe_v1 은 폐기(제거 예정일 2026-07-09,
                                #    이미 지났다). 문서 enum 에는 아직 남아 있으니 믿지 마라
  file=@audio.wav
  language_code=kor             # ISO-639-3. 'ko' 도 받는다
  timestamps_granularity=word   # 기본값이지만 명시해라
  tag_audio_events=false        # ⚠ 기본이 true 다 — 켜두면 자막에 '(laughter)' 가 섞인다
  diarize=false                 # 화자 분리가 필요하면 true (num_speakers 1~32)
```

- 자격증명은 **환경변수**(`ELEVENLABS_API_KEY`). 코드·설정 파일에 키를 박지 마라.
  키가 없는데 `--transcribe-backend elevenlabs` 가 오면 **즉시 실패**하고 메시지에
  "무엇을 어디에 넣어야 하는지"를 써라 — 조용히 기본 전사로 떨어지면 안 된다
  (vlp `dub_argv` 의 voice_id 없음 처리와 같은 규율).
- **오디오만 보내라.** 영상 파일도 받아주지만 60초 1080p mp4 는 30~80MB, 같은 길이의
  모노 wav 는 ~1MB 다. `ffmpeg -i in.mp4 -vn -ac 1 -ar 16000 -c:a pcm_s16le out.wav`
  + `file_format=pcm_s16le_16`. **두 백엔드에 똑같은 전처리를 먹여야** E11-3 의 비교가
  의미를 가진다.
- **응답 `words[]` 를 그대로 쓰지 마라.** `type` 이 `word` · `spacing`(폭 0) ·
  `audio_event` 세 가지로 섞여 온다 — `type == "word"` 만 걸러서 cue 로 묶어라.
  안 거르면 줄 길이·타이밍이 조용히 어긋난다. 필드: `text` · `start` · `end`(초) ·
  `type` · `speaker_id` · `logprob`(음수, 클수록 확신).
- `logprob` 는 공짜로 오는 **줄별 확신도**다. 낮은 줄을 결과 로그에 남기면 검수자가
  어디를 볼지 안다(지금 내장 전사에는 없는 것 — 이 백엔드의 실질 이득 중 하나).
- **SRT 를 직접 짜지 마라(검토 사항).** `additional_formats`(⚠ 일반 폼 필드가 아니라
  **multipart 파일 파트**로 보내는 JSON) 에 `srt` 를 요청하면
  `max_characters_per_line` · `max_segment_duration_s` ·
  `segment_on_silence_longer_than_s` 로 끊어 만들어 준다. 다만 지금 파이프라인의
  cue 규칙과 어긋나면 쓰지 마라 — **두 백엔드가 같은 좌표계·같은 cue 규칙으로
  돌아오는 것이 E11-1 의 전제**다. 어느 쪽을 택했는지 보고에 써라.
- 실패 분류: 401·403·잘못된 인자 = permanent, 429·5xx·네트워크 = transient(재시도).
  8분 넘는 파일은 ElevenLabs 가 알아서 쪼개 최대 4개를 동시에 돌린다(동시성 예산에
  잡힌다). 쇼츠 길이에서는 무관하다.
- **비용을 로그로 남겨라** — 분 단위 과금이다(조사 시점 배치 $0.22/오디오시간 ≈
  60초 클립 $0.004. 요율은 바뀐다 — 살아 있는 값을 확인해라). 응답의
  `audio_duration_secs` 와 백엔드 이름을 run 로그에 남겨 정산이 가능하게 해라.

## E11-3. 실측 검증 (필수)

**한국어 정확도는 실측으로만 판단해라.** ElevenLabs 마케팅 페이지는 한국어 WER
3.1%(FLEURS)를 말하는데 같은 회사 문서의 언어 등급표는 한국어를 훨씬 아래 칸에
놓은 것으로 보인다(2026-08-21 조사에서 두 값이 충돌했고 확정하지 못했다). 어느
쪽이든 FLEURS·Common Voice 는 **낭독체 스튜디오 음성**이라 예능 대사(겹말·배경음악·
은어·한영 혼용)에는 그대로 옮겨지지 않는다. 참고로 Whisper large-v3 는 자발 발화
한국어(KsponSpeech)에서 CER 11% 대다.

⚠ 한국어는 **WER 대신 CER 로 재라** — 띄어쓰기 규칙 차이만으로 WER 이 10%p 넘게
흔들려 같은 소리를 두고 엉뚱한 결론이 난다.

한국어 소스 1편(예능 대사가 실제로 섞인 편)으로 두 백엔드를 각 1회 돌리고 보고하라.

1. 완성본 자막의 **싱크**(첫 줄·중간·끝 줄) — 두 경로가 같은 좌표계인가.
2. 받아쓰기 **정확도**(CER) 와 체감 차이(고유명사·겹말·배경음악 구간·한영 혼용).
3. 소요 시간과 요금(`audio_duration_secs` × 단가).
4. `--transcribe-backend` 없는 실행이 종전과 **완전히 같은지**(회귀 0).
5. `tag_audio_events=false` 로도 `(laughter)` 류가 새어 들어오지 않는지.

## 완료 보고에 명시할 것

커밋 sha · 플래그 이름과 choices 그대로 · 자격증명 환경변수 이름 · 실패 분류 표 ·
E11-3 실측 4항목. 오케스트레이터 파트(어댑터·RPC·화면)는 이미 있으므로, 전 노드
`last_seen_sha` 확인 후 `ops_config channel_transcribe = on` 만 남는다.

먼저 `chunk_transcribe` 호출부와 `subtitle_segments.json` 생성 경로, `app/cli.py`
의 플래그 처리부를 읽고 계약을 확정한 뒤 구현해라.
