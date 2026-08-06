#!/usr/bin/env python3
"""version_watch — origin 최신 sha 를 시간당 1회만 조회해 deployments 에 기록 (§11-1).

워커가 직접 ls-remote 를 치면 6대×분당 20회 = 시간당 7,200회 원격 조회가 된다.
원격 조회는 여기 한 곳, 워커는 DB 문자열 비교만(비용 0).
"""
from __future__ import annotations

import subprocess


def run(conn, cfg):
    with conn.cursor() as c:
        c.execute("SELECT engine, repo_url, track_ref FROM public.deployments")
        rows = c.fetchall()
    for d in rows:
        sha = _ls_remote(d["repo_url"], d["track_ref"])
        if not sha:
            print(f"[version_watch] {d['engine']} ls-remote 실패 — 이번 주기 보류")
            continue
        with conn.cursor() as c:
            c.execute("""UPDATE public.deployments
                            SET last_seen_sha=%s, updated_at=now()
                          WHERE engine=%s AND last_seen_sha IS DISTINCT FROM %s""",
                      (sha, d["engine"], sha))
            if c.rowcount:
                print(f"[version_watch] {d['engine']} → {sha[:7]} (새 커밋 감지)")


def _ls_remote(repo_url, ref):
    try:
        r = subprocess.run(["git", "ls-remote", repo_url, ref],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split()[0]
    except Exception as e:  # noqa: BLE001
        print(f"[version_watch] {repo_url}: {e}")
    return None
