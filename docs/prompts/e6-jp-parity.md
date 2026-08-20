# E6 — JP 편집실 완전 동등화: vlp 엔진 확장 발주서

vlp(video-localization-project) 엔진 세션용 작업 프롬프트. 목표: 일본 채널
편집실(잔망루피 LOOPY, 혜미리예채파 SHOTCONE)을 KR 편집실과 동등하게 —
대시보드가 지금 계약으로 할 수 있는 것(JP-3a)은 이미 붙었고, 아래는 엔진이
계약을 넓혀야 열리는 나머지다. 좌표 정본: 오케스트레이터 p_edits
(reject_and_rerender, idx 좌표 diff — 값은 문자열 또는
dict{ja?, style?, start_sec?, end_sec?, use?}).

## 컨텍스트 (기존 자산 — 먼저 읽기)

- E5 산출(현행 배포 72d4cd5): `docs/subtitle-style-overrides.md`,
  `scripts/localize_run.py`(apply_overrides·build_ko_ja_pairs·l3t_tts·l4_render),
  `engine/render.py`(validate_line_style·render_replace),
  `engine/common.py`(burn_subtitles), `src/dub.py`(apply_dub_overrides),
  B/BJ 루트 `ja_events.json`(entry_idx 좌표).
- 오케스트레이터 측 소비자: 대시보드가 pairs 의 subs/tts/telops 에서
  start/end(+style)를 읽어 타임라인·유령 자막을 그린다. **pairs 에 넣는 것 =
  화면에 생기는 것.**

## 작업 항목 (독립적 — 각각 별 커밋 권장)

### E6-1. SHOTCONE tts 타이밍 오버라이드 수용 (중)
지금은 tts idx 값에 start_sec/end_sec 가 오면 즉시 ValueError.
- apply_overrides 거절 해제 → tts cue 의 창(start~end)을 사용자 값으로 교체
- l3t 재합성: 새 창 길이에 맞춰 rate 재계산(기존 '창 초과 시 rate 상향' 로직 재사용)
- checkpoint_resources 의 cue 타이밍 갱신 — build_ko_ja_pairs 가 다음 카드에
  **사용자 값**을 동봉해야 한다(안 그러면 편집실이 매번 옛 값으로 되돌아 보인다)
- 창 겹침(앞뒤 cue 침범)은 fail-loud 가 아니라 검증 거절(명확한 한국어 메시지)

### E6-2. tts 목소리 선택 (중)
- tts idx dict 에 `voice` 키 신설(edge-tts 보이스 id 문자열)
- l3t 의 locale 단위 vmap 을 per-cue 오버라이드로 — 모르는 보이스 id 는 거절
- pairs.tts 에 현재 voice 동봉(화면 셀렉트의 현재값)

### E6-3. 합성 mp3 내보내기 — 미리듣기 (소~중)
- l3t 산출 cue별 mp3 를 스토리지(ves-localized 권장)에 업로드하고
  pairs.tts[].audio_key 로 동봉 — 대시보드가 서명 URL 로 재생(KR F-204 상당)
- 실패는 비치명(키 없으면 화면이 버튼을 안 그림)

### E6-4. 이미지 오버레이 (중 — 선확인 1건)
- **선확인**: SHOTCONE 재렌더가 타는 ai-video `--from-step render` 가
  edit_overrides.images 를 읽는지. 읽으면 SHOTCONE 은 그 경로로 끝(엔진 무변경).
- LOOPY BJ/C: burn_subtitles 의 `-vf ass` 를 `-filter_complex`(overlay×N + ass)로
- LOOPY B(replace): render_replace 에 Pillow paste
- 계약: p_edits 최상위 `images` 배열 — {key(editor_uploads/ 스토리지),
  start_sec, end_sec, x, y, w(0~1, 캔버스 비율), layer, rotate}. 실물은 엔진이
  스토리지에서 직접 다운로드(404 = 명확한 실패). png/jpg 만.
- 구 엔진과의 공존: 모르는 최상위 키는 **조용히 무시**가 현행 동작인지 확인하고
  아니면 무시로 통일 — 오케스트레이터는 전 노드 배포 확인 후 플래그로 개방한다.

### E6-5. LOOPY B(replace) 루트 자막 스타일·타이밍 번인 반영 (중)
E5 에서 사이드카(ass/srt)에만 반영되던 것 — 번인 경로에도.
docs/subtitle-style-overrides.md 의 '후속' 명시 항목.

### E6-6. pairs 에 fps·duration 동봉 (소)
대시보드 타임라인이 프레임 스냅과 축척에 쓴다. 없으면 0.01s 스냅으로 동작하니
데이터만 넣으면 된다.

## 멈춤 시점 (critical 만)

1. E6-1 에서 checkpoint 갱신이 **기존 재개(resume) 체인을 깨뜨릴 위험**이
   보이면 — 갱신 방식을 정하기 전에 보고.
2. E6-4 선확인 결과 ai-video 가 images 를 안 읽어 SHOTCONE 에 l4 overlay 체인
   신설이 필요하면 — 착수 전에 규모 보고(ko/ja 길이검증 ±0.05s 와의 상호작용 포함).

## 시작 신호

각 항목 완료 시 커밋 sha 를 알려달라 — 오케스트레이터 쪽은 전 노드
last_seen_sha 확인 후 대시보드 배선(JP-3b)과 플래그 개방을 진행한다.
