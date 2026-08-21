#!/usr/bin/env bash
# fetch_node_keys.sh — 노드(기본 mm-06)에서 이 프로젝트가 쓰는 key/시크릿을 가져온다.
#
# 시크릿 정본은 sops/age 지만 실제로 돌고 있는 값은 노드의 env 파일이다(ARCHITECTURE §5).
# "지금 mm-06 이 어떤 키로 돌고 있나"를 확인하거나 회수할 때 쓴다.
#
# 사용법 (노트북에서, 6대와 같은 네트워크):
#   bash deploy/fetch_node_keys.sh                          # mm-06 키 목록 — 값은 마스킹
#   bash deploy/fetch_node_keys.sh --reveal                 # 평문 stdout (화면 노출 주의)
#   bash deploy/fetch_node_keys.sh --out ~/mm-06.env        # 평문 파일 저장 (chmod 600)
#   bash deploy/fetch_node_keys.sh --key GEMINI_API_KEY     # 값 1개만 평문 1줄
#   bash deploy/fetch_node_keys.sh --node mm-02 --files all # 다른 노드 · rclone/토큰까지
# 노드에서 직접:
#   bash fetch_node_keys.sh --local [--files …]             # 번들을 stdout 으로 (마스킹 없음)
#
# --files: default(env 파일들) | all | 콤마목록
#          ves.env,node.env,secrets,brain,aivideo,vlp,rclone,tokens
#          secrets = $VES_HOME/secrets 아래 파일 전부 (백업본·대용량·바이너리는 목록만)
# 값은 ssh 파이프로만 흐른다 — argv·원격 임시파일·셸 히스토리에 남지 않는다.
set -euo pipefail

VES_HOME="${VES_HOME:-/opt/ves}"
NODE_ENV="${NODE_ENV:-/etc/ves/node.env}"
NODE="${NODE:-mm-06}"
HOST="${HOST:-}"            # 지정하면 --node 무시 (user@host)
FILES="${FILES:-default}"
MODE=mask                   # mask | reveal | out | key
OUT="" WANT_KEY="" LOCAL=0

# ── 노드 → SSH 호스트 (apply_loopy_token.sh 의 HOSTS 와 같은 목록·같은 순서) ──
host_for() {
    case "$1" in
        mm-01) echo "lunaleuteumaeg1@lunaleuteumaeg1ui-Macmini.local" ;;
        mm-02) echo "lunaleuteumaeg2@lunaleuteumaeg2ui-Macmini.local" ;;
        mm-03) echo "lunaleuteumaeg4@3-Mac-mini.local" ;;
        mm-04) echo "lunaleuteumaeg4@lunaleuteumaeg4ui-Macmini.local" ;;
        mm-05) echo "lunaleuteumaeg5@lunaleuteumaeg5s-Mac-mini.local" ;;
        mm-06) echo "lunaleuteumaeg6@lunaleuteumaeg6ui-Macmini.local" ;;
        *)     echo "" ;;
    esac
}

usage() { sed -n '2,18p' "$0" >&2; exit "${1:-2}"; }

while [ $# -gt 0 ]; do case "$1" in
    --local)   LOCAL=1; shift ;;
    --node)    NODE="$2"; shift 2 ;;
    --host)    HOST="$2"; shift 2 ;;
    --files)   FILES="$2"; shift 2 ;;
    --reveal)  MODE=reveal; shift ;;
    --out)     MODE=out; OUT="$2"; shift 2 ;;
    --key)     MODE=key; WANT_KEY="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "알 수 없는 인자: $1" >&2; usage ;;
esac; done

