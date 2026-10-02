"""새 방식(tikitaka) 어댑터 — argv·번들 찾기·저장소 키 회귀 가드 (0111)."""
from __future__ import annotations

import json

import pytest

from ves.adapters import base
from ves.adapters.tikitaka import (build_argv_pure, classify_tail, duration_of, engine_args, job_dir_name, last_json_line, logo_flags,
                                   list_bundles, object_key, sprite_argv, make_sprites, apply_report)


def test_argv_basic():
    argv = build_argv_pure("/py", {"work_title": "가왕쇼", "episode": 9, "count": 3}, "/cache/abc", "/out/wo-1")
    assert argv == ["/py", "-u", "-m", "app.tikitaka", "--source", "/cache/abc", "--title", "가왕쇼",
                    "--episode", "9화", "--count", "3", "--out", "/out/wo-1"]


def test_argv_engine_args():
    argv = build_argv_pure("/py", {"work_title": "w", "episode": 1, "count": 1,
                                   "args": {"design_preset": "gawangsho", "style_preset": "recap",
                                            "cover_cut_guard": True, "copy": ""}}, "/s", "/o")
    assert argv[-5:] == ["--design-preset", "gawangsho", "--style-preset", "recap", "--cover-cut-guard"]


@pytest.mark.parametrize("args", [{"nope": 1}, {"voice": "--rm"}, {"copy": "a\nb"},
                                  {"cover_cut_guard": "yes"}, {"speed": ["fast"]}, {"logo_width": True}])
def test_engine_args_reject(args):
    with pytest.raises(base.PermanentError):
        engine_args(args)


@pytest.mark.parametrize("p", [{"episode": 1}, {"work_title": "w"}, {"work_title": "w", "episode": 1, "count": 15},
                               {"work_title": "w", "episode": 1, "count": 0}])
def test_argv_reject(p):
    p = dict(p)
    if p.get("count") == 0:
        p["count"] = -1
    with pytest.raises(base.PermanentError):
        build_argv_pure("/py", p, "/s", "/o")


def test_list_bundles(tmp_path):
    v = tmp_path / "videos"
    for name in ("v1", "v8_r3637-3820", "v2.prev_123", "v3", "notes"):
        (v / name).mkdir(parents=True)
    for name in ("v1", "v8_r3637-3820", "v2.prev_123", "notes"):
        (v / name / "video.json").write_text(json.dumps({}))
    assert [s for s, _ in list_bundles(tmp_path)] == ["v1", "v8_r3637-3820"]
    assert list_bundles(tmp_path / "missing") == []


def test_object_key():
    assert object_key("wo", "v1", "tts/a.mp3") == "tikitaka/wo/v1/tts/a.mp3"
    for bad in ("../x", "한글.json", "a b.json"):
        with pytest.raises(base.PermanentError):
            object_key("wo", "v1", bad)


def test_job_dir_ascii():
    assert job_dir_name("0f3c-1") == "wo-0f3c-1"


def test_classify_tail_ignores_early_log():
    early = "quota 설명 줄\n" + "x" * 5000
    assert classify_tail(early + "\nTraceback: boom", "") == "transient"
    assert classify_tail("... 429 RESOURCE_EXHAUSTED", "") == "quota"


def test_duration_from_review_json():
    assert duration_of({}, {"validation": {"duration_sec": 55.3}}) == 55.3
    assert duration_of({"duration": 12}, None) == 12
    assert duration_of({}, {"validation": {}}) is None
    assert duration_of({}, {"validation": {"duration_sec": True}}) is None


def test_last_json_line():
    assert last_json_line('로그\n{"edit_id": "e1", "ok": true}\n') == {"edit_id": "e1", "ok": True}
    assert last_json_line('로그만') == {}
    assert last_json_line('{"a":1}\n{깨짐') == {}


def test_logo_flags():
    assert logo_flags(None, "/x.png") == [] and logo_flags({"render_width": 960}, None) == []
    assert logo_flags({"render_width": 960}, "/c/a.png") == ["--logo", "/c/a.png", "--logo-width", "960"]
    with pytest.raises(base.PermanentError):
        logo_flags({"render_width": 5000}, "/c/a.png")


def test_sprite_argv_matches_workspace():
    a = sprite_argv("/s/editor_scan.mp4", "/o/sprite_%03d.jpg")
    assert a[:6] == ["ffmpeg", "-v", "error", "-y", "-skip_frame", "nokey"]
    assert "fps=1/2,scale=160:90" in a[a.index("-vf") + 1] and "tile=10x10" in a[a.index("-vf") + 1]
    assert a[-1] == "/o/sprite_%03d.jpg"


def test_make_sprites_without_scan(tmp_path):
    assert make_sprites(tmp_path) == []
    assert not (tmp_path / "sprites").exists()


