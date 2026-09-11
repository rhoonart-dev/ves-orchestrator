#!/usr/bin/env bash
# apply_channel_token.sh — 채널 refresh token 을 6대 ves.env 에 일괄 반영 (apply_loopy_token.sh 의 범용판)
#
# 경위(2026-09-11): 새 채널(부먹?찍먹?)을 등록하며 토큰을 노트북에서 발급했다. 노드는
# /opt/ves/secrets/ves.env 만 읽고(config.job_env), 그 파일은 노드마다 따로라 6대에 넣어야
# 발행이 된다 — 한 입 주막(08-17) 때 "넣었는데 왜 안 되지"로 시간을 쓴 자리다. LOOPY 전용
# 스크립트는 채널·키 이름이 박혀 있어 채널마다 복사본이 늘어나므로 인자로 받는다.
#
# 게이트는 같다: 토큰이 **기대 채널에 바인딩된 것을 확인한 경우에만** 쓴다(오채널 발행 방지).
#
# 사용법 (노트북에서, 6대와 같은 네트워크):
#   bash deploy/apply_channel_token.sh --slug BUMEOKJJIKMEOK --expect-id UCxxxx \
#        [--from-env ~/rhoonart/ai-improvement-edit-video/.env]   # 없으면 프롬프트(비표시)
# 노드 1대에서 직접:
#   bash apply_channel_token.sh --local --slug … --expect-id …     # 토큰은 프롬프트 또는 stdin
#
# 토큰은 프롬프트(비표시)·파일에서 읽어 ssh stdin·환경변수로만 전달한다 — argv·히스토리에 안 남는다.
set -euo pipefail

ENV_PATH="${ENV_PATH:-/opt/ves/secrets/ves.env}"
HOSTS="${HOSTS:-lunaleuteumaeg1@lunaleuteumaeg1ui-Macmini.local \
lunaleuteumaeg2@lunaleuteumaeg2ui-Macmini.local \
lunaleuteumaeg4@3-Mac-mini.local \
lunaleuteumaeg4@lunaleuteumaeg4ui-Macmini.local \
lunaleuteumaeg5@lunaleuteumaeg5s-Mac-mini.local \
lunaleuteumaeg6@lunaleuteumaeg6ui-Macmini.local}"
SKIP_VERIFY="${SKIP_VERIFY:-0}"   # 1 = 테스트 전용. 실전에서 켜면 오채널 게이트가 사라진다.

SLUG="" EXPECTED_ID="" FROM_ENV="" LOCAL=0
while [ $# -gt 0 ]; do
    case "$1" in
        --slug)       SLUG="$2"; shift 2 ;;
        --expect-id)  EXPECTED_ID="$2"; shift 2 ;;
        --from-env)   FROM_ENV="$2"; shift 2 ;;
        --local)      LOCAL=1; shift ;;
        -h|--help)    sed -n 2,18p "$0"; exit 0 ;;
        *) echo "알 수 없는 인자: $1" >&2; exit 2 ;;
    esac
done
[ -n "$SLUG" ] && [ -n "$EXPECTED_ID" ] || { echo "--slug 와 --expect-id 는 필수" >&2; exit 2; }
TOKEN_VAR="YT_REFRESH_TOKEN_${SLUG}"

# ── 공용: 토큰이 기대 채널에 바인딩됐는지 확인 ──
# env 입력: CH_TOKEN, CLIENT_PAIRS("client_id<TAB>client_secret" 줄들 — 차례로 시도)
# stdout: "OK <channel_id> <title>" | "NOCLIENT"
verify_token() {
    python3 <<'PYEOF'
import json, os, urllib.parse, urllib.request
token = os.environ["CH_TOKEN"]
result = None
for line in os.environ.get("CLIENT_PAIRS", "").splitlines():
    if "\t" not in line:
        continue
    cid, csec = line.split("\t", 1)
    body = urllib.parse.urlencode({"client_id": cid, "client_secret": csec,
                                   "refresh_token": token, "grant_type": "refresh_token"}).encode()
    try:
        access = json.load(urllib.request.urlopen(urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=body), timeout=20))["access_token"]
    except Exception:
        continue          # 이 클라이언트로 발급된 토큰이 아님 — 다음 후보
    try:
        req = urllib.request.Request(
            "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true",
            headers={"Authorization": f"Bearer {access}"})
        items = json.load(urllib.request.urlopen(req, timeout=20)).get("items") or []
    except Exception:
        continue
    if items:
        result = f'OK {items[0]["id"]} {items[0]["snippet"]["title"]}'
        break
print(result or "NOCLIENT")
PYEOF
}

