#!/usr/bin/env python3
"""잔존 편집실 재료 일괄 정리 — **기본은 dry-run**.

왜 필요한가: Storage 의 delete 는 body 필드명(prefixes)과 달리 **정확한 이름만**
지운다 — 일치 0건이어도 200 이다(supabase-js remove() 와 같은 계약, 폴더 삭제
미지원). storage_gc 는 편집실 카탈로그의 접두사 행('{h16}/editor/', 0042)을 그대로
넘겨 왔으므로 조용한 무동작이었고, 그 200 을 성공으로 믿고 kind 를 '_expired' 로
마킹해 재시도조차 막았다. 결과: 0042 이래 만료된 편집실 재료(스프라이트 시트·
scan ≤300MB·클로즈업·파형, 0049 부터 tts mp3)가 전부 잔존한다. GC 자체는
2026-08-19 에 고쳤다(ves/scheduler/storage_gc.py — 접두사를 list 로 확장해 삭제).
이 스크립트는 그 이전에 쌓인 잔존분을 한 번에 치운다.

dry-run 출력이 곧 실측 증거다: '_expired' 로 마킹된(= GC 가 지웠다고 믿은) 행의
접두사 아래에 객체가 그대로 나열되면, delete 가 접두사를 지우지 않는다는 계약을
실계정에서 재확인한 것이다.

무엇을 지우나 (접두사 단위로 판정):
  · 카탈로그가 '_expired' 인데 객체가 남은 것        — GC 무동작의 잔존분
  · 카탈로그가 살아 있지만 이미 만료(expires_at<now) — 수정된 GC 도 다음 주기에 지움
  · 카탈로그 행이 없는 것(_catalog 실패분)           — editor_assets 표에서 역산
무엇을 안 지우나:
  · 화면 TTL(editor_assets.expires_at) 또는 카탈로그 TTL 이 살아 있는 접두사 —
    편집실이 지금 서명 URL 로 쓰고 있을 수 있다.

사용:
    # 무엇이 얼마나 남았는지만 본다 (아무것도 지우지 않는다)
    python3 deploy/cleanup_editor_leftovers.py
    # 실제로 지운다 (삭제 후 접두사가 비었는지 재확인)
    python3 deploy/cleanup_editor_leftovers.py --apply

환경: SUPABASE_URL · SUPABASE_SERVICE_KEY (backfill_published_ts.py 와 같다).
카탈로그 행은 건드리지 않는다 — '_expired' 는 이미 맞는 상태가 되고, 만료 대기 행은
수정된 GC 가 다음 주기(06:00)에 마킹한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

PAGE = 1000                     # REST·Storage list 페이지 크기
DELETE_BATCH = 100              # delete 한 번에 넘길 이름 수(storage_gc 와 같은 값)
BUCKET_DEFAULT = "ves-outputs"  # 편집실 재료 버킷(editor_assets._catalog 고정값)


def die(msg):
    print(f"✗ {msg}", file=sys.stderr)
    raise SystemExit(1)


def env(k):
    return os.environ.get(k) or die(f"환경변수 {k} 필요")


def req(url, method="GET", headers=None, data=None, timeout=120):
    r = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def alive(ts: str | None, now) -> bool:
    """expires_at 이 아직 미래인가. 값이 없으면(만료 없음 취급) 보수적으로 산 것으로."""
    if not ts:
        return True
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")) > now
    except ValueError:
        return True


def editor_prefix(run_id: str) -> str:
    """run_id → '{h16}/editor/' — ves/adapters/base.storage_key 와 같은 공식."""
    return hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()[:16] + "/editor/"


def fetch_all(base, H, path_query) -> list:
    rows, off = [], 0
    while True:
        st, body = req(f"{base}/rest/v1/{path_query}&limit={PAGE}&offset={off}", headers=H)
        if st != 200:
            die(f"조회 실패 {st} ({path_query.split('?')[0]}): {body[:300]}")
        page = json.loads(body)
        rows += page
        if len(page) < PAGE:
            return rows
        off += PAGE


def list_objects(base, H, bucket, prefix) -> list:
    """접두사 아래 실물 (키, bytes) 전량 — 페이지네이션·하위 폴더 재귀 포함."""
    out, off = [], 0
    root = prefix.rstrip("/")
    while True:
        st, body = req(f"{base}/storage/v1/object/list/{bucket}", method="POST",
                       headers={**H, "Content-Type": "application/json"},
                       data=json.dumps({"prefix": root, "limit": PAGE, "offset": off,
                                        "sortBy": {"column": "name", "order": "asc"}
                                        }).encode("utf-8"))
        if st != 200:
            die(f"storage list {st}: {body[:300]}")
        batch = json.loads(body) or []
        for it in batch:
            name = it.get("name")
            if not name:
                continue
            if it.get("id") is None:           # 가상 폴더 — 한 단계 내려간다
                out += list_objects(base, H, bucket, f"{root}/{name}")
            else:
                size = (it.get("metadata") or {}).get("size") or 0
                out.append((f"{root}/{name}", int(size)))
        if len(batch) < PAGE:
            return out
        off += PAGE


def delete_names(base, H, bucket, names):
    for i in range(0, len(names), DELETE_BATCH):
        st, body = req(f"{base}/storage/v1/object/{bucket}", method="DELETE",
                       headers={**H, "Content-Type": "application/json"},
                       data=json.dumps({"prefixes": names[i:i + DELETE_BATCH]}
                                       ).encode("utf-8"))
        if st != 200:
            die(f"storage delete {st}: {body[:300]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 지운다(기본은 dry-run)")
    a = ap.parse_args()

    base = env("SUPABASE_URL").rstrip("/")
    skey = env("SUPABASE_SERVICE_KEY")
    H = {"Authorization": f"Bearer {skey}", "apikey": skey}
    now = datetime.now(timezone.utc)

    # 접두사 대장: 카탈로그(artifacts)와 화면 표(editor_assets) 양쪽에서 모은다 —
    # _catalog 은 실패해도 비치명이라, artifacts 에 없는 접두사가 실제로 있을 수 있다.
    cats = fetch_all(base, H, "artifacts?select=kind,sha256,bucket,object_key,expires_at"
                              "&kind=like.editor*&order=created_at")
    screens = fetch_all(base, H, "editor_assets?select=run_id,status,expires_at&order=run_id")

    reg: dict = {}

    def entry(prefix):
        return reg.setdefault(prefix, {"run_id": None, "bucket": BUCKET_DEFAULT,
                                       "protected": False, "reasons": []})

    for r in cats:
        p = r["object_key"] if str(r["object_key"]).endswith("/") else r["object_key"] + "/"
        e = entry(p)
        e["bucket"] = r.get("bucket") or BUCKET_DEFAULT
        sha = str(r.get("sha256") or "")
        if sha.startswith("editor:"):
            e["run_id"] = sha.split("editor:", 1)[1]
        if r["kind"] == "editor_assets" and alive(r.get("expires_at"), now):
            e["protected"] = True
            e["reasons"].append("카탈로그 TTL 생존")
        elif r["kind"] == "editor_assets":
            e["reasons"].append("만료 대기(GC 몫)")
        else:
            e["reasons"].append("'_expired' 마킹됨(GC 무동작 잔존)")

    for r in screens:
        e = entry(editor_prefix(r["run_id"]))
        e["run_id"] = e["run_id"] or r["run_id"]
        if alive(r.get("expires_at"), now):
            e["protected"] = True
            e["reasons"].append("화면 TTL 생존")
        elif not e["reasons"]:
            e["reasons"].append("카탈로그 행 없음(_catalog 실패분)")

    print(f"접두사 {len(reg)}개 (카탈로그 {len(cats)}행 · 화면 표 {len(screens)}행) — "
          f"실물 조회 중…")
    targets, kept, empty = [], 0, 0
    total_n = total_b = 0
    for prefix, e in sorted(reg.items()):
        if e["protected"]:
            kept += 1
            continue
        objs = list_objects(base, H, e["bucket"], prefix)
        if not objs:
            empty += 1
            continue
        n, b = len(objs), sum(s for _, s in objs)
        total_n += n
        total_b += b
        targets.append((prefix, e, [k for k, _ in objs]))
        print(f"  {e['run_id'] or prefix:<44} {n:>4}개 {b / 1e6:>8.1f}MB  "
              f"[{' · '.join(sorted(set(e['reasons'])))}]")

    print(f"\n합계: 지울 접두사 {len(targets)}개 · 객체 {total_n}개 · {total_b / 1e9:.2f}GB"
          f"  (보호 {kept} · 이미 빈 것 {empty})")
    if not targets:
        print("지울 것이 없습니다.")
        return
    if not a.apply:
        print("\n[dry-run] 아무것도 지우지 않았습니다 — 지우려면 --apply")
        return

    for prefix, e, names in targets:
        delete_names(base, H, e["bucket"], names)
        left = list_objects(base, H, e["bucket"], prefix)
        mark = "✓" if not left else f"⚠ {len(left)}개 남음(재실행 필요)"
        print(f"  {mark} {e['run_id'] or prefix}: {len(names)}개 삭제")
    print("\n✓ 완료. 만료 대기였던 카탈로그 행은 수정된 GC 가 다음 주기(06:00)에 "
          "'_expired' 로 마킹합니다.")


if __name__ == "__main__":
    main()
