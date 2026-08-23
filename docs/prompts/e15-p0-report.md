# L-P0 실측 보고 — 이관 인벤토리 · 의존성 · updater 진단 (2026-08-23)

기획서: [`docs/LOCALIZE_UNIFY.md`](../LOCALIZE_UNIFY.md) §9 단계표의 **P0**.
완료 판정은 두 가지였다 — ① 파일별 이관/합치기/폐기 판정표 ② 6대 pip sync
용량·소요·실패 복구 실측치. ①은 아래 §1 에서 끝났고, ②는 **절반**이다:
용량·해석은 쟀고(§2), 시간·복구는 **노드에서 재야 한다**(§2-4, 도구 동봉).

P0 에서 나온 것 중 **가장 중요한 것은 §3 이다.** 기획서 §10-1 완충책 ①이
"updater 가 pip sync 실패 시 이전 venv 를 유지하는지 먼저 확인·보강한다"였는데,
확인 결과 **유지되지 않았고, 더 나쁜 경로가 하나 더 있었다.**

---

## 0. 한 줄 요약

| # | 항목 | 결과 |
|---|---|---|
| 1 | 이관 인벤토리 | 29개 파일 · 8,775줄 → 이관 36% · 분해 40% · 폐기 15% · 승격 8% · 합치기 1% |
| 2 | 의존성 용량 | 현재 411 MiB(124개) → 이관 후 **약 720 MiB(161개)**, +75% |
| 3 | **opencv 이중 설치** | paddleocr 가 `opencv-contrib-python` 을 끌어와 ai-video 의 `opencv-python` 과 **같은 `cv2` 를 덮어쓴다** — 얼굴검출(reframe)이 걸려 있는 자리다 |
| 4 | **updater 결함 3건** | pip 타임아웃이 예외로 새고, venv 복원이 없고, 예외 시 노드가 **검증 안 된 venv 로 자동 복귀**했다 → 이번 커밋에서 보강 |
| 5 | 도구 2종 | `localize_ab.py`(회귀 0 판정) · `deps_probe.py`(노드 실측) |
| 6 | 미결 해소 | brain 리포 접속 확인 — 기획서 §6-7 델타가 정본과 일치(§5) |

---

## 1. 이관 인벤토리

판정 다섯 가지:

- **이관** — ai-video `app/localize/` 로 파일째 옮긴다
- **분해** — 한 파일이 여러 목적지로 쪼개진다 (가장 손이 많이 간다)
- **합치기** — ai-video 에 같은 일을 하는 코드가 이미 있다
- **승격** — 엔진이 아니라 **관제**의 일이다 → ves-orchestrator
- **폐기** — 옮기지 않는다

