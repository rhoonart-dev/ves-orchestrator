# L-P4 의존성 배포 — 노드 검증 절차

overlay 를 ai-video 엔진으로 돌리려면 그 venv 에 OCR·인페인트·더빙 런타임이 있어야 한다.
이 문서는 **본 requirements 를 바꾸기 전에 노드에서 확인할 것**을 적는다.

🛑 **이 변경은 6대 전 채널에 나간다.** `deployments.auto_update=true` 라 main 머지 =
즉시 배포다. 그래서 이 작업은 **브랜치에 있고**, 아래 A/B 가 통과해야 머지한다.

---

## 0. 왜 A/B 가 선결인가 (P0 §2-6)

`numpy 2.5.1 → 2.3.5` 로 내려간다. 지금 도는 **deepface(얼굴검출)·opencv·faster-whisper**
가 전부 그 numpy 위에서 돈다. P0 스모크에서 셋 다 **import 는 됐지만 import 가 곧 동작은
아니다.** 얼굴검출은 리프레임 단계라 산출 화면이 직접 바뀐다.

그리고 `opencv-python` → `opencv-contrib-python` 통합이 함께 간다(P0 §2-5 확정 권고).
contrib 는 상위집합이고 `cv2/data/haarcascades` 도 싣지만, **실물로 확인해야 한다.**

## 1. 일회용 venv 에 후보를 깐다 (운영 venv 를 안 건드린다)

```zsh
R=/opt/ves/engines
cd $R/ai-video && git fetch origin
git worktree add -f /tmp/aiv-deps origin/claude/ai-video-feature-migration-btbkqn
cd /tmp/aiv-deps

$R/ai-video/.venv/bin/python -m scripts.deps_probe \
    --resolve requirements.txt --install --smoke
```

보는 것: **해석 통과 · 다운그레이드 목록 · venv 크기 · `cv2 승자` · 스모크 전항목 OK**.

⚠ `deps_probe` 는 `--no-deps` 파일을 모른다. lama 까지 보려면 그 venv 에 직접:

```zsh
V=/tmp/deps_probe/probe_venv/bin/python
$V -m pip install -q --no-deps -r requirements-nodeps.txt
$V -c "import simple_lama_inpainting; print('lama OK')"
```

## 2. 🛑 얼굴검출·전사 A/B (P0 §2-6 이 요구한 것)

**새 numpy·cv2 위에서 기존 산출이 그대로 나오는가.** 이것이 통과해야 머지한다.

**같은 트리를 두 venv 로 돌린다.** 기억한 숫자와 맞대지 않는다 — A 판을 그 자리에서
같이 재야 '원래 있던 실패'와 '새 스택이 만든 실패'가 구분된다.

```zsh
V=/tmp/deps_probe/probe_venv/bin/python
R=/opt/ves/engines
cd /tmp/aiv-deps

# A판 — 운영 스택(현행 numpy·opencv-python)
$R/ai-video/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3 | tee /tmp/ab_A.txt
# B판 — 후보 스택(numpy 2.3.5 · opencv-contrib)
$V -m pytest tests/ -q 2>&1 | tail -3 | tee /tmp/ab_B.txt

# 어느 것이 늘었는지 이름으로
diff <($R/ai-video/.venv/bin/python -m pytest tests/ -q 2>&1 | grep -E '^(FAILED|ERROR)' | sort) \
     <($V -m pytest tests/ -q 2>&1 | grep -E '^(FAILED|ERROR)' | sort)
```

기존 회귀 가드(`test_e1*`·`test_platform_mark`·`test_e10_*`)가 얼굴검출·자막 기하를
문자열·수치로 고정하고 있다 — **새 스택에서 그 값들이 그대로 나오는지**가 1차 관문이다.

**합격선: 실패 목록이 A 판과 B 판에서 같을 것**(`diff` 가 빈 출력). 개수만 같고 종목이
바뀌면 통과가 아니다 — 하나가 낫고 하나가 상한 것을 개수가 가린다.

