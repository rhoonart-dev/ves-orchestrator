#!/usr/bin/env python3
"""유튜브 소스 회차 재파싱 이행 도구 (0027 후속) — **기본은 dry-run**.

왜 필요한가: 0027 이전에 등록된 유튜브 행의 episode 는 '목록 위치 순번'이다.
0027 백필은 그런 행을 전부 episode_source='ordinal' 로 표시했지만, 두 가지가 남았다.
  ① 실제로는 제목에서 뽑은 방송 회차인데 ordinal 로 잘못 찍힌 행이 있다
     (실측: 「언니네 산지직송 in 칼라페」 901·902 — 서수라면 1~7 이어야 한다).
     ordinal 로 남으면 발행 설명란에서 회차 표기가 통째로 생략된다.
  ② 서수인 행은 방송 회차로 고쳐야 설명란에 옳은 'N화' 가 박힌다.

왜 위험한가: episode 를 바꾸면 레거시 장부(source_usage_legacy)가 (작품·채널·회차)로
물려 있어 매칭이 끊긴다. 끊기면 구 시스템이 이미 쓴 몫이 planner 에 반영되지 않아
중복 생산이 난다. 그래서 이 도구는 **바꾸기 전에 그 충돌을 먼저 보여준다**.

사용:
    # 무엇이 어떻게 바뀌는지만 본다 (아무것도 바꾸지 않는다)
    python3 deploy/reparse_youtube_episodes.py --work "놀라운 토요일"
    python3 deploy/reparse_youtube_episodes.py --all
    # 레거시 충돌이 없는 작품만 실제로 반영
    python3 deploy/reparse_youtube_episodes.py --work "언더커버셰프" --apply

환경: SUPABASE_URL · SUPABASE_SERVICE_KEY (register_source.py 와 같다).
yt-dlp 는 ai-video venv 모듈로 부른다 — 없으면 --python 으로 지정.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import unicodedata
import urllib.parse
import urllib.request


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


def guess_episode_title(title: str, regex: str = ""):
    """제목 → 방송 회차. ves/adapters/base.py 의 동명 함수와 같은 규칙(사본 유지 —
    이 스크립트는 무의존으로 어디서나 돌아야 한다). 어떤 입력에도 죽지 않는다."""
    t = unicodedata.normalize("NFC", str(title or ""))
    pats = (regex,) if regex else (r"[Ee][Pp]?\.?\s*(\d{1,4})(?!\d)",
                                   r"제\s*(\d{1,4})\s*[화회]?",
                                   r"(\d{1,4})\s*[화회]")
    for pat in pats:
        try:
            m = re.search(pat, t)
        except re.error:
            return None
        if m:
            try:
                return int(m.group(1))
            except (IndexError, ValueError):
                return None
    return None


def fetch_titles(url: str, py: str) -> dict:
    """플레이리스트/채널 → {영상URL: 제목}. yt-dlp --flat-playlist."""
    argv = [py, "-m", "yt_dlp", "--flat-playlist", "-J", url]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        die(f"yt-dlp 실패: {(r.stderr or r.stdout)[-400:]}")
    data = json.loads(r.stdout or "{}")
    out = {}
    for e in (data.get("entries") or ([data] if data.get("id") else [])):
        vid = (e or {}).get("id")
        if vid:
            out[f"https://www.youtube.com/watch?v={vid}"] = str((e or {}).get("title") or "")
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--work", help="작품명(laeebly 정본 표기)")
    g.add_argument("--all", action="store_true", help="work_cards 의 모든 작품")
    ap.add_argument("--apply", action="store_true",
                    help="실제로 UPDATE 한다. 없으면 dry-run(기본)")
    ap.add_argument("--python", default=None, help="yt-dlp 를 가진 파이썬 경로")
    a = ap.parse_args()

    base = env("SUPABASE_URL").rstrip("/")
    key = env("SUPABASE_SERVICE_KEY")
    H = {"Authorization": f"Bearer {key}", "apikey": key}
    JH = {**H, "Content-Type": "application/json", "Prefer": "return=minimal"}
    py = a.python or _ai_video_python()

    st, body = req(f"{base}/rest/v1/work_cards?select=work_title,title_episode_regex,"
                   f"title_filter,playlist_url", headers=H)
    st == 200 or die(f"work_cards 조회 실패 {st}: {body[:200]}")
    cards = {c["work_title"]: c for c in json.loads(body)}
    if not cards:
        die("work_cards 가 비어 있다 — 0030 시드를 먼저 적용하라")

    works = list(cards) if a.all else [a.work]
    total_change = total_block = 0
    for work in works:
        card = cards.get(work)
        if not card:
            print(f"\n[{work}] 작품 카드 없음 — 건너뜀(정규식·원천 URL 을 모른다)")
            continue
        if not card.get("playlist_url"):
            print(f"\n[{work}] playlist_url 없음 — 건너뜀")
            continue
        ch, bl = reparse_one(base, H, JH, work, card, py, a.apply)
        total_change += ch
        total_block += bl

    print(f"\n{'=' * 60}")
    print(f"바뀔 행 {total_change}건 · 레거시 충돌로 막힌 작품 {total_block}건")
    if not a.apply and total_change:
        print("실제로 반영하려면 --apply 를 붙여 다시 실행하라.")


def _ai_video_python():
    for p in ("/opt/ves/engines/ai-video/.venv/bin/python",
              str(pathlib.Path.home() / "rhoonart/ai-video/.venv/bin/python")):
        if pathlib.Path(p).exists():
            return p
    return sys.executable


def reparse_one(base, H, JH, work, card, py, apply):
    qwork = urllib.parse.quote(work)
    st, body = req(f"{base}/rest/v1/sources?work_title=eq.{qwork}&source_url=not.is.null"
                   f"&select=id,episode,episode_source,source_url&order=episode", headers=H)
    st == 200 or die(f"sources 조회 실패 {st}: {body[:200]}")
    rows = json.loads(body)
    if not rows:
        print(f"\n[{work}] 유튜브 소스 행 없음")
        return 0, 0

    # 레거시 장부 — episode 를 바꾸면 이 매칭이 끊긴다
    st, body = req(f"{base}/rest/v1/source_usage_legacy?work_title=eq.{qwork}"
                   f"&select=episode,channel_slug,used", headers=H)
    legacy = json.loads(body) if st == 200 else []

    titles = fetch_titles(card["playlist_url"], py)
    rx = card.get("title_episode_regex") or ""
    print(f"\n[{work}] 소스 {len(rows)}행 · 목록에서 받은 제목 {len(titles)}개"
          f" · 정규식 {'있음' if rx else '없음(기본 패턴)'}")

    plan, missing, unchanged = [], 0, 0
    for r in rows:
        title = titles.get(r["source_url"])
        if title is None:
            missing += 1
            continue
        new_ep = guess_episode_title(title, rx)
        if new_ep is None:
            unchanged += 1            # 못 읽으면 손대지 않는다(서수 유지)
            continue
        if new_ep == r["episode"] and r["episode_source"] == "parsed":
            unchanged += 1
            continue
        plan.append({"id": r["id"], "old": r["episode"], "new": new_ep,
                     "old_src": r["episode_source"], "title": title[:52]})

    for p in plan:
        tag = "회차만 표시 정정" if p["old"] == p["new"] else f"{p['old']} → {p['new']}"
        print(f"   · {tag:<22} [{p['old_src']}→parsed]  {p['title']}")
    if missing:
        print(f"   ⚠ 목록에 없는 소스 {missing}건 — 비공개·삭제됐거나 원천이 바뀌었다")
    print(f"   변경 예정 {len(plan)}건 · 유지 {unchanged}건")

    # 레거시 충돌: 바뀌는 회차 번호가 레거시 장부에 걸려 있으면 그 몫이 붕 뜬다
    legacy_eps = {l["episode"] for l in legacy}
    hit = sorted({p["old"] for p in plan if p["old"] in legacy_eps and p["old"] != p["new"]})
    if hit:
        print(f"   🛑 레거시 장부가 물린 회차가 바뀐다: {hit}")
        print(f"      (source_usage_legacy {len(legacy)}행 · 합계 "
              f"{sum(l['used'] for l in legacy)}편). 그대로 바꾸면 구 시스템이 이미 쓴 몫이")
        print( "      planner 에 반영되지 않아 중복 생산이 난다 — 장부를 먼저 재매핑하라.")
        if apply:
            print("      → 이 작품은 --apply 라도 건너뛴다.")
            return 0, 1

    if not apply:
        return len(plan), 0
    for p in plan:
        payload = json.dumps({"episode": p["new"], "episode_source": "parsed"}).encode()
        st, body = req(f"{base}/rest/v1/sources?id=eq.{p['id']}", method="PATCH",
                       headers=JH, data=payload)
        (st in (200, 204)) or die(f"갱신 실패 {st}: {body[:200]}")
    print(f"   ✓ {len(plan)}건 반영")
    return len(plan), 0


if __name__ == "__main__":
    main()