# ── 원격에서 도는 부분: 파일들을 주석 헤더가 붙은 하나의 번들로 뱉는다 ──
# 헤더가 '#' 으로 시작하므로 번들 자체가 그대로 유효한 env 파일이다.
run_local() {
    local sel
    case "$FILES" in
        default) sel=" ves.env node.env brain aivideo vlp " ;;
        all)     sel=" ves.env node.env secrets brain aivideo vlp rclone tokens " ;;
        *)       sel=" $(printf '%s' "$FILES" | tr ',' ' ') " ;;
    esac
    want() { case "$sel" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
    meta() { # 권한·수정시각 — GNU 먼저(맥의 BSD stat 은 -c 를 모른다), 다음 BSD
        local m
        m="$(stat -c '%a %.16y' "$1" 2>/dev/null)" \
            || m="$(stat -f '%Lp %Sm' -t '%Y-%m-%d %H:%M' "$1" 2>/dev/null)" || m='?'
        printf '%s' "$m" | tr -d '\n'
    }
    EMITTED=""
    emit() { # $1 = 경로 (같은 파일은 한 번만)
        case "$EMITTED" in *"|$1|"*) return 0 ;; esac
        EMITTED="$EMITTED|$1|"
        if [ -f "$1" ] && [ -r "$1" ]; then
            printf '#=== FILE %s | %s ===\n' "$1" "$(meta "$1")"
            cat "$1"; printf '\n'
        elif [ -e "$1" ]; then
            printf '#=== UNREADABLE %s ===\n' "$1"
        else
            printf '#=== MISSING %s ===\n' "$1"
        fi
    }

    emit_secrets() { # $1 = 디렉토리 — 그 아래 파일 전부. 백업·대용량·바이너리는 이름만 알린다.
        local d="$1" f sz n_bak=0
        [ -d "$d" ] || { printf '#=== MISSING %s ===\n' "$d"; return 0; }
        while IFS= read -r f; do
            [ -n "$f" ] || continue
            case "$f" in *.bak|*.bak-*|*~|*.DS_Store) n_bak=$((n_bak + 1)); continue ;; esac
            sz="$(wc -c < "$f" 2>/dev/null | tr -d ' ')"
            if [ "${sz:-0}" -gt 262144 ]; then
                printf '#=== SKIPPED %s (%s bytes — 너무 큼, 필요하면 scp) ===\n' "$f" "$sz"
            elif [ "${sz:-0}" -gt 0 ] && ! LC_ALL=C grep -Iq . "$f" 2>/dev/null; then
                printf '#=== SKIPPED %s (바이너리 — 필요하면 scp) ===\n' "$f"
            else
                emit "$f"
            fi
        done <<EOF
$(find "$d" -maxdepth 3 -type f 2>/dev/null | sort)
EOF
        [ "$n_bak" = 0 ] || printf '#=== SKIPPED %s (백업본 %s개 — .bak-*) ===\n' "$d" "$n_bak"
    }

    printf '#=== NODE %s | %s ===\n' \
        "$(sed -n 's/^VES_NODE_ID=//p' "$NODE_ENV" 2>/dev/null | head -1)" \
        "$(hostname -s 2>/dev/null || hostname)"
    want node.env && emit "$NODE_ENV"
    want ves.env  && emit "$VES_HOME/secrets/ves.env"
    want brain    && emit "$VES_HOME/engines/ai-improvement-edit-video/.env"
    want aivideo  && emit "$VES_HOME/engines/ai-video/.env"
    want vlp      && emit "$VES_HOME/engines/video-localization-project/.env"
    want rclone   && emit "$VES_HOME/secrets/rclone.conf"
    want secrets  && emit_secrets "$VES_HOME/secrets"
    if want tokens; then
        # 발행이 실제로 쓰는 refresh token JSON (zanmang.py — outputs/yt_oauth_token.json 등)
        local vlp="$VES_HOME/engines/video-localization-project" f found=0 list
        list="$(find "$vlp" -maxdepth 4 -name '*.json' -not -path '*/.venv*' \
                -exec grep -l '"refresh_token"' {} + 2>/dev/null || true)"
        while IFS= read -r f; do
            [ -n "$f" ] || continue
            found=1; emit "$f"
        done <<EOF
$list
EOF
        [ "$found" = 1 ] || printf '#=== MISSING %s (refresh_token JSON 없음) ===\n' "$vlp"
    fi
    return 0
}

if [ "$LOCAL" = 1 ]; then run_local; exit 0; fi

# ── 오케스트레이터 모드: ssh 로 자기 자신을 흘려보내 --local 실행 ──
[ -n "$HOST" ] || HOST="$(host_for "$NODE")"
[ -n "$HOST" ] || { echo "모르는 노드: $NODE (--host user@host 로 직접 지정)" >&2; exit 2; }
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
[ -f "$SELF" ] || { echo "스크립트 경로를 못 찾음: $SELF" >&2; exit 1; }
[ "$MODE" != out ] || [ -n "$OUT" ] || { echo "--out 에 파일 경로가 없다" >&2; exit 2; }

