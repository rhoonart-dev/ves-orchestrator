"""0121 유튜브 원천 여러 채널 · 합본 · 작업 가이드 — 순수 함수."""
from ves.adapters import register_sources as rs
from ves.adapters import tikitaka as tk
from ves.adapters import youtube_clips as yc
from ves.scheduler import youtube_watch as yw


def test_clip_kind_and_episode_label_from_tving_titles():
    t = "[로또 1등도 출근합니다] 팀장님 술주정 힘들지..? 한 장 해~ | 5-6화 선공개ㅣTVING"
    assert rs.clip_kind_of(t) == "prerelease" and rs.episode_label_of(t) == (5, "5-6")
    t = "[로또 1등도 출근합니다] 가장 가까운 동료가 하루아침에 적이 됐다 | 3-4화 몰아보기 | TVING"
    assert rs.clip_kind_of(t) == "recap" and rs.episode_label_of(t) == (3, "3-4")
    t = "[로또 1등도 출근합니다] 영업부... 넌 감동이었어 | 5화 클립 | TVING"
    assert rs.clip_kind_of(t) == "clip" and rs.episode_label_of(t) == (5, None)
    assert rs.clip_kind_of("[로또] 현장 | 5-6화 비하인드 | TVING") == "extra"
    assert rs.clip_kind_of("[로또] 저랑 사고 한번 | 메인 예고 | TVING") == "extra"
    # 디글 · tvN 표기
    assert rs.episode_label_of("[#로또1등도출근합니다 6화] 30억 수습 완")[0] == 6
    assert rs.episode_label_of("6화 하이라이트｜정면승부 #로또1등도출근합니다 EP.6")[0] == 6
    assert rs.episode_label_of("놀토 받아쓰기 amazingsaturday EP.410", r"amazingsaturday\s*EP[.\s]?(\d{1,3})\b")[0] == 410


def test_plan_clip_rows_filters_and_keeps_unknown_episode():
    entries = [
        {"id": "a" * 11, "title": "[로또 1등도 출근합니다] A | 5화 클립 | TVING", "duration": 200},
        {"id": "b" * 11, "title": "[다른 작품] B | 5화 클립", "duration": 200},
        {"id": "c" * 11, "title": "[로또 1등도 출근합니다] 쇼츠", "duration": 40},
        {"id": "d" * 11, "title": "[로또 1등도 출근합니다] 하이라이트 | TVING", "duration": 192},
        {"id": "e" * 11, "title": None},
    ]
    rows = rs.plan_clip_rows(entries, "로또 1등도 출근합니다")
    assert [r["url"][-11:] for r in rows] == ["a" * 11, "d" * 11]
    assert rows[1]["episode"] is None


def test_youtube_watch_plan_adds_overlap_only_for_multi_source_works():
    srcs = [{"id": "1", "work_title": "로또", "url": "u1", "is_active": True},
            {"id": "2", "work_title": "로또", "url": "u2", "is_active": True},
            {"id": "3", "work_title": "놀토", "url": "u3", "is_active": True},
            {"id": "4", "work_title": "놀토", "url": "u4", "is_active": False}]
    jobs = yw.plan(srcs, "2026-10-01")
    kinds = [(k, p.get("work_title")) for k, p, _key, _deps in jobs]
    assert kinds.count(("register_playlist", "로또")) == 2 and ("youtube_overlap", "로또") in kinds
    assert ("youtube_overlap", "놀토") not in kinds
    ov = [j for j in jobs if j[0] == "youtube_overlap"][0]
    assert ov[3] == ["ytwatch:1:2026-10-01", "ytwatch:2:2026-10-01"]


def test_compile_plan_extracts_video_ids():
    comp = {"work_title": "로또", "episode_key": "5-6", "name": "본편 합본",
            "recipe": {"items": [{"source_url": "https://www.youtube.com/watch?v=sp5LNA8wR20", "kind": "recap", "start": 3}]}}
    plan = yc.compile_plan(comp)
    assert plan["items"][0]["video_id"] == "sp5LNA8wR20" and plan["items"][0]["start"] == 3
    assert plan["tag"] == "5-6 본편 합본"
    assert yc.first_episode("5-6") == 5 and yc.first_episode("410") == 410


def test_used_ranges_skips_covers_and_merges():
    plans = [{"timeline": [{"clip_start_sec": 10, "clip_end_sec": 20},
                           {"clip_start_sec": 20.4, "clip_end_sec": 25, "use_original_audio": True},
                           {"clip_start_sec": 40, "clip_end_sec": 44, "cover": True}]}]
    assert tk.used_ranges(plans) == [[9.5, 25.5]]
    g = tk.avoid_guide([[9.5, 25.5]], ["라마몽"])
    assert "활용 불가: 00:09.5~00:25.5" in g


def test_prev_summary_never_emits_guide_keys():
    text = tk.prev_summary("3-4 #1", [{"title": "공 팀장의 한마디", "rows": [{"mode": "N", "text": "관점: 공은태"}]}])
    assert all(not ln.startswith("관점") for ln in text.splitlines())
    assert "(내레이션) 관점: 공은태" in text


def test_argv_uses_episode_label():
    argv = tk.build_argv_pure("py", {"work_title": "로또", "episode": 5, "episode_label": "5-6화", "count": 3}, "/s", "/o")
    assert argv[argv.index("--episode") + 1] == "6화"          # 엔진은 회차 하나만 받는다 — 두 회차 합본은 마지막 회차
    assert tk.engine_episode({"episode_label": "410회", "episode": 410}) == "410회"
    argv = tk.build_argv_pure("py", {"work_title": "로또", "episode": 5, "count": 3}, "/s", "/o")
    assert argv[argv.index("--episode") + 1] == "5화"
