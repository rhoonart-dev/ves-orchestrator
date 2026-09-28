#!/usr/bin/env python3
"""새 방식(tikitaka) 어댑터 — 회차 1개로 영상 N 편 (0111).

tikitaka_generate(subprocess형): python -m app.tikitaka --source <캐시> --title <작품> --episode <n>화
    --count N --out outputs_tikitaka_grid/wo-<작업지시> [엔진 선택 인자]
    엔진이 렌더 뒤 편마다 videos/<vN>/ 번들(tikitaka_video/v1 — video.json·shorts.mp4·편집실 재료)을 만든다.
tikitaka_upload(네이티브): 그 번들들을 ves-outputs/tikitaka/<작업지시>/ 로 올리고 tikitaka_videos 에 편마다 한 줄.

종전 generate(aivideo.py)와 다른 점 — 1 잡 = N 편이라 run_id 가 없다. 잡 폴더(run_dir) 하나를 후속 잡에 넘긴다.
재시도는 같은 명령을 다시 부른다: 엔진이 잡 폴더의 전사·분석·대본 캐시를 이어 쓰므로 처음부터 다시 과금되지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import pathlib
import re

from ves import config as cfgmod
from ves.adapters import base

OUT_ROOT = "outputs_tikitaka_grid"
# 엔진 인자 허용 목록 — 0111 order_tikitaka_run 의 c_keys 와 같은 어휘. 값의 모양까지 여기서 본다
# (모르는 플래그는 엔진 argparse 가 즉사하므로 조용히 버리지 않고 PermanentError 로 알린다).
ARG_FLAGS = {
    "design_preset": "--design-preset", "style_preset": "--style-preset", "script_flow": "--script-flow",
    "voice": "--voice", "speed": "--speed", "copy": "--copy", "copy_pos": "--copy-pos",
    "logo_width": "--logo-width", "range": "--range", "pov": "--pov", "stt": "--stt",
}
BOOL_FLAGS = {"cover_cut_guard": "--cover-cut-guard"}
# 편 폴더 이름: v8 · v8_r3637-3820 (엔진 bundle.py 규약). .prev_<ns> 는 이전 번들 보관분이라 뺀다.
SUFFIX_RE = re.compile(r"^v\d{1,2}(_[A-Za-z0-9_-]+)?$")

# 후속 업로드는 잡 폴더가 있는 이 노드에서만 — executor._pin_dependents 가 읽는다.
PIN_DEPENDENT_KINDS = ("tikitaka_upload",)


# ───────── 순수 헬퍼 (테스트 대상) ─────────
def job_dir_name(work_order_id) -> str:
    """잡 폴더 이름 — ASCII 고정(작품명 한글은 폴더·저장소 키에 쓰지 않는다. base.storage_key 머리말 참조)."""
    return f"wo-{work_order_id}"


def engine_args(args: dict | None) -> list:
    """엔진 선택 인자 → argv 조각. 허용 밖의 키나 이상한 값은 PermanentError(사람이 작업을 다시 걸어야 풀린다)."""
    out = []
    for k, v in (args or {}).items():
        if k in BOOL_FLAGS:
            if v is True:
                out.append(BOOL_FLAGS[k])
            elif v not in (False, None):
                raise base.PermanentError(f"엔진 설정 {k} 는 true/false 여야 해요: {v!r}")
            continue
        flag = ARG_FLAGS.get(k)
        if flag is None:
            raise base.PermanentError(f"모르는 엔진 설정: {k}")
        if v is None or v == "":
            continue
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            raise base.PermanentError(f"엔진 설정 {k} 값이 이상해요: {v!r}")
        s = str(v)
        if s.startswith("-") or "\n" in s:
            raise base.PermanentError(f"엔진 설정 {k} 값이 이상해요: {v!r}")
        out += [flag, s]
    return out


def build_argv_pure(py: str, params: dict, source_path: str, out_dir: str) -> list:
    p = params or {}
    if not p.get("work_title"):
        raise base.PermanentError("작품명이 없어요")
    if p.get("episode") in (None, ""):
        raise base.PermanentError("회차가 없어요")
    count = int(p.get("count") or 1)
    if not 1 <= count <= 14:
        raise base.PermanentError(f"편수는 1~14 사이여야 해요: {count}")
    return [py, "-u", "-m", "app.tikitaka",
            "--source", source_path,
            "--title", str(p["work_title"]),
            "--episode", f"{p['episode']}화",
            "--count", str(count),
            "--out", out_dir,
            *engine_args(p.get("args"))]


def list_bundles(job_dir) -> list:
    """잡 폴더의 편 번들 [(suffix, 폴더)] — video.json 이 있는 것만, 이름순."""
    root = pathlib.Path(job_dir) / "videos"
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and SUFFIX_RE.match(d.name) and (d / "video.json").is_file():
            out.append((d.name, d))
    return out


def object_key(work_order_id, suffix: str, rel: str) -> str:
    """저장소 키 — ves-outputs/tikitaka/<작업지시>/<편>/<상대경로>. 상대경로는 엔진 번들 규약이라 ASCII 다."""
    rel = rel.replace("\\", "/")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", rel) or ".." in rel.split("/"):
        raise base.PermanentError(f"올릴 수 없는 파일 이름: {rel!r}")
    return f"tikitaka/{work_order_id}/{suffix}/{rel}"


def classify_tail(stderr: str, stdout: str = "") -> str:
    """엔진 로그는 길다 — 앞쪽 진행 로그의 단어('quota' 설명 등)에 걸리지 않게 끝부분만 본다."""
    return base.classify_by_patterns((stderr or "")[-4000:], (stdout or "")[-2000:])


# ───────── tikitaka_generate (subprocess형) ─────────
class Generate:
    PIN_DEPENDENT_KINDS = PIN_DEPENDENT_KINDS
    WANT_STDERR = True

    @staticmethod
    def _out_dir(cfg, job) -> str:
        return str(pathlib.Path(cfgmod.engine_dir(cfg, "ai_video")) / OUT_ROOT / job_dir_name(job["work_order_id"]))

    @staticmethod
    def cwd(cfg, job):
        return cfgmod.engine_dir(cfg, "ai_video")

    @staticmethod
    def env(cfg, job):
        env = cfgmod.job_env(cfg)
        stt = ((job.get("params") or {}).get("args") or {}).get("stt") or "elevenlabs"
        # 전사(Scribe)·내레이션이 ElevenLabs 다 — 키가 없으면 엔진이 한참 분석을 준비한 뒤에야 죽는다. 먼저 끊는다.
        if stt == "elevenlabs" and not (env or os.environ).get("ELEVENLABS_API_KEY"):
            raise base.PermanentError("이 맥미니에 ELEVENLABS_API_KEY 가 없어요 — secrets/ves.env 에 넣어 주세요")
        return env

    @staticmethod
    def resource(cfg, job):
        return (job.get("params") or {}).get("resource")

    @staticmethod
    def build_argv(cfg, job):
        p = job.get("params") or {}
        sha = p.get("source_sha256")
        if not sha:
            raise base.PermanentError("원본 파일(sha256)이 없어요 — 새 방식은 소스 창고의 파일만 받아요")
        src = cfgmod.source_cache_path(cfg, sha)
        if not os.path.exists(src):
            raise base.PermanentError(f"원본 캐시가 이 노드에 없어요: {src} — acquire 가 다른 노드에서 돌았을 수 있어요")
        return build_argv_pure(cfgmod.engine_py(cfg, "ai_video"), p, src, Generate._out_dir(cfg, job))

    @staticmethod
    def parse_result(cfg, job, stdout, stderr=""):
        out_dir = Generate._out_dir(cfg, job)
        bundles = list_bundles(out_dir)
        if not bundles:
            tail = (stderr or stdout or "")[-600:]
            raise base.PermanentError(f"엔진은 끝났는데 편 번들(videos/*/video.json)이 없어요. 로그 끝: {tail}")
        return {"run_dir": out_dir, "videos": [s for s, _ in bundles]}

    @staticmethod
    def classify_error(rc, stderr, stdout):
        return classify_tail(stderr, stdout)

    @staticmethod
    def is_already_done(cfg, job):
        r = job.get("result") or {}
        return bool(r.get("run_dir") and r.get("videos") and list_bundles(r["run_dir"]))


# ───────── tikitaka_upload (네이티브) ─────────
def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _duration(bundle: dict):
    for k in ("duration", "duration_sec"):
        v = bundle.get(k)
        if isinstance(v, (int, float)):
            return v
    return None


class Upload:
    @staticmethod
    def run(cfg, conn, job, deps):
        from ves.storage.supabase_storage import Store
        gen = deps.get("tikitaka_generate") or {}
        run_dir = gen.get("run_dir") or (job.get("params") or {}).get("run_dir")
        if not run_dir:
            raise base.PermanentError("tikitaka_generate 결과(run_dir)가 없어요")
        bundles = list_bundles(run_dir)
        if not bundles:
            raise base.PermanentError(f"올릴 편이 없어요: {run_dir}/videos")
        p = job.get("params") or {}
        wo = job["work_order_id"]
        store = Store(cfg.supabase_url, cfg.supabase_service_key)
        done = []
        for suffix, d in bundles:
            files, sent = {}, set()
            for f in sorted(x for x in d.rglob("*") if x.is_file()):
                rel = f.relative_to(d).as_posix()
                key = object_key(wo, suffix, rel)
                sha = _sha256(f)
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                if key not in sent:
                    store.upload("ves-outputs", key, str(f), content_type=ctype)
                    sent.add(key)
                files[rel] = {"key": key, "bytes": f.stat().st_size, "sha256": sha}
            bundle = json.loads((d / "video.json").read_text(encoding="utf-8"))
            publish = None
            if (d / "publish.json").is_file():
                try:
                    publish = json.loads((d / "publish.json").read_text(encoding="utf-8"))
                except ValueError:
                    publish = None
            with conn.cursor() as c:
                c.execute(
                    """INSERT INTO public.tikitaka_videos
                           (work_order_id, job_id, node_id, suffix, version, tag, channel_slug, work_title,
                            episode, title, render_fingerprint, duration_sec, review_items, bundle, publish, files)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb)
                       ON CONFLICT (work_order_id, suffix) DO UPDATE SET
                           job_id=EXCLUDED.job_id, node_id=EXCLUDED.node_id, title=EXCLUDED.title,
                           render_fingerprint=EXCLUDED.render_fingerprint, duration_sec=EXCLUDED.duration_sec,
                           review_items=EXCLUDED.review_items, bundle=EXCLUDED.bundle,
                           publish=EXCLUDED.publish, files=EXCLUDED.files, updated_at=now()""",
                    (wo, job["id"], cfg.node_id, suffix, bundle.get("version"), bundle.get("tag") or None,
                     p.get("channel_slug"), p.get("work_title") or bundle.get("work"),
                     str(bundle.get("episode") or p.get("episode") or ""), bundle.get("title"),
                     bundle.get("render_fingerprint"), _duration(bundle), bundle.get("review_items"),
                     json.dumps(bundle, ensure_ascii=False), json.dumps(publish, ensure_ascii=False),
                     json.dumps(files, ensure_ascii=False)))
            done.append(suffix)
        return {"run_dir": run_dir, "videos": done}
