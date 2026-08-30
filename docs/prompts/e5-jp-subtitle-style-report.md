# E5 완료 보고 — 일본어 자막 줄 스타일·타이밍 (JP-2 엔진 파트, vlp)

(video-localization-project · [PR #11](https://github.com/rhoonart-dev/video-localization-project/pull/11) 머지 완료 · 2026-08-20)
계약·노출 스키마 정본: vlp `docs/subtitle-style-overrides.md` — 아래는 오케스트레이터
후속(어댑터 payload·편집실 WYSIWYG·플래그)에 필요한 요약만.

## 1. 배포 sha (플래그 게이트)

- **main `72d4cd5`** (72d4cd50dcdc8948824eeb35b6a282fb5da978bf, 기능 커밋 29bf391 포함).
- 구 엔진의 병합 함수는 오버라이드 dict 값에서 `ja` 외 키를 **조용히 무시**한다(에러
  없이 미반영). → **전 노드가 72d4cd5 이상임을 확인한 뒤에만** style·타이밍 편집 UI
  플래그를 연다.
- SHOTCONE 대사 style 은 ai-video 노드 **69e5c06 이상**(v3 F-407/F-410) 추가 전제.

## 2. 오버라이드 계약 (보내는 쪽)

subs/telops 의 dict 값에 선택 키 — 좌표(idx)는 종전 그대로:

```json
{ "ja": "…", "style": { "size": 64, "y": 0.8, "color": "#FFDD00", "rotate": -8 },
  "start_sec": 12.4, "end_sec": 15.0 }
```

- 의미 = ai-video edit_overrides/v3 subtitles[].style. size=1080×1920 px ·
  y=0~1(줄 하단, 하단=1) · color=#RRGGBB · rotate=-180~180 **시계방향 양수**
  (ASS \frz 부호 반전은 엔진 책임 — 편집실은 계약 부호만 보낸다).
- start/end = 초, 편집본(영상) 시간축. end > start.
- 검증 위반·모르는 style 키 = 거절(SHOTCONE/BJ 는 즉시 실패로 검수함에 남고,
  C 루트는 기존 정책대로 경고 후 원문 진행 → 재검수에서 걸러짐).
- **tts 의 style·start_sec/end_sec 는 후속 범위 — 지금 보내면 즉시 거절**(조용한
  무시 아님). 편집실 UI 에서 tts 줄은 스타일·타이밍 편집을 잠글 것.

## 3. 검수 노출 스키마 (읽는 쪽 — 어댑터/review_meta)

### SHOTCONE `localize_ja/metadata.json` → `ko_ja_pairs` (확장)
- `subs[] {idx, start, end, ko, ja, style?}` — end 는 클램프·오버라이드 반영 후 **실표시 값**
- `tts[] {idx, start, end, ko, ja}` — cue 계획 창(표시용, 편집 불가)
- `telops[] {idx, start, end, ko, ja, style?}` — ⚠ **좌표 전환: 이 판부터 idx = orig_index**
  (소스 onscreen_refined.json). 종전 onscreen.json 원시 순번은 translation 좌표와
  어긋난 버그였음 — 이 판 전후로 같은 영상의 telops idx 가 달라질 수 있다.
- 각 항목의 style 은 현재 적용값 — 편집실 WYSIWYG 초기값으로 쓸 것.

### 잔망루피 C `outputs/{id}/ko_ja_pairs.json` (확장)
- `subs[] {idx, start, end, end_actual, ko, ja, style?, end_fixed?}`
- `end_actual: true` = retime(실측 더빙 길이) 후 실표시 값 / `false` = 합성 전 계획값.
- `end_fixed: true` = 사용자 지정 end(아래 규칙으로 retime 미적용).

### 잔망루피 BJ/B `outputs/{id}/ja_events.json` (신설 — render 가 항상 생성)
```json
{ "video_id": "…", "coord": "translations.json entries 순번(entry_idx)",
  "events": [{"entry_idx": 3, "start": 2.0, "end": 5.5, "text": "…",
              "position": "bottom-center", "bbox": [x1,y1,x2,y2],
              "style": {…}|null, "end_fixed": false}] }
```
- BJ/B 타이밍은 detections 기반 0.5s 양자화 — 표시 구간·현재 스타일은 이 파일로 노출.
- `entry_idx` = 오버라이드 `subs{idx}` 좌표(미매칭 null). 같은 원문이 여러 구간에
  등장하면 style 은 전부, 타이밍은 첫 이벤트에만 적용된다(엔진 로그 경고).

## 4. retime 우선순위 규칙 (C 루트, 신설)

- 사용자 지정 `end_sec` 세그는 `end_fixed` 표시 → retime(실측 길이 재정렬)·다음 세그
  클램프가 **덮지 않는다**. 사용자 값이 항상 이긴다.
- 타이밍 병합은 ja_dub.srt 1차 기록 **전** → 페이싱 캡·합성 슬롯에도 사용자 타이밍 반영.
  start 이동 시 시작 시각 오름차순 재정렬.
- SHOTCONE 대응 규칙: 사용자 타이밍이 있으면 8s/20자 ASR 환각 클램프를 건너뛴다.

## 5. 검증 상태

- 단위 267개 통과. 실측 3회(프레임 픽셀): SHOTCONE 대사 style+타이밍+텔롭 회전
  (ai-video 실코드가 subtitle_segments.json style 소비 확인 — 렌더 추가 작업 불요),
  C 자막 style+end 고정, BJ style(위치·크기·색·회전 방향).
- 멈춤 조건 2건(더빙 품질 훼손 / ai-video style 미소비) 모두 미발동.

## 6. 범위 밖 (후속 백로그)

- tts 자막 style(디자인 레벨 KR 공유 해제 필요)·tts 타이밍(재합성 창 재계산).
- B replace(Pillow) 경로의 style 반영.
- (운영 이슈, 별도 진행 중) vlp 로컬 머신 ffmpeg 8 빌드에 libass 누락 — 번인 경로
  ffmpeg 지정 수리 세션이 따로 돌고 있음. 워커 노드 ffmpeg 빌드도 같은 문제인지 점검 요.
