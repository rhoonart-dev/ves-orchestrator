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
            "--episode", str(p.get("episode_label") or f"{p['episode']}화"),
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


# ───────── 작품 로고 (0112) — 채널이 고른 로고, 없으면 기본. 잡마다 고정(work_asset_pins)해 재시도가 새 로고를 줍지 않게 ─────────
ASSET_BUCKET = "ves-work-assets"
ASSET_KEY_RE = re.compile(r"^works/[a-f0-9-]{36}/[a-f0-9]{64}\.(png|jpg|webp)$")


def logo_flags(asset: dict | None, path: str | None) -> list:
    """고정한 로고 → 엔진 인자. 로고 상자 폭만 엔진이 받는다(높이 240 고정). 순수 — 테스트 대상."""
    if not asset or not path:
        return []
    width = int(asset.get("render_width") or 600)
    if not 16 <= width <= 1080:
        raise base.PermanentError(f"로고 표시 폭이 이상해요: {width}")
    return ["--logo", path, "--logo-width", str(width)]


def pinned_logo(conn, job) -> dict | None:
    """이 잡의 작품 로고 — 처음 부를 때 work_asset_for 로 골라 work_asset_pins 에 고정, 그 뒤엔 고정본."""
    from psycopg.types.json import Jsonb
    p = job.get("params") or {}
    work, slug = p.get("work_title"), p.get("channel_slug")
    if not work:
        return None
    with conn.cursor() as c:
        c.execute("SELECT manifest FROM public.work_asset_pins WHERE job_id=%s", (job["id"],))
        row = c.fetchone()
        if not row:
            c.execute("SELECT id, role, label, object_key, sha256, mime, render_width, render_height "
                      "FROM public.work_asset_for(%s, %s, 'work_logo')", (slug, work))
            assets = [{**r, "id": str(r["id"])} for r in c.fetchall()]
            c.execute("INSERT INTO public.work_asset_pins(job_id, work_title, manifest) VALUES (%s,%s,%s) "
                      "ON CONFLICT (job_id) DO NOTHING", (job["id"], work, Jsonb(assets)))
            c.execute("SELECT manifest FROM public.work_asset_pins WHERE job_id=%s", (job["id"],))
            row = c.fetchone()
    return (row["manifest"] or [None])[0]


def fetch_asset(cfg, asset: dict) -> str:
    """고정한 로고 파일을 노드 캐시로(sha 확인). 경로를 돌려준다."""
    import hashlib as _h
    key, sha = str(asset.get("object_key") or ""), str(asset.get("sha256") or "")
    if not ASSET_KEY_RE.match(key) or not key.split("/")[-1].startswith(sha):
        raise base.PermanentError(f"로고 파일 경로가 이상해요: {key}")
    d = pathlib.Path(cfg.home) / "cache" / "work-assets"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / key.split("/")[-1]
    if not (dest.is_file() and _h.sha256(dest.read_bytes()).hexdigest() == sha):
        from ves.storage.supabase_storage import Store
        tmp = dest.with_suffix(dest.suffix + ".part")
        Store(cfg.supabase_url, cfg.supabase_service_key).download(ASSET_BUCKET, key, str(tmp))
        if _h.sha256(tmp.read_bytes()).hexdigest() != sha:
            tmp.unlink(missing_ok=True)
            raise base.PermanentError("로고 파일이 기록과 달라요")
        tmp.replace(dest)
    return str(dest)


# ───────── 작업 가이드(0121) — 합본 구성 메모 · 작업 메모 · 앞 회차 요약 · 다른 채널이 쓴 장면 ─────────
# 엔진은 --guide 를 주면 작품·회차 가이드 자동 탐색을 끈다. 그래서 자동 탐색과 같은 규칙으로 찾은 파일을 먼저 넘기고
# 이 작업의 가이드를 뒤에 붙인다(같은 키는 뒤 파일이 이긴다).
GUIDE_DIR = "guides/tikitaka"
PREV_SUMMARY_MAX = 5000


