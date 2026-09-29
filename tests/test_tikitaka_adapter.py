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
