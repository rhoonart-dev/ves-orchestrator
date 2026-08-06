#!/usr/bin/env python3
"""잡 실행기 — 어댑터 디스패치 · caffeinate · lease 갱신 스레드 · 펜싱 완료/실패.

subprocess 형 어댑터: caffeinate -i 로 감싸 실행(슬립 → lease 만료 루프 방지, §6-2).
LeaseRenewer.lost 가 서면(소유권 상실·사람 취소) 서브프로세스를 즉시 kill —
남의 잡이 된 작업에 컴퓨트를 낭비하지 않는다(★⑤).
"""
from __future__ import annotations

import json
import subprocess

from ves import config as cfgmod
from ves import db
from ves.adapters import base
from ves.agent import lease, resources
from ves.agent.claim import return_pending

CAFFEINATE = "/usr/bin/caffeinate"
RESOURCE_RETRY_SEC = 120


def _dep_results(conn, job) -> dict:
    """선행 잡 결과 모음 {kind: result} — upload_artifacts 등이 run_dir 를 읽는 용도."""
    ids = job.get("depends_on") or []
    if not ids:
        return {}
    with conn.cursor() as c:
        c.execute("SELECT kind, result FROM public.job_queue WHERE id = ANY(%s)", (list(ids),))
        return {r["kind"]: (r["result"] or {}) for r in c.fetchall()}


def run_job(cfg, conn, job) -> None:
    ad = base.get(job["kind"])
    if ad is None:
        lease.fail(conn, job, f"어댑터 없음: {job['kind']}", "permanent")
        return

    # 멱등 스킵(§6-6): 이미 된 일은 다시 하지 않는다
    try:
        if getattr(ad, "is_already_done", None) and ad.is_already_done(cfg, job):
            lease.complete(conn, job, {"skipped": "already_done"})
            return
    except Exception as e:  # noqa: BLE001 — 선확인 실패는 본 실행으로 진행
        print(f"[executor] is_already_done 오류(본 실행 진행): {e}")

    # 자원 세마포어(§7): 포화면 잡 반납 — 슬롯을 점유하지 않는다
    res = None
    res_fn = getattr(ad, "resource", None)
    if res_fn:
        res = res_fn(cfg, job)
    if res and not resources.acquire(conn, res, job["id"], cfg.node_id):
        return_pending(conn, job, RESOURCE_RETRY_SEC, f"자원 포화: {res}")
        return

    try:
        if hasattr(ad, "run"):                       # 네이티브 어댑터
            result = ad.run(cfg, conn, job, _dep_results(conn, job))
        else:                                        # subprocess 어댑터
            result = _run_subprocess(cfg, conn, job, ad)
        result = dict(result or {})
        result["engine_sha"] = _local_shas(cfg)      # 디버깅용 실행 시점 sha(§11-1)
        if lease.complete(conn, job, result):
            hook = getattr(ad, "post_success", None)
            if hook:
                try:
                    hook(cfg, conn, job, result)
                except Exception as e:  # noqa: BLE001 — 훅 실패가 성공을 뒤집지 않는다
                    print(f"[executor] post_success 오류: {e}")
        else:
            _record_orphan(conn, job, result)        # 소유권 상실분 기록(지표16)
    except base.QuotaError as e:
        lease.fail(conn, job, str(e), "quota", until=e.until,
                   result_patch=getattr(e, "patch", None))
    except base.HumanRequired as e:
        lease.fail(conn, job, str(e), "human_required")
    except base.PermanentError as e:
        lease.fail(conn, job, str(e), "permanent")
    except Exception as e:  # noqa: BLE001
        lease.fail(conn, job, f"{type(e).__name__}: {e}", "transient")
    finally:
        if res:
            try:
                resources.release(conn, res, job["id"])
            except Exception:  # noqa: BLE001
                pass


def _run_subprocess(cfg, conn, job, ad) -> dict:
    partial = ((job.get("result") or {}).get("partial_run_id"))
    argv = None
    if job["attempt"] > 1 and partial and hasattr(ad, "resume_argv"):
        argv = ad.resume_argv(cfg, job, partial)     # ★⑦ 체크포인트 재개 — 68분 재소각 방지
    if argv is None:
        argv = ad.build_argv(cfg, job)
    cwd = getattr(ad, "cwd", lambda c, j: None)(cfg, job)
    env = getattr(ad, "env", lambda c, j: None)(cfg, job)

    cmd = ([CAFFEINATE, "-i"] if _has_caffeinate() else []) + argv
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with lease.LeaseRenewer(lambda: db.connect(cfg.db_url), job) as lr:
        while True:
            try:
                out, err = proc.communicate(timeout=5)
                break
            except subprocess.TimeoutExpired:
                if lr.lost.is_set():                  # 소유권 상실/취소 → 즉시 중단(★⑤)
                    proc.kill()
                    out, err = proc.communicate()
                    raise base.PermanentError("소유권 상실로 중단(orphan)")  # fail 은 펜싱에 막혀 no-op

    if proc.returncode == 0:
        return ad.parse_result(cfg, job, out or "")
    cls = ad.classify_error(proc.returncode, err or "", out or "") \
        if hasattr(ad, "classify_error") else base.classify_by_patterns(err or "", out or "")
    patch = {}
    rid = getattr(ad, "extract_partial_run_id", lambda o: None)(out or "")
    if rid:
        patch["partial_run_id"] = rid                 # 실패해도 재개 근거는 남긴다(★⑦)
    msg = (err or out or "")[-800:]
    if cls == "quota":
        raise base.QuotaError(msg)
    if cls == "permanent":
        raise base.PermanentError(msg)
    e = RuntimeError(msg)
    e.patch = patch  # type: ignore[attr-defined]
    raise e


def _record_orphan(conn, job, result):
    try:
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.artifacts(job_id, work_order_id, kind, sha256,
                                                bytes, bucket, object_key)
                   VALUES (%s,%s,'result_orphan',%s,0,'-', %s)
                   ON CONFLICT DO NOTHING""",
                (job["id"], job["work_order_id"],
                 base.idem_key(job["id"], "orphan", result), f"orphan/{job['id']}"))
    except Exception as e:  # noqa: BLE001
        print(f"[executor] orphan 기록 실패(무시): {e}")


def _local_shas(cfg) -> dict:
    out = {}
    for eng in cfgmod.ENGINE_DIRS:
        try:
            r = subprocess.run(["git", "-C", cfgmod.engine_dir(cfg, eng),
                                "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                out[eng] = r.stdout.strip()
        except Exception:  # noqa: BLE001
            pass
    return out


def _has_caffeinate() -> bool:
    import os
    return os.path.exists(CAFFEINATE)
