#!/bin/bash
# ves 노드 부트스트랩 — 6대 전부 동일하게 1회 실행 (ARCHITECTURE §11-2 레이아웃)
#   ./bootstrap.sh --node-id mm-03 --caps generate,analyze,publish,network [--concurrency 1]
# 전제: (1) 시크릿 파일을 먼저 준비해 둘 것(복호화본 경로를 VES_SECRETS_SRC 로 지정)
#      (2) 사설 레포 접근 토큰이 시크릿에 포함(GIT_HTTPS_TOKEN — 놓친부분⑤)
set -euo pipefail

VES_HOME="${VES_HOME:-/opt/ves}"
NODE_ID="" CAPS="" CONCURRENCY=1
# TODO: 조직 실제 URL 로 교체 (brain CLAUDE.md §1 기준)
REPO_ORCH="${REPO_ORCH:-https://github.com/rhoonart-dev/ves-orchestrator.git}"
REPO_AIVIDEO="${REPO_AIVIDEO:-https://github.com/rht-22/ai-video.git}"
REPO_BRAIN="${REPO_BRAIN:-https://github.com/rhoonart-dev/ai-improvement-edit-video.git}"
REPO_LOCAL="${REPO_LOCAL:-https://github.com/rhoonart-dev/video-localization-project.git}"

while [[ $# -gt 0 ]]; do case "$1" in
  --node-id) NODE_ID="$2"; shift 2;;
  --caps) CAPS="$2"; shift 2;;
  --concurrency) CONCURRENCY="$2"; shift 2;;
  *) echo "알 수 없는 인자: $1"; exit 1;;
esac; done
[[ -n "$NODE_ID" && -n "$CAPS" ]] || { echo "사용법: $0 --node-id mm-0X --caps a,b,c"; exit 1; }

echo "== [1/7] Homebrew 의존 =="
for pkg in ffmpeg yt-dlp git; do
  command -v "$pkg" >/dev/null || brew install "$pkg"
done
command -v python3.12 >/dev/null || brew install python@3.12

echo "== [2/7] 디렉토리 =="
sudo mkdir -p "$VES_HOME"/{engines,cache/sources,secrets,logs}
sudo chown -R "$(whoami)" "$VES_HOME"

echo "== [3/7] 시크릿 =="
if [[ -n "${VES_SECRETS_SRC:-}" ]]; then
  cp "$VES_SECRETS_SRC" "$VES_HOME/secrets/ves.env"
fi
[[ -f "$VES_HOME/secrets/ves.env" ]] || { echo "⚠ $VES_HOME/secrets/ves.env 없음 — sops 복호화본을 배치하세요"; exit 1; }
chmod 600 "$VES_HOME/secrets/ves.env"

echo "== [4/7] 레포 clone (엔진별 venv ★④) =="
clone_and_venv() { # $1 url  $2 dest  $3 reqs(optional)
  [[ -d "$2/.git" ]] || git clone "$1" "$2"
  if [[ ! -d "$2/.venv" ]]; then python3.12 -m venv "$2/.venv"; fi
  if [[ -f "$2/${3:-requirements.txt}" ]]; then
    "$2/.venv/bin/pip" install -q -U pip
    "$2/.venv/bin/pip" install -q -r "$2/${3:-requirements.txt}"
  fi
}
clone_and_venv "$REPO_ORCH"    "$VES_HOME/orchestrator"
clone_and_venv "$REPO_AIVIDEO" "$VES_HOME/engines/ai-video"
clone_and_venv "$REPO_BRAIN"   "$VES_HOME/engines/ai-improvement-edit-video"
clone_and_venv "$REPO_LOCAL"   "$VES_HOME/engines/video-localization-project"

echo "== [5/7] /etc/ves/node.env =="
sudo mkdir -p /etc/ves
sudo tee /etc/ves/node.env >/dev/null <<EOF
VES_HOME=$VES_HOME
VES_NODE_ID=$NODE_ID
VES_CAPABILITIES=$CAPS
VES_MAX_CONCURRENCY=$CONCURRENCY
EOF

echo "== [6/7] launchd =="
PLIST_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$PLIST_DIR"
for f in com.rhoonart.ves-agent.plist com.rhoonart.ves-scheduler.plist; do
  if [[ "$f" == *scheduler* && "$CAPS" != *scheduler* ]]; then continue; fi
  sed "s|__VES_HOME__|$VES_HOME|g" "$VES_HOME/orchestrator/deploy/launchd/$f" > "$PLIST_DIR/$f"
  launchctl bootout "gui/$(id -u)/${f%.plist}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST_DIR/$f"
done

echo "== [7/7] 전원/절전 (권장 설정 — sudo 필요) =="
echo "  sudo pmset -a sleep 0 displaysleep 10   # 항시 가동(전원 연결 전제)"
echo "  시스템 설정 › 자동 로그인 켜기 (LaunchAgent 는 로그인 세션에서 동작 — 놓친부분③)"
echo
echo "완료. 확인: tail -f $VES_HOME/logs/agent.log  (node_registry 에 $NODE_ID 등록되면 정상)"