read_token() {
    if [ -n "$FROM_ENV" ]; then
        TOKEN="$(grep "^${TOKEN_VAR}=" "$FROM_ENV" | head -1 | cut -d= -f2- | tr -d '"'"'" | tr -d '[:space:]')"
        [ -n "$TOKEN" ] || { echo "$FROM_ENV 에 $TOKEN_VAR 없음 — 중단" >&2; exit 1; }
    elif [ -t 0 ]; then
        printf '%s 붙여넣기 (화면 비표시): ' "$TOKEN_VAR" >&2
        read -rs TOKEN; echo >&2
    else
        TOKEN="$(cat)"                       # 오케스트레이터가 ssh stdin 으로 넘긴 값
    fi
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    [ -n "$TOKEN" ] || { echo "토큰이 비어 있음 — 중단" >&2; exit 1; }
}

# ── 로컬 모드: 이 머신의 ves.env 를 교체 ──
run_local() {
    local host_label; host_label="$(hostname -s 2>/dev/null || hostname)"
    read_token
    [ -f "$ENV_PATH" ] || { echo "[$host_label] $ENV_PATH 없음 — 중단" >&2; exit 1; }

    # 1) 채널 검증 — ves.env 의 모든 YT_CLIENT_ID*/SECRET* 쌍을 후보로 자동 시도
    if [ "$SKIP_VERIFY" != "1" ]; then
        local pairs verdict
        pairs="$(python3 - "$ENV_PATH" <<'PYEOF'
import sys
env = {}
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
for k in sorted(env):
    if k.startswith("YT_CLIENT_ID"):
        sec = env.get(k.replace("YT_CLIENT_ID", "YT_CLIENT_SECRET"), "")
        if env[k] and sec:
            print(f"{env[k]}\t{sec}")
PYEOF
)"
        [ -n "$pairs" ] || { echo "[$host_label] ves.env 에 YT_CLIENT_ID*/SECRET* 쌍 없음 — 중단" >&2; exit 1; }
        verdict="$(CH_TOKEN="$TOKEN" CLIENT_PAIRS="$pairs" verify_token)"
        case "$verdict" in
            "OK $EXPECTED_ID "*)
                echo "[$host_label] 채널 검증 통과: ${verdict#OK }" ;;
            NOCLIENT)
                echo "[$host_label] 중단: 어떤 클라이언트로도 refresh 실패(invalid_grant) — 발급에 쓴 클라이언트(YT_CLIENT_ID_<project>)가 ves.env 에 없음" >&2
                exit 1 ;;
            *)
                echo "[$host_label] 중단: 토큰이 다른 채널에 바인딩됨 → ${verdict#OK } (기대: $EXPECTED_ID)" >&2
                exit 1 ;;
        esac
    fi

    # 2) ves.env 교체 — 기존 줄 제거→추가 방식(토큰 속 '/' 가 sed 구분자를 깨는 사고 방지)
    local bak tmp
    bak="$ENV_PATH.bak-$(date +%Y%m%d-%H%M%S)"
    cp -p "$ENV_PATH" "$bak"
    tmp="$(mktemp)"
    grep -v "^${TOKEN_VAR}=" "$ENV_PATH" > "$tmp" || true
    printf '%s=%s\n' "$TOKEN_VAR" "$TOKEN" >> "$tmp"
    cat "$tmp" > "$ENV_PATH" && rm -f "$tmp"
    chmod 600 "$ENV_PATH" "$bak"
    [ "$(grep -c "^${TOKEN_VAR}=" "$ENV_PATH")" = "1" ] \
        || { echo "[$host_label] ves.env 교체 검증 실패 — 백업: $bak" >&2; exit 1; }
    echo "[$host_label] ves.env 교체 완료 (백업: $bak) — 잡은 다음 실행부터 새 값을 읽는다(job_env)"
}

# ── 오케스트레이터 모드: 6대 순회 (scp → 원격 --local, 토큰은 ssh stdin 파이프) ──
run_remote() {
    local script_path
    script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    read_token
    local h ok=0 fail=0 failed=""
    for h in $HOSTS; do
        echo "──── $h ────"
        if scp -q -o ConnectTimeout=10 "$script_path" "$h:/tmp/apply_channel_token.sh" \
           && printf '%s' "$TOKEN" | ssh -o ConnectTimeout=10 "$h" \
                "ENV_PATH='$ENV_PATH' SKIP_VERIFY='$SKIP_VERIFY' \
                 bash /tmp/apply_channel_token.sh --local --slug '$SLUG' --expect-id '$EXPECTED_ID'; \
                 s=\$?; rm -f /tmp/apply_channel_token.sh; exit \$s"; then
            ok=$((ok+1))
        else
            fail=$((fail+1)); failed="$failed $h"
        fi
    done
    echo "════════════════"
    # macOS bash 3.2 는 $ok대 처럼 한글이 붙으면 한글까지 변수명으로 읽는다 — 중괄호 필수
    echo "결과: 성공 ${ok}대 / 실패 ${fail}대${failed:+ —$failed}"
    [ "$fail" -eq 0 ]
}

if [ "$LOCAL" = "1" ]; then run_local; else run_remote; fi