| 파일 | 줄 | 판정 | 목적지·근거 |
|---|---:|---|---|
| `engine/__init__.py` | 14 | **폐기** | 새 패키지 __init__ 이 대체 |
| `engine/common.py` | 410 | **분해** | ffmpeg 헬퍼→ai-video ffmpeg_utils 합치기 / 설정·경로·로깅→localize 축소판 |
| `engine/cuts.py` | 129 | **이관** | localize/external/cuts.py — E9 계약 그대로 |
| `engine/detect.py` | 331 | **이관** | localize/external/detect.py — OCR |
| `engine/inpaint.py` | 218 | **이관** | localize/external/inpaint.py — 상업 게이트 유지 |
| `engine/llm.py` | 121 | **합치기** | ai-video gemini_client.py — 모델 규칙(pro/flash 2종) 고정 |
| `engine/mask.py` | 136 | **이관** | localize/external/mask.py |
| `engine/qa.py` | 173 | **이관** | localize/qa.py — 인페인팅 품질 프록시 |
| `engine/qa_compare.py` | 187 | **폐기 후보** | 레포 안 호출자 0 — 죽은 코드. 확인 후 폐기 |
| `engine/render.py` | 595 | **분해** | ASS 조립→subtitle.py 합치기 / 스타일 태그(편집실 계약)→그대로 이관 / 번인→external/overlay.py |
| `engine/schemas.py` | 184 | **이관** | localize/__init__.py 계약 dataclass |
| `engine/translate.py` | 212 | **이관** | localize/translate.py |
| `scripts/localize_run.py` | 917 | **이관** | ★핵심 — localize/ L0~L5 로 분해 |
| `scripts/yt_upload_test.py` | 221 | **폐기** | 일회성 점검 스크립트 |
| `src/autopilot.py` | 1004 | **분해** | scan→수집기 승격 / score→선별기 승격 / process→어댑터+CLI / approve·upload·auto_*→폐기 |
| `src/convert_short.py` | 314 | **폐기** | 등급 J — 운영 부하 0, overlay 가 흡수 |
| `src/dub.py` | 1469 | **분해** | EL 합성→tts.py 합치기 / 전사→speech·stt_elevenlabs 합치기 / 타이밍·믹스·보컬분리·백체크→external/dub.py |
| `src/jp_score.py` | 130 | **승격** | 선별기 게이트 2 (§5-6) |
| `src/ledger.py` | 324 | **승격** | PG 아카이브 external_shorts (0077) |
| `src/metadata.py` | 122 | **이관** | localize/meta.py |
| `src/notify.py` | 63 | **폐기** | 오케스트레이터 obs/notify.py 가 있다 |
| `src/precheck.py` | 236 | **이관** | localize/external/precheck.py — 선별기 게이트 1-c |
| `src/process_video.py` | 271 | **폐기** | 오케스트레이션은 어댑터+CLI 몫 |
| `src/refbank.py` | 206 | **이관** | localize/external/refbank.py — 더빙 음색 |
| `src/scout.py` | 214 | **승격** | 수집기 loopy_scout (§6-3) |
| `src/select.py` | 136 | **폐기** | 자기채널 analytics 기반 — 선별기가 대체 |
| `src/thumbnail.py` | 122 | **이관** | localize/thumbnail.py |
| `src/uploader.py` | 137 | **폐기** | 오케스트레이터 발행 경로 |
| `src/voice_clone.py` | 179 | **이관** | localize/external/voice_clone.py — EL IVC |
**합계 8,775줄** — 이관 3,165(36.1%) · 분해 3,478(39.6%) · 폐기 1,156(13.2%) ·
승격 668(7.6%) · 폐기 후보 187(2.1%) · 합치기 121(1.4%).

### 1-1. 읽는 법

- **"분해"가 40% 로 가장 크다** — `autopilot.py`(1,004) · `dub.py`(1,469) ·
  `render.py`(595) · `common.py`(410) 네 파일이다. 이 넷이 P0~P4 작업량의 대부분이고,
  넷 다 **여러 관심사가 한 파일에 있어서** 그렇다. 통째로 옮기면 ai-video 에 중복이
  생기고(전사·TTS·ffmpeg 탐색이 두 벌), 쪼개면 회귀 위험이 커진다 — 그래서 §4 도구로
  판정하며 옮긴다.
- **폐기 15% 는 대부분 "오케스트레이터가 이미 하는 일"이다** — `uploader.py`(발행)·
  `notify.py`(알림)·`process_video.py`(오케스트레이션)·`select.py`(선별).
  vlp 가 독립 운영되던 시절의 잔재이고, 지금은 관제가 그 자리를 갖고 있다.
- **`engine/qa_compare.py`(187줄)는 레포 안에 호출자가 없다.** 테스트만 있다.
  죽은 코드로 보이나 P0 에서 단정하지 않는다 — 폐기 후보로 두고 P4 에서 확인한다.
- **승격 668줄(`scout.py` + `jp_score.py` + `ledger.py`)이 §5-6 선별기의 몸통이다.**
  새로 쓰는 게 아니라 옮기는 것이라는 기획서의 주장이 줄 수로 확인된다.

---

## 2. 의존성 실측

### 2-1. 잰 방법과 그 한계

macOS arm64 · cp312(노드 부트스트랩이 `python@3.12` 를 깐다) 기준으로
`pip install --dry-run --report` 해석 + 각 휠의 `Content-Length` 합.