def discover_guides(engine_dir: str, title: str, episode_label: str) -> list:
    """엔진 guide.discover_guides 와 같은 규칙(작품 → 회차, 있는 것만). 순수에 가깝다 — 파일 존재만 본다."""
    base = pathlib.Path(engine_dir) / GUIDE_DIR
    found = []
    for cand in (base / f"{title}.md", base / f"{title}.txt"):
        if cand.exists():
            found.append(str(cand))
            break
    labels = [str(episode_label)]
    m = re.fullmatch(r"(\d+)(?:회|화)?", str(episode_label))
    if m:
        labels += [m[1], m[1] + "화", m[1] + "회"]
    for cand in (base / title / f"{lab}{ext}" for lab in dict.fromkeys(labels) for ext in (".md", ".txt")):
        if cand.exists():
            found.append(str(cand))
            break
    return found


def _mmss(sec: float) -> str:
    return f"{int(sec // 60):02d}:{sec % 60:04.1f}"


def used_ranges(edit_plans: list, pad: float = 0.5) -> list:
    """다른 채널 편들의 edit_plan → 대사·현장음으로 쓴 원본 구간(덮개 컷은 뺀다) 합친 것. 순수 — 테스트 대상."""
    spans = []
    for ep in edit_plans:
        for t in (ep or {}).get("timeline") or []:
            if t.get("cover") or not t.get("use_original_audio", True):
                continue
            a, b = t.get("clip_start_sec"), t.get("clip_end_sec")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a:
                spans.append((max(0.0, a - pad), b + pad))
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 1.0:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def avoid_guide(ranges: list, channels: list) -> str:
    if not ranges:
        return ""
    who = ", ".join(dict.fromkeys(channels)) or "다른 채널"
    return ("# 다른 채널이 이미 쓴 장면\n\n"
            f"같은 원본으로 {who} 채널이 먼저 만든 편들이 대사·현장음으로 쓴 구간이다. 채널끼리 같은 장면이 겹치지 않게 이 구간은 쓰지 않는다.\n\n"
            "활용 불가: " + " / ".join(f"{_mmss(a)}~{_mmss(b)} (다른 채널 사용)" for a, b in ranges) + "\n")


def prev_summary(label: str, videos: list) -> str:
    """앞 회차 작업 편들(title · grid rows) → 대본 요약 본문. 구조 키로 읽히지 않게 줄마다 '- ' 를 붙인다. 순수 — 테스트 대상."""
    if not videos:
        return ""
    lines = [f"# 앞 회차 내용 — {label} 작업에서 만든 편들의 대본 요약", "",
             "이번 회차 이야기를 이해시키려고 지난 회 맥락을 내레이션으로 짧게 말할 때만 참고한다. 앞 회차 편과 같은 말을 되풀이하지 않는다.", ""]
    for v in videos:
        lines.append(f"- 편 제목: {v.get('title') or ''}")
        for r in (v.get("rows") or [])[:40]:
            txt = str(r.get("text") or "").strip().replace("\n", " ")
            if txt:
                lines.append(f"  - ({'내레이션' if r.get('mode') == 'N' else '대사'}) {txt}")
    body = "\n".join(lines)
    return body[:PREV_SUMMARY_MAX] + ("\n- (이하 생략)" if len(body) > PREV_SUMMARY_MAX else "") + "\n"


