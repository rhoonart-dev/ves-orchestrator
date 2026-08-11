#!/usr/bin/env python3
"""잡 실행기 — 어댑터 디스패치 · caffeinate · lease 갱신 스레드 · 펜싱 완료/실패.

subprocess 형 어댑터: caffeinate -i 로 감싸 실행(슬립 → lease 만료 루프 방지, §6-2).
LeaseRenewer.lost 가 서면(소유권 상실·사람 취소) 서브프로세스를 즉시 kill —
남의 잡이 된 작업에 컴퓨트를 낭비하지 않는다(★⑤).
"""
from __future__ import annotations

import json
import shutil
import subprocess

from ves import config as cfgmod
from ves import db
from ves.adapters import base
from ves.agent import lease, resources
from ves.agent.claim import return_pending

CAFFEINATE = "/usr/bin/caffeinate"
RESOURCE_RETRY_SEC = 120

# 디스크 사전 점검(8/11 실측: mm-01 0.1GB 로 잡을 집어 전부 죽임 — 오염 워커 방지)
HEAVY_KINDS = {"acquire", "generate", "sync_drive_folder", "localize", "zanmang_autopilot"}
MIN_FREE_GB = 15
DISK_RETRY_SEC = 900


def disk_ok(free_bytes: int, min_gb: int = MIN_FREE_GB) -> bool:
    """무거운 잡을 받아도 되는가. 순수 — 테스트 대상."""
    return free_bytes >= min_gb * (1000 ** 3)


def merge_dep_outputs(params, deps) -> dict:
    """선행 잡 결과에서 run_id/run_dir 를 params 로 승계(기존 값 우선). 순수 — 테스트 대상."""
    merged = dict(params or {})
    for d in (deps or {}).values():
        if not isinstance(d, dict):
            continue
        for k in ("run_id", "run_dir"):
            if d.get(k) and not merged.get(k):
                merged[k] = d[k]
    return merged


def carry_chain_keys(params, result) -> dict:
    """★체인 계약(첫 전체 회전 실측): run_id/run_dir 를 결과에 자동 재방출 —
    ingest 처럼 어댑터가 되돌려주길 잊어도 다음 잡(evaluate/localize)으로 끊기지 않는다.
    어댑터가 스스로 넣은 값이 우선. 순수 — 테스트 대상."""
    out = dict(result or {})
    for k in ("run_id", "run_dir"):
        if (params or {}).get(k) and not out.get(k):
            out[k] = params[k]
    return out


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

    # 디스크 사전 점검 — 부족하면 잡을 반납해 건강한 노드가 가져가게 한다(8/11 mm-01 실측)
    if job["kind"] in HEAVY_KINDS:
        try:
            free = shutil.disk_usage(cfg.home).free
        except OSError:
            free = 0
        if not disk_ok(free):
            return_pending(conn, job, DISK_RETRY_SEC,
                           f"디스크 부족({free / 1e9:.1f}GB < {MIN_FREE_GB}GB) — 반납")
            return

    # ★체인 계약: 선행 잡 결과(run_id·run_dir)를 params 에 병합 — ingest/evaluate/publish
    # (subprocess형)가 generate 산출 위치를 알게 한다. (스모크2에서 발견한 전파 누락 수정)
    deps = _dep_results(conn, job)
    job = {**job, "params": merge_dep_outputs(job.get("params"), deps)}

    # 실행 직전 주입(관제 오버라이드 등, 0014) — 어댑터 선택 훅. 실패는 기본값 강등일 뿐.
    hook = getattr(ad, "enrich_params", None)
    if hook:
        try:
            job = {**job, "params": hook(cfg, conn, job) or job["params"]}
        except Exception as e:  # noqa: BLE001
            print(f"[executor] enrich_params 오류(기본값 진행): {e}")

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
            # 네이티브도 lease 갱신 필요(스모크3 후속): 업로드·judge 가 TTL 을 넘으면
            # reaper 가 산 잡을 뺏는다. complete 는 펜싱이 있으니 갱신만 보장하면 된다.
            with lease.LeaseRenewer(lambda: db.connect(cfg.db_url), job):
                result = ad.run(cfg, conn, job, deps)
        else:                                        # subprocess 어댑터
            result = _run_subprocess(cfg, conn, job, ad)
        result = carry_chain_keys(job["params"], result)
        result["engine_sha"] = _local_shas(cfg)      # 디버깅용 실행 시점 sha(§11-1)
        if lease.complete(conn, job, result):
            _pin_dependents(conn, job, ad)           # 로컬 산출물 어피니티(스모크3 실측)
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


def _pin_dependents(conn, job, ad) -> None:
    """산출물을 로컬 디스크에 남기는 잡(generate)이 끝나면, 그 파일을 읽는 후속 kind 들을
    이 노드로 고정한다 — required_caps 에 'node:<노드>' 를 추가(claim 의 <@ 가 걸러줌).
    스모크3 실측: upload_artifacts 재시도가 다른 노드에 떨어져 'shorts 없음' 즉사.
    수동 해제(노드 사망 시): UPDATE job_queue SET required_caps=array_remove(required_caps,
    'node:mm-0X') WHERE work_order_id='…' AND status='pending';"""
    kinds = getattr(ad, "PIN_DEPENDENT_KINDS", ())
    if not kinds:
        return
    cap = [f"node:{job['node_id']}"]
    try:
        with conn.cursor() as c:
            c.execute(
                """UPDATE public.job_queue
                      SET required_caps = required_caps || %s::text[], updated_at=now()
                    WHERE work_order_id=%s AND kind = ANY(%s) AND status='pending'
                      AND NOT required_caps @> %s::text[]""",
                (cap, job["work_order_id"], list(kinds), cap))
    except Exception as e:  # noqa: BLE001 — 고정 실패는 종전(비고정) 동작으로 강등될 뿐
        print(f"[executor] 어피니티 고정 실패(무시): {e}")


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