🛑 **리눅스에서 잰 값에는 구멍이 하나 있다.** pip 은 `--platform macosx_…` 를 줘도
환경 마커(`platform_system`)를 **실행 중인 OS** 로 평가한다. 그래서 torch 를 끼우면
macOS 에 없는 CUDA 패키지를 끌어와 `ResolutionImpossible` 이 난다 — **노드의 충돌이
아니라 측정 도구의 한계다.** 아래 수치는 torch 계열을 빼고 해석한 뒤 그 셋의 macOS
arm64 휠 크기를 따로 더한 값이다.

> 운영 함의: **requirements 변경은 리눅스 CI 에서 사전 검증할 수 없다.**
> 반드시 노드에서 `deps_probe.py` 로 확인해야 한다(§4-2).

### 2-2. 용량

| 구성 | 패키지 | 휠 합계 |
|---|---:|---:|
| 현재 ai-video | 124 | 411 MiB |
| + 더빙 경로(elevenlabs·psycopg2·pyyaml) | 126 | 417 MiB |
| + OCR·인페인팅(paddleocr·paddlepaddle·rapidocr·scikit-image) | 158 | 649 MiB |
| + torch 계열(torch 71.0 · torchaudio 0.8 · demucs) | ~161 | **약 720 MiB** |

신규 35개 중 큰 것: `paddlepaddle` 99.7 · `opencv-contrib-python` 60.7 ·
`scipy` 26.9 · `rapidocr-onnxruntime` 14.2 · `scikit-image` 11.5 MiB.

⚠ 참고 — **현재 411 MiB 중 절반이 이미 `tensorflow`(213.1 MiB)다.** `deepface`
(얼굴검출)가 끌고 온다. "무거운 의존" 문제는 이관이 만드는 게 아니라 이미 있고,
이관은 그 위에 +75% 를 얹는다. 디스크에 풀린 크기는 통상 휠의 2~3배다.

### 2-3. 🛑 opencv 이중 설치 — 가장 위험한 발견

해석 결과 `opencv-python`(기존)과 `opencv-contrib-python`(paddleocr 가 요구)이
**한 venv 에 함께** 들어온다. 둘은 같은 `cv2` 패키지를 배포하므로 **나중에 설치된
쪽이 앞의 것을 덮어쓴다.**

하필 그 자리에 ai-video 의 명시적 제약이 걸려 있다:

```
opencv-python>=4.9.0.80,<5   # 5.x 는 번들 haarcascade 를 제거해 얼굴검출(reframe) 단계가 죽는다
```

지금 해석에서는 contrib 가 4.10 이라 `<5` 안이지만, **그 핀은 `opencv-python` 에만
걸려 있고 contrib 에는 안 걸린다.** contrib 가 5.x 로 올라가는 날 `reframe` 이
조용히 죽고, 원인은 requirements 어디에도 안 보인다.

**조치(P4 전에):** ① `opencv-contrib-python` 에 같은 상한을 명시하거나
② paddleocr 를 `--no-deps` 로 깔고 contrib 를 배제하거나 ③ 아예 contrib 하나로
합친다(contrib 는 base 의 상위집합). 어느 쪽이든 **선택을 requirements 에 적어야**
한다 — `deps_probe.py` 가 이 조합을 검사해 경고한다.

### 2-4. 노드 실측 (macmini · darwin · py3.12.13 · 2026-08-23)

`scripts/requirements-localize-probe.txt` 로 실제 노드에서 잰 값이다.

| 항목 | 결과 |
|---|---|
| **해석** | ✅ **통과** — 165개(신규 42 · 변경 21 · 다운그레이드 3). arm64 에서 `ResolutionImpossible` 없음 ⇒ §2-1 의 리눅스 실패는 측정 도구 한계가 맞았다 |
| **디스크** | 현재 venv **1.8 GiB** → 후보 **3.1 GiB** (**+1.3 GiB/노드**, 6대면 +8 GiB) |
| 설치 시간 | 36초 — **쓸 수 없는 값**(아래 ⚠) |
| **paddlepaddle arm64** | ✅ **`import paddle` 3.3.1 성공** — route B 이관의 전제가 풀렸다 |
| import 스모크 | cv2·paddle·paddleocr·rapidocr·torch(2.13.0)·torchaudio(2.11.0)·demucs(4.1.0)·faster_whisper·skimage **전부 OK** |
| 실패 복구 | ⏳ 미실시 (일부러 깨진 requirements 로 갱신 → 노드 상태 확인 — DB·워커 필요) |

