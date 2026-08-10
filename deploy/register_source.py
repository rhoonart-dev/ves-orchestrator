#!/usr/bin/env python3
"""원본 소스 등록 — 메인 맥에서 실행 (표준 라이브러리만 사용, 의존성 0).

  source ~/rhoonart/_ves_secrets_draft.env
  python3 deploy/register_source.py --file ~/Movies/ep1.mp4 \
      --work "도깨비 10주년 여행" --episode 1 [--subtitle ep1.srt] [--use-limit 3]

하는 일: sha256 계산 → ves-sources 버킷 업로드(masters/<sha>) → sources 카탈로그
UPSERT → 회차 사용 현황 출력. 같은 파일을 다시 등록하면 업로드는 건너뛴다(content-addressed).
회차당 사용 한도 기본 3회(0010, 사용자 결정 2026-08-07) — planner 가 한도 소진 시 다음 회차로.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

CHUNK = 1 << 20


def die(msg):
    sys.exit(f"오류: {msg}")


def env(name):
    v = os.environ.get(name)
    if not v:
        die(f"{name} 미설정 — 먼저 `source ~/rhoonart/_ves_secrets_draft.env` 하세요")
    return v


def sha256_of(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


class Progress:
    """업로드 진행률 — urllib 이 read() 하는 만큼 % 출력."""

    def __init__(self, path, total):
        self.f, self.total, self.sent, self.mark = open(path, "rb"), total, 0, 0

    def read(self, n=-1):
        b = self.f.read(n)
        self.sent += len(b)
        if self.total and self.sent - self.mark >= (100 << 20):
            self.mark = self.sent
            print(f"  … {self.sent * 100 // self.total}% ({self.sent >> 20}MB)")
        return b


def req(url, method="GET", headers=None, data=None, timeout=120):
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".ts", ".avi", ".webm")


def guess_episode(name: str):
    """파일명 → 회차 추정. 명시 표기만 신뢰(E01·ep.2·제3회·4화) — '시즌5' 같은
    제목 속 숫자를 회차로 오인하지 않는다. 못 찾으면 None — 순수."""
    import re
    s = pathlib.Path(name).stem
    for pat in (r"[Ee][Pp]?\.?\s*(\d{1,4})(?!\d)",
                r"제\s*(\d{1,4})\s*[화회]?",
                r"(\d{1,4})\s*[화회]"):
        m = re.search(pat, s)
        if m:
            return int(m.group(1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="마스터 영상 파일 1개")
    ap.add_argument("--dir", help="폴더 통째 등록 — 회차는 파일명(E01/1화/숫자)에서 추정, "
                                  "동명 .srt 자막 자동 동반")
    ap.add_argument("--work", required=True, help="작품명 (laeebly 정본과 정확히 일치 — R14)")
    ap.add_argument("--episode", type=int, default=None, help="회차 (영화 등 단회차는 생략)")
    ap.add_argument("--subtitle", default=None, help="자막 파일(.srt) — 있으면 함께 등록")
    ap.add_argument("--use-limit", type=int, default=3, help="이 회차 사용 한도(기본 3)")
    a = ap.parse_args()
    (a.file or a.dir) or die("--file 또는 --dir 필요")

    if a.dir:
        d = pathlib.Path(a.dir).expanduser()
        d.is_dir() or die(f"폴더 없음: {d}")
        vids = sorted(p for p in d.iterdir() if p.suffix.lower() in VIDEO_EXTS)
        vids or die(f"영상 파일 없음: {d}")
        print(f"폴더 등록: {len(vids)}개 파일")
        for i, v in enumerate(vids, start=1):
            ep = guess_episode(v.name) or i
            srt = v.with_suffix(".srt")
            print(f"\n── {v.name} → {a.work} {ep}화"
                  + (f" (+자막)" if srt.exists() else ""))
            register_one(v, a.work, ep, srt if srt.exists() else None, a.use_limit)
        summary(a.work)
        return
    register_one(pathlib.Path(a.file).expanduser(), a.work, a.episode,
                 pathlib.Path(a.subtitle).expanduser() if a.subtitle else None, a.use_limit)
    summary(a.work)


def register_one(path, work, episode, subtitle, use_limit):

    base = env("SUPABASE_URL").rstrip("/")
    key = env("SUPABASE_SERVICE_KEY")
    H = {"Authorization": f"Bearer {key}", "apikey": key}

    path.is_file() or die(f"파일 없음: {path}")
    size = path.stat().st_size
    print(f"[1/3] sha256 계산 중… ({size >> 20}MB)")
    sha = sha256_of(path)
    okey = f"masters/{sha}"
    print(f"      {sha[:16]}… → ves-sources/{okey}")

    st, _ = req(f"{base}/storage/v1/object/info/ves-sources/{okey}", headers=H)
    if st == 200:
        print("[2/3] 업로드 생략 — 같은 내용이 이미 버킷에 있음(content-addressed)")
    else:
        print("[2/3] 업로드 중…")
        st, body = req(f"{base}/storage/v1/object/ves-sources/{okey}", method="POST",
                       headers={**H, "Content-Type": "application/octet-stream",
                                "x-upsert": "true", "Content-Length": str(size)},
                       data=Progress(path, size), timeout=3600 * 6)
        st in (200, 201) or die(f"업로드 실패 {st}: {body[:300]}\n"
                                "(파일 크기 제한이면 Supabase 대시보드 Storage 설정에서 상향)")

    sub_key = None
    if subtitle:
        sp = pathlib.Path(subtitle).expanduser()
        sp.is_file() or die(f"자막 없음: {sp}")
        sub_key = f"{okey}.srt"
        st, body = req(f"{base}/storage/v1/object/ves-sources/{sub_key}", method="POST",
                       headers={**H, "Content-Type": "application/octet-stream",
                                "x-upsert": "true",
                                "Content-Length": str(sp.stat().st_size)},
                       data=open(sp, "rb"), timeout=600)
        st in (200, 201) or die(f"자막 업로드 실패 {st}: {body[:200]}")

    print("[3/3] 카탈로그(sources) 등록…")
    epq = f"episode=eq.{episode}" if episode is not None else "episode=is.null"
    qwork = urllib.parse.quote(work)
    st, body = req(f"{base}/rest/v1/sources?work_title=eq.{qwork}&{epq}&select=id", headers=H)
    st == 200 or die(f"조회 실패 {st}: {body[:200]}")
    row = {"work_title": work, "episode": episode, "sha256": sha, "object_key": okey,
           "bytes": size, "has_subtitle": bool(sub_key), "subtitle_key": sub_key,
           "origin": "drive", "use_limit": use_limit, "is_active": True}
    js = json.dumps(row, ensure_ascii=False).encode("utf-8")
    JH = {**H, "Content-Type": "application/json", "Prefer": "return=minimal"}
    if json.loads(body):
        rid = json.loads(body)[0]["id"]
        st, body = req(f"{base}/rest/v1/sources?id=eq.{rid}", method="PATCH", headers=JH, data=js)
        (st in (200, 204)) or die(f"카탈로그 실패 {st}: {body[:300]}")
        print(f"      기존 회차 갱신 (id={rid})")
    else:
        st, body = req(f"{base}/rest/v1/sources", method="POST", headers=JH, data=js)
        st == 201 or die(f"카탈로그 실패 {st}: {body[:300]}")
        print("      신규 회차 등록")


def summary(work):
    base = env("SUPABASE_URL").rstrip("/")
    key = env("SUPABASE_SERVICE_KEY")
    H = {"Authorization": f"Bearer {key}", "apikey": key}
    print("\n회차 현황:")
    st, body = req(f"{base}/rest/v1/source_usage?work_title=eq.{urllib.parse.quote(work)}"
                   f"&select=episode,times_used,use_limit,remaining&order=episode", headers=H)
    for r in (json.loads(body) if st == 200 else []):
        mark = "⚠ 소진" if r["remaining"] == 0 else f"남음 {r['remaining']}"
        print(f"  {r['episode']}화: {r['times_used']}/{r['use_limit']} 사용 · {mark}")
    print("완료. planner 가 다음 주기부터 이 소스를 회차 순서대로 사용합니다.")


if __name__ == "__main__":
    main()
