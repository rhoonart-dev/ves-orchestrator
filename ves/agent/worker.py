#!/usr/bin/env python3
"""ves-agent 메인 루프 — 6대 전부 이 프로그램 하나를 돌린다 (동질 워커, §6).

루프: heartbeat → (버전 드리프트 확인·갱신) → claim → 실행.
유휴 백오프는 poll_sec→poll_max_sec (VES_POLL_SEC/VES_POLL_MAX_SEC, 기본 둘 다 180초 — 사실상 고정 180초).
★'일했다'에 반납은 안 든다(next_idle) — 반납을 리셋으로 세면 못 하는 노드가 무휴면
재폴링으로 큐를 독식한다. 애초에 못 할 잡은 집지도 않는다(claim 의 skip_kinds).
명령 채널은 없다 — 일감은 테이블에 있고, 이 루프가 폴링 주기마다 스스로 집어간다(pull 모델).
실행: /opt/ves/orchestrator/.venv/bin/python -m ves.agent.worker  (launchd KeepAlive)
"""
from __future__ import annotations

import time
import traceback

from ves import db
from ves.agent import claim as claim_mod
from ves.agent import diskgc, executor, gemini_key, updater
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
    import json
    import shutil
    free_gb = shutil.disk_usage(cfg.home).free / 2**30 if _exists(cfg.home) else None
    # 이 맥이 가진 Gemini 키 슬롯(0025) — 예비 키 배포가 6대 중 어디까지 됐는지 관제가 본다.
    # 키 값이 아니라 '있다/없다'만 올린다.
    meta = json.dumps({"gemini_slots": gemini_key.available_slots()}, ensure_ascii=False)
    with conn.cursor() as c:
        c.execute("UPDATE public.node_registry "
                  "   SET last_seen_at=now(), disk_free_gb=%s, "
                  "       meta = coalesce(meta,'{}'::jsonb) || %s::jsonb "
                  " WHERE node_id=%s", (free_gb, meta, cfg.node_id))
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
    blocked_prev = []          # 디스크로 보류한 kind — 바뀔 때만 로그
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

            # 못 할 잡은 애초에 안 집는다 — 집었다 반납하면 그 유예(15분)가 모든 노드에
            # 걸려, 디스크가 찬 한 대가 큐 전체를 세운다(8/25 실측 — claim.skip_kinds)
            free = free_bytes(cfg)
            blocked = executor.blocked_kinds(free)
            if blocked != blocked_prev:
                # 조용히 멈추지 않는다 — 8/25 정지를 두 시간 아무도 몰랐던 이유가 이거다.
                # 상태가 바뀔 때만 찍는다(매 주기면 로그가 무의미해진다).
                print(f"[worker] 디스크 {free / 1e9:.1f}GB — 무거운 잡 보류: {blocked}"
                      if blocked else
                      f"[worker] 디스크 {free / 1e9:.1f}GB — 무거운 잡 재개")
                blocked_prev = blocked
            job = claim_mod.claim(conn, cfg.node_id, cfg.capabilities, blocked)
            if job is None:
                time.sleep(idle_sleep)
                idle_sleep = next_idle(idle_sleep, cfg, worked=False)  # 유휴 백오프
                continue
            print(f"[worker] 잡 {job['kind']} {str(job['id'])[:8]} 시작 (attempt {job['attempt']})")
            worked = executor.run_job(cfg, conn, job) != executor.RETURNED
            if not worked:
                # ★반납은 '일했다'가 아니다. 여기서 안 쉬면 반납(18ms)마다 곧장 재폴링해
                # 못 하는 노드가 큐를 독식한다 — 위 사전 필터가 못 막은 경우의 짝.
                time.sleep(idle_sleep)
            idle_sleep = next_idle(idle_sleep, cfg, worked=worked)
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


def next_idle(current: float, cfg, *, worked: bool) -> float:
    """다음 유휴 폴링 간격 — 일했으면 리셋, 아니면(빈 큐·반납) 한 칸 백오프.
    ★반납을 '일했다'로 세면 안 된다: 못 하는 노드가 무휴면 재폴링으로 큐를 독식한다
    (8/25 실측 — mm-06 이 반납 18ms 마다 재폴링해 일일 배치를 2시간 세웠다).
    순수 — 테스트 대상."""
    return cfg.poll_sec if worked else min(current * 1.7, cfg.poll_max_sec)


def free_bytes(cfg) -> int:
    """이 노드의 홈 여유 공간. 못 읽으면 0 — 모르면 무거운 잡을 안 받는 쪽으로 판정한다."""
    import shutil
    try:
        return shutil.disk_usage(cfg.home).free if _exists(cfg.home) else 0
    except OSError:
        return 0


def _exists(p):
    import os
    return os.path.exists(p)


if __name__ == "__main__":
    main()