⚠ **36초는 캐시가 더운 값이라 타임아웃 근거로 쓸 수 없다.** 3.1 GiB 를 36초에 깔 수는
없다 — `--resolve` 와 기존 설치가 pip HTTP 캐시를 이미 채워 놨다. 여기에 "3배"를 적용해
`PIP_TIMEOUT_SEC=108` 로 잡으면 **새로 깐 노드가 첫 갱신에서 전부 타임아웃**한다.
도구에 `--cold`(`--no-cache-dir`)를 넣었고, 그 값이 나오기 전까지는 **현재 기본
3600초를 유지**한다.

### 2-5. 🛑 cv2 실측 — 이름 비교로는 안 보이는 다운그레이드

스모크가 잡았다. 해석표와 런타임이 어긋난다:

| | 버전 |
|---|---|
| 해석표 `opencv-python` | 4.14.0.94 |
| 해석표 `opencv-contrib-python` | 4.10.0.84 |
| **실제 `cv2.__version__`** | **4.10.0** ⇒ contrib 가 이겼다 |

즉 `cv2` 가 **4.14 → 4.10 으로 내려앉는다.** 그런데 이 다운그레이드는 §2-2 의
다운그레이드 3건(numpy·opt-einsum·pyyaml)에 **안 들어 있다** — 두 배포판은 패키지
**이름이 달라서** 버전 비교가 성립하지 않기 때문이다. `find_conflicts` 가 공존을
경고하고 `--smoke` 의 `cv2_winner` 가 승자를 지목해야만 보인다.

**권고(확정): 옵션 ③ — `opencv-contrib-python` 하나로 합친다.**
contrib 는 base 의 상위집합이고 `cv2/data/haarcascades` 도 함께 싣는다(얼굴검출
전제 충족). 둘을 같이 두면 *설치 순서*가 버전을 정하는데, 그건 requirements 어디에도
안 적히는 우연이다. 상한(`<5`)은 남는 한 패키지에 그대로 옮긴다.

### 2-6. numpy 다운그레이드

`numpy 2.5.1 → 2.3.5`. 신규 42개보다 이쪽이 위험하다 — 지금 도는 **deepface(얼굴검출)·
opencv·faster-whisper 가 전부 그 numpy 위에서** 돈다. 스모크에서 셋 다 import 는
되지만, import 가 곧 동작은 아니다. P1~P4 에서 requirements 를 실제로 바꾸기 전에
**얼굴검출·전사 산출을 A/B 로 확인**해야 한다(`localize_ab.py` 가 아니라 기존
`test_e1*` 회귀 + 실렌더 1편).

---

## 3. 🛑 updater 진단 — 부분 설치된 venv 로 노드가 되살아난다

기획서 §10-1 완충책 ①의 확인 결과다. `ves/agent/updater.py` 를 읽고 세 갈래를 찾았다.

### ① pip 타임아웃이 예외로 샌다 → 노드가 자동 복귀한다 (가장 위험)

```
_pip_sync:  subprocess.run(..., timeout=1800)      # try/except 없음
```

`TimeoutExpired` 는 `_update_engine` → `check_and_update` 를 그대로 뚫고 나간다
(`try:` 에 `finally:` 만 있고 `except` 가 없다). 그러면:

1. 노드는 `_set_node(draining, updating=True)` 상태로 **남는다**
   (실패 경로의 `disabled` 처리를 건너뛰었으므로)
