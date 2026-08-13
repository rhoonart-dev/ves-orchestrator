#!/usr/bin/env python3
"""엔진 자동 업데이트 — claim 직전 문자열 비교, 드리프트 시 갱신 (§11).

원격 조회는 하지 않는다 — version_watch(스케줄러, 시간당 1회)가 deployments.last_seen_sha 를
갱신하고, 워커는 DB 값과 로컬 sha 를 비교만 한다(비용 0). 갱신 절차:
  draining → checkout → (마이그레이션 게이트 ★③) → pip sync(엔진별 venv ★④) → smoke
  → 실패 시 이전 sha 롤백 + 노드 disabled + 경보 / 성공 시 engine_versions 보고 → active
orchestrator 자신의 갱신은 pull 후 exit(42) — launchd KeepAlive 가 새 코드로 재기동(§11-4).
"""
from __future__ import annotations

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
        _set_node(conn, cfg.node_id, status="draining", updating=True)
        try:
            if not _update_engine(cfg, conn, eng, path, cur, target):
                _set_node(conn, cfg.node_id, status="disabled", updating=False)
                _alert(conn, cfg, f"{eng} 업데이트 실패 — 노드 disabled, 이전 sha 유지")
                return
        finally:
            _report_versions(cfg, conn)
        if eng == "orchestrator":
            print("[updater] 오케스트레이터 자기 갱신 — 재기동을 위해 종료(launchd KeepAlive)")
            sys.exit(SELF_UPDATE_EXIT)
    # 갱신 사이클이 '스스로' 드레인한 경우(updating_since 有)에만 복귀시킨다.
    # 무조건 active 로 되돌리면 사람/대시보드가 내린 draining 을 매 사이클 밟는다(스모크3 실측).
    # 자기 갱신 exit(42) 재기동 후의 복귀도 이 조건이 담당한다(updating_since 가 남아 있음).
    _reactivate_if_self_drained(conn, cfg.node_id)


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
    if not _pip_sync(cfg, eng, path):
        _git(path, "checkout", "--quiet", prev_sha)  # 롤백
        return False
    if not _smoke(cfg, eng, path):
        _git(path, "checkout", "--quiet", prev_sha)
        _pip_sync(cfg, eng, path)  # 이전 requirements 로 복원 시도
        return False
    return True


def _required_migrations_at(path, sha, eng) -> list:
    sub = {"brain": "docs/migrations", "orchestrator": "ves/control/migrations"}[eng]
    r = _git(path, "ls-tree", "-r", "--name-only", sha, sub)
    return migration_versions(r.stdout.splitlines()) if r.returncode == 0 else []


def _applied(conn, eng) -> list:
    with conn.cursor() as c:
        c.execute("SELECT version FROM public.applied_migrations WHERE engine=%s", (eng,))
        return [r["version"] for r in c.fetchall()]


def _pip_sync(cfg, eng, path) -> bool:
    req = pathlib.Path(path) / "requirements.txt"
    if not req.exists():
        return True
    py = cfgmod.engine_py(cfg, eng) if eng != "orchestrator" else f"{path}/.venv/bin/python"
    # 1800초(8/14): demucs 가 vlp requirements 로 들어오며 torch 첫 설치가 600초를
    # 넘길 수 있다 — 타임아웃이 터지면 갱신 실패→노드 disabled 로 번진다.
    r = subprocess.run([py, "-m", "pip", "install", "-q", "-r", str(req)],
                       capture_output=True, text=True, timeout=1800)
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


def _reactivate_if_self_drained(conn, node_id):
    with conn.cursor() as c:
        c.execute(
            """UPDATE public.node_registry
                  SET status='active', updating_since=NULL, last_seen_at=now()
                WHERE node_id=%s AND updating_since IS NOT NULL""", (node_id,))


def _set_node(conn, node_id, status, updating):
    with conn.cursor() as c:
        c.execute(
            """UPDATE public.node_registry
                  SET status=%s, updating_since = CASE WHEN %s THEN now() ELSE NULL END,
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