def _storage_json(store, key: str):
    import tempfile as _tf
    with _tf.NamedTemporaryFile(suffix=".json") as f:
        try:
            store.download("ves-outputs", key, f.name)
            return json.loads(pathlib.Path(f.name).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 없는 파일은 건너뛴다
            return None


def task_guides(cfg, conn, p: dict) -> list:
    """이 작업(0121 tikitaka_tasks)의 가이드 [(파일 이름, 본문)]. 작업 번호가 없는 옛 작업은 빈 목록."""
    if not p.get("task_id"):
        return []
    from ves.storage.supabase_storage import Store
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    out = []
    with conn.cursor() as c:
        if p.get("compilation_id"):
            c.execute("SELECT notes FROM public.source_compilations WHERE id=%s", (p["compilation_id"],))
            r = c.fetchone()
            if r and r.get("notes"):
                out.append(("compilation.md", r["notes"]))
        if p.get("prev_ref"):
            c.execute("""SELECT t.episode_key, t.work_no, t.work_order_id FROM public.tikitaka_tasks t
                          WHERE t.work_title=%s AND t.status='queued' AND t.work_order_id IS NOT NULL
                            AND split_part(t.episode_key,'-',1)::int < split_part(%s,'-',1)::int
                            AND EXISTS (SELECT 1 FROM public.tikitaka_videos v WHERE v.work_order_id=t.work_order_id)
                          ORDER BY split_part(t.episode_key,'-',1)::int DESC, t.work_no DESC LIMIT 1""",
                      (p["work_title"], p.get("episode_key") or str(p.get("episode"))))
            prev = c.fetchone()
            if prev:
                c.execute("""SELECT title, files FROM public.tikitaka_videos WHERE work_order_id=%s
                              AND status NOT IN ('rejected','discarded') ORDER BY suffix""", (prev["work_order_id"],))
                vids = []
                for v in c.fetchall():
                    key = ((v.get("files") or {}).get("grid_table.json") or {}).get("key")
                    grid = _storage_json(store, key) if key else None
                    vids.append({"title": v.get("title"), "rows": (grid or {}).get("rows") or []})
                text = prev_summary(f"{prev['episode_key']} #{prev['work_no']}", vids)
                if text:
                    out.append(("prev_episode.md", text))
        if p.get("avoid_other") and p.get("source_sha256"):
            c.execute("""SELECT v.files, v.channel_slug, m.name FROM public.tikitaka_videos v
                           JOIN public.work_orders w ON w.id = v.work_order_id
                           LEFT JOIN public.channels_mirror m ON m.token_slug = v.channel_slug
                          WHERE w.source_sha256=%s AND v.channel_slug <> %s AND v.status NOT IN ('rejected','discarded')""",
                      (p["source_sha256"], p.get("channel_slug") or ""))
            plans, names = [], []
            for v in c.fetchall():
                key = ((v.get("files") or {}).get("edit_plan.json") or {}).get("key")
                ep = _storage_json(store, key) if key else None
                if ep:
                    plans.append(ep)
                    names.append(v.get("name") or v.get("channel_slug"))
            text = avoid_guide(used_ranges(plans), names)
            if text:
                out.append(("avoid_other.md", text))
    if p.get("memo"):
        out.append(("memo.md", "# 작업 메모\n\n" + str(p["memo"]).strip() + "\n"))
    return out


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
    def enrich_params(cfg, conn, job):
        p = dict(job.get("params") or {})
        p["logo_asset"] = pinned_logo(conn, job)   # 없으면 None — 엔진은 작품 가이드의 '로고:' 를 쓴다
        p["task_guides"] = task_guides(cfg, conn, p)
        return p

    @staticmethod
    def build_argv(cfg, job):
        p = job.get("params") or {}
        sha = p.get("source_sha256")
        if not sha:
            raise base.PermanentError("원본 파일(sha256)이 없어요 — 새 방식은 소스 창고의 파일만 받아요")
        src = cfgmod.source_cache_path(cfg, sha)
        if not os.path.exists(src):
            raise base.PermanentError(f"원본 캐시가 이 노드에 없어요: {src} — acquire 가 다른 노드에서 돌았을 수 있어요")
        argv = build_argv_pure(cfgmod.engine_py(cfg, "ai_video"), p, src, Generate._out_dir(cfg, job))
        guides = p.get("task_guides") or []
        if guides:
            gdir = pathlib.Path(Generate._out_dir(cfg, job)) / "task_guides"
            gdir.mkdir(parents=True, exist_ok=True)
            files = discover_guides(cfgmod.engine_dir(cfg, "ai_video"), str(p["work_title"]),
                                    str(p.get("episode_label") or f"{p['episode']}화"))
            for name, text in guides:
                (gdir / name).write_text(text, encoding="utf-8")
                files.append(str(gdir / name))
            at = argv.index("--out") + 2
            argv[at:at] = [x for f in files for x in ("--guide", f)]
        asset = p.get("logo_asset")
        if asset:
            # 작업에 직접 준 엔진 인자(logo_width 등)가 이기도록 --out 바로 뒤, 엔진 선택 인자 앞에 넣는다
            at = argv.index("--out") + 2
            argv[at:at] = logo_flags(asset, fetch_asset(cfg, asset))
        return argv

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


def duration_of(bundle: dict, review: dict | None):
    """편 길이(초) — 엔진은 video.json 이 아니라 review.json 의 validation.duration_sec 에 적는다
    (워크스페이스 로컬 목록 local_videos_api.summary 와 같은 곳). 순수 — 테스트 대상."""
    v = ((review or {}).get("validation") or {}).get("duration_sec")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    for k in ("duration", "duration_sec"):
        v = (bundle or {}).get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    return None


def _read_json(path: pathlib.Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


SHA_NAME_RE = re.compile(r"^[0-9a-f]{64}$")


def cached_source_sha(path: str, cache_dir: str):
    """번들이 기억하는 원본 경로가 이 노드의 원본 캐시(cache/sources/<sha>) 자리면 그 sha. 아니면 None. 순수 — 테스트 대상."""
    p = pathlib.PurePosixPath(path or "")
    return p.name if str(p.parent) == str(pathlib.PurePosixPath(cache_dir)) and SHA_NAME_RE.match(p.name) else None


def ensure_source(cfg, conn, video_json: pathlib.Path) -> None:
    """다시 렌더에 쓸 원본이 캐시에서 치워졌으면(diskgc · 디스크 부족) 소스 창고에서 다시 받는다.
    내용은 sha 로 확인하고, 수정 시각은 번들이 기억하는 값으로 돌려 둔다 — 엔진이 '원본이 바뀌었다'고 보지 않게."""
    src = (_read_json(video_json) or {}).get("source") or {}
    path = src.get("path") or ""
    if not path or os.path.isfile(path):
        return
    sha = cached_source_sha(path, os.path.dirname(cfgmod.source_cache_path(cfg, "x")))
    if not sha:
        raise base.PermanentError(f"원본 영상이 이 노드에 없어요: {path}")
    from ves.adapters import acquire
    acquire.run(cfg, conn, {"params": {"source_sha256": sha, "work_title": "", "episode": None}}, {})
    try:
        if str(os.path.getsize(path)) == str(src.get("size")) and src.get("mtime_ns"):
            ns = int(src["mtime_ns"])
            os.utime(path, ns=(ns, ns))
    except (OSError, ValueError):
        pass


# 편집실 필름 스트립(장면 썸네일) — 워크스페이스 local_videos_api.sprite_sheets 와 같은 모양(2초 간격 · 160x90 · 10x10).
# 편집실을 서버 없이 열려면 브라우저가 저장소에서 바로 받아야 해서, 번들을 올릴 때 여기서 같이 만든다.
SPRITE_DIR, SPRITE_INTERVAL, SPRITE_GRID = "sprites", 2, 10


def sprite_argv(scan: str, out_pattern: str, interval: int = SPRITE_INTERVAL, grid: int = SPRITE_GRID) -> list:
    """필름 스트립 ffmpeg argv — 키프레임만 디코드해 긴 원본도 몇 초. 순수 — 테스트 대상."""
    w, h = 160, 90
    return ["ffmpeg", "-v", "error", "-y", "-skip_frame", "nokey", "-i", scan, "-an", "-vf",
            f"fps=1/{interval},scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,tile={grid}x{grid}",
            "-q:v", "5", "-start_number", "0", out_pattern]


def make_sprites(d: pathlib.Path) -> list:
    """편 번들 d 에 sprites/sprite_NNN.jpg 를 만든다(editor_scan.mp4 가 같으면 다시 안 만든다). 실패해도 업로드는 계속 —
    필름 스트립이 없으면 편집실은 빈 칸으로 그린다."""
    import shutil
    import subprocess
    scan = d / "editor_scan.mp4"
    if not scan.is_file():
        return []
    out = d / SPRITE_DIR
    st = scan.stat()
    tag = f"{st.st_size}:{st.st_mtime_ns}"
    done = _read_json(out / "done.json") or {}
    if done.get("scan") == tag and all((out / n).is_file() for n in done.get("sheets") or [None]):
        return done["sheets"]
    tmp = d / f".{SPRITE_DIR}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        exe = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
        subprocess.run([exe, *sprite_argv(str(scan), str(tmp / "sprite_%03d.jpg"))[1:]],
                       check=True, capture_output=True, timeout=600)
        sheets = sorted(f.name for f in tmp.glob("sprite_*.jpg"))
        if not sheets:
            return []
        (tmp / "done.json").write_text(json.dumps({"scan": tag, "interval": SPRITE_INTERVAL, "grid": SPRITE_GRID,
                                                   "sheets": sheets}), encoding="utf-8")
        shutil.rmtree(out, ignore_errors=True)
        tmp.replace(out)
        return sheets
    except (subprocess.SubprocessError, OSError):
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


LOGO_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def logo_copies(design: dict) -> list:
    """이 편을 렌더한 디자인의 로고 파일 → 번들에 담을 (원본 경로, 번들 안 이름). 순수 — 테스트 대상.
    워크스페이스 '프리미어로 내보내기'가 로고를 같은 그림으로 얹으려면 번들에 있어야 한다(엔진 폴더는 맥미니에만 있다)."""
    out = []
    d = design or {}
    for key, name, need in (("work_value", "logo_work", "image"), ("platform_image", "logo_platform", None)):
        v = d.get(key)
        if not isinstance(v, str) or not v.startswith("/") or (need and d.get("work_type") != need):
            continue
        ext = pathlib.PurePath(v).suffix.lower()
        if ext in LOGO_EXTS:
            out.append((v, f"assets/{name}{'.jpg' if ext == '.jpeg' else ext}"))
    return out


def copy_logos(d: pathlib.Path) -> None:
    """번들 video.json 의 렌더 디자인에서 로고 파일을 assets/ 로 복사한다(있는 것만, 실패해도 업로드는 계속)."""
    import shutil
    video = _read_json(d / "video.json") or {}
    design = ((video.get("provenance") or {}).get("render") or {}).get("design") or {}
    for src, rel in logo_copies(design):
        try:
            if pathlib.Path(src).is_file():
                (d / rel).parent.mkdir(exist_ok=True)
                shutil.copyfile(src, d / rel)
        except OSError:
            pass


def upload_bundle(cfg, conn, store, job, wo, suffix: str, d: pathlib.Path, p: dict) -> None:
    """편 번들 하나를 ves-outputs 로 올리고 tikitaka_videos 한 줄을 넣거나 갱신한다(생성 뒤·편집실 재렌더 뒤 공통)."""
    make_sprites(d)
    copy_logos(d)
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
    publish = _read_json(d / "publish.json")
    review = _read_json(d / "review.json")
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
             bundle.get("render_fingerprint"), duration_of(bundle, review), bundle.get("review_items"),
             json.dumps(bundle, ensure_ascii=False), json.dumps(publish, ensure_ascii=False),
             json.dumps(files, ensure_ascii=False)))


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
        for suffix, d in bundles:
            upload_bundle(cfg, conn, store, job, wo, suffix, d, p)
        return {"run_dir": run_dir, "videos": [s for s, _ in bundles]}


