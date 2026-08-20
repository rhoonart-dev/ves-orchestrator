#!/usr/bin/env bash
# apply_loopy_token.sh — LOOPY(まいにちじゃんまんるぴー) refresh token 6대 일괄 교체
#
# 경위(2026-08-20): LOOPY 토큰이 같은 구글 계정의 다른 브랜드 채널(ジャンマンルピーの日常)로
# 발급돼 있어 발행이 오채널로 나갔다. 이 스크립트는 새 토큰이 **기대 채널에 바인딩된 것을
# 확인한 경우에만** 각 노드의 ves.env 와 vlp 레포 토큰 파일에 반영한다.
#
# 사용법 (노트북에서, 6대와 같은 네트워크):
#   bash deploy/apply_loopy_token.sh          # 토큰 1회 입력 → 6대 순회
# 노드 1대에서 직접 돌릴 때(AirDrop 배포 등):
#   bash apply_loopy_token.sh --local
#
# 토큰은 프롬프트(비표시)로 받아 ssh stdin·환경변수로만 전달한다 — argv·히스토리에 안 남는다.
set -euo pipefail

EXPECTED_ID="UCmwTj4MunybPyWA4DNdpWCg"
EXPECTED_NAME="まいにちじゃんまんるぴー"
ENV_PATH="${ENV_PATH:-/opt/ves/secrets/ves.env}"
VLP_REPO="${VLP_REPO:-/opt/ves/engines/video-localization-project}"
TOKEN_VAR="YT_REFRESH_TOKEN_LOOPY"
HOSTS="${HOSTS:-lunaleuteumaeg1@lunaleuteumaeg1ui-Macmini.local \
lunaleuteumaeg2@lunaleuteumaeg2ui-Macmini.local \
lunaleuteumaeg4@3-Mac-mini.local \
lunaleuteumaeg4@lunaleuteumaeg4ui-Macmini.local \
lunaleuteumaeg5@lunaleuteumaeg5s-Mac-mini.local \
lunaleuteumaeg6@lunaleuteumaeg6ui-Macmini.local}"
SKIP_VERIFY="${SKIP_VERIFY:-0}"   # 1 = 테스트 전용. 실전에서 켜면 오채널 게이트가 사라진다.

# ── 공용: 토큰이 기대 채널에 바인딩됐는지 확인 ──
# env 입력: LOOPY_TOKEN, CLIENT_PAIRS("client_id<TAB>client_secret" 줄들 — 차례로 시도)
# stdout: "OK <channel_id> <title>" | "NOCLIENT"
verify_token() {
    python3 <<'PYEOF'
import json, os, urllib.parse, urllib.request

token = os.environ["LOOPY_TOKEN"]
result = None
for line in os.environ.get("CLIENT_PAIRS", "").splitlines():
    if "\t" not in line:
        continue
    cid, csec = line.split("\t", 1)
    body = urllib.parse.urlencode({"client_id": cid, "client_secret": csec,
                                   "refresh_token": token,
                                   "grant_type": "refresh_token"}).encode()
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=body), timeout=20)
        access = json.load(r)["access_token"]
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

# ── 로컬 모드: 이 머신의 ves.env(+vlp 토큰)를 교체 ──
run_local() {
    local host_label; host_label="$(hostname -s 2>/dev/null || hostname)"
    if [ -t 0 ]; then
        printf '새 %s 붙여넣기 (화면 비표시): ' "$TOKEN_VAR" >&2
        read -rs TOKEN; echo >&2
    else
        TOKEN="$(cat)"                       # 오케스트레이터가 ssh stdin 으로 넘긴 값
    fi
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    [ -n "$TOKEN" ] || { echo "[$host_label] 토큰이 비어 있음 — 중단" >&2; exit 1; }
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
        verdict="$(LOOPY_TOKEN="$TOKEN" CLIENT_PAIRS="$pairs" verify_token)"
        case "$verdict" in
            "OK $EXPECTED_ID "*)
                echo "[$host_label] 채널 검증 통과: ${verdict#OK }" ;;
            NOCLIENT)
                echo "[$host_label] 중단: 어떤 클라이언트로도 refresh 실패(invalid_grant) — 발급에 쓴 클라이언트가 ves.env 에 없음" >&2
                exit 1 ;;
            *)
                echo "[$host_label] 중단: 토큰이 다른 채널에 바인딩됨 → ${verdict#OK } (기대: $EXPECTED_ID $EXPECTED_NAME)" >&2
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
    echo "[$host_label] ves.env 교체 완료 (백업: $bak)"

    # 3) vlp 레포 토큰 — 실제 LOOPY 업로드가 쓰는 쪽(zanmang.py: '토큰은 기존 위치').
    #    레포가 있는 노드에서만. 실패는 경고로 남기고 계속(ves.env 는 이미 반영됨).
    if [ -d "$VLP_REPO" ]; then
        local files f fbak fpair fverdict
        files="$(find "$VLP_REPO" -maxdepth 4 -name '*.json' -not -path '*/.venv/*' \
                 -exec grep -l '"refresh_token"' {} + 2>/dev/null || true)"
        if [ -z "$files" ]; then
            echo "[$host_label] ⚠ vlp 레포에서 refresh_token JSON 을 못 찾음 — 후보 목록:" >&2
            find "$VLP_REPO" -maxdepth 4 \( -iname '*token*' -o -iname '*cred*' \) \
                 -not -path '*/.venv/*' 2>/dev/null | head -10 >&2 || true
        fi
        while IFS= read -r f; do
            [ -n "$f" ] || continue
            fbak="$f.bak-$(date +%Y%m%d-%H%M%S)"
            cp -p "$f" "$fbak"
            LOOPY_TOKEN="$TOKEN" python3 - "$f" <<'PYEOF'
