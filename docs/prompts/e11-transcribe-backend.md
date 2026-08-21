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
- `default` = 지금의 내장 전사 경로. 명시해도 미지정과 같은 결과.
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

- 자격증명은 **환경변수**로 받아라(예: `ELEVENLABS_API_KEY`). 코드·설정 파일에
  키를 박지 마라. 키가 없는데 `--transcribe-backend elevenlabs` 가 오면
  **즉시 실패**하고 메시지에 "무엇을 어디에 넣어야 하는지"를 써라 — 조용히
  기본 전사로 떨어지면 안 된다(vlp `dub_argv` 의 voice_id 없음 처리와 같은 규율).
- 오디오는 원본에서 뽑은 트랙을 보낸다(영상 통째 업로드 금지 — 업로드 시간·요금).
- 단어 단위 타임스탬프를 받아 지금의 segment 로 접어라. 자막은 **타이밍이 본체**라
  문장 단위 타임스탬프만으로는 지금 품질을 못 지킨다.
- 실패 분류: 401·403·잘못된 인자 = permanent, 429·5xx·네트워크 = transient(재시도).
  긴 소스는 분할 업로드/재시도 경계를 청크와 맞춰라.
- **비용을 로그로 남겨라** — 이 백엔드는 초 단위 과금이다. run 로그에 보낸 오디오
  길이와 백엔드 이름을 남겨 나중에 정산이 가능해야 한다.

## E11-3. 실측 검증 (필수)

한국어 소스 1편으로 두 백엔드를 각 1회 돌리고 다음을 보고하라.

1. 완성본 자막의 **싱크**(첫 줄·중간·끝 줄) — 두 경로가 같은 좌표계인가.
2. 받아쓰기 **정확도** 체감 차이(고유명사·겹말·잡음 구간).
3. 소요 시간과 요금(보낸 오디오 길이 × 단가).
4. `--transcribe-backend` 없는 실행이 종전과 **완전히 같은지**(회귀 0).

## 완료 보고에 명시할 것

커밋 sha · 플래그 이름과 choices 그대로 · 자격증명 환경변수 이름 · 실패 분류 표 ·
E11-3 실측 4항목. 오케스트레이터 파트(어댑터·RPC·화면)는 이미 있으므로, 전 노드
`last_seen_sha` 확인 후 `ops_config channel_transcribe = on` 만 남는다.

먼저 `chunk_transcribe` 호출부와 `subtitle_segments.json` 생성 경로, `app/cli.py`
의 플래그 처리부를 읽고 계약을 확정한 뒤 구현해라.
