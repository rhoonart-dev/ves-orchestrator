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
⚠ 참고로 병합 전 main 의 실패는 **7건**이었다(2026-08-25). A 판이 그 근처가 아니면
트리·venv 를 잘못 짚은 것이다.

2차 관문은 **실렌더 1편**이다 — 리프레임이 켜진 채널로 한 편 만들어 종전 산출과 프레임을
맞대야 한다. 단위 테스트는 얼굴검출 *좌표*를 고정하지만 *검출 자체*를 재현하진 않는다.

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