import json, os, sys
path = sys.argv[1]
d = json.load(open(path, encoding="utf-8"))
d["refresh_token"] = os.environ["LOOPY_TOKEN"].strip()
json.dump(d, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
PYEOF
            chmod 600 "$f"
            # vlp 는 이 파일 안의 클라이언트로 refresh 한다 — 그 클라이언트로도 검증하고,
            # 불일치면 파일을 되돌린다(빈 채로 두면 다음 업로드가 invalid_grant 로 죽는다).
            fpair="$(python3 - "$f" <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
if d.get("client_id") and d.get("client_secret"):
    print(f'{d["client_id"]}\t{d["client_secret"]}')
PYEOF
)"
            if [ "$SKIP_VERIFY" = "1" ]; then
                echo "[$host_label] vlp 토큰 교체(검증 생략): $f"
            elif [ -z "$fpair" ]; then
                echo "[$host_label] vlp 토큰 교체(파일에 클라이언트 없음 — 검증 생략): $f"
            else
                fverdict="$(LOOPY_TOKEN="$TOKEN" CLIENT_PAIRS="$fpair" verify_token)"
                case "$fverdict" in
                    "OK $EXPECTED_ID "*)
                        echo "[$host_label] vlp 토큰 교체+검증 완료: $f" ;;
                    NOCLIENT)
                        cp -p "$fbak" "$f"
                        echo "[$host_label] ⚠ $f 되돌림: 새 토큰이 이 파일의 클라이언트로 발급된 게 아님 — vlp 클라이언트로 재발급 필요" >&2 ;;
                    *)
                        cp -p "$fbak" "$f"
                        echo "[$host_label] ⚠ $f 되돌림: 다른 채널 바인딩 → ${fverdict#OK }" >&2 ;;
                esac
            fi
        done <<< "$files"
    fi
    echo "[$host_label] 완료"
}

# ── 오케스트레이터 모드: 6대 순회 (scp → 원격 --local, 토큰은 ssh stdin 파이프) ──
run_remote() {
    local script_path
    script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    printf '새 %s 붙여넣기 (화면 비표시, 1회 입력 → 전 노드 적용): ' "$TOKEN_VAR" >&2
    read -rs TOKEN; echo >&2
    TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
    [ -n "$TOKEN" ] || { echo "토큰이 비어 있음 — 중단" >&2; exit 1; }

    local h ok=0 fail=0 failed=""
    for h in $HOSTS; do
        echo "──── $h ────"
        if scp -q -o ConnectTimeout=10 "$script_path" "$h:/tmp/apply_loopy_token.sh" \
           && printf '%s' "$TOKEN" | ssh -o ConnectTimeout=10 "$h" \
                "ENV_PATH='$ENV_PATH' VLP_REPO='$VLP_REPO' SKIP_VERIFY='$SKIP_VERIFY' \
                 bash /tmp/apply_loopy_token.sh --local; s=\$?; rm -f /tmp/apply_loopy_token.sh; exit \$s"; then
            ok=$((ok+1))
        else
            fail=$((fail+1)); failed="$failed $h"
        fi
    done
    echo "════════════════"
    echo "결과: 성공 $ok대 / 실패 $fail대${failed:+ —$failed}"
    cat >&2 <<'REMIND'

남은 일 (스크립트 밖):
 1. sops/age 시크릿 정본의 YT_REFRESH_TOKEN_LOOPY 도 교체 — 안 하면 다음 배포 때 되돌아간다.
 2. ジャンマンルピーの日常 채널 Studio 에서 잘못 올라간 영상 비공개/삭제 (예약공개 해제 포함).
 3. 재발행: mm-06 vlp 원장에서 해당 건 uploaded→approved 되돌린 뒤 관제에서 발행
    (첫 편은 private 로 올려 채널 확인 후 공개 전환 권장).
REMIND
    [ "$fail" = "0" ]
}

case "${1:-}" in
    --local) run_local ;;
    "")      run_remote ;;
    *)       echo "사용법: $0 [--local]   (옵션은 env 로: HOSTS, ENV_PATH, VLP_REPO, SKIP_VERIFY=1)" >&2; exit 2 ;;
esac