# ───────── tikitaka_apply_edit (네이티브) — 워크스페이스 편집실 제출 → 그 편을 만든 노드에서 다시 렌더 ─────────
# 잡 폴더(전사·대본·TTS 캐시·원본 캐시)는 편을 만든 노드에만 있다 — 워크스페이스가 required_caps 에 node:<그 노드> 를 박아 넣는다.
# 로컬 편집실과 같은 두 단계: bundle record-edit(수정 기록, stdin=overrides) → apply_edit(렌더 + 묶음 교체) → 다시 올리기.
def last_json_line(text: str) -> dict:
    """엔진 CLI 는 마지막 줄에 JSON 한 줄을 낸다. 없거나 깨졌으면 빈 dict. 순수 — 테스트 대상."""
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                out = json.loads(line)
                return out if isinstance(out, dict) else {}
            except ValueError:
                return {}
    return {}


FACE_EDGE_RE = re.compile(r"⚠ \d+(?:\.\d+)?~\d+(?:\.\d+)?s 인물 얼굴이 (?:왼쪽|오른쪽) 잘림 띠에 걸림")


def apply_report(result: dict, stderr: str) -> dict:
    """다시 렌더 결과에서 편집실 '지난 수정에서 달라진 점'에 쓸 재료만 — 엔진 적용 기록(log[])과 얼굴 경고 줄.
    문장으로 바꾸는 건 워크스페이스(local_videos_api.apply_notes)가 로컬 편과 같은 규칙으로 한다. 순수 — 테스트 대상."""
    log = [x for x in (result or {}).get("log") or [] if isinstance(x, dict)][:200]
    faces = []
    for line in (stderr or "").splitlines():
        m = FACE_EDGE_RE.search(line)
        if m and m.group(0) not in faces:
            faces.append(m.group(0))
    out = {"log": log, "log_text": "\n".join(faces[:50])}
    dur = (result or {}).get("duration_sec")
    if isinstance(dur, (int, float)) and not isinstance(dur, bool):
        out["duration_sec"] = dur
    return out