⚠ **주석(`#`)을 붙여 넣지 마라.** 노드 zsh 는 `interactive_comments` 가 꺼져 있어
주석이 명령의 인자가 된다(실제로 `tail: #: No such file or directory` 로 A/B 가 한 번
헛돌았다). 라벨이 필요하면 `echo` 로 낸다.

⚠ **실패 0 이 정상이다.** 노드 실측(2026-08-25 mm-06): 양쪽 다 `1103 passed, 1 skipped`.
컨테이너에서 세던 '실패 7건'은 **의존이 없어서** 나던 것이라 노드 기준이 아니다.

2차 관문은 **실렌더 1편**이다 — 리프레임이 켜진 채널로 한 편 만들어 종전 산출과 프레임을
맞대야 한다. 단위 테스트는 얼굴검출 *좌표*를 고정하지만 *검출 자체*를 재현하진 않는다.

## 2-1. 🛑 opencv 는 **두 줄** 이어야 한다 (2026-08-25 실측이 잡은 것)

1차 시도는 `opencv-python` 을 지우고 contrib 만 남겼다. 그런데 해석표에
`opencv-python: 4.14.0.94 → 5.0.0.93` 이 떴다 — **전이로 들어온다**:

```
paddlex(paddleocr)   -> opencv-contrib-python==4.10.0.84   (정확 핀)
deepface             -> opencv-python>=4.5.5.64            (상한 없음)
retina-face          -> opencv-python>=3.4.4               (상한 없음)
rapidocr-onnxruntime -> opencv-python>=4.5.1.48            (상한 없음)
```

둘은 같은 `cv2` 디렉토리를 덮어써서 **설치 순서가 승자를 정한다.** 그 실측에서는 contrib
4.10 이 이겨 무사했지만(`cv2.data.haarcascades` xml 17개) 순서가 뒤집히면 5.x 가 이기고
**번들 haarcascade 가 없어 얼굴검출이 죽는다.**

⇒ 두 배포판을 **같은 버전으로 못 박는다**(`==4.10.0.84`). 승자가 누구든 결과가 같다.
`tests/test_deps_probe.py` 가 두 줄의 버전이 같은지·5 미만인지 묶어 둔다.

## 2-2. ✅ 통과 실측 (2026-08-25 · mm-06)

```
해석     opencv-python 4.14.0.94 → 4.10.0.84   (5.x 없음)
         · 공존(같은 버전 4.10.0.84 — 승자가 누구든 같다)
런타임   cv2 4.10.0 · haarcascade xml 17건
스모크   9/9 OK + lama(--no-deps) OK
A/B      운영 1108 passed, 1 skipped · 후보 1108 passed, 1 skipped · diff 빈 출력
설치     warm 41초 · cold 96초 · 디스크 3.1 GiB (종전 1.8 GiB)
```

`PIP_TIMEOUT_SEC` 기본 3600초 대비 cold 96초 = **37배 여유**. 머지 시 6대가 동시에
받는 것을 감안해도 안전하다. 디스크는 노드 최소 여유가 26 GiB(mm-04)라 +1.3 GiB 는 문제없다.

⇒ 머지함: ai-video `98ae4b5`.

## 2-3. 🛑 2차 관문 — 리프레임 얼굴검출 실측 (`scripts/reframe_ab.py`)

1차 관문(pytest)이 재는 것은 회귀 가드의 **좌표 고정**이지 **검출 자체**가 아니다.
`numpy 2.5.1→2.3.5` · `cv2 4.14→4.10` 위에서 haar cascade 와 ArcFace 가 같은 답을
내는지는 실물로만 보인다.

🛑 **A 판(구 스택)은 노드가 갱신되기 전에 떠야 한다.** 갱신되면 운영 venv 가 곧
새 스택이라 A 판을 만들 곳이 없어진다(구 requirements 로 venv 를 다시 만들어야 한다).
`version_watch` 가 시간당 1회 `deployments.last_seen_sha` 를 올리므로 그 전에.

```zsh
R=/opt/ves/engines
V=/tmp/deps_probe/probe_venv/bin/python
cd /tmp/aiv-deps && git fetch -q origin && git checkout -q --detach origin/main

grep -l face_track $R/ai-video/outputs/*/edit_plan.json | tail -5
```