BUNDLE="$(ssh -o ConnectTimeout=10 "$HOST" \
    "VES_HOME='$VES_HOME' NODE_ENV='$NODE_ENV' FILES='$FILES' bash -s -- --local" < "$SELF")" \
    || { echo "[$NODE] $HOST 에서 가져오기 실패 — ssh 연결/권한 확인" >&2; exit 1; }
[ -n "$BUNDLE" ] || { echo "[$NODE] 빈 응답 — 가져올 파일이 하나도 없다" >&2; exit 1; }

case "$MODE" in
    reveal)
        printf '%s\n' "$BUNDLE"
        ;;
    out)
        (umask 077; printf '%s\n' "$BUNDLE" > "$OUT")
        chmod 600 "$OUT"
        echo "[$NODE] $OUT 저장 (600) — 키 $(grep -c '^[A-Za-z_][A-Za-z0-9_]*=' "$OUT")개" >&2
        echo "⚠ 평문이다. 커밋 금지. 다 쓰면: rm -P '$OUT'" >&2
        ;;
    key)
        BUNDLE="$BUNDLE" KEYNAME="$WANT_KEY" python3 <<'PYEOF'
import os, sys

name = os.environ["KEYNAME"]
src = val = None
cur = "?"
for ln in os.environ["BUNDLE"].splitlines():
    if ln.startswith("#=== FILE "):
        cur = ln[len("#=== FILE "):].split(" | ")[0]
    elif ln.strip().startswith(name + "="):
        val = ln.split("=", 1)[1].strip().strip('"').strip("'")
        src = cur                      # 뒤에 나온 파일이 이긴다 — 출처를 같이 알린다
if val is None:
    sys.exit(f"{name} 없음")
sys.stderr.write(f"# {name} <- {src}\n")
print(val)
PYEOF
        ;;
    mask)
        BUNDLE="$BUNDLE" NODE="$NODE" python3 <<'PYEOF'
import os, re

# 비밀이 아닌 게 확실한 것만 그대로 보여준다 — 나머지는 전부 마스킹(기본이 안전).
PLAIN = re.compile(r"^(VES_|SUPABASE_URL$|YT_CLIENT_ID|.*_(ROOT|DIR|PATH)$)")
KV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
JSONKV = re.compile(r'^\s*"([^"]+)"\s*:\s*"(.*?)",?\s*$')


def mask(v):
    v = v.strip().strip('"').strip("'")
    if not v:
        return "⚠ 빈 값"
    if len(v) <= 12:
        return "*" * len(v) + f"  ({len(v)}자)"
    return f"{v[:4]}…{v[-4:]}  ({len(v)}자)"


keys = empty = other = 0


def flush_other():
    # KV 도 JSON 도 아닌 줄(쿠키·PEM·설정 등)은 내용 대신 줄 수만 — 값은 --reveal/--out 으로.
    global other
    if other:
        print(f"  ({other}줄은 KEY=VALUE 형식이 아님 — 내용은 --reveal/--out 으로)")
    other = 0


for ln in os.environ["BUNDLE"].splitlines():
    s = ln.strip()
    if s.startswith("#=== ") and s.endswith(" ==="):
        flush_other()
        kind, _, rest = s[5:-4].strip().partition(" ")
        if kind == "NODE":
            print(f"════ {os.environ['NODE']} · {rest} ════")
        elif kind == "FILE":
            print(f"\n──── {rest} ────")
        else:
            print(f"\n──── {rest}  [{kind.lower()}] ────")
        continue
    if not s or s.startswith("#"):
        continue
    m = KV.match(s)
    if m:
        k, v = m.group(1), m.group(2)
        keys += 1
        shown = v.strip().strip('"').strip("'") if PLAIN.match(k) else mask(v)
        if shown == "⚠ 빈 값":
            empty += 1
        print(f"  {k:<32} {shown}")
        continue
    j = JSONKV.match(ln)
    if j:
        keys += 1
        print(f"  {j.group(1):<32} {mask(j.group(2))}")
    elif s.startswith("["):
        print(f"  {s}")                 # rclone.conf 섹션명
    else:
        other += 1

flush_other()
print(f"\n키 {keys}개" + (f" · ⚠ 빈 값 {empty}개" if empty else ""))
print("평문: --reveal(화면) · --out FILE(파일,600) · --key NAME(1개)")
PYEOF
        ;;
esac