2. 코드는 이미 `checkout target` 이 끝나 **새 sha** 다
3. 다음 주기에 `check_and_update` 는 `cur == target` 이라 **아무것도 안 하고**
   끝에서 `_reactivate_if_self_drained()` 를 부른다
4. 그 함수는 `updating_since IS NOT NULL` 인 노드를 **`active` 로 되돌린다**

⇒ **새 코드 + pip 이 중간에 끊긴 venv** 로 잡을 받기 시작한다.
기획서가 "부분 설치된 venv 로 계속 도는 것이 최악"이라고 쓴 바로 그 상태이고,
지금 코드로 도달 가능하다. torch·paddlepaddle 이 들어오면 1800초 초과가
가정이 아니라 일상이 된다.

### ② pip 실패 시 venv 를 복원하지 않는다

```
if not _pip_sync(...):
    _git(path, "checkout", "--quiet", prev_sha)   # 코드만 롤백
    return False
```

`pip install` 은 원자적이지 않다 — 실패해도 새 패키지 일부가 남는다. 코드만 되돌리면
**옛 코드 + 새 패키지**라는, 아무도 검증한 적 없는 조합이 된다. 노드가 `disabled` 라
잡은 안 돌지만, 사람이 다시 켜면 그 조합으로 돈다.
(smoke 실패 경로는 이전 requirements 재설치를 **시도는 한다** — 두 경로가 달랐다.)

### ③ 복원 실패가 조용하다

smoke 경로의 복원 `_pip_sync(...)` 는 반환값을 버린다. 복원까지 실패해도 아무도 모른다.

### 보강 (이번 커밋)

| 고친 것 | 어떻게 |
|---|---|
| ① | `_pip_sync` 가 `TimeoutExpired` 를 **실패로 흡수**(예외 안 냄) + `check_and_update` 가 `_update_engine` 예외를 잡아 실패와 동일 처리 → `disabled` + `updating_since` 정리로 자동 복귀 경로 차단 |
| ② | 실패 두 경로를 `_rollback()` 하나로 통일 — **코드 롤백 + 이전 requirements 재설치** |
| ③ | 복원 실패 시 `_alert` 로 "부분 설치 상태일 수 있음 · 수동 복구 필요" 명시 |
| 시간 | 상한을 `PIP_TIMEOUT_SEC`(기본 3600, env `VES_PIP_TIMEOUT_SEC`)로 뺐다 — §2-4 실측 후 조정 |

회귀 가드: `tests/test_updater_failure_paths.py` 6건 (전체 239 passed).

> ⚠ 이 보강은 **부분 설치를 없애지 못한다** — pip 에 트랜잭션이 없기 때문이다.
> 없앤 것은 *부분 설치된 채 조용히 active 로 돌아가는 경로*다. 진짜 격리(venv 를
> 새로 만들어 성공했을 때만 교체)는 별건으로 다룰 값어치가 있으나 P0 범위 밖이다.

---

## 4. 도구

### 4-1. `ai-video/scripts/localize_ab.py` — 회귀 0 판정

```bash
python -m scripts.localize_ab --snapshot outputs/JOB --to /tmp/snap_old   # 구 엔진 산출 보관
python -m scripts.localize_ab --a /tmp/snap_old --b outputs/JOB           # 신 엔진 후 대조
```

재는 것: 최종 mp4 길이·**샘플 프레임 해시 12장** · `subtitle_segments.json` 구조 동일성
(줄 단위 차이 요약) · metadata 제목·설명 · `ko_ja_pairs` · 백업 디렉토리.

설계에서 중요한 두 가지:

- **부동소수 잡음을 회귀로 잡지 않는다** — 시각은 ms 로 반올림해 비교한다.
  안 그러면 같은 계산도 경로가 다르면 1e-9 자리가 흔들려 전부 차이로 뜬다.
- **번역문 차이는 판정에서 뺀다**(`~~` 로 표시만). LLM 은 런마다 다르므로 회귀 판정에
  넣으면 항상 빨간불이다. 고정 `translation.json` 을 주입한 대조에서만 `--strict` 로 켠다.