리프레임이 켜진 job 하나를 고른 뒤(소스 영상이 아직 있어야 한다):

```zsh
J=$R/ai-video/outputs/<고른-job>
$R/ai-video/.venv/bin/python -m scripts.reframe_ab --job-dir $J --out /tmp/rf_A
$V                          -m scripts.reframe_ab --job-dir $J --out /tmp/rf_B
$V -m scripts.reframe_ab --diff /tmp/rf_A /tmp/rf_B
```

**합격선: `✅ 회귀 0`.** 크롭 키프레임이 개수·좌표까지 같아야 한다(검출은 결정적이다).
임베딩만 부동소수 오차를 허용한다(기본 1e-4 — ArcFace 코사인 임계 0.4 를 뒤집기에
한참 모자란 크기). 캐스트 사진이 없어 임베딩을 건너뛴 것은 실패가 아니고 사유가 찍힌다.

크롭이 갈리면 그것이 곧 **리프레임 화면이 움직인다**는 뜻이다 — 그때는 `x_center` 차이가
얼마나 큰지(0.01 = 캔버스 1%)로 되돌릴지 받아들일지 정한다.

### 2-3-1. ✅ 실측 (2026-08-25 · mm-06 · 하트시그널 시즌5 `8951e2c7`)

```
환경     A cv2 4.14.0 · numpy 2.5.2      B cv2 4.10.0 · numpy 2.3.5
크롭     crop_hook_0    31/31 키프레임 · x 0 y 0 w 0 h 0   동일
         crop_payoff_1  11/11 키프레임 · x 0 y 0 w 0 h 0   동일
임베딩   건너뜀(checkpoint_research.json 없음)
판정     ✅ 회귀 0
```

haar cascade 검출이 **42개 키프레임 전부 좌표까지 같다.** cv2 가 4.14 → 4.10 으로
내려가고 numpy 가 2.5 → 2.3 으로 내려간 위에서 리프레임 화면이 안 움직인다.

**2판(혜미리예채파 `c2d49040`, 클립 9개 61키프레임)도 전부 동일** — 합계 **2편 · 클립
11개 · 키프레임 103개**가 좌표까지 같다.

## 2-4. 🛑 실측이 드러낸 별건 — deepface 얼굴**인식**은 지금 안 돈다

임베딩 대조를 하려다 **양쪽 스택에서 똑같이** 터졌다:

```
ValueError: You have tensorflow 2.21.0 and this requires tf-keras package.
```

`requirements.txt` 에 `tf-keras` 가 없다(어디에도). deepface 0.0.100 + tensorflow 2.21
조합은 `DeepFace.represent` 가 **항상** 이 예외를 낸다 — 노드마다 같은 requirements 라
**6대 전부** 그렇다. 운영 venv(mm-06 갱신본)에서 직접 확인했다.

- **회귀는 아니다.** 구 스택도 같은 예외라 L-P4 가 만든 문제가 아니고, 그래서 P0 §2-6 이
  지목한 deepface 축은 **잴 것이 없다**(오늘 기여가 0인 코드다).
- **대신 조용하다.** `pipeline` 은 `build_references` 실패를 인물별로 삼키고
  `[FaceID] 유효한 레퍼런스 없음 — 화자 추적 폴백` 을 찍은 뒤 계속 간다. 즉
  `enable_face_recognition` 이 켜져 있어도 **인물 타겟 리프레이밍·멀티크롭 와이드
  프레이밍은 한 번도 발동한 적이 없고**, 늘 화자 추적 폴백으로 갔다.
- **고치는 것은 별건이다.** `tf-keras` 를 넣으면 그날부터 인물 인식이 *처음으로* 동작해
  `character_focus` 를 쓰는 채널의 크롭이 **달라진다.** 지금 승인된 화면이 움직이므로
  이 A/B 와 같은 절차(구/신 크롭 대조)를 따로 밟아야 한다.

### 2-4-1. ✅ tf-keras 실측 — deepface 축도 회귀 0 (2026-08-25)

