#!/usr/bin/env python3
"""스케줄러 틱 루프 — advisory lock 으로 '한 번에 한 대만' (§3·§8-2).

scheduler capability 를 2~3대에 켜두면 리더 선출 없이 자동 승계된다:
락을 못 잡은 노드는 그 틱을 조용히 스킵한다. 모든 태스크는 멱등 — 재실행이 안전하다.
실행: python -m ves.scheduler.main  (launchd, scheduler 태그 노드만)
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
import time
import traceback

from ves import config as cfgmod
from ves import db
from ves.config import get_config
from ves.scheduler import (channels_sync, drive_balance, drive_watch, editor_uploads_gc,
                           perf_sync, planner, reaper, reconcile, source_watch,
                           storage_gc, version_watch, zanmang_daily)

KST = dt.timezone(dt.timedelta(hours=9))
TICK_SEC = 30


def _due_daily(last: dt.datetime | None, now: dt.datetime, hour: int) -> bool:
    """KST hour시 이후 오늘 아직 안 돌았으면 due. (잠들어 있었으면 깨어날 때 보충 — launchd 관행)"""
    if now.hour < hour:
        return False
    return last is None or last.astimezone(KST).date() < now.date()


def _due_interval(last: dt.datetime | None, now: dt.datetime, minutes: int) -> bool:
    return last is None or (now - last) >= dt.timedelta(minutes=minutes)


def kick_due(seen: str | None, cur: str | None, booted: bool) -> tuple[bool, str | None]:
    """ops_config.planner_kick 값 '변경' 시에만 due — '오늘 다시 계획' 스위치(8/10).
    기동 직후엔 현재값을 승계만 한다(재시작 오발사 방지). 순수 — 테스트 대상.
    사용법: INSERT INTO ops_config(key,value) VALUES('planner_kick', now()::text)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=now();"""
    if not booted:
        return False, cur
    if cur is not None and cur != seen:
        return True, cur
    return False, seen


def _read_kick(conn) -> str | None:
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key='planner_kick'")
        row = c.fetchone()
    return row and row["value"]


def _code_sha(cfg) -> str | None:
    """체크아웃의 현재 sha — 워커 updater 가 새 코드를 받아놓으면 값이 바뀐다."""
    try:
        r = subprocess.run(["git", "-C", cfgmod.engine_dir(cfg, "orchestrator"),
                            "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def main():
    cfg = get_config()
    conn = db.connect(cfg.db_url)
    lock_conn = db.connect(cfg.db_url)   # advisory lock 전용 세션(세션 락)
    last: dict = {}
    boot_sha = _code_sha(cfg)
    print(f"[scheduler] {cfg.node_id} 기동 (sha {(boot_sha or '?')[:7]})")

    while True:
        try:
            # ★자기 재시작(8/10 실측 구멍): 워커 updater 는 exit(42) 로 새 코드를 태우지만
            # 스케줄러는 옛 임포트로 계속 돌았다 — 체크아웃 sha 가 바뀌면 종료(KeepAlive 재기동).
            cur_sha = _code_sha(cfg)
            if boot_sha and cur_sha and cur_sha != boot_sha:
                print(f"[scheduler] 코드 갱신 감지({boot_sha[:7]}→{cur_sha[:7]}) — 재기동 종료")
                sys.exit(0)
            with lock_conn.cursor() as c:
                c.execute("SELECT pg_try_advisory_lock(hashtext('ves:scheduler')) AS got")
                got = c.fetchone()["got"]
            if not got:
                time.sleep(TICK_SEC)     # 다른 노드가 스케줄러 — 이번 틱 스킵
                continue
            try:
                now = dt.datetime.now(KST)
                # planner_kick: 값이 바뀌면 planner 즉시 1회(멱등 — R7·소스순환이 중복을 걸러줌)
                try:
                    due_kick, seen = kick_due(last.get("planner_kick"),
                                              _read_kick(conn), "planner_kick" in last)
                    last["planner_kick"] = seen
                    if due_kick:
                        print("[scheduler] planner_kick 감지 — planner 즉시 실행")
                        planner.run(conn, cfg)
                        last["planner"] = now
                except Exception as e:  # noqa: BLE001
                    print(f"[scheduler] planner_kick 처리 실패(무시): {e}")
                tasks = [
                    ("reaper",        lambda: reaper.run(conn),            _due_interval(last.get("reaper"), now, 1)),
                    ("version_watch", lambda: version_watch.run(conn, cfg), _due_interval(last.get("version_watch"), now, 60)),
                    ("reconcile",     lambda: reconcile.run(conn, cfg),     _due_interval(last.get("reconcile"), now, 60)),
                    ("drive_watch",   lambda: drive_watch.run(conn, cfg),   _due_daily(last.get("drive_watch"), now, 7)),
                    ("drive_balance", lambda: drive_balance.run(conn, cfg), _due_interval(last.get("drive_balance"), now, 5)),
                    ("source_watch",  lambda: source_watch.run(conn, cfg),  _due_interval(last.get("source_watch"), now, 60)),
                    ("planner",       lambda: planner.run(conn, cfg),       _due_daily(last.get("planner"), now, 9)),
                    ("channels_sync", lambda: channels_sync.run(conn, cfg), _due_daily(last.get("channels_sync"), now, 8)),
                    ("perf_sync",     lambda: perf_sync.run(conn, cfg),     _due_interval(last.get("perf_sync"), now, 60)),
                    ("zanmang_daily", lambda: zanmang_daily.run(conn, cfg), _due_daily(last.get("zanmang_daily"), now, 10)),
                    ("storage_gc",    lambda: storage_gc.run(conn, cfg),    _due_daily(last.get("storage_gc"), now, 6)),
                    ("editor_uploads_gc", lambda: editor_uploads_gc.run(conn, cfg), _due_daily(last.get("editor_uploads_gc"), now, 6)),
                ]
                for name, fn, due in tasks:
                    if not due:
                        continue
                    try:
                        print(f"[scheduler] {name} 실행")
                        fn()
                        last[name] = now
                    except Exception as e:  # noqa: BLE001 — 한 태스크 실패가 틱을 죽이지 않는다
                        print(f"[scheduler] {name} 실패: {type(e).__name__} {e}")
            finally:
                with lock_conn.cursor() as c:
                    c.execute("SELECT pg_advisory_unlock(hashtext('ves:scheduler'))")
            time.sleep(TICK_SEC)
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] 루프 오류: {e}\n{traceback.format_exc()[-400:]}")
            time.sleep(TICK_SEC)
            try:
                conn.close(); lock_conn.close()
            except Exception:  # noqa: BLE001
                pass
            conn = db.connect(cfg.db_url)
            lock_conn = db.connect(cfg.db_url)


if __name__ == "__main__":
    main()
