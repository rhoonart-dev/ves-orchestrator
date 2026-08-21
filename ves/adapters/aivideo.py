#!/usr/bin/env python3
"""generate 어댑터 — ai-video app.cli create_shorts (subprocess 형).

params 계약(planner 가 채움):
  work_title(laeebly 정본) · source_sha256 | source_url · episode · max_shorts
  topic · no_research(기본 true) · no_subtitles(sources.has_subtitle=false 면 true)
  flags{silence,length,loudness} — 라운드 노브(§12) · resource('gemini:<GCP>')
경로: 소스는 content-addressed 캐시(sha 만으로 결정) — acquire 가 워밍, 여기선 경로 계산만.

편집실(0043): params.edit_overrides 가 있으면 그 JSON 을 run_dir 에 써서
`--edit-overrides` 로 넘긴다 — 사람이 고친 제목·자막·구간이 체크포인트를 이긴다.
반드시 이어달리기(resume_run_id) 와 함께여야 한다(아래 _build_argv_fresh 참고).
"""
from __future__ import annotations

import glob
import json
import pathlib
import re

from ves import config as cfgmod
from ves.adapters import base

# ai-video 14단계 순서 — 재개 스텝 선택(★⑦)의 기준 (README 파이프라인 표)
STEP_ORDER = ["research", "probe", "proxy", "chunk", "character_index",
              "chunk_transcribe", "gemini", "graph", "story", "silence_cut",
              "resources", "render", "validate"]

_RUNLOG_RE = re.compile(r"([^/\s]+)/run_log\.json")

# 이 잡의 산출물(run_dir)을 로컬에서 읽는 후속 kind — executor 가 완료 시 이 노드로 고정
# (upload=글롭, ingest/evaluate=--run-dir. publish 는 검수 후 별도 생성이라 대상 밖 —
#  스토리지 폴백(Phase 2)이 정답이며, 그 전까지는 같은 노드 유지가 사실상 강제됨)
PIN_DEPENDENT_KINDS = ("upload_artifacts", "ingest", "evaluate", "localize")


# 채널 템플릿(channels.json "design") → --design-* 플래그. 규약 정본은 brain
# channel_registry.py(CHANNEL_DESIGN_FLAGS) — 1:1 미러(2026-08-10, 첫 회전 실측:
# 템플릿 채널 4곳이 기본 디자인으로 생성됨). 두 층 구분: 템플릿=채널 정체성, 로고=작품 권리물.
CHANNEL_DESIGN_FLAGS = {
    "title_y": "--design-title-y",
    "video_y": "--design-video-y",         # 영상영역 상단 Y(미지정=세로 중앙)
    "title_font": "--design-title-font",
    "title_size": "--design-title-size",
    "title_color": "--design-title-color",      # 제목 1번째 줄
    "title_color2": "--design-title-color2",    # 제목 2번째 줄
    "subtitle_font": "--design-subtitle-font",  # 자막·TTS 자막 공통
    "subtitle_size": "--design-subtitle-size",
    "subtitle_color": "--design-subtitle-color",
    "subtitle_y_margin": "--design-subtitle-y-margin",
    "subtitle_style": "--design-subtitle-style",
    "tts_color": "--design-tts-color",
    "tts_size": "--design-tts-size",
    "tts_y_margin": "--design-tts-y-margin",
    # E7(ai-video 2a087eb): 디자인 레벨 회전·배속 — 지금은 편집실(edit_overrides.design)
    # 경로 전용. 채널 템플릿(channels.json)에 넣으려면 brain CHANNEL_DESIGN_FLAGS 미러
    # 선행(1:1 규율). 범위 검증(회전 -180~180 · 배속 0.8~2.0, 밖이면 즉시 실패)은 엔진 CLI.
    "title_rotate": "--design-title-rotate",
    "tts_rotate": "--design-tts-rotate",
    "video_speed": "--design-video-speed",
    "work_title_y": "--design-work-title-y",    # 작품명(하단) Y
    "work_font_size": "--design-work-font-size",
    "work_color": "--design-work-color",        # 작품명 색
    "aspect_ratio": "--design-aspect-ratio",
    # 플랫폼 표기 — 영상영역 왼쪽 상단 로고/텍스트(ai-video 2026-08-19). brain 과 1:1 유지.
    "platform_image": "--design-platform-image",
    "platform_text": "--design-platform-text",
    "platform_x": "--design-platform-x",
    "platform_y": "--design-platform-y",
    "platform_image_width": "--design-platform-image-width",
    "platform_image_height": "--design-platform-image-height",
    "platform_font_size": "--design-platform-font-size",
    "platform_color": "--design-platform-color",
    "platform_align": "--design-platform-align",   # left(기본)|right
}
CHANNEL_DESIGN_SWITCHES = {
    "face_tracking": ("--no-reframe", False),   # false 면 얼굴 추종 크롭 끔
    # 대사 자막 끔(8/20 Sally) — false 면 소스에 자막이 있어도 이 채널은 안 그린다.
    # ⚠ 편집실 자막 예외(8/17 규칙)가 이긴다 — design_for_job 이 그 편만 이 키를 뺀다.
    "subtitles": ("--no-subtitles", False),
    # F-409(dc1060f): 참이면 제목 동적 배치 대신 title_y 를 그대로 쓴다 — 편집실
    # 제목 드래그가 이 키로 나간다. ⚠ 채널 템플릿에 넣으려면 brain
    # CHANNEL_DESIGN_FLAGS 미러가 선행이다(1:1 규율 — 안 하면 brain 쪽 unknown-key
    # fail-loud 에 걸린다). 지금은 편집실(edit_overrides.design) 경로 전용.
    "title_y_fixed": ("--design-title-y-fixed", True),
}