`tf-keras` 를 양쪽 일회용 venv 에 넣고 다시 뜬 결과. **P0 §2-6 이 지목한 deepface 축을
처음으로 실제로 잰 판**이다(그전에는 대상이 안 돌아 잴 수가 없었다):

```
해석     tf-keras 2.21.0 · tensorflow 2.21.0 — 신규 1개뿐, 다운그레이드 0
크롭     클립 9개 · 키프레임 61개 동일
임베딩   레퍼런스 5/5개 · 최대 절대차 4.768e-07 (허용 1e-04)
판정     ✅ 회귀 0
```

4.77e-07 은 float32 해상도 수준이다 — ArcFace 코사인 임계 0.4 를 뒤집으려면 이보다
대여섯 자리 큰 차이가 나야 한다. **numpy 2.5 → 2.3 은 ArcFace 임베딩을 안 움직인다.**

⚠ 이것은 '엔진 교체가 임베딩을 안 바꾼다'는 뜻이지 **'인물 인식을 켜도 화면이 그대로'는
아니다.** 켜면 인물 타겟 크롭과 [7/15] 인물 등장 인덱스가 *처음으로* 동작한다.

### 2-4-2. 🛑 그런데 지금은 켤 수 없다 — 재료(배우 사진)가 없다

on/off 대조를 돌리려다 도구가 `🛑 켠 판이 실제로는 안 켜졌다` 로 거절했다. 파고든 결과:

```
cast_photo_survey   혜미리예채파 2편 — 인물 6·7명 · url 0 · 파일 0 · 사용 가능 0/2
TMDB_API_KEY        /etc/ves/node.env      없음
                    /opt/ves/secrets/ves.env 없음
                    launchd                  없음
```

파이프라인은 `TMDB_API_KEY` 가 없으면 배우 사진을 **아예 안 받는다**(`cast_images =
list(research.characters)` — `image_url` 이 없는 항목). 레퍼런스가 없으면 deepface 는
할 일이 없어 화자 추적으로 간다 = **켠 것과 끈 것이 같다.**

⇒ 인물 인식은 **재료가 없어서** 못 켜는 것이지 코드가 없어서가 아니다. 순서는:
   ① TMDb 키를 붙인다(제품 결정) → ② 사진이 붙는 소재로 `cast_photo_survey` 확인 →
   ③ `reframe_ab --face-recognition` 으로 크롭 변화·인덱스 비용 측정 → ④ 채널별 옵트인.

키 없이 켜면 엔진이 그 사실을 크게 남긴다(ai-video `ef464bd`) — 조용히 폴백하지 않는다.

⚠ **표본은 2편이다.** 결정적 검출이라 표본이 커도 결과가 같을 공산이 크지만,
'같은 답을 낸다'를 본 범위는 이만큼이다.

⚠ A 판 venv 의 numpy 는 2.5.**2** 다(운영은 2.5.1 이었다) — 구 requirements 가 numpy 를
핀하지 않아 해석 시점의 최신이 잡힌다. 축(2.5 계열 vs 2.3 계열)은 그대로다.

## 3. 통과하면

```zsh
cd $R/ai-video && git worktree remove /tmp/aiv-deps --force
rm -rf /tmp/deps_probe
```

브랜치를 main 에 머지 → 6대 자동 갱신 → `deployments.last_seen_sha` 확인 →
그 다음에야 `ops_config.localize_overlay_engine` 을 `ai-video` 로 켠다.

⚠ 켜기 전에 어댑터 사전검사가 통과하는지는 **잡을 걸어 보면 안다** — 의존이 빠졌으면
비싼 단계 앞에서 무엇이 없는지 이름으로 알려 준다.

## 4. 되돌리기

| 무엇 | 어떻게 |
|---|---|
| 스위치 | `UPDATE ops_config SET value='vlp' WHERE key='localize_overlay_engine'` |
| 의존성 | 브랜치를 되돌리고 배포 — updater 가 실패 시 **이전 requirements 로 재설치**한다(P0 §3 보강) |

⚠ pip 는 `install -r` 로 **지우지 않는다.** 되돌려도 깔린 3.1 GiB 는 남는다 —
디스크를 되찾으려면 venv 를 새로 만들어야 한다.
