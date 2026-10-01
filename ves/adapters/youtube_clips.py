#!/usr/bin/env python3
"""유튜브 클립 겹침 · 합본 어댑터(네이티브) — 0121.

youtube_overlap: 작품 하나의 유튜브 클립(sources, 원천이 여럿인 작품)을 ai-video scripts/clip_overlap.py 로 소리 대조해
    아래 순위 채널 클립마다 위 채널과 겹치는 구간 · 남는 구간을 sources.overlap 에 적는다. 하루 한 번(youtube_watch).
build_compilation: 소스 창고에서 사람이 고른 구성(source_compilations.recipe)대로 ai-video scripts/concat_source_clips.py --plan
    으로 이어 붙여, 결과를 ves-sources/masters/<sha> 에 올리고 sources(clip_kind=compilation) 한 줄로 등록한다.
    구성 메모(source_notes.md — 덮개 전용 · 선공개 주의)는 source_compilations.notes 에 남겨, 작업할 때 제작 가이드로 넘긴다.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

from ves import config as cfgmod
from ves.adapters import base

PROGRESS_RE = re.compile(r"^\[(\d+)/(\d+)\]")


# ───────── 순수 헬퍼 (테스트 대상) ─────────
def overlap_plan(rows: list) -> dict:
    """sources 행(+원천 순위) → clip_overlap 입력. 회차 모르는 클립도 넣는다(스크립트가 모두와 비교)."""
    clips = []
    for r in rows:
        if not r.get("source_url") or r.get("rank") is None:
            continue
        clips.append({"id": str(r["id"]), "url": r["source_url"], "rank": int(r["rank"]),
                      "episode": r.get("episode"), "label": r.get("episode_label"),
                      "duration": float(r["duration_sec"]) if r.get("duration_sec") is not None else None})
    return {"clips": clips}


def compile_plan(comp: dict) -> dict:
    """source_compilations 행 → concat_source_clips --plan 입력. 영상 id 는 주소에서 뽑아 모양을 확인한다."""
    items = []
    for it in (comp.get("recipe") or {}).get("items") or []:
        url = it.get("source_url") or ""
        m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", url)
        if not m:
            raise base.PermanentError(f"유튜브 주소가 없는 클립이에요: {it.get('title') or it.get('source_id')}")
        items.append({"video_id": m.group(1), "source_id": it.get("source_id"), "title": it.get("title"),
                      "kind": it.get("kind"), "episode": it.get("episode"), "label": it.get("label"),
                      "duration": it.get("duration"), "published": it.get("published"), "rank": it.get("rank"),
                      "start": it.get("start"), "end": it.get("end")})
    if not items:
        raise base.PermanentError("합본 구성에 클립이 없어요")
    return {"work": comp["work_title"], "tag": f"{comp['episode_key']} {comp['name']}", "items": items}


def first_episode(key: str):
    try:
        return int(str(key).split("-")[0])
    except ValueError:
        return None


def _set(conn, comp_id, **kw) -> None:
    cols = ", ".join(f"{k}=%s" for k in kw)
    with conn.cursor() as c:
        c.execute(f"UPDATE public.source_compilations SET {cols} WHERE id=%s", (*kw.values(), comp_id))


# ───────── youtube_overlap ─────────
class Overlap:
    @staticmethod
    def run(cfg, conn, job, deps):
        work = (job.get("params") or {}).get("work_title")
        if not work:
            raise base.PermanentError("작품이 없어요")
        with conn.cursor() as c:
            c.execute("""SELECT s.id, s.source_url, s.episode, s.episode_label, s.duration_sec, w.rank
                           FROM public.sources s JOIN public.work_youtube_sources w ON w.id = s.yt_source_id
                          WHERE s.work_title=%s AND s.is_active AND s.clip_kind IN ('clip','prerelease','recap')
                            AND w.is_active""", (work,))
            rows = c.fetchall()
        plan = overlap_plan(rows)
        if len({cl["rank"] for cl in plan["clips"]}) < 2:
            return {"work": work, "skipped": "원천 채널이 하나라 비교할 게 없어요"}
        engine = cfgmod.engine_dir(cfg, "ai_video")
        cache = pathlib.Path(cfg.home) / "cache" / "clip_fp"
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as td:
            pin, pout = pathlib.Path(td) / "plan.json", pathlib.Path(td) / "out.json"
            pin.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            r = subprocess.run([cfgmod.engine_py(cfg, "ai_video"), "-u", "scripts/clip_overlap.py",
                                "--plan", str(pin), "--out", str(pout), "--cache", str(cache)],
                               cwd=engine, env=cfgmod.job_env(cfg), capture_output=True, text=True, timeout=3600)
            if r.returncode != 0 or not pout.exists():
                raise RuntimeError(f"겹침 찾기 실패: {(r.stderr or r.stdout or '')[-500:]}")
            out = json.loads(pout.read_text(encoding="utf-8"))
        res = out.get("results") or {}
        top = min(cl["rank"] for cl in plan["clips"])
        with conn.cursor() as c:
            for cl in plan["clips"]:
                if cl["rank"] <= top:
                    c.execute("UPDATE public.sources SET overlap=NULL WHERE id=%s AND overlap IS NOT NULL", (cl["id"],))
                elif cl["id"] in res:
                    c.execute("UPDATE public.sources SET overlap = %s::jsonb || jsonb_build_object('checked_at', now()) WHERE id=%s",
                              (json.dumps(res[cl["id"]], ensure_ascii=False), cl["id"]))
        skip = sum(1 for v in res.values() if v.get("skip"))
        cut = sum(1 for v in res.values() if v.get("covered") and not v.get("skip"))
        return {"work": work, "compared": len(res), "cut": cut, "skip": skip, "errors": len(out.get("errors") or {})}


# ───────── build_compilation ─────────
class Build:
    @staticmethod
    def run(cfg, conn, job, deps):
        from ves.storage.supabase_storage import Store
        cid = (job.get("params") or {}).get("compilation_id")
        with conn.cursor() as c:
            c.execute("SELECT * FROM public.source_compilations WHERE id=%s", (cid,))
            comp = c.fetchone()
        if not comp:
            raise base.PermanentError("없는 합본이에요")
        if comp["status"] == "ready" and comp.get("source_id"):
            return {"compilation_id": str(cid), "source_id": str(comp["source_id"]), "already": True}
        if comp["status"] == "deleted":
            return {"compilation_id": str(cid), "skipped": "지운 합본"}
        plan = compile_plan(comp)
        _set(conn, cid, status="building", error=None, progress="클립을 받고 있어요")
        engine = cfgmod.engine_dir(cfg, "ai_video")
        work_dir = pathlib.Path(cfg.home) / "cache" / "compilations" / str(cid)
        work_dir.mkdir(parents=True, exist_ok=True)
        pin = work_dir / "plan.json"
        pin.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        ytdlp = str(pathlib.Path(cfgmod.engine_py(cfg, "ai_video")).with_name("yt-dlp"))
        argv = [cfgmod.engine_py(cfg, "ai_video"), "-u", "scripts/concat_source_clips.py",
                "--plan", str(pin), "--out", str(work_dir), "--ytdlp", ytdlp]
        n = len(plan["items"])
        tail: list = []
        try:
            p = subprocess.Popen(argv, cwd=engine, env=cfgmod.job_env(cfg), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True)
            for line in p.stdout:
                tail = (tail + [line.rstrip()])[-40:]
                m = PROGRESS_RE.match(line)
                if m:
                    _set(conn, cid, progress=f"클립 받는 중 {m.group(1)}/{n}")
                    if m.group(1) == str(n):
                        _set(conn, cid, progress="이어 붙이고 있어요")
            rc = p.wait(timeout=7200)
            src = work_dir / "source.mp4"
            if rc not in (0, 1) or not src.exists():     # 1 = 길이가 계획과 조금 다름(경고) — 결과는 쓴다
                raise RuntimeError("합본 만들기 실패: " + " / ".join(tail[-6:]))
            _set(conn, cid, progress="저장소에 올리고 있어요")
            h = hashlib.sha256()
            with open(src, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            sha, size = h.hexdigest(), src.stat().st_size
            okey = f"masters/{sha}"
            Store(cfg.supabase_url, cfg.supabase_service_key).upload("ves-sources", okey, str(src), content_type="video/mp4")
            manifest = json.loads((work_dir / "manifest.json").read_text(encoding="utf-8"))
            notes = (work_dir / "source_notes.md").read_text(encoding="utf-8") if (work_dir / "source_notes.md").exists() else None
            dur = manifest.get("total_sec")
            # 다음 작업이 같은 노드면 다시 받지 않게 원본 캐시 자리에 둔다(acquire 가 sha 로 확인)
            cache = pathlib.Path(cfgmod.source_cache_path(cfg, sha))
            cache.parent.mkdir(parents=True, exist_ok=True)
            if not cache.exists():
                shutil.move(str(src), str(cache))
            key = comp["episode_key"]
            with conn.cursor() as c:
                c.execute(
                    """INSERT INTO public.sources
                           (work_title, episode, episode_source, episode_label, clip_kind, sha256, object_key, bytes,
                            duration_sec, has_subtitle, origin, registered_by, use_limit, is_active, title, compilation_id)
                       VALUES (%s,%s,'parsed',%s,'compilation',%s,%s,%s,%s,false,'compilation',%s,%s,true,%s,%s)
                       ON CONFLICT (sha256) DO UPDATE SET compilation_id = EXCLUDED.compilation_id, is_active = true
                       RETURNING id""",
                    (comp["work_title"], first_episode(key), key, sha, okey, size, dur,
                     f"build_compilation:{job['id']}", base.use_limit_for(dur), comp["name"], cid))
                sid = c.fetchone()["id"]
                c.execute("""UPDATE public.source_compilations SET status='ready', progress=NULL, error=NULL, source_id=%s,
                                    duration_sec=%s, notes=%s, done_at=now(),
                                    recipe = recipe || jsonb_build_object('manifest', %s::jsonb)
                              WHERE id=%s""",
                          (sid, dur, notes, json.dumps(manifest, ensure_ascii=False), cid))
            shutil.rmtree(work_dir / "clips", ignore_errors=True)
            return {"compilation_id": str(cid), "source_id": str(sid), "sha256": sha, "duration_sec": dur}
        except base.PermanentError as e:
            _set(conn, cid, status="failed", progress=None, error=str(e)[-500:])
            raise
        except Exception as e:
            # 다시 시도할 수 있는 실패 — 재시도가 다 떨어지면 reaper 가 잡을 dead 로 내린다. 화면엔 마지막 오류를 보인다.
            _set(conn, cid, status="queued" if int(job.get("attempt") or 1) < int(job.get("max_attempts") or 3) else "failed",
                 progress=None, error=str(e)[-500:])
            raise
