#!/usr/bin/env python3
"""ves-agent 메인 루프 — 6대 전부 이 프로그램 하나를 돌린다 (동질 워커, §6).

루프: heartbeat → (버전 드리프트 확인·갱신) → claim → 실행. 유휴 백오프 3→30초.
명령 채널은 없다 — 일감은 테이블에 있고, 이 루프가 3초마다 스스로 집어간다(pull 모델).
실행: /opt/ves/orchestrator/.venv/bin/python -m ves.agent.worker  (launchd KeepAlive)
"""
from __future__ import annotations

import time
import traceback

from ves import db
from ves.agent import claim as claim_mod
from ves.agent import diskgc, executor, updater
from ves.config import get_config


def register_node(conn, cfg):
    import shutil
    free_gb = shutil.disk_usage(cfg.home).free / 2**30 if _exists(cfg.home) else None
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.node_registry(node_id, capabilities, max_concurrency,
                                                status, disk_free_gb, last_seen_at)
               VALUES (%s,%s,%s,'active',%s,now())
               ON CONFLICT (node_id) DO UPDATE
                 SET capabilities=EXCLUDED.capabilities,
                     max_concurrency=EXCLUDED.max_concurrency,
                     disk_free_gb=EXCLUDED.disk_free_gb, last_seen_at=now()""",
            (cfg.node_id, claim_mod.effective_caps(cfg.capabilities, cfg.node_id),
             cfg.max_concurrency, free_gb))


def heartbeat(conn, cfg):
    import shutil
    free_gb = shutil.disk_usage(cfg.home).free / 2**30 if _exists(cfg.home) else None
    with conn.cursor() as c:
        c.execute("UPDATE public.node_registry SET last_seen_at=now(), disk_free_gb=%s "
                  "WHERE node_id=%s", (free_gb, cfg.node_id))
        c.execute("SELECT status FROM public.node_registry WHERE node_id=%s", (cfg.node_id,))
        row = c.fetchone()
    return (row or {}).get("status", "active")


def main():
    cfg = get_config()
    if not cfg.db_url:
        raise SystemExit("PIPELINE_DB_URL 없음 — /etc/ves/node.env · secrets/ves.env 확인")
    conn = db.connect(cfg.db_url)
    register_node(conn, cfg)
    print(f"[worker] {cfg.node_id} 기동 · caps={cfg.capabilities}")

    idle_sleep = cfg.poll_sec
    last_gc = 0.0
    while True:
        try:
            # 로컬 디스크 청소(6시간마다) — 잡보다 먼저. 디스크가 막히면 잡도 못 돈다.
            if time.time() - last_gc > diskgc.INTERVAL_SEC:
                last_gc = time.time()
                try:
                    diskgc.run(cfg)
                except Exception as e:  # noqa: BLE001 — 청소 실패가 루프를 죽이지 않는다
                    print(f"[worker] diskgc 오류(무시): {e}")
            status = heartbeat(conn, cfg)
            if status == "disabled":          # 사람이 대시보드에서 내린 상태 — 대기만
                time.sleep(30)
                continue
            updater.check_and_update(cfg, conn)   # §11 — 드리프트면 여기서 갱신(드레인 포함)
            if status == "draining":          # 새 잡 안 받음(하던 건 이 루프 구조상 없음)
                time.sleep(10)
                continue

            job = claim_mod.claim(conn, cfg.node_id, cfg.capabilities)
            if job is None:
                time.sleep(idle_sleep)
                idle_sleep = min(idle_sleep * 1.7, cfg.poll_max_sec)  # 유휴 백오프
                continue
            idle_sleep = cfg.poll_sec
            print(f"[worker] 잡 {job['kind']} {str(job['id'])[:8]} 시작 (attempt {job['attempt']})")
            executor.run_job(cfg, conn, job)
        except SystemExit:
            raise                              # 자기 갱신 exit(42) — launchd 가 재기동
        except Exception as e:  # noqa: BLE001 — 루프는 죽지 않는다
            print(f"[worker] 루프 오류: {type(e).__name__} {e}\n{traceback.format_exc()[-500:]}")
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(10)
            conn = db.connect(cfg.db_url)


def _exists(p):
    import os
    return os.path.exists(p)


if __name__ == "__main__":
    main()