def _switch_value(channel, key, v):
    """스위치 값 정규화 — JSON 불리언 외에 손 편집 템플릿의 "true"/"false" 도 받되,
    그 밖의 값은 즉시 실패(registry 원칙: 조용한 무시 = 오타가 기본값으로 발행)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    raise base.PermanentError(
        f"채널 '{channel}': design 스위치 {key} 는 불리언이어야 합니다({v!r})")


def channel_design_flags(design, channel) -> list:
    """채널 'design' dict → CLI 플래그. '_' 키 무시, 모르는 키는 즉시 실패 —
    조용히 무시하면 오타 난 템플릿이 기본값으로 발행되고 아무도 모른다(registry 원칙). 순수."""
    flags = []
    for k, v in (design or {}).items():
        if k.startswith("_"):
            continue
        if k in CHANNEL_DESIGN_SWITCHES:
            flag, on_value = CHANNEL_DESIGN_SWITCHES[k]
            if _switch_value(channel, k, v) is on_value:
                flags.append(flag)
            continue
        flag = CHANNEL_DESIGN_FLAGS.get(k)
        if not flag:
            raise base.PermanentError(
                f"채널 '{channel}': 알 수 없는 design 키 {k!r} — "
                f"허용: {sorted(CHANNEL_DESIGN_FLAGS) + sorted(CHANNEL_DESIGN_SWITCHES)}")
        flags += [flag, str(v)]
    return flags


def design_for_job(design, params):
    """편집실 자막 예외(8/17 규칙 우선, 8/20 스위치 추가와 함께). 순수 — 테스트 대상.

    템플릿 subtitles:'끔'을 일반 디자인 플래그 경로로 그냥 흘리면 build_argv_pure 의
    subtitles_requested 가드를 우회한다 — 사람이 자막을 고쳐 보낸 편에 --no-subtitles
    가 그대로 붙어 '고쳤는데 안 나가는' 편집실 거짓말이 재발한다. 그래서 자막을 고쳐
    보낸 잡에서는 이 키만 빼고 나머지 디자인은 그대로 둔다."""
    if subtitles_requested(params) and (design or {}).get("subtitles") is False:
        return {k: v for k, v in design.items() if k != "subtitles"}
    return design


def effective_design(override, file_design):
    """관제 오버라이드(0014) > 파일 정본(channels.json design). 순수 — 테스트 대상.
    오버라이드는 통째 교체(편집기에서 보이는 그대로 실행) — 필드 병합의 미묘함을 피한다."""
    return override if override is not None else file_design


def edit_design(base_design, edit):
    """편집실 스타일(edit_overrides.design)을 채널 디자인 **위에** 얹는다. 순수 — 테스트 대상.

    여기만 통째 교체가 아니라 **필드 병합**인 이유: 편집실이 보내는 것은 사람이 이 한 편에서
    만진 몇 개 값뿐이고, 나머지는 채널 정체성(폰트·색 규약)을 그대로 따라야 한다. 통째로
    바꾸면 자막 크기 하나 고쳤다고 채널 폰트가 기본값으로 돌아간다.
    빈 값(None·'')은 '안 건드림'이다 — 화면의 빈 입력칸이 기본값 강제로 둔갑하지 않게."""
    if not edit:
        return base_design
    out = dict(base_design or {})
    for k, v in edit.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        out[k] = v
    return out


def enrich_params(cfg, conn, job):
    """실행 직전(관제 저장 즉시 다음 잡부터): channel_design_overrides → params.design_override."""
    p = dict(job.get("params") or {})
    if not p.get("channel_slug"):
        return p
    with conn.cursor() as c:
        c.execute("SELECT design FROM public.channel_design_overrides WHERE token_slug=%s",
                  (p["channel_slug"],))
        row = c.fetchone()
    if row and row.get("design") is not None:
        p["design_override"] = row["design"]
    return p


def _channel_record(cfg, channel_name):
    raw = _brain_json(cfg, "channels.json")
    chans = raw.get("channels") if isinstance(raw, dict) else raw
    for rec in chans or []:
        if isinstance(rec, dict) and rec.get("name") == channel_name:
            return rec
    return None


def branding_flags(card, policy) -> list:
    """작품 카드 branding.logo → --design-work-image 플래그 (가이드 자동화 2026-08-10).
    규약 정본은 brain channel_registry.py(§로고) — 여기와 그쪽이 같은 works.json 을 읽으므로
    scene_loop 과 신규 파이프라인의 로고가 항상 일치한다. 카드에 logo 없으면 텍스트(종전)."""
    brand = ((card or {}).get("branding") or {})
    if not brand.get("logo"):
        return []
    flags = ["--design-work-image", str(brand["logo"])]
    box = brand.get("box") or (policy or {}).get("logo_box")
    if box and "x" in str(box).lower():
        w, h = str(box).lower().split("x", 1)
        try:
            flags += ["--design-work-image-width", str(int(w)),
                      "--design-work-image-height", str(int(h))]
        except ValueError:
            pass
    align = brand.get("align") or (policy or {}).get("logo_align")
    if align in ("top", "center"):
        flags += ["--design-work-align", str(align)]
    return flags


# 작품 카드 editorial 허용 키 — ai-video app/modules/editorial.py 계약의 미러(1:1 규율,
# brain channel_registry.EDITORIAL_KEYS 와 동일). 셋이 어긋나면 ai-video 쪽 fail-loud 에 걸린다.
EDITORIAL_KEYS = frozenset({"avoid", "rules", "prefer", "tone"})


def editorial_flags(card, work) -> list:
    """작품 카드 editorial → --editorial-json (편집 지침 자동화 2026-08-20). 순수 — 테스트 대상.
    규약 정본은 brain channel_registry.editorial_flags — 여기와 그쪽이 같은 works.json 을
    읽으므로 scene_loop 과 신규 파이프라인의 지침이 항상 일치한다. '_' 키(_note)는 문서용.
    모르는 키는 즉시 실패 — 조용히 무시하면 권리 지침 없이 발행된다(registry 원칙)."""
    ed = {k: v for k, v in ((card or {}).get("editorial") or {}).items()
          if not k.startswith("_")}
    if not ed:
        return []
    unknown = set(ed) - EDITORIAL_KEYS
    if unknown:
        raise base.PermanentError(
            f"작품 '{work}': 알 수 없는 editorial 키 {sorted(unknown)} — "
            f"허용: {sorted(EDITORIAL_KEYS)}")
    return ["--editorial-json", json.dumps(ed, ensure_ascii=False, sort_keys=True)]


def _brain_json(cfg, name):
    p = pathlib.Path(cfgmod.engine_dir(cfg, "brain")) / "config" / name
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw.get("works", raw) if isinstance(raw, dict) and "works" in raw else raw
    except (OSError, json.JSONDecodeError):
        return {}


# ───────── 순수 (테스트 대상) ─────────
def subtitles_requested(params: dict) -> bool:
    """편집실에서 사람이 대사 자막을 고쳐 보냈는가. 순수 — 테스트 대상.

    지금 모든 소스가 has_subtitle=false 라 planner 가 no_subtitles=true 를 넣고, 엔진은
    대사 자막을 아예 굽지 않는다(subtitle_segments.json·subtitles.ass 는 만들어지지만
    렌더 입력에서 빠진다). 그 상태에서 편집실 자막 수정을 받으면 파일만 바뀌고 영상은
    그대로다 — 사람 눈에는 '고쳤는데 안 바뀌는' 버그로 보인다. 그래서 자막을 고쳐 보낸
    그 편만 자막을 켠다. 사용자 결정(2026-08-17): 평상시는 지금대로, 손대면 켜진다."""
    ov = (params or {}).get("edit_overrides") or {}
    return bool(ov.get("subtitles"))


def build_argv_pure(py: str, params: dict, source_path: str | None) -> list:
    p = params
    cmd = [py, "-u", "-m", "app.cli", "create_shorts",
           "--title", p["work_title"],
           "--max-shorts", str(p.get("max_shorts") or 1)]
    if source_path:
        cmd += ["--video", source_path]
    elif p.get("source_url"):
        cmd += ["--youtube-url", p["source_url"]]
    if p.get("topic"):
        cmd += ["--topic", p["topic"]]
    if p.get("reject_note"):     # 검수함 반려 사유 → 분석·스토리 프롬프트의 '재작업 지시'
        cmd += ["--reject-note", str(p["reject_note"])]
    if p.get("editorial_run"):   # 홈 '기획 방향'(0063) — 이번 한 편에만 얹는 지시.
        # 카드 상시 지침(--editorial-json)과 ai-video 가 병합한다 — avoid·rules 완화 불가.
        cmd += ["--editorial-run-json", json.dumps(p["editorial_run"], ensure_ascii=False)]
    if p.get("episode") is not None:
        cmd += ["--episode", str(p["episode"])]
    if p.get("no_research", True):
        cmd += ["--no-research"]
    # 자막 미제공 작품 합의(brain CLAUDE.md §5) — 다만 편집실에서 사람이 자막을 고쳐
    # 보냈으면 그 편만 자막을 켠다. 고친 문장이 화면에 안 나가면 편집실이 거짓말을 하는
    # 셈이다(2026-08-17 실측: subtitles.ass 는 바뀌는데 mp4 는 그대로였다).
    if p.get("no_subtitles") and not subtitles_requested(p):
        cmd += ["--no-subtitles"]
    if p.get("no_tts_subtitles"):    # 등급 J(8/13): 텍스트는 vlp 가 일본어로 그린다
        cmd += ["--no-tts-subtitles"]
    if p.get("no_title_overlay"):    # J v2(8/13): 제목·작품명 오버레이도 생성 단계에서 생략
        cmd += ["--no-title-overlay"]
    if p.get("no_tts_audio"):        # J v2: KR TTS 오디오 미믹스 — 일본어 TTS 는 vlp 가
        cmd += ["--no-tts-audio"]
    f = p.get("flags") or {}
    if f.get("silence"):
        cmd += ["--silence-profile", f["silence"]]
    if f.get("length"):
        cmd += ["--length-profile", f["length"]]
    if f.get("loudness"):
        cmd += ["--loudness-lufs", str(f["loudness"])]
    cmd += ["--outdir", p.get("outdir") or "outputs"]
    return cmd


def pick_resume_step(checkpoint_filenames) -> str | None:
    """checkpoint_<step>.json 목록 → --from-step 값(마지막 완료 스텝 재실행부터).
    없으면 None(처음부터)."""
    done = []
    for fn in checkpoint_filenames:
        name = str(fn).rsplit("/", 1)[-1]
        if name.startswith("checkpoint_") and name.endswith(".json"):
            step = name[len("checkpoint_"):-len(".json")]
            if step in STEP_ORDER:
                done.append(step)
    if not done:
        return None
    return max(done, key=STEP_ORDER.index)


def extract_partial_run_id(stdout: str) -> str | None:
    """실패 출력에서도 run 디렉토리명 회수 — 재개(★⑦)의 근거. autogen.parse_job_id 계약."""
    m = _RUNLOG_RE.search(stdout or "")
    return m.group(1) if m else None


def scene_span(edit_plan: dict):
    """edit_plan.json → 이 장면이 커버하는 소스 구간 (min clip_start, max clip_end).
    구 시스템 scene_loop.scene_span 과 같은 계약. 순수 — 테스트 대상."""
    tl = (edit_plan or {}).get("timeline") or []
    starts = [c.get("clip_start") for c in tl if isinstance(c, dict) and c.get("clip_start") is not None]
    ends = [c.get("clip_end") for c in tl if isinstance(c, dict) and c.get("clip_end") is not None]
    if not starts or not ends:
        return None
    return [float(min(starts)), float(max(ends))]


DUP_OVERLAP_RATIO = 0.50   # 사용자 결정(8/12): '같은 부분을 50% 이상 썼을 때'만 같은 장면


def overlap_ratio(a, b) -> float:
    """두 구간이 얼마나 같은 부분을 쓰는가 — 겹친 초 / 짧은 쪽 길이. 0~1. 순수.

    짧은 쪽으로 나누는 이유: 60초 장면 안에 20초 장면이 통째로 들어가면 그건 같은 부분을
    100% 다시 쓴 것이다. 합집합(IoU)으로 재면 0.33 이라 '다른 장면'으로 통과해 버린다."""
    if not a or not b:
        return 0.0
    a0, a1 = float(a[0]), float(a[1])
    b0, b1 = float(b[0]), float(b[1])
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    shorter = min(a1 - a0, b1 - b0)
    return inter / shorter if shorter > 0 else 0.0


def spans_overlap(a, b, ratio_th: float = DUP_OVERLAP_RATIO) -> bool:
    """두 구간이 '같은 장면'인가 — 겹침이 짧은 쪽의 ratio_th 이상이면 같다고 본다. 순수.

    종전(IoU 0.30 또는 중심 15초 이내)은 스치기만 해도 중복으로 몰아 재생성을 헛돌게 했다.
    8/12 사용자 결정으로 '50% 이상' 단일 기준으로 바꾼다 — 중심 근접 규칙은 폐기."""
    return overlap_ratio(a, b) >= ratio_th


def is_duplicate_take(span, avoid_spans) -> bool:
    """새 장면이 반려·기존 구간과 겹치는가. 순수 — 테스트 대상."""
    return any(spans_overlap(span, s) for s in (avoid_spans or []))


# ───────── 반려 단계 (사용자 결정 2026-08-12) ─────────
# 검수함에서 고른 반려 단계 → ai-video 를 어디서부터 다시 돌릴지.
# 엔진 13단계: init research probe proxy chunk character_index chunk_transcribe
#              gemini graph story silence_cut resources render validate
REJECT_STAGES = {
    "영상 분석":   {"mode": "fresh",  "from_step": None,     "eta": "40~70분"},
    "스토리 구성": {"mode": "resume", "from_step": "story",  "eta": "15~25분"},
    "제작":       {"mode": "resume", "from_step": "render", "eta": "수 분"},
    "장면":       {"mode": "fresh",  "from_step": None,     "eta": "40~70분"},   # 0019 호환
}


def reject_plan(stage):
    """반려 단계 → 재실행 계획. 모르는 값은 가장 안전한 쪽(처음부터)으로. 순수 — 테스트 대상."""
    return REJECT_STAGES.get(stage) or REJECT_STAGES["영상 분석"]


def resolve_resume_step(explicit, checkpoint_filenames, default=None):
    """--from-step 결정. 순수 — 테스트 대상.

    사람이 단계를 골라 반려했으면(explicit) 그 단계가 절대 우선이다. 체크포인트 자동 선택은
    '죽은 잡 이어달리기'용이라, 완주한 run 에 쓰면 마지막 단계(validate)를 집어 아무것도
    다시 만들지 않는다 — 8/12 실측 전 잠재 결함."""
    if explicit:
        return explicit
    return pick_resume_step(checkpoint_filenames) or default


def provenance_ok(run_log: dict) -> bool:
    """R8 판정 — ai-video run_log 실제 스키마는 {input, steps, job_id, provenance}
    (스모크3 실측: 최상위 'provenance_complete' 키는 존재한 적이 없다. 그 키를 읽던
    종전 코드는 건강한 런을 전부 막았다). ingest(T0-2)와 같은 기준을 쓴다:
    provenance 에 git_sha 와 config 스냅샷이 있으면 완전. 레거시 키는 관용 허용."""
    rl = run_log or {}
    prov = rl.get("provenance") or {}
    if bool(prov.get("git_sha")) and bool(prov.get("config")):
        return True
    return bool(rl.get("provenance_complete"))   # 레거시/미래 엔진 호환


# ───────── 어댑터 인터페이스 ─────────
def cwd(cfg, job):
    return cfgmod.engine_dir(cfg, "ai_video")


def env(cfg, job):
    # 잡마다 env 파일을 다시 읽는다 — 노드에 새로 넣은 시크릿(YouTube 쿠키 등)이
    # 에이전트 재기동 없이도 이 서브프로세스에 닿아야 한다(config.job_env 주석 참고).
    return cfgmod.job_env(cfg)


def resource(cfg, job):
    return (job.get("params") or {}).get("resource")   # 'gemini:VES01' — planner 가 채움(§7)


def build_argv(cfg, job):
    # 반려 재생성(0019): '제작' 반려는 같은 run 을 렌더 단계부터 이어달린다(수 분).
    rid = (job["params"] or {}).get("resume_run_id")
    if rid:
        return resume_argv(cfg, job, rid, default_step=(job["params"].get("from_step") or "render"))
    return _build_argv_fresh(cfg, job)


def edit_overrides_argv(base_argv, overrides_path) -> list:
    """편집실 오버라이드 경로가 있으면 `--edit-overrides` 를 뒤에 붙인다. 순수 — 테스트 대상.

    앞부분은 절대 손대지 않는다(하위호환) — 오버라이드가 없는 잡은 종전과 완전히 같은
    명령으로 돌아야 한다. localize.scene_rerender_argv 와 같은 규약."""
    argv = list(base_argv)
    return argv + ["--edit-overrides", str(overrides_path)] if overrides_path else argv


def localize_edit_images(overrides, run_dir, download):
    """images[].key(스토리지) → run_dir 상대 file 치환. 순수 판정 + 주입된 download 로 IO.

    엔진은 로컬 파일만 받는다(v3 계약: file 은 run_dir 상대 경로, 절대/'..' 거절) —
    스토리지 자격은 오케스트레이터 소유라는 현행 규율 유지. 실패는 즉시 에러:
    조용히 빼면 사람이 올린 이미지가 소리 없이 사라진 영상이 나간다(fail-loud).
    download(key, dest_path) 는 호출자 주입 — 테스트가 IO 없이 계약을 검증한다."""
    imgs = (overrides or {}).get("images")
    if not imgs:
        return overrides
    d0 = pathlib.Path(run_dir)
    # run_dir 존재 검사를 여기서도 — 아래 mkdir 가 없는 run_dir 을 만들어버리면
    # _write_edit_overrides 의 같은 fail-loud 가드가 영영 통과해 빈 가짜 run 이 생긴다.
    if not d0.exists():
        raise base.PermanentError(f"run_dir 없음: {d0} — 편집 재렌더는 원본 run 이 있어야 합니다")
    d = d0 / "editor_images"
    d.mkdir(exist_ok=True)
    new_imgs = []
    for i, im in enumerate(imgs):
        im = dict(im or {})
        if "file" in im:
            # file 은 이 함수의 산출물이다 — 클라이언트가 넣어 보내면 prefix 검증을
            # 통째로 우회해 run_dir 안 임의 파일을 오버레이 소스로 지정하게 된다.
            raise base.PermanentError(
                f"images[{i}]: file 은 어댑터가 만드는 값입니다 — 화면은 key 만 보냅니다")
        key = im.pop("key", None)
        if not key:
            raise base.PermanentError(
                f"images[{i}]: key 가 없습니다 — 대시보드 수집 계약 확인")
        if not str(key).startswith("editor_uploads/") or ".." in str(key):
            raise base.PermanentError(
                f"images[{i}]: 허용 prefix 밖의 키({key!r}) — editor_uploads/ 만 받습니다(0056)")
        name = f"{i:02d}_{pathlib.Path(str(key)).name}"
        try:
            download(str(key), str(d / name))
        except Exception as ex:
            # 없는 키는 재시도해도 안 생긴다(업로드 불변·삭제 정책 없음) — 즉시 실패.
            # 그 외(네트워크·5xx)는 그대로 전파 = 재시도 대상.
            if "404" in str(ex):
                raise base.PermanentError(
                    f"images[{i}]: 스토리지에 없는 키({key}) — 업로드가 지워졌거나 초안이 낡았습니다"
                ) from ex
            raise
        im["file"] = f"editor_images/{name}"
        new_imgs.append(im)
    out = dict(overrides)
    out["images"] = new_imgs
    return out


def _download_editor_upload(cfg):
    """스토리지 다운로드 주입자 — 서비스 키는 여기서만 쓴다(어댑터 순수부와 분리)."""
    from ves.storage.supabase_storage import Store
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    return lambda key, dest: store.download("ves-outputs", key, dest)


def _write_edit_overrides(run_dir, overrides) -> pathlib.Path | None:
    """오버라이드 dict → <run_dir>/edit_overrides.json. 없으면 None.

    파일로 넘기는 이유: 자막 수십 줄이 들어가면 argv 로는 셸 인용·길이 한계에 걸린다.
    0038 의 localize_overrides.json 과 같은 방식이며, 파일이 run_dir 에 남으므로
    '무엇을 보냈는지'가 그 맥에 증거로 남는다."""
    if not overrides:
        return None
    d = pathlib.Path(run_dir)
    if not d.exists():
        raise base.PermanentError(f"run_dir 없음: {d} — 편집 재렌더는 원본 run 이 있어야 합니다")
    p = d / "edit_overrides.json"
    p.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _build_argv_fresh(cfg, job):
    p = job["params"]
    if p.get("edit_overrides") and not p.get("resume_run_id"):
        # 새 run 에 편집 오버라이드는 의미가 없다 — 사람이 고친 구간은 그 run 의 좌표계
        # (원본 절대초 + 그 편의 자막 타임라인)에 묶여 있다. 조용히 무시하면 사람이 고친
        # 값이 빠진 영상이 나가므로 즉시 실패시킨다(edit_overrides 모듈과 같은 원칙).
        raise base.PermanentError(
            "edit_overrides 는 resume_run_id 와 함께여야 합니다 — 새 run 에는 적용할 수 없습니다")
    src = cfgmod.source_cache_path(cfg, p["source_sha256"]) if p.get("source_sha256") else None
    if src and not pathlib.Path(src).exists():
        raise base.PermanentError(f"소스 캐시 없음: {src} — acquire 선행 확인")
    argv = build_argv_pure(cfgmod.engine_py(cfg, "ai_video"), p, src)
    # 채널 템플릿(채널 정체성): 관제 오버라이드(0014) > channels.json "design" (registry 규약)
    # 편집실 스타일(0044)은 그보다 위 — 사람이 이 한 편에 대해 지금 고른 값이다.
    rec = _channel_record(cfg, p.get("channel_name"))
    design = effective_design(p.get("design_override"), (rec or {}).get("design"))
    design = edit_design(design, (p.get("edit_overrides") or {}).get("design"))
    design = design_for_job(design, p)   # 편집실 자막 예외 — 자막 고친 편은 템플릿 '끔' 무시
    argv += channel_design_flags(design, p.get("channel_name"))
    # 로고(가이드 자동화): 작품 카드에 branding.logo 가 있으면 scene_loop 과 같은 플래그
    card = _brain_json(cfg, "works.json").get(p.get("work_title"))
    argv += branding_flags(card, _brain_json(cfg, "loop_policy.json"))
    # 편집 지침(권리 가이드 자동화 2026-08-20): 카드 editorial → 프롬프트 1차 필터.
    # 검수함 사람 확인은 그대로 — 반려 사유(--reject-note)가 실행 단위 지시 통로를 겸한다.
    argv += editorial_flags(card, p.get("work_title"))
    return argv


def resume_argv(cfg, job, partial_run_id, default_step=None):
    """★⑦ 재시도는 이어달리기 — 같은 run_id 로 마지막 체크포인트부터."""
    argv = _build_argv_fresh(cfg, job)
    outdir = (job["params"].get("outdir") or "outputs")
    run_dir = pathlib.Path(cfgmod.engine_dir(cfg, "ai_video")) / outdir / partial_run_id
    step = resolve_resume_step((job["params"] or {}).get("from_step"),
                               glob.glob(str(run_dir / "checkpoint_*.json")), default_step)
    argv += ["--job-id", partial_run_id]
    if step:
        argv += ["--from-step", step]
    # 편집실(0043): 사람이 고친 제목·자막·구간. 파일로 써서 경로만 넘긴다.
    # 이미지(F-408)는 스토리지 키 → run_dir 파일로 먼저 바꾼다(엔진은 로컬만 받는다).
    ov = (job["params"] or {}).get("edit_overrides")
    if ov and ov.get("images"):
        ov = localize_edit_images(ov, run_dir, _download_editor_upload(cfg))
    return edit_overrides_argv(argv, _write_edit_overrides(run_dir, ov))


def parse_result(cfg, job, stdout):
    rid = extract_partial_run_id(stdout)
    if not rid:
        raise base.PermanentError("stdout 에서 run_id 를 못 찾음 — ai-video 출력 계약 확인")
    outdir = (job["params"].get("outdir") or "outputs")
    run_dir = pathlib.Path(cfgmod.engine_dir(cfg, "ai_video")) / outdir / rid
    run_log = {}
    rl = run_dir / "run_log.json"
    if rl.exists():
        try:
            run_log = json.loads(rl.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            run_log = {}
    if not provenance_ok(run_log):   # R8: provenance 없이 succeeded 불가
        raise base.PermanentError(
            f"provenance 불완전(provenance.git_sha/config 스냅샷 없음) — R8 (run={rid})")

    # 장면 구간 기록(0019) — 반려 회피·중복 판정의 근거. 구 시스템 edit_plan 계약 계승.
    span = None
    ep = run_dir / "edit_plan.json"
    if ep.exists():
        try:
            span = scene_span(json.loads(ep.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            span = None
    avoid = (job["params"] or {}).get("avoid_spans") or []
    if span and is_duplicate_take(span, avoid):
        # 반려한 장면을 또 만든 것 — 일시 실패로 돌려 재시도가 다른 구간을 뽑게 한다
        raise RuntimeError(f"반려 구간과 중복된 장면(span={span}, 회피={avoid}) — 다른 장면으로 재시도")
    return {"run_id": rid, "run_dir": str(run_dir), "provenance_complete": True,
            "scene_span": span}


def classify_error(rc, stderr, stdout):
    return base.classify_by_patterns(stderr, stdout)


def is_already_done(cfg, job):
    """멱등: 직전 성공 run 이 있으면 스킵 — result 에 run_id 가 남아있는 경우."""
    rid = ((job.get("result") or {}).get("run_id"))
    if not rid:
        return False
    outdir = (job["params"].get("outdir") or "outputs")
    rl = pathlib.Path(cfgmod.engine_dir(cfg, "ai_video")) / outdir / rid / "run_log.json"
    return rl.exists()
