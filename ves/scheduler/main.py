#!/usr/bin/env python3
"""스케줄러 틱 루프 — advisory lock 으로 '한 번에 한 대만' (§3·§8-2).

scheduler capability 를 2~3대에 켜두면 리더 선출 없이 자동 승계된다:
락을 못 잡은 노드는 그 틱을 조용히 스킵한다. 모든 태스크는 멱등 — 재실행이 안전하다.
실행: python -m ves.scheduler.main  (launchd, scheduler 태그 노드만)
"""
from __future__ import annotations

import datetime as dt
import time
import traceback

from ves import db
from ves.config import get_config
from ves.scheduler import channels_sync, planner, reaper, reconcile, storage_gc, version_watch

KST = dt.timezone(dt.timedelta(hours=9))
TICK_SEC = 30


def _due_daily(last: dt.datetime | None, now: dt.datetime, hour: int) -> bool:
    """KST hour시 이후 오늘 아직 안 돌았으면 due. (잠들어 있었으면 깨어날 때 보충 — launchd 관행)"""
    if now.hour < hour:
        return False
    return last is None or last.astimezone(KST).date() < now.date()


def _due_interval(last: dt.datetime | None, now: dt.datetime, minutes: int) -> bool:
    return last is None or (now - last) >= dt.timedelta(minutes=minutes)


def main():
    cfg = get_config()
    conn = db.connect(cfg.db_url)
    lock_conn = db.connect(cfg.db_url)   # advisory lock 전용 세션(세션 락)
    last: dict = {}
    print(f"[scheduler] {cfg.node_id} 기동")

    while True:
        try:
            with lock_conn.cursor() as c:
                c.execute("SELECT pg_try_advisory_lock(hashtext('ves:scheduler')) AS got")
                got = c.fetchone()["got"]
            if not got:
                time.sleep(TICK_SEC)     # 다른 노드가 스케줄러 — 이번 틱 스킵
                continue
            try:
                now = dt.datetime.now(KST)
                tasks = [
                    ("reaper",        lambda: reaper.run(conn),            _due_interval(last.get("reaper"), now, 1)),
                    ("version_watch", lambda: version_watch.run(conn, cfg), _due_interval(last.get("version_watch"), now, 60)),
                    ("reconcile",     lambda: reconcile.run(conn, cfg),     _due_interval(last.get("reconcile"), now, 60)),
                    ("planner",       lambda: planner.run(conn, cfg),       _due_daily(last.get("planner"), now, 9)),
                    ("channels_sync", lambda: channels_sync.run(conn, cfg), _due_daily(last.get("channels_sync"), now, 8)),
                    ("storage_gc",    lambda: storage_gc.run(conn, cfg),    _due_daily(last.get("storage_gc"), now, 6)),
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
