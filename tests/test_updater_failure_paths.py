"""updater 실패 경로 — 부분 설치된 venv 로 노드가 되살아나지 않는가 (P0 진단).

세 갈래를 고정한다:
  ① pip 타임아웃이 **예외로 새지 않고** 실패가 된다
  ② pip·smoke 실패 모두 코드 롤백 + 이전 requirements 재설치(venv 복원)를 부른다
  ③ 갱신 중 예외가 나도 노드가 draining 에 남지 않는다
     (남으면 다음 주기 _reactivate_if_self_drained 가 검증 안 된 venv 로 active 로 되살린다)

전부 순수 단위 — DB·네트워크·pip 없이 subprocess 만 대역으로 바꾼다.
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ves.agent import updater  # noqa: E402


class FakeCursor:
    def __init__(self, store):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.store.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.store.rows_for_select

    def fetchone(self):
        return None


class SqlLog(list):
    """execute 로그 + SELECT 가 돌려줄 행을 함께 든다."""
    rows_for_select: list = []


class FakeConn:
    """execute 된 SQL 을 문자열로 모아 두는 최소 대역."""

    def __init__(self, deployments):
        self.sql = SqlLog()
        self.sql.rows_for_select = deployments

    def cursor(self):
        return FakeCursor(self.sql)


class Cfg:
    node_id = "mm-test"
    home = "/tmp"


def _cfg():
    return Cfg()


# ── ① 타임아웃은 예외가 아니라 실패다 ──────────────────────────────────
def test_pip_sync_timeout_is_failure_not_exception(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    monkeypatch.setattr(updater.cfgmod, "engine_py", lambda cfg, eng: "/usr/bin/python3")

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="pip", timeout=1)

    monkeypatch.setattr(updater.subprocess, "run", boom)
    assert updater._pip_sync(_cfg(), "ai_video", str(tmp_path)) is False


def test_pip_sync_nonzero_is_failure(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    monkeypatch.setattr(updater.cfgmod, "engine_py", lambda cfg, eng: "/usr/bin/python3")

    class R:
        returncode = 1
        stderr = "ResolutionImpossible"
        stdout = ""

    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: R())
    assert updater._pip_sync(_cfg(), "ai_video", str(tmp_path)) is False


def test_pip_sync_missing_requirements_is_noop_success(tmp_path):
    assert updater._pip_sync(_cfg(), "ai_video", str(tmp_path)) is True


# ── ② 실패 두 경로 모두 venv 를 복원한다 ────────────────────────────────
def _wire(monkeypatch, *, pip_results, smoke_ok):
    """_update_engine 의 외부 호출을 전부 대역으로. 호출 순서를 리스트로 돌려준다."""
    calls = []

    def fake_git(cwd, *args, **kw):
        calls.append(("git",) + args)

        class R:
            returncode = 0
            stdout = ""
        return R()

    seq = list(pip_results)

    def fake_pip(cfg, eng, path):
        calls.append(("pip", eng))
        return seq.pop(0) if seq else True

    monkeypatch.setattr(updater, "_git", fake_git)
    monkeypatch.setattr(updater, "_pip_sync", fake_pip)
    monkeypatch.setattr(updater, "_smoke", lambda *a, **k: smoke_ok)
    monkeypatch.setattr(updater, "_alert", lambda conn, cfg, msg: calls.append(("alert", msg)))
    return calls


def test_pip_failure_rolls_back_code_and_restores_venv(monkeypatch):
    # pip: 첫 호출(새 requirements) 실패 → 롤백 안에서 두 번째 호출(이전 requirements) 성공
    calls = _wire(monkeypatch, pip_results=[False, True], smoke_ok=True)
    ok = updater._update_engine(_cfg(), object(), "ai_video", "/eng", "aaaaaaa", "bbbbbbb")

    assert ok is False
    kinds = [c[0] for c in calls]
    assert kinds.count("pip") == 2, "이전 requirements 재설치(venv 복원)가 없다"
    checkouts = [c for c in calls if c[0] == "git" and c[1] == "checkout"]
    assert checkouts and checkouts[-1][-1] == "aaaaaaa", "이전 sha 로 롤백하지 않았다"


def test_smoke_failure_also_restores_venv(monkeypatch):
    calls = _wire(monkeypatch, pip_results=[True, True], smoke_ok=False)
    ok = updater._update_engine(_cfg(), object(), "ai_video", "/eng", "aaaaaaa", "bbbbbbb")

    assert ok is False
    assert [c[0] for c in calls].count("pip") == 2


def test_restore_failure_is_alerted(monkeypatch):
    # 복원 pip 까지 실패 = 부분 설치 상태. 조용히 넘어가면 안 된다.
    calls = _wire(monkeypatch, pip_results=[False, False], smoke_ok=True)
    updater._update_engine(_cfg(), object(), "ai_video", "/eng", "aaaaaaa", "bbbbbbb")

    alerts = [c[1] for c in calls if c[0] == "alert"]
    assert any("venv 복원 실패" in a for a in alerts), alerts


# ── ③ 예외가 나도 노드를 draining 에 남기지 않는다 ──────────────────────
def test_exception_during_update_disables_node(monkeypatch):
    """종전: _update_engine 예외 → 노드가 draining+updating_since 로 남고 다음 주기에
    _reactivate_if_self_drained 가 active 로 되살렸다. 이제는 실패와 같이 처리한다."""
    deployments = [{"engine": "ai_video", "auto_update": True,
                    "pinned_sha": None, "last_seen_sha": "bbbbbbb"}]
    conn = FakeConn(deployments)

    monkeypatch.setattr(updater.cfgmod, "engine_dir", lambda cfg, eng: "/tmp")
    monkeypatch.setattr(updater, "local_sha", lambda p: "aaaaaaa")
    monkeypatch.setattr(updater, "_report_versions", lambda cfg, conn: None)
    monkeypatch.setattr(updater, "_alert", lambda conn, cfg, msg: None)

    def boom(*a, **k):
        raise RuntimeError("디스크 꽉 참")

    monkeypatch.setattr(updater, "_update_engine", boom)

    updater.check_and_update(_cfg(), conn)     # 예외가 새어 나오면 안 된다

    node_writes = [sql for sql, _ in conn.sql if "node_registry" in sql and "SET status" in sql]
    params = [p for sql, p in conn.sql if "node_registry" in sql and "SET status" in sql]
    assert node_writes, "노드 상태를 쓴 적이 없다"
    assert params[-1][0] == "disabled", f"마지막 상태가 disabled 가 아니다: {params[-1]}"
    assert params[-1][1] is False, "updating_since 를 비우지 않으면 다음 주기에 자동 복귀한다"