- `ko_ja_pairs` 는 **ko 와 ja 를 나눠 센다** — ja 만 달라지면 LLM 잡음일 수 있지만
  **ko 가 달라지면 번역 이전 단계가 흔들린 것**이라 성격이 다르다.

회귀 가드: `tests/test_localize_ab.py` 18건.

### 4-2. `ai-video/scripts/deps_probe.py` — 노드 실측

```bash
python -m scripts.deps_probe                                     # 현재 venv + 충돌 신호
python -m scripts.deps_probe --resolve requirements.txt          # 해석만
python -m scripts.deps_probe --resolve requirements.txt --install  # 시간·용량 실측
```

- `opencv-python` × `opencv-contrib-python` 같은 **같은 모듈을 덮어쓰는 조합**을 검사한다(§2-3).
- **버전 변경(업그레이드)을 신규 설치보다 위쪽에 세워 보여준다** — 새 패키지는 안 쓰면
  그만이지만, 쓰던 패키지가 올라가면 지금 도는 채널이 조용히 달라진다.
- `--install` 의 소요 시간이 `PIP_TIMEOUT_SEC` 를 정하는 근거다(3배 이상 권장).

---

## 5. 미결 해소 — brain 정본 대조

`rhoonart-dev/ai-improvement-edit-video`(4839931)를 붙여 `config/channels.json` 을
직접 확인했다. 채널 21개, LOOPY·SHOTCONE 모두 사용자가 준 내용과 **일치**한다.

| 채널 | pipeline | country | source |
|---|---|---|---|
| SHOTCONE | (없음) | JP | (없음) |
| LOOPY | `zanmang_autopilot` | JP | **(없음)** |

⇒ 기획서 §6-7 델타(LOOPY `pipeline` 교체 + `source` 신설)가 정본 기준으로 맞다.
`source` 필드는 두 JP 채널 모두에 없으므로 **신설이 맞다**(원 채널이 vlp
`pipeline.config.yaml` 의 `channel_handle: "@zanmangloopy"` 에만 있다).

---

## 6. P0 판정 · 다음

| 완료 판정 | 상태 |
|---|---|
| 파일별 이관/합치기/폐기 판정표 | ✅ §1 |
| 의존성 용량·해석 | ✅ §2 (리눅스 한계 명시) |
| 의존성 해석·디스크·스모크 | ✅ §2-4 노드 실측 — 해석 통과 · +1.3 GiB/노드 · **paddle arm64 OK** |
| 의존성 콜드 설치 시간 | ⏳ `--cold` 로 재측정 필요(36초는 캐시 웜) |
| 실패 복구 실측 | ⏳ 노드에서 (DB·워커 필요) |
| A/B 하네스 | ✅ §4-1 |
| updater 확인·보강 | ✅ §3 (요구된 것은 확인이었고, 결함이 나와 보강까지 했다) |

**P0 의 큰 질문 두 개가 다 풀렸다:**

1. **paddlepaddle 이 arm64 에서 도는가** → ✅ 된다. 기획서 §10-1 완충책 ④(rapidocr 로
   뒤집기)는 **발동하지 않는다.** route B 이관을 계획대로 진행한다.
2. **의존성이 감당 가능한가** → 노드당 +1.3 GiB. 6대면 +8 GiB. 감당 가능하다.

**남은 것은 P1 을 막지 않는다** — 콜드 설치 시간과 실패 복구 실측은 requirements 를
실제로 바꾸는 **P4** 의 전제지, P1(rerender 계층 이관, 추가 의존성 0)의 전제가 아니다.
따라서 **P1 을 지금 시작한다.**

P4 전에 반드시 끝낼 것:
- `--cold` 설치 시간 → `PIP_TIMEOUT_SEC` 확정 (그때까지 기본 3600 유지)
- opencv 를 contrib 하나로 합치기(§2-5) + 상한 이설
- numpy 2.3.5 위에서 얼굴검출·전사 산출 A/B (§2-6)
- 일부러 깨진 requirements 로 갱신 → 노드가 `disabled` 로 멈추고 자동 복귀하지 않는지 확인(§3 보강 검증)
