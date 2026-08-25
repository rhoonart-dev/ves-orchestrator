#!/usr/bin/env python3
"""엔진 자동 업데이트 — claim 직전 문자열 비교, 드리프트 시 갱신 (§11).

원격 조회는 하지 않는다 — version_watch(스케줄러, 시간당 1회)가 deployments.last_seen_sha 를
갱신하고, 워커는 DB 값과 로컬 sha 를 비교만 한다(비용 0). 갱신 절차:
  draining → checkout → (마이그레이션 게이트 ★③) → pip sync(엔진별 venv ★④) → smoke
  → 실패 시 이전 sha 롤백 + 노드 disabled + 경보 / 성공 시 engine_versions 보고 → active
orchestrator 자신의 갱신은 pull 후 exit(42) — launchd KeepAlive 가 새 코드로 재기동(§11-4).
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

from ves import config as cfgmod

SELF_UPDATE_EXIT = 42
_MIG_RE = re.compile(r"^(\d{4})_")


# ───────── 순수 로직 (테스트 대상) ─────────
def migration_versions(filenames) -> list:
    """migrations 디렉토리 파일명 → 버전 목록('0006' 등). ★③ 게이트의 재료."""
    out = []
    for fn in filenames:
        m = _MIG_RE.match(str(fn).rsplit("/", 1)[-1])
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def gate_blocks(required_versions, applied_versions) -> list:
    """적용 안 된 필수 마이그레이션 목록. 비어있지 않으면 업데이트 보류(보수적 — ★③)."""
    return sorted(set(required_versions) - set(applied_versions))


def pick_target(auto_update: bool, pinned_sha, last_seen_sha):
    """갱신 목표 sha. 핀이 있으면 핀(런북 부록C), 아니면 origin 최신."""
    return (pinned_sha or None) if not auto_update else (last_seen_sha or None)


# ───────── 실행부 ─────────
def _git(cwd, *args, timeout=60):
    return subprocess.run(["git", "-C", cwd, *args],
                          capture_output=True, text=True, timeout=timeout)


def local_sha(path: str):
    r = _git(path, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else None


def check_and_update(cfg, conn) -> None:
    """워커 메인 루프에서 claim 직전 호출. 드리프트 시 이 함수 안에서 갱신을 마친다."""
    with conn.cursor() as c:
        c.execute("SELECT engine, auto_update, pinned_sha, last_seen_sha FROM public.deployments")
        rows = c.fetchall()

    for d in rows:
        eng = d["engine"]
        path = cfgmod.engine_dir(cfg, eng)
        if not pathlib.Path(path).exists():
            continue
        target = pick_target(d["auto_update"], d["pinned_sha"], d["last_seen_sha"])
        cur = local_sha(path)
        if not target or not cur or cur.startswith(target) or target.startswith(cur):
            continue

        print(f"[updater] {eng}: {cur[:7]} → {target[:7]} 갱신 시작")
        _begin_update(conn, cfg.node_id)
        try:
            ok = _update_engine(cfg, conn, eng, path, cur, target)
        except Exception as e:  # noqa: BLE001
            # 예상 못 한 예외로 여기를 빠져나가면 노드가 draining+updating_since 로 남고,
            # 다음 주기에 _restore_after_self_drain 가 **검증 안 된 venv 그대로 active** 로
            # 되살린다(P0 진단 ③). 실패와 똑같이 처리해 그 경로를 막는다.
            ok = False
            print(f"[updater] {eng} 갱신 중 예외: {type(e).__name__} {e}")
        finally:
            _report_versions(cfg, conn)
        if not ok:
            _set_node(conn, cfg.node_id, status="disabled", updating=False)
            _alert(conn, cfg, f"{eng} 업데이트 실패 — 노드 disabled, 이전 sha 유지")
            return
        if eng == "orchestrator":
            print("[updater] 오케스트레이터 자기 갱신 — 재기동을 위해 종료(launchd KeepAlive)")
            sys.exit(SELF_UPDATE_EXIT)
    # 갱신 사이클이 '스스로' 드레인한 경우(updating_since 有)에만 복귀시킨다.
    # 무조건 active 로 되돌리면 사람/대시보드가 내린 draining 을 매 사이클 밟는다(스모크3 실측).
    # 자기 갱신 exit(42) 재기동 후의 복귀도 이 조건이 담당한다(updating_since 가 남아 있음).
    _restore_after_self_drain(conn, cfg.node_id)


def _update_engine(cfg, conn, eng, path, prev_sha, target) -> bool:
    if _git(path, "fetch", "--all", "--quiet", timeout=120).returncode != 0:
        print(f"[updater] {eng}: fetch 실패 — 이번 주기 보류")
        return True  # 네트워크 문제로 노드를 죽이지 않는다
    # ★③ 마이그레이션 게이트: 새 sha 의 migrations/ 최대 버전 vs applied_migrations
    if eng in ("brain", "orchestrator"):
        req = _required_migrations_at(path, target, eng)
        applied = _applied(conn, eng)
        blocks = gate_blocks(req, applied)
        if blocks:
            _alert(conn, cfg, f"{eng} {target[:7]} 은 마이그레이션 {blocks} 적용 대기 — 구버전 유지")
            return True  # 보수적: 지연이지 실패가 아니다
    if _git(path, "checkout", "--quiet", target).returncode != 0:
        return False
    # pip install 은 원자적이지 않다 — 실패하면 venv 에 새 패키지가 일부 남는다.
    # 코드만 되돌리면 '옛 코드 + 새 패키지' 라는 아무도 검증한 적 없는 조합이 된다.
    # 그래서 두 경로(pip 실패·smoke 실패) 모두 **코드 롤백 + 이전 requirements 재설치**로
    # 맞춘다. 복원까지 실패하면 그 사실을 따로 알린다 — 사람이 손대야 하는 상태다.
    if not _pip_sync(cfg, eng, path):
        _rollback(cfg, conn, eng, path, prev_sha, "pip sync 실패")
        return False
    if not _smoke(cfg, eng, path):
        _rollback(cfg, conn, eng, path, prev_sha, "smoke 실패")
        return False
    return True


def _rollback(cfg, conn, eng, path, prev_sha, why: str) -> None:
    """이전 sha 로 코드를 되돌리고 그 sha 의 requirements 로 venv 를 복원한다."""
    if _git(path, "checkout", "--quiet", prev_sha).returncode != 0:
        _alert(conn, cfg, f"{eng} {why} 후 코드 롤백 실패 — 수동 복구 필요(sha {prev_sha[:7]})")
        return
    if not _pip_sync(cfg, eng, path):
        _alert(conn, cfg,
               f"{eng} {why} 후 venv 복원 실패 — 부분 설치 상태일 수 있습니다. "
               f"수동 복구 필요: {path}/.venv 재생성 후 requirements 재설치")


def _required_migrations_at(path, sha, eng) -> list:
    sub = {"brain": "docs/migrations", "orchestrator": "ves/control/migrations"}[eng]
    r = _git(path, "ls-tree", "-r", "--name-only", sha, sub)
    return migration_versions(r.stdout.splitlines()) if r.returncode == 0 else []


def _applied(conn, eng) -> list:
    with conn.cursor() as c:
        c.execute("SELECT version FROM public.applied_migrations WHERE engine=%s", (eng,))
        return [r["version"] for r in c.fetchall()]


# pip 설치 상한(초). 첫 설치가 이 시간을 넘기면 **실패로 처리**한다 —
# 종전엔 TimeoutExpired 가 예외로 새어 나가 노드가 '부분 설치된 venv + 새 코드'로
# 되살아났다(P0 진단 ③). 무거운 의존(torch·paddlepaddle)이 본체 requirements 로
# 들어오면 첫 설치가 길어지므로 env 로 올릴 수 있게 뺀다.
PIP_TIMEOUT_SEC = int(os.environ.get("VES_PIP_TIMEOUT_SEC") or 3600)


def _pip_sync(cfg, eng, path) -> bool:
    """requirements 설치. 성공만 True — 타임아웃도 실패다(예외로 새지 않는다)."""
    req = pathlib.Path(path) / "requirements.txt"
    if not req.exists():
        return True
    py = cfgmod.engine_py(cfg, eng) if eng != "orchestrator" else f"{path}/.venv/bin/python"
    try:
        r = subprocess.run([py, "-m", "pip", "install", "-q", "-r", str(req)],
                           capture_output=True, text=True, timeout=PIP_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        print(f"[updater] pip sync 타임아웃({PIP_TIMEOUT_SEC}s) — {eng}: 실패로 처리")
        return False
    if r.returncode != 0:
        print(f"[updater] pip sync 실패: {r.stderr[-400:]}")
    return r.returncode == 0


SMOKE_CMDS = {  # import + 진입점 — 깨진 배포를 6대에 퍼뜨리지 않는 최소 방어(§11-1)
    "ai_video": ["-c", "import app.cli"],
    "brain": ["-c", "import sys; sys.path.insert(0,'scripts'); import channel_registry, loop_controller"],
    "localization": ["-c", "import src.autopilot"],
    "orchestrator": ["-m", "pytest", "tests/", "-q", "--no-header", "-x"],
}


def _smoke(cfg, eng, path) -> bool:
    py = cfgmod.engine_py(cfg, eng) if eng != "orchestrator" else f"{path}/.venv/bin/python"
    r = subprocess.run([py, *SMOKE_CMDS.get(eng, ["-c", "pass"])],
                       cwd=path, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        print(f"[updater] smoke 실패({eng}): {(r.stderr or r.stdout)[-400:]}")
    return r.returncode == 0


def _begin_update(conn, node_id):
    """갱신용 드레인 — 내리기 **전** 상태를 meta 에 적어 둔다.

    ★사람이 내려 둔 draining 을 갱신이 지우면 안 된다(8/25 mm-06 실측: 디스크가 차
    큐를 독식하던 노드를 사람이 draining 으로 내렸는데, 엔진 갱신 한 번에 조용히
    active 로 돌아왔다). 자기 갱신은 exit(42) 로 프로세스가 죽어 재기동되므로 파이썬
    변수로는 못 남긴다 — 그래서 DB(meta)에 적는다.

    `updating_since IS NULL` 가드가 핵심이다: 한 주기에 엔진이 둘 이상 밀리면 이 함수가
    여러 번 불리는데, 가드가 없으면 두 번째 호출이 'draining'(첫 호출이 넣은 값)을
    갱신 전 상태로 적어 노드가 영구히 draining 에 갇힌다."""
    with conn.cursor() as c:
        c.execute(
            """UPDATE public.node_registry
                  SET meta = coalesce(meta,'{}'::jsonb)
                             || jsonb_build_object('pre_update_status', status),
                      status='draining', updating_since=now(), last_seen_at=now()
                WHERE node_id=%s AND updating_since IS NULL""", (node_id,))


def _restore_after_self_drain(conn, node_id):
    """갱신이 스스로 내린 드레인만 되돌린다 — 복귀 상태는 **갱신 전** 상태다.
    사람이 내려 둔 draining 이었으면 draining 으로 돌아간다(active 로 올리지 않는다).

    기록이 없거나 알 수 없는 값이면 'active' — 종전 동작이다(회귀 0).
    ⚠ 갱신 **도중에** 사람이 상태를 바꾸면 이 복귀가 그 값을 덮는다(창은 갱신 1회 길이).
       막으려면 set_node_status RPC 가 updating_since 를 함께 비워야 하는데, 그건
       마이그레이션이 필요하고 마이그레이션 게이트가 6대 갱신을 막으므로 별건으로 둔다."""
    with conn.cursor() as c:
        c.execute(
            """UPDATE public.node_registry
                  SET status = CASE
                        WHEN meta->>'pre_update_status' IN ('draining','disabled')
                          THEN meta->>'pre_update_status'
                        ELSE 'active' END,
                      updating_since=NULL,
                      meta = coalesce(meta,'{}'::jsonb) - 'pre_update_status',
                      last_seen_at=now()
                WHERE node_id=%s AND updating_since IS NOT NULL""", (node_id,))


def _set_node(conn, node_id, status, updating):
    """상태 직접 지정(갱신 실패 → disabled). 갱신 전 상태 기록도 함께 버린다 —
    남겨 두면 다음 갱신의 복귀가 지금은 뜻이 없는 옛 값을 되살린다."""
    with conn.cursor() as c:
        c.execute(
            """UPDATE public.node_registry
                  SET status=%s, updating_since = CASE WHEN %s THEN now() ELSE NULL END,
                      meta = coalesce(meta,'{}'::jsonb) - 'pre_update_status',
                      last_seen_at=now()
                WHERE node_id=%s""", (status, updating, node_id))


def _report_versions(cfg, conn):
    import json
    from ves.agent.executor import _local_shas
    with conn.cursor() as c:
        c.execute("UPDATE public.node_registry SET engine_versions=%s::jsonb WHERE node_id=%s",
                  (json.dumps(_local_shas(cfg)), cfg.node_id))


def _alert(conn, cfg, msg):
    print(f"[ALERT] {msg}")  # TODO(Phase 2): obs/notify.py Slack 웹훅 연결