class ApplyEdit:
    @staticmethod
    def run(cfg, conn, job, deps):
        import subprocess
        from ves.storage.supabase_storage import Store
        p = job.get("params") or {}
        wo, suffix = job["work_order_id"], str(p.get("suffix") or "")
        if not SUFFIX_RE.match(suffix):
            raise base.PermanentError(f"편 이름이 이상해요: {suffix!r}")
        overrides = p.get("overrides")
        if not isinstance(overrides, dict) or not overrides:
            raise base.PermanentError("고친 내용이 없어요")
        engine = cfgmod.engine_dir(cfg, "ai_video")
        job_dir = pathlib.Path(engine) / OUT_ROOT / job_dir_name(wo)
        if not (job_dir / "videos" / suffix / "video.json").is_file():
            raise base.PermanentError(f"이 노드에 잡 폴더가 없어요: {job_dir} — 편을 만든 노드가 아니거나 정리됐어요")
        ensure_source(cfg, conn, job_dir / "videos" / suffix / "video.json")
        py, env = cfgmod.engine_py(cfg, "ai_video"), cfgmod.job_env(cfg)
        rec = subprocess.run([py, "-m", "app.tikitaka.bundle", "record-edit", str(job_dir), suffix,
                              "--by", str(p.get("by") or "workspace"), "--based-on", str(p.get("based_on") or ""),
                              "--note", str(p.get("note") or "")[:500]],
                             input=json.dumps(overrides, ensure_ascii=False), capture_output=True, text=True,
                             cwd=engine, env=env, timeout=120)
        out = last_json_line(rec.stdout)
        if rec.returncode == 3:
            raise base.PermanentError(out.get("error") or "최신 판이 아니에요 — 편집실을 새로 열어 주세요")
        if rec.returncode != 0 or not out.get("edit_id"):
            raise base.PermanentError(out.get("error") or f"수정 기록을 남기지 못했어요: {(rec.stderr or '')[-400:]}")
        # 실패는 다시 시도하지 않는다 — 같은 제출이 기록을 두 번 남긴다. 사람이 편집실에서 다시 낸다.
        ap = subprocess.run([py, "-m", "app.tikitaka.apply_edit", str(job_dir), suffix, "--edit", out["edit_id"]],
                            capture_output=True, text=True, cwd=engine, env=env, timeout=3600)
        if ap.returncode != 0:
            tail = (ap.stderr or ap.stdout or "")[-600:]
            raise base.PermanentError(f"다시 렌더하지 못했어요: {tail}")
        store = Store(cfg.supabase_url, cfg.supabase_service_key)
        upload_bundle(cfg, conn, store, job, wo, suffix, job_dir / "videos" / suffix, p)
        return {"suffix": suffix, "edit_id": out["edit_id"], "video_id": p.get("video_id"),
                **apply_report(last_json_line(ap.stdout), ap.stderr)}