def test_apply_report():
    got = apply_report({"log": [{"kind": "dropped", "what": "zoom"}, "x"], "duration_sec": 58.2},
                       "렌더 중\n  ⚠ 12.5~14s 인물 얼굴이 왼쪽 잘림 띠에 걸림 (확인)\n⚠ 12.5~14s 인물 얼굴이 왼쪽 잘림 띠에 걸림\n")
    assert got["log"] == [{"kind": "dropped", "what": "zoom"}]
    assert got["log_text"] == "⚠ 12.5~14s 인물 얼굴이 왼쪽 잘림 띠에 걸림"
    assert got["duration_sec"] == 58.2
    assert apply_report({}, "") == {"log": [], "log_text": ""}


def test_logo_copies():
    from ves.adapters.tikitaka import logo_copies
    d = {"work_type": "image", "work_value": "/e/logos/jigeum.PNG", "platform_image": "/e/logos/tving.jpeg"}
    assert logo_copies(d) == [("/e/logos/jigeum.PNG", "assets/logo_work.png"), ("/e/logos/tving.jpeg", "assets/logo_platform.jpg")]
    assert logo_copies({"work_type": "text", "work_value": "지금 불륜이"}) == []
    assert logo_copies({"work_type": "image", "work_value": "relative.png"}) == []
    assert logo_copies(None) == []


def test_cached_source_sha():
    from ves.adapters.tikitaka import cached_source_sha
    sha = "7610400acfa537a58a08bde98bd7669cde07791acbb17692cf2c14bcb9a4b2f9"
    assert cached_source_sha(f"/opt/ves/cache/sources/{sha}", "/opt/ves/cache/sources") == sha
    assert cached_source_sha(f"/opt/ves/cache/sources/{sha}", "/opt/ves/cache/sources/") == sha
    assert cached_source_sha("/Users/x/Movies/ep1.mp4", "/opt/ves/cache/sources") is None
    assert cached_source_sha(f"/tmp/{sha}", "/opt/ves/cache/sources") is None
    assert cached_source_sha("", "/opt/ves/cache/sources") is None


def test_generate_passes_render_template(tmp_path, monkeypatch):
    """렌더 템플릿(0133)이 있으면 잡 폴더에 template_design.json 을 쓰고 --design-json 으로 넘긴다."""
    import json
    from ves import config as cfgmod
    from ves.adapters.tikitaka import Generate
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(cfgmod, "source_cache_path", lambda cfg, sha: str(src))
    monkeypatch.setattr(cfgmod, "engine_dir", lambda cfg, eng: str(tmp_path / "engine"))
    monkeypatch.setattr(cfgmod, "engine_py", lambda cfg, eng: "/py")
    params = {"work_title": "w", "episode": 1, "count": 1, "source_sha256": "abc", "work_order_id": "wo1",
              "template": {"name": "지금불륜 · 노랑 빨강 제목", "design": {"title_color": "#FDE657"}}}
    argv = Generate.build_argv(None, {"id": "j", "work_order_id": "wo1", "params": params})
    f = argv[argv.index("--design-json") + 1]
    assert json.loads(open(f, encoding="utf-8").read()) == {"design": {"title_color": "#FDE657"}}   # 엔진은 다른 최상위 키를 거절한다
    params.pop("template")
    assert "--design-json" not in Generate.build_argv(None, {"id": "j", "work_order_id": "wo1", "params": params})


def test_render_template_reads_db_and_tolerates_missing():
    from ves.adapters.tikitaka import render_template

    class Cur:
        def __init__(self, row=None, boom=False): self.row, self.boom = row, boom
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a):
            if self.boom: raise RuntimeError("없는 함수")
        def fetchone(self): return self.row

    class Conn:
        def __init__(self, cur): self.cur = cur
        def cursor(self): return self.cur

    t = {"id": "t1", "name": "n", "design": {"title_color": "#FFFFFF"}, "from": "channel"}
    assert render_template(Conn(Cur({"t": t})), {"work_title": "w", "channel_slug": "c"}) == t
    assert render_template(Conn(Cur({"t": None})), {"work_title": "w"}) is None
    assert render_template(Conn(Cur(boom=True)), {"work_title": "w"}) is None


def test_effective_args_defaults_fixed_and_overrides():
    from ves.adapters.tikitaka import effective_args
    assert effective_args({}, {}) == {"stt": "elevenlabs", "cover_cut_guard": True, "script_flow": "staged", "speed": "fast"}
    got = effective_args({"cover_cut_guard": False, "speed": "normal"}, {"voice": "elevenlabs:x", "stt": "default", "script_flow": "single"})
    assert got["cover_cut_guard"] is False and got["stt"] == "default" and got["voice"] == "elevenlabs:x"
    assert got["speed"] == "fast" and got["script_flow"] == "staged"


def test_effective_args_channel_voice_wins():
    from ves.adapters.tikitaka import effective_args
    assert effective_args({"voice": "a"}, {"voice": "b"}, "elevenlabs:c")["voice"] == "elevenlabs:c"
    assert effective_args({}, {"voice": "elevenlabs:b"}, None)["voice"] == "elevenlabs:b"
