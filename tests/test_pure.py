#!/usr/bin/env python3
"""순수 로직 단위테스트 — DB/네트워크 의존 없음 (엔진 레포들의 테스트 관행 계승)."""
import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ves.adapters.base import (backoff_minutes, canonical, classify_by_patterns,  # noqa: E402
                               idem_key)
from ves.adapters.aivideo import (build_argv_pure, extract_partial_run_id,  # noqa: E402
                                  pick_resume_step)
from ves.agent.updater import gate_blocks, migration_versions, pick_target  # noqa: E402
from ves.scheduler.channels_sync import plan_sync  # noqa: E402
from ves.scheduler.planner import geoblock_from_guide, job_chain, norm_title  # noqa: E402


# ── 멱등키 (§6-6) ──
def test_idem_key_deterministic_and_order_free():
    a = idem_key("wo1", "generate", {"b": 1, "a": [2, 3]})
    b = idem_key("wo1", "generate", {"a": [2, 3], "b": 1})
    assert a == b and len(a) == 64
    assert idem_key("wo1", "generate", {"a": [2, 3]}) != a          # params 차이
    assert idem_key("wo2", "generate", {"b": 1, "a": [2, 3]}) != a  # wo 차이


def test_canonical_stable():
    assert canonical({"y": 1, "x": None}) == '{"x":null,"y":1}'


# ── 백오프 (§6-5): 1 → 3 → 9분 ──
def test_backoff():
    assert [backoff_minutes(n) for n in (1, 2, 3)] == [1, 3, 9]


# ── 에러 분류 ──
def test_classify_patterns():
    assert classify_by_patterns("HTTP 429 Too Many Requests") == "quota"
    assert classify_by_patterns("", "RESOURCE_EXHAUSTED: gemini") == "quota"
    assert classify_by_patterns("No such file or directory: ep1.mp4") == "permanent"
    assert classify_by_patterns("error: unrecognized arguments: --loudness") == "permanent"
    assert classify_by_patterns("Connection reset by peer") == "transient"


# ── ai-video argv (autogen.build_gen_cmd 계약 계승 + no_subtitles) ──
def test_build_argv_flags_and_subtitles():
    argv = build_argv_pure("/py", {
        "work_title": "유미의 세포들 시즌3", "max_shorts": 1, "episode": 2,
        "no_subtitles": True, "flags": {"silence": "aggressive", "loudness": "-14"},
    }, "/cache/abc")
    s = " ".join(argv)
    assert "--video /cache/abc" in s and "--title 유미의 세포들 시즌3" in s
    assert "--no-subtitles" in s and "--no-research" in s
    assert "--silence-profile aggressive" in s and "--loudness-lufs -14" in s
    assert "--length-profile" not in s     # 미지정 노브는 부착 안 함


def test_build_argv_youtube_source():
    argv = build_argv_pure("/py", {"work_title": "도깨비 10주년 여행",
                                   "source_url": "https://youtu.be/x"}, None)
    assert "--youtube-url" in argv and "--video" not in argv


# ── 재개 스텝 선택 (★⑦) ──
def test_pick_resume_step():
    assert pick_resume_step([]) is None
    assert pick_resume_step(["checkpoint_probe.json", "checkpoint_gemini.json",
                             "checkpoint_story.json"]) == "story"
    assert pick_resume_step(["checkpoint_unknown.json"]) is None
    assert pick_resume_step(["/a/b/checkpoint_render.json",
                             "checkpoint_chunk.json"]) == "render"


def test_extract_partial_run_id():
    out = "…\n작업 완료: outputs/유미의_세포들_시즌3_c7/run_log.json\n"
    assert extract_partial_run_id(out) == "유미의_세포들_시즌3_c7"
    assert extract_partial_run_id("아무것도 없음") is None


# ── 업데이트 게이트 (★③) · 타깃 선택 ──
def test_migration_gate():
    req = migration_versions(["0006_orchestration.sql", "0007_rpc.sql", "README.md",
                              "docs/migrations/0005_gen_queue.sql"])
    assert req == ["0005", "0006", "0007"]
    assert gate_blocks(req, ["0005", "0006"]) == ["0007"]   # 0007 대기 → 업데이트 보류
    assert gate_blocks(req, req) == []


def test_pick_target_pin_wins():
    assert pick_target(False, "pin123", "new456") == "pin123"   # 런북 핀
    assert pick_target(True, "pin123", "new456") == "new456"    # 자동 추적
    assert pick_target(True, None, None) is None


# ── channels_mirror sync (★②): 파일이 정본 ──
def test_plan_sync_file_canonical():
    file_recs = [{"token_slug": "JAEMISHOTS"}, {"token_slug": "KIKKIK"}, {"name": "무슬러그"}]
    ups, dels = plan_sync(file_recs, {"JAEMISHOTS", "OLDCHAN"})
    assert [r["token_slug"] for r in ups] == ["JAEMISHOTS", "KIKKIK"]
    assert dels == ["OLDCHAN"]                                  # 파일에 없으면 미러에서 제거


# ── planner 순수부 (★① 지오블락 · R14 정본 대조 · DAG) ──
def test_geoblock_from_guide():
    assert geoblock_from_guide("… 지오블락 필수 …") is True
    assert geoblock_from_guide("자막 제공 X") is False
    assert geoblock_from_guide(None) is False


def test_norm_title():
    assert norm_title("언더커버 셰프") == norm_title("언더커버셰프")   # 공백 무시 대조


def test_job_chain_kr_vs_jp():
    base_wo = {"work_title": "w", "channel_slug": "S", "channel_name": "n",
               "gcp_project": "VES01", "pipeline": "shorts_kr"}
    kinds = [k for k, *_ in job_chain(base_wo)]
    assert kinds == ["acquire", "generate", "upload_artifacts", "ingest", "evaluate"]
    jp = [k for k, *_ in job_chain({**base_wo, "pipeline": "shorts_jp_localized"})]
    assert jp[-1] == "localize"
    gen = dict((k, (p, c, t)) for k, p, c, t in job_chain(base_wo))["generate"]
    assert gen[0]["resource"] == "gemini:VES01" and gen[2] == 300   # §7 자원 · §6-2 lease


# ── 체인 전파(스모크2 실측 수정) · 에러 분류 보강 ──
def test_merge_dep_outputs():
    from ves.agent.executor import merge_dep_outputs
    deps = {"generate": {"run_id": "r1", "run_dir": "/x/r1", "provenance_complete": True}}
    m = merge_dep_outputs({"channel_slug": "TETOCHIP"}, deps)
    assert m["run_id"] == "r1" and m["run_dir"] == "/x/r1" and m["channel_slug"] == "TETOCHIP"
    assert merge_dep_outputs({"run_id": "keep"}, deps)["run_id"] == "keep"   # 기존 값 우선
    assert merge_dep_outputs(None, {}) == {}


def test_carry_chain_keys():
    """첫 전체 회전 실측: ingest 결과에 run_id 가 없어 evaluate 가 permanent 사망.
    완료 시 params 의 run_id/run_dir 를 결과에 자동 재방출 — 체인이 어댑터 기억력에
    의존하지 않게 한다(유미의 세포들 ep1 회귀)."""
    from ves.agent.executor import carry_chain_keys
    p = {"run_id": "유미의_세포들_시즌3_12", "run_dir": "/x/r12", "channel_slug": "C"}
    r = carry_chain_keys(p, {"stdout_tail": "inserted clip …"})   # ingest 꼴
    assert r["run_id"] == p["run_id"] and r["run_dir"] == p["run_dir"]
    assert carry_chain_keys(p, {"run_id": "own"})["run_id"] == "own"   # 어댑터 값 우선
    assert carry_chain_keys({}, None) == {}
    assert carry_chain_keys(None, {"a": 1}) == {"a": 1}


def test_episode_from_path_checks_parent_dirs():
    """SNL8 실측(8/10): 회차가 폴더명에 있고 파일명(SNL_803)엔 패턴이 없다."""
    from ves.adapters.register_drive import episode_from_path
    assert episode_from_path("SNL 코리아 시즌 8/ 3화/SNL_803_2997_FHD_MASTER_V1.mp4") == 3
    assert episode_from_path("SNL 코리아 시즌 8/10화/SNL_810_X.mp4") == 10
    assert episode_from_path("작품/E07/무제.mp4") == 7
    assert episode_from_path("작품/단편.mp4") is None
    assert episode_from_path(None) is None


def test_scheduler_kick_due():
    """planner_kick: 기동 승계(오발사 방지) → 값 변경 시에만 due."""
    from ves.scheduler.main import kick_due
    assert kick_due(None, "t1", False) == (False, "t1")     # 기동: 승계만
    assert kick_due("t1", "t1", True) == (False, "t1")      # 변화 없음
    assert kick_due("t1", "t2", True) == (True, "t2")       # 변경 → 발사
    assert kick_due(None, "t1", True) == (True, "t1")       # 최초 등록도 발사
    assert kick_due("t1", None, True) == (False, "t1")      # 행 삭제 → 무시


def test_job_chain_acquire_carries_sha():
    """acquire 가 WO 의 sha 로 정확 조회하도록 params 에 승계(SNL8 중복행 실측)."""
    wo = {"work_title": "w", "channel_slug": "S", "channel_name": "n",
          "source_sha256": "abc123", "pipeline": "shorts_kr"}
    acq = dict((k, p) for k, p, *_ in job_chain(wo))["acquire"]
    assert acq["source_sha256"] == "abc123"


def test_channel_design_flags():
    """채널 템플릿(첫 회전 실측: 템플릿 채널 4곳 미적용) — registry 규약 1:1 미러."""
    from ves.adapters.aivideo import channel_design_flags
    from ves.adapters.base import PermanentError
    f = channel_design_flags({"title_color": "white", "title_color2": "#FFD84D",
                              "work_title_y": 1560, "_note": "메모"}, "킥킥극장")
    s = " ".join(f)
    assert "--design-title-color white" in s and "--design-title-color2 #FFD84D" in s
    assert "--design-work-title-y 1560" in s and "_note" not in s
    assert channel_design_flags({"face_tracking": False}, "c") == ["--no-reframe"]
    assert channel_design_flags({"face_tracking": True}, "c") == []
    assert channel_design_flags(None, "c") == []
    try:
        channel_design_flags({"title_colour": "x"}, "c"); assert False, "오타 키가 통과"
    except PermanentError:
        pass


def test_drive_batch_slicing():
    """배치 인입(8/11): 한 회차 N건만 등록하고 나머지는 이어받기 — plan_new 결과를 자른다."""
    from ves.adapters.register_drive import plan_new
    files = [(f"id{i}", f"작품A/ep{i}.mp4") for i in range(500)]
    todo_all = plan_new(files, "external", None, set(), None)
    assert len(todo_all) == 500
    limit = 200
    todo, remaining = todo_all[:limit], max(0, len(todo_all) - limit)
    assert len(todo) == 200 and remaining == 300
    # 이미 등록된 것은 known_ids 로 빠진다 → 다음 회차가 자연히 그 다음부터
    known = {f"id{i}" for i in range(200)}
    nxt = plan_new(files, "external", None, known, None)
    assert len(nxt) == 300 and nxt[0][0] == "id200"


def test_yt_public_pure():
    """0020/성과 보완: id 묶음·응답 파싱·아이콘 선택 (YouTube 공개 API 계약)."""
    from ves.scheduler.yt_public import (chunk_ids, parse_video_stats,
                                         parse_channel_avatars, pick_avatar)
    assert chunk_ids([]) == []
    assert chunk_ids(list(range(120)))[0].__len__() == 50
    assert len(chunk_ids(list(range(120)))) == 3
    assert chunk_ids(["a", None, "b"]) == [["a", "b"]]
    st = {"items": [{"id": "v1", "statistics": {"viewCount": "1500", "likeCount": "12"}},
                    {"id": None, "statistics": {}}]}
    assert parse_video_stats(st) == [("v1", 1500, 12, 0)]
    assert parse_video_stats({}) == []
    assert pick_avatar({"default": {"url": "d"}, "high": {"url": "h"}}) == "h"
    assert pick_avatar({}) is None
    av = {"items": [{"id": "c1", "snippet": {"thumbnails": {"high": {"url": "u1"}}}},
                    {"id": "c2", "snippet": {"thumbnails": {}}}]}
    assert parse_channel_avatars(av) == [("c1", "u1")]


def test_scene_span_and_duplicate():
    """0019 반려 재생성: edit_plan 구간 추출 + 반려 구간 중복 판정(구 시스템 규칙 계승)."""
    from ves.adapters.aivideo import scene_span, spans_overlap, is_duplicate_take
    plan = {"timeline": [{"clip_start": 120.0, "clip_end": 140.0},
                         {"clip_start": 150.5, "clip_end": 165.0}]}
    assert scene_span(plan) == [120.0, 165.0]
    assert scene_span({"timeline": []}) is None
    assert scene_span(None) is None
    assert spans_overlap([100, 160], [110, 170])          # 크게 겹침
    assert spans_overlap([100, 160], [128, 132])          # 중심 근접
    assert not spans_overlap([100, 160], [900, 960])      # 완전히 다른 구간
    assert not spans_overlap(None, [100, 160])
    assert is_duplicate_take([100, 160], [[900, 960], [110, 170]])
    assert not is_duplicate_take([100, 160], [[900, 960]])
    assert not is_duplicate_take([100, 160], [])


def test_diskgc_expired_and_emergency():
    """로컬 디스크 GC(8/11 컷오버 후 신설): 보존일 경과분 + 여유 부족 시 오래된 순 추가 삭제."""
    from ves.agent.diskgc import expired, emergency_plan, GB
    now = 1_800_000_000.0
    ents = [("old", now - 20 * 86400), ("fresh", now - 1 * 86400)]
    assert expired(ents, now, 14) == ["old"]
    assert expired(ents, now, 30) == []
    assert expired([], now, 14) == []
    # 여유 충분 → 아무것도 안 지운다
    pool = [("a", now - 30 * 86400, 10 * GB), ("b", now - 2 * 86400, 10 * GB)]
    assert emergency_plan(pool, 100 * GB) == []
    # 여유 5GB → 60GB 목표까지 오래된 것부터
    picked = emergency_plan(pool, 5 * GB)
    assert picked[0] == "a" and len(picked) == 2


def test_disk_ok_guard():
    """8/11 실측: mm-01 디스크 0.1GB 로 잡을 집어 전부 죽임 — 15GB 미만이면 반납."""
    from ves.agent.executor import disk_ok
    assert disk_ok(200 * 1000 ** 3)
    assert disk_ok(15 * 1000 ** 3)
    assert not disk_ok(14 * 1000 ** 3)
    assert not disk_ok(0)


def test_drive_sync_nodes_roundrobin():
    """드라이브 인입 다중 노드(8/10): nodes 목록 우선, 없으면 단수 키, 공백 관용."""
    from ves.scheduler.drive_watch import sync_nodes
    assert sync_nodes("mm-01,mm-02", "mm-01") == ["mm-01", "mm-02"]
    assert sync_nodes(" mm-01 , mm-02 ", None) == ["mm-01", "mm-02"]
    assert sync_nodes(None, "mm-01") == ["mm-01"]
    assert sync_nodes("", "") == []


def test_plan_for_channel():
    """0016: 채널별 작품·회차 지정 — 정본(works) 안에서만 적용, 밖이면 자동 유지."""
    from ves.scheduler.planner import plan_for_channel
    works = ["유미의 세포들 시즌3", "언더커버셰프"]
    assert plan_for_channel(works, None) == (works, None)                       # 자동
    assert plan_for_channel(works, {"work_title": "언더커버셰프"}) == (["언더커버셰프"], None)
    assert plan_for_channel(works, {"work_title": "언더커버셰프", "episode": 3}) == (["언더커버셰프"], 3)
    assert plan_for_channel(works, {"work_title": "남의 작품"}) == (works, None)  # R14 방어
    assert plan_for_channel(None, {"work_title": "x"}) == ([], None)


def test_zanmang_daily_argv():
    """잔망루피 편입(8/10): 그 레포 .venv 로 autopilot 을 그대로 실행 — task 화이트리스트."""
    from ves.adapters.zanmang import daily_argv
    from ves.adapters.base import PermanentError
    argv = daily_argv("/opt/ves/engines/video-localization-project")
    assert argv[0].endswith("/.venv/bin/python")
    assert argv[1:] == ["-m", "src.autopilot", "daily"]
    assert daily_argv("/r", "status")[-1] == "status"
    try:
        daily_argv("/r", "rm -rf /"); assert False, "임의 task 통과"
    except PermanentError:
        pass


def test_zanmang_summarize():
    """8/11 실측: 성공했는데 stdout 이 비어 원인 추적 불가 — stderr 로그를 지표로 요약."""
    from ves.adapters.zanmang import summarize
    s = summarize("INFO scan 완료: 수집 42편, 신규 7편\nINFO 스코어링 대상 없음(discovered 0)\n")
    assert s["scanned"] == 42 and s["new"] == 7 and s["idle"] is False
    assert "스코어링 대상 없음" in s["log_tail"]
    empty = summarize("")
    assert empty["idle"] is True and empty["log_tail"] == ""


def test_perf_sync_chunks():
    """IN 절 안전 분할(0015) — 대량 content_id 를 laeebly 에 한 방에 던지지 않는다."""
    from ves.scheduler.perf_sync import chunks
    assert chunks([]) == []
    assert chunks([1, 2, 3], n=2) == [[1, 2], [3]]
    assert sum(len(c) for c in chunks(list(range(450)))) == 450
    assert max(len(c) for c in chunks(list(range(450)))) == 200


def test_yt_key_lookup_order():
    """키는 환경변수 → 노드 시크릿 → brain .env 순. 시크릿을 넣고 재기동을 안 해도 잡히는 게 핵심."""
    from ves.scheduler.yt_public import pick_key
    env = {"YOUTUBE_API_KEY": "from-env"}
    sec = {"YOUTUBE_API_KEY": "from-secrets"}
    brain = {"REACT_APP_YOUTUBE_API_KEY": '"from-brain"'}
    assert pick_key(env, sec, brain) == "from-env"
    assert pick_key({}, sec, brain) == "from-secrets"
    assert pick_key({}, {}, brain) == "from-brain"          # 따옴표는 벗긴다
    assert pick_key({}, {"YOUTUBE_API_KEY": "  "}, brain) == "from-brain"   # 빈 값은 건너뛴다
    assert pick_key({}, {}, {}) is None


def test_yt_backfill_reason():
    """호출이 깨진 것과 받을 게 없는 것은 다른 사건 — 붉은 경고가 영영 안 꺼지는 걸 막는다."""
    from ves.scheduler.yt_public import backfill_reason
    assert backfill_reason(48, 47, 1) == "api_error"     # 한 묶음이라도 실패하면 API 쪽
    assert backfill_reason(48, 48, 0) == "ok"
    assert backfill_reason(0, 0, 0) == "ok"              # 채울 게 없으면 정상
    assert backfill_reason(48, 46, 0) == "partial"
    # 8/19 실측: 비공개 1편. 호출은 됐고 항목만 안 왔다 — 경고 수위를 낮춰야 한다
    assert backfill_reason(1, 0, 0) == "unavailable"


def test_yt_status_payload():
    """조용한 실패를 막는 기록 — 대시보드가 이 JSON 을 읽어 경고를 띄운다."""
    import json
    from ves.scheduler.yt_public import status_payload
    d = json.loads(status_payload("api_key_missing", 48, 0, "2026-08-19T05:00:00+00:00"))
    assert d == {"reason": "api_key_missing", "pending": 48, "filled": 0,
                 "at": "2026-08-19T05:00:00+00:00"}
    assert json.loads(status_payload("ok", 0, 0, "x"))["reason"] == "ok"


def test_perf_sync_copy_window():
    """복사 창(매시간)과 보존 창(미러 보관)의 분리 — 과거를 매시간 다시 긁지 않는다."""
    from datetime import date, timedelta
    from ves.scheduler.perf_sync import copy_since
    today = date(2026, 8, 18)
    recent = today - timedelta(days=7)

    # 미러가 원천만큼 거슬러 갖고 있다 → 평시 창(최근 7일)만 다시 읽는다
    assert copy_since(date(2026, 6, 25), date(2026, 6, 25), today) == recent
    # 미러가 비었다 → 원천이 가진 시작점부터 한 번에 메운다
    assert copy_since(None, date(2026, 6, 25), today) == date(2026, 6, 25)
    # 미러에 과거 구멍(35일만 남기던 시절) → 원천 시작까지 넓힌다
    assert copy_since(date(2026, 7, 9), date(2026, 6, 25), today) == date(2026, 6, 25)
    # 원천이 보존 창보다 더 과거를 갖고 있어도 보존 창 경계까지만
    assert copy_since(None, date(2025, 1, 1), today) == today - timedelta(days=120)
    # 원천이 비었다(수집 중단) → 평시 창. 없는 과거를 계속 요청하지 않는다
    assert copy_since(None, None, today) == recent


def test_effective_design_precedence():
    """0014: 관제 오버라이드 > 파일 정본 > 없음(엔진 기본). 통째 교체 의미."""
    from ves.adapters.aivideo import effective_design
    f = {"title_color": "white"}
    o = {"title_color2": "#FF00AA"}
    assert effective_design(o, f) == o          # 오버라이드가 통째로 이긴다
    assert effective_design(None, f) == f       # 오버라이드 없으면 파일
    assert effective_design(None, None) is None
    assert effective_design({}, f) == {}        # 빈 오버라이드도 명시적 교체


def test_acquire_should_pin():
    """첫 전체 회전 실측: 참교육 acquire(mm-06)→generate(다른 노드) '소스 캐시 없음' 즉사.
    파일형만 핀, URL 소스는 쏠림 방지를 위해 핀 없음."""
    from ves.adapters.acquire import should_pin
    assert should_pin({"source": "downloaded", "sha256": "x"})
    assert should_pin({"source": "cache_hit"})
    assert not should_pin({"source": "url"})
    assert not should_pin(None)


def test_classify_smoke_lessons():
    assert classify_by_patterns("ModuleNotFoundError: No module named 'yt_dlp'") == "permanent"
    assert classify_by_patterns("ERROR: [youtube] X: Private video. Sign in") == "human_required"


# ── 노드 어피니티(스모크3 실측: 재시도 노드 이탈 → 'shorts 없음' 즉사) ──
def test_effective_caps_adds_self_tag_once():
    from ves.agent.claim import effective_caps
    caps = effective_caps(["generate", "network"], "mm-01")
    assert caps[-1] == "node:mm-01" and caps[:2] == ["generate", "network"]
    assert effective_caps(["node:mm-01"], "mm-01").count("node:mm-01") == 1
    assert effective_caps(None, "mm-02") == ["node:mm-02"]


def test_pin_dependent_kinds_cover_local_readers():
    from ves.adapters import aivideo
    # upload=글롭 · ingest/evaluate=--run-dir · localize(scene_rerender)=--job-dir
    # — run_dir 를 로컬에서 읽는 kind 전부 고정 대상이어야 한다
    assert set(aivideo.PIN_DEPENDENT_KINDS) == {"upload_artifacts", "ingest", "evaluate", "localize"}


def test_drive_balance_moves_backlog_to_idle_node():
    """실측(8/12): mm-01 에 4건이 몰려 줄 서는 동안 mm-02 는 빈손이었다."""
    from ves.scheduler.drive_balance import plan_rebalance
    nodes = ["mm-01", "mm-02"]
    pending = [("j1", "mm-01"), ("j2", "mm-01"), ("j3", "mm-01")]
    moves = dict(plan_rebalance(pending, {"mm-01": 1}, nodes))
    # mm-01 은 이미 1건을 돌리는 중 → 빈 mm-02 부터 채우고, 비긴 뒤엔 번갈아 간다
    assert moves == {"j1": "mm-02", "j3": "mm-02"}   # j2 는 제자리(옮길 이유 없음)
    # 이미 고른 상태면 아무것도 옮기지 않는다(무의미한 UPDATE 금지)
    assert plan_rebalance([("a", "mm-01"), ("b", "mm-02")], {}, nodes) == []
    # 인입 노드가 한 대뿐이거나 목록이 비면 재배치 없음
    assert plan_rebalance([("a", "mm-01")], {}, ["mm-01"]) == []
    assert plan_rebalance([("a", "mm-01")], {}, []) == []
    # 핀이 아예 없던 잡도 배정된다
    assert plan_rebalance([("a", None)], {}, nodes) == [("a", "mm-01")]


def test_refill_priority_actually_jumps_the_queue():
    """claim 은 ORDER BY priority DESC — 앞세우려면 기본값(100)보다 커야 한다(8/12 실측)."""
    from ves.scheduler.source_watch import REFILL_PRIORITY
    import pathlib
    sql = pathlib.Path("ves/agent/claim.py").read_text(encoding="utf-8")
    assert "ORDER BY j.priority DESC" in sql      # 규약이 바뀌면 이 테스트가 먼저 깨진다
    assert REFILL_PRIORITY > 100


def test_source_watch_finds_dry_works_first():
    """소모는 채널이 하고 보충은 폴더가 한다 — 며칠치 남았는지로 급한 순서를 정한다(8/12)."""
    from ves.scheduler.source_watch import runway_days, needs_refill, target_for
    assert runway_days(9, 3) == 3.0 and runway_days(0, 1) == 0.0
    assert runway_days(5, 0) == float("inf")      # 배정 채널이 없으면 소모되지 않는다
    assert runway_days(None, 1) == 0.0
    rows = [
        {"work_title": "언더커버셰프", "remaining": 180, "channels": 1},   # 180일치 — 여유
        {"work_title": "언니네 산지직송", "remaining": 0,  "channels": 1},  # 0일치 — 오늘 공백
        {"work_title": "김부장",        "remaining": 3,  "channels": 1},   # 3일치 — 임계
        {"work_title": "배정없음",      "remaining": 0,  "channels": 0},   # 채널 없음 — 대상 아님
        {"remaining": 0, "channels": 1},                                   # 작품명 없음 — 무시
    ]
    assert needs_refill(rows) == ["언니네 산지직송", "김부장"]   # 급한 순
    assert needs_refill(rows, low_days=0) == ["언니네 산지직송"]
    assert needs_refill([], 3) == [] and needs_refill(None, 3) == []
    # 대상 결정: laeebly 폴더가 있으면 그것, 없으면 외부 감시폴더의 '실제로 있는' 하위폴더만
    targets = [("외부폴더", "URL_EXT", None, "external"),
               ("김부장", "URL_KIM", "김부장", "single")]
    seen = ["참교육", "김부장", "chamgyoyuk_old"]
    assert target_for("김부장", targets, None, seen) == ("URL_KIM", "single", None)
    assert target_for("참교육", targets, {}, seen) == ("URL_EXT", "external", "참교육")
    # 폴더가 영문이고 별칭이 있으면 그 폴더명을 쓴다(별칭은 '폴더명 → 작품명' 방향)
    assert target_for("옛참교육", targets, {"chamgyoyuk_old": "옛참교육"}, seen) \
        == ("URL_EXT", "external", "chamgyoyuk_old")
    # ★없는 폴더를 추측해서 넣지 않는다 — 8/12 실측: 'kimbujang' 을 넣어 조용히 0건이 됐다
    assert target_for("놀라운 토요일", targets, {}, seen) is None
    assert target_for("참교육", targets, {}, []) is None      # 폴더 목록을 모르면 겨냥하지 않는다
    assert target_for("무엇이든", [], {}, seen) is None


def test_short_sources_are_not_used():
    """3분 이하는 예고편·클립 — 등록은 하되 쓰지 않는다(사용자 결정 8/12)."""
    from ves.adapters.register_drive import is_usable, MIN_USABLE_SEC
    assert MIN_USABLE_SEC == 180
    assert not is_usable(180) and not is_usable(179) and not is_usable(1)
    assert is_usable(181) and is_usable(3600)
    # 길이를 못 잰 경우는 종전대로 사용 — 프로브 실패로 멀쩡한 소스를 죽이지 않는다
    assert is_usable(None) and is_usable("") and is_usable(0) and is_usable(-1)


def test_planner_excludes_short_sources_in_sql():
    """SQL 쪽 2차 방어 — 사람이 실수로 활성화해도 하한 이하는 안 집힌다.
    0031 부터 하한은 작품별이라 숫자가 아니라 정본 함수를 부른다(기본값은 함수 안에 180).
    길이 미상은 종전대로 통과시킨다 — 프로브 실패로 소스를 잃지 않기 위해."""
    import inspect
    from ves.scheduler import planner
    sql = inspect.getsource(planner._pick_source)
    assert "s.duration_sec IS NULL" in sql
    assert "public.source_min_duration(s.work_title)" in sql


def test_use_limit_by_source_length():
    """소스 길이 → 만들 편수 (사용자 결정 8/12): 10분 미만 1 · 10~30분 2 · 30분 이상 3."""
    from ves.adapters.register_drive import use_limit_for
    assert use_limit_for(9 * 60) == 1 and use_limit_for(599) == 1
    assert use_limit_for(600) == 2 and use_limit_for(29 * 60) == 2
    assert use_limit_for(1800) == 3 and use_limit_for(3 * 3600) == 3
    # 길이를 모르면(프로브 실패·구 데이터) 종전값 3 을 유지 — 갑자기 편수를 줄이지 않는다
    assert use_limit_for(None) == 3 and use_limit_for("") == 3 and use_limit_for(0) == 3


def test_youtube_sources_numbered_oldest_first():
    """사용자 결정(8/12): 오래된 것부터 쓴다 → 오래된 영상이 1화여야 한다."""
    from ves.adapters.register_sources import chronological, is_newest_first, plan_rows
    # 채널 업로드 피드는 최신이 앞 — 뒤집어야 오래된 것이 1번이 된다
    assert is_newest_first("https://www.youtube.com/@tvn/videos")
    assert is_newest_first("https://www.youtube.com/channel/UCabc/videos")
    # 사람이 만든 재생목록은 대개 순서대로 — 건드리지 않는다
    assert not is_newest_first("https://www.youtube.com/playlist?list=PLxyz")
    feed = [{"id": "new"}, {"id": "mid"}, {"id": "old"}]
    assert [e["id"] for e in chronological(feed, "https://youtube.com/@ch/videos")] \
        == ["old", "mid", "new"]
    assert [e["id"] for e in chronological(feed, "https://youtube.com/playlist?list=P")] \
        == ["new", "mid", "old"]
    # 업로드 시각이 있으면 URL 모양보다 그게 우선이다
    stamped = [{"id": "b", "timestamp": 200}, {"id": "a", "timestamp": 100},
               {"id": "c", "timestamp": 300}]
    assert [e["id"] for e in chronological(stamped, "https://youtube.com/playlist?list=P")] \
        == ["a", "b", "c"]
    # 일부만 시각이 있으면 신뢰하지 않고 URL 규칙으로 간다
    partial = [{"id": "x", "timestamp": 5}, {"id": "y"}]
    assert [e["id"] for e in chronological(partial, "https://youtube.com/@c/videos")] == ["y", "x"]
    # 서수 폴백 번호는 오래된 것부터 1,2,3 — 사멸 항목은 빠지되 번호는 이어진다
    rows = plan_rows("작품", [{"id": "n", "title": "최신"}, {"id": "m", "title": "[Private video]"},
                             {"id": "o", "title": "최초"}],
                     source_url="https://youtube.com/@c/videos")
    assert [(r["episode"], r["title"]) for r in rows] == [(1, "최초"), (3, "최신")]
    assert all(r["episode_source"] == "ordinal" for r in rows)


def test_localize_lease_long_enough():
    """scene_rerender 컷오버(8/13): localize 는 생성 노드 재렌더 — generate 와 같은
    LONG_LEASE(갱신 스레드가 연장). LOCALIZE_LEASE(3600)는 mm-06 완성-mp4 경로의
    역사적 근거로 남는다(8/12 lease 실측)."""
    from ves.scheduler import planner
    assert planner.LOCALIZE_LEASE >= 3600 > planner.LONG_LEASE
    chain = planner.job_chain({"pipeline": "shorts_jp_localized", "work_title": "작품",
                               "channel_slug": "SHOTCONE", "channel_name": "ショトコン"})
    loc = [c for c in chain if c[0] == "localize"]
    assert loc and loc[0][3] == planner.LONG_LEASE
    assert loc[0][2] == ["generate"]                    # 캡 — mm-06 아니라 생성 노드
    gen = [c for c in chain if c[0] == "generate"]
    assert gen and gen[0][3] == planner.LONG_LEASE      # generate 는 종전 그대로


def test_top_folders_from_listing():
    """감시폴더의 실제 하위폴더명 — '그 작품 폴더가 있긴 한가'의 근거."""
    from ves.adapters.register_drive import top_folders
    files = [("a", "참교육/E01.mkv"), ("b", "참교육/E02.mkv"),
             ("c", "김부장/E01.mp4"), ("d", "루트파일.mp4"), ("e", " /x.mp4")]
    assert top_folders(files) == ["김부장", "참교육"]     # 루트 파일·공백뿐인 조각은 제외
    assert top_folders([]) == [] and top_folders(None) == []


def test_drive_excludes_let_batches_make_progress():
    """이미 받은 것을 빼줘야 다음 8G 가 그다음 파일로 간다(B급이 11개에서 멈춘 원인)."""
    from ves.adapters.register_drive import excludes_for, rclone_escape
    known = {"path|FID|01. 시즌1/1화/a.mp4", "path|FID|01. 시즌1/2화/b.mp4",
             "path|OTHER|남의폴더/c.mp4", "drive:legacy-id", "path|FID|"}
    assert excludes_for("FID", known) == ["01. 시즌1/1화/a.mp4", "01. 시즌1/2화/b.mp4"]
    assert excludes_for("FID", set()) == [] and excludes_for("FID", None) == []
    # 글롭 문자가 든 폴더명은 문자 그대로 빠져야 한다 — 아니면 엉뚱한 파일이 제외된다
    assert rclone_escape("[예능] 시즌{1}/a*.mp4") == "\\[예능\\] 시즌\\{1\\}/a\\*.mp4"


def test_overlap_ratio_50_percent_rule():
    """사용자 결정(8/12): '같은 부분을 50% 이상 썼을 때'만 같은 장면으로 본다."""
    from ves.adapters.aivideo import overlap_ratio, spans_overlap, is_duplicate_take
    assert overlap_ratio([0, 60], [0, 60]) == 1.0
    assert overlap_ratio([0, 60], [30, 90]) == 0.5          # 30초 겹침 / 60초
    assert overlap_ratio([0, 60], [31, 91]) < 0.5
    assert overlap_ratio([0, 60], [20, 40]) == 1.0          # 짧은 쪽이 통째로 안에 들어감
    assert overlap_ratio([0, 60], [60, 120]) == 0.0         # 맞닿기만 함
    assert overlap_ratio(None, [0, 10]) == 0.0 and overlap_ratio([0, 10], []) == 0.0
    assert overlap_ratio([10, 10], [10, 10]) == 0.0         # 길이 0 — 0 나눗셈 금지
    # 경계: 정확히 50% 는 '같은 장면'
    assert spans_overlap([0, 60], [30, 90]) and not spans_overlap([0, 60], [31, 91])
    # 짧은 쪽이 통째로 안에 들면 중심 근접 규칙 없이도 중복으로 잡힌다
    assert spans_overlap([0, 100], [45, 55])
    # 반대로 끝만 살짝 스치는 건 이제 '다른 장면' — 종전 중심 규칙이 헛되이 잡던 경우
    assert not spans_overlap([0, 100], [95, 145])
    assert is_duplicate_take([0, 60], [[200, 260], [30, 90]])
    assert not is_duplicate_take([0, 60], [[200, 260]])
    assert not is_duplicate_take([0, 60], [])


def test_reject_stage_plan_and_resume_step():
    """반려 단계 → 어디서부터 다시 돌릴지(0021). 사람이 고른 단계가 자동 선택을 이긴다."""
    from ves.adapters.aivideo import reject_plan, resolve_resume_step
    assert reject_plan("영상 분석")["mode"] == "fresh"
    assert reject_plan("스토리 구성") == {"mode": "resume", "from_step": "story", "eta": "15~25분"}
    assert reject_plan("제작")["from_step"] == "render"
    assert reject_plan("장면")["mode"] == "fresh"            # 0019 유형 호환
    assert reject_plan(None)["mode"] == "fresh"              # 모르면 가장 안전한 쪽
    # 완주한 run 의 체크포인트는 마지막 단계를 가리킨다 — 그걸 따르면 아무것도 다시 안 만든다
    cps = ["checkpoint_story.json", "checkpoint_render.json", "checkpoint_validate.json"]
    assert resolve_resume_step("story", cps) == "story"      # 사람 선택 우선
    assert resolve_resume_step(None, cps) != "story"         # 죽은 잡 이어달리기는 자동 선택
    assert resolve_resume_step(None, [], "render") == "render"


def test_reject_note_reaches_engine_argv():
    """반려 사유가 ai-video 의 --reject-note 로 넘어가야 프롬프트에 주입된다."""
    from ves.adapters.aivideo import build_argv_pure
    base_p = {"work_title": "작품", "source_url": "u"}
    assert "--reject-note" not in build_argv_pure("py", base_p, None)
    argv = build_argv_pure("py", {**base_p, "reject_note": "인물이 잘못 잡혔다"}, None)
    assert argv[argv.index("--reject-note") + 1] == "인물이 잘못 잡혔다"


def test_repin_caps_replaces_not_appends():
    """반려 재실행이 노드를 옮기면 핀도 옮겨가야 한다 — 쌓이면 claim 이 영구 불가."""
    from ves.agent.executor import repin_caps
    # 숏테토칩 WO(08-06) 실측: acquire=mm-01 → 반려 재생성=mm-06 → 두 핀이 공존해 6일 교착
    assert repin_caps(["analyze", "node:mm-01"], "mm-06") == ["analyze", "node:mm-06"]
    assert repin_caps(["analyze", "node:mm-01", "node:mm-06"], "mm-06") == ["analyze", "node:mm-06"]
    # node:* 는 정확히 하나만 남는다(어떤 입력이 와도)
    for caps in ([], None, ["node:mm-03"], ["a", "node:mm-01", "b", "node:mm-02"]):
        out = repin_caps(caps, "mm-04")
        assert [c for c in out if c.startswith("node:")] == ["node:mm-04"]
    # 비-node 캡은 순서대로 보존한다
    assert repin_caps(["network", "analyze"], "mm-01")[:2] == ["network", "analyze"]


# ── Storage 키 ASCII 규약 (스모크3 실측: 한글 키 → 400 InvalidKey) ──
def test_storage_key_ascii_and_shared_convention():
    from ves.adapters.base import storage_key
    k = storage_key("도깨비_10주년_여행_d6", "preview.mp4")
    assert k.isascii() and k.endswith("/preview.mp4") and len(k.split("/")[0]) == 16
    assert k == storage_key("도깨비_10주년_여행_d6", "preview.mp4")   # 결정론
    assert k.split("/")[0] != storage_key("다른_런", "preview.mp4").split("/")[0]


def test_provenance_ok_real_schema():
    """스모크3 실측 스키마: {input,steps,job_id,provenance:{git_sha,config,...}}."""
    from ves.adapters.aivideo import provenance_ok
    real = {"input": {}, "steps": [], "job_id": "도깨비_10주년_여행_d6",
            "provenance": {"git_sha": "af00557d2e74", "config": {"app": {"x": 1}},
                           "prompt_set_hash": "b8a1"}}
    assert provenance_ok(real)
    assert not provenance_ok({"provenance": {"git_sha": "x"}})     # config 스냅샷 없음
    assert not provenance_ok({"provenance": {"config": {"a": 1}}})  # git_sha 없음
    assert not provenance_ok({}) and not provenance_ok(None)
    assert provenance_ok({"provenance_complete": True})             # 레거시 관용


def test_brain_evaluate_argvs():
    from ves.adapters.brain import feature_argv, judge_argv
    f = feature_argv("/py", "/s")
    assert f[:2] == ["/py", "/s/run_feature_extraction.py"] and "--limit" in f
    j = judge_argv("/py", "/s", "clip-uuid", "/out/shorts_1.mp4")
    assert j[1].endswith("run_judge.py") and "--clip-id" in j and "--video" in j
    assert "--video" not in judge_argv("/py", "/s", "clip-uuid", None)


def test_guess_episode_and_drive_plan():
    """드라이브 자동 인입(0013): 회차 추정·작품 하위폴더 규약·기등록 제외."""
    from ves.adapters.base import guess_episode
    assert guess_episode("약한영웅_E01.mp4") == 1 and guess_episode("참교육 3화.mkv") == 3
    assert guess_episode("하트시그널5_제2회.mp4") == 2      # '시즌5' 숫자 오인 금지
    assert guess_episode("finale.mp4") is None
    import unicodedata
    nfd = unicodedata.normalize("NFD", "샤먼미신전_클립마스터_2화.mp4")
    assert guess_episode(nfd) == 2       # NFD 자모 분해형(맥 경유 Drive) — 샤먼 6행 NULL 실측
    from ves.adapters.register_drive import episode_from_path
    assert episode_from_path(unicodedata.normalize("NFD", "샤먼: 미신전/ 3화/클립.mp4")) == 3
    from ves.adapters.register_drive import plan_new
    files = [("f1", "유부녀 킬러/유부녀킬러_E01.mp4"), ("f2", "유부녀 킬러/자막_E01.srt"),
             ("f3", "루트직치기.mp4"), ("f4", "김부장/김부장 2화.mp4"), ("f1", "중복/x.mp4")]
    got = plan_new(files, "external", None, known_ids={"f4"})
    assert got == [("f1", "유부녀 킬러", "유부녀 킬러/유부녀킬러_E01.mp4"),
                   ("f1", "중복", "중복/x.mp4")]            # srt·루트파일·기등록 제외
    single = plan_new([("a", "sub/ep1.mp4")], "single", "참교육", set())
    assert single == [("a", "참교육", "sub/ep1.mp4")]


def test_branding_flags():
    """가이드 자동화(로고): works.json branding 규약 — channel_registry 와 동일 플래그."""
    from ves.adapters.aivideo import branding_flags
    assert branding_flags(None, {"logo_box": "395x280"}) == []           # 카드 없음 → 텍스트
    f = branding_flags({"branding": {"logo": "Vt1NV"}},
                       {"logo_box": "395x280", "logo_align": "center"})
    assert f[:2] == ["--design-work-image", "Vt1NV"]
    assert "--design-work-image-width" in f and "395" in f and "center" in f
    f2 = branding_flags({"branding": {"logo": "x", "box": "100x50", "align": "top"}}, {})
    assert "100" in f2 and "50" in f2 and "top" in f2                    # 카드 예외가 정책보다 우선


def test_editorial_flags():
    """가이드 자동화(편집 지침): works.json editorial 규약 — channel_registry 와 동일 플래그.
    카드에 채운 지침이 argv 에 실리는지 고정 — 경로가 버리면 지침 없이 밤새 발행된다."""
    import json as _json
    from ves.adapters.aivideo import editorial_flags
    assert editorial_flags(None, "작품") == []                            # 카드 없음 → 종전 동일
    assert editorial_flags({"editorial": {"_note": "문서만"}}, "작품") == []
    f = editorial_flags({"editorial": {"avoid": ["경연 결과"], "prefer": ["무대"],
                                       "_note": "문서용"}}, "가왕쇼")
    assert f[0] == "--editorial-json"
    assert _json.loads(f[1]) == {"avoid": ["경연 결과"], "prefer": ["무대"]}  # '_' 키 제외
    import pytest as _pytest
    from ves.adapters import base as _base
    with _pytest.raises(_base.PermanentError):                            # 오타 즉시 실패
        editorial_flags({"editorial": {"avoids": ["x"]}}, "작품")


def test_jp_pipeline_wiring():
    """JP 현지화 배선: 채널→파이프라인, localize argv, 체인 마지막에 localize."""
    from ves.scheduler.planner import job_chain, pipeline_for
    assert pipeline_for({"country": "JP"}) == "shorts_jp_localized"
    assert pipeline_for({"country": "KR"}) == "shorts_kr"
    from ves.adapters.localize import localize_argv
    a = localize_argv("/py", "/v.mp4", "run1", {"content_type": "anime", "backend": "lama"})
    assert a[:4] == ["/py", "-m", "src.process_video", "--video"]
    assert "run1" in a and "anime" in a and "lama" in a
    jp = {"work_title": "혜미리예채파", "channel_slug": "SHOTCONE", "channel_name": "ショトコン",
          "gcp_project": "VES03", "pipeline": "shorts_jp_localized"}
    assert [k for k, *_ in job_chain(jp)][-1] == "localize"


def test_rclone_helpers():
    """rclone 인증 경로(실측 2026-08-10): 원격 파싱·lsjson 매핑·폴더 ID 추출."""
    from ves.adapters.register_drive import first_remote, folder_id_of, lsjson_files
    assert first_remote("gdrive:\n") == "gdrive:" and first_remote("") is None
    # --long 형식: 이름 gdrive 우선 → 없으면 타입 drive → 없으면 첫 원격 (실측 2026-08-10)
    assert first_remote("backup: s3\ngdrive: drive\n") == "gdrive:"
    assert first_remote("backup: s3\nmydrv: drive\n") == "mydrv:"
    assert first_remote("backup: s3\nother: sftp\n") == "backup:"
    assert folder_id_of("https://drive.google.com/drive/folders/"
                        "1nbob1KhTt-x68xKUKb8P8GoHfo2uqKSj?usp=sharing") \
        == "1nbob1KhTt-x68xKUKb8P8GoHfo2uqKSj"
    files = lsjson_files(json.dumps([
        {"Path": "참교육/참교육_E01.mp4", "Name": "참교육_E01.mp4", "ID": "abc123"},
        {"Path": "메모.txt", "Name": "메모.txt"}]))
    assert files[0] == ("abc123", "참교육/참교육_E01.mp4")
    assert len(files) == 2 and files[1][0]                     # ID 없으면 해시 대체
    assert lsjson_files("깨진 json") == []


def test_drive_watch_folder_url():
    from ves.scheduler.drive_watch import folder_url_of
    u = folder_url_of('산문 <a href="https://drive.google.com/drive/folders/'
                      '1nbob1KhTt-x68xKUKb8P8GoHfo2uqKSj?usp=sharing">폴더</a>')
    assert u == "https://drive.google.com/drive/folders/1nbob1KhTt-x68xKUKb8P8GoHfo2uqKSj"
    assert folder_url_of("링크 없음") is None


def test_register_playlist_plan_rows():
    """구 관제 이관: 사멸 항목 스킵·제목 필터(0012) + 영상 단위 회차(0027)."""
    from ves.adapters.register_sources import plan_rows
    entries = [
        {"id": "a1", "title": "[Private video]"},                 # 도깨비 1번 실측
        {"id": "b2", "title": "도깨비 10주년 여행 EP.2"},
        {"id": None, "title": "이상 항목"},
        {"id": "c3", "title": "산지직송 하이라이트"},
    ]
    rows = plan_rows("도깨비 10주년 여행", entries)
    assert [(r["episode"], r["url"]) for r in rows] == [
        (2, "https://www.youtube.com/watch?v=b2"),
        (4, "https://www.youtube.com/watch?v=c3")]     # EP.2 는 파싱, 나머진 위치 서수
    assert [r["episode_source"] for r in rows] == ["parsed", "ordinal"]
    only = plan_rows("언니네 산지직송 in 칼라페", entries, title_filter="산지직송")
    assert len(only) == 1 and only[0]["episode"] == 4
    assert plan_rows("x", None) == []
    # 띄어쓰기 무시 대조 (플릿 실측: '놀라운 토요일' 필터가 '놀라운토요일' 제목을 놓침)
    sp = [{"id": "z9", "title": "[놀라운토요일] 도레미마켓 레전드"}]
    assert len(plan_rows("놀라운 토요일", sp, title_filter="놀라운 토요일")) == 1


def test_plan_rows_per_video_quota_and_shorts_skip():
    """0027: 3분 이하는 등록 제외(번호도 안 줌) · use_limit 은 길이 비례 · 업로드시각 보존."""
    from ves.adapters.register_sources import plan_rows
    entries = [
        {"id": "t", "title": "티저", "duration": 90, "timestamp": 100},      # ≤180s 제외
        {"id": "a", "title": "5화 하이라이트", "duration": 8 * 60, "timestamp": 200},
        {"id": "b", "title": "5화 풀버전", "duration": 40 * 60, "timestamp": 300},
        {"id": "c", "title": "길이 미상", "timestamp": 400},
    ]
    rows = plan_rows("작품", entries)
    assert [r["url"][-1] for r in rows] == ["a", "b", "c"]        # 티저는 행 자체가 없다
    assert [(r["episode"], r["episode_source"]) for r in rows] == [
        (5, "parsed"), (5, "parsed"), (4, "ordinal")]             # 같은 회차 공존 + 서수 폴백
    assert [r["use_limit"] for r in rows] == [1, 3, 3]            # 8분→1 · 40분→3 · 미상→3
    assert [r["published_ts"] for r in rows] == [200.0, 300.0, 400.0]
    # 수동 오버라이드는 길이 규칙을 이긴다
    assert {r["use_limit"] for r in plan_rows("작품", entries, use_limit=2)} == {2}


def test_legacy_pinned_to_source_survives_reorder():
    """0039: 장부에 source_url 이 있으면 정렬이 바뀌어도 그 영상에 소진이 남는다.
    도깨비 1회차 실측 구조 — 레거시는 최장 하이라이트를 썼는데 업로드는 그게 가장 늦다."""
    from ves.scheduler.planner import pick_from_rows
    hi = {"episode": 1, "use_limit": 3, "used_wo": 0,
          "source_url": "https://www.youtube.com/watch?v=RMw9on5u2j0"}   # 레거시가 쓴 것
    a = {"episode": 1, "use_limit": 3, "used_wo": 0,
         "source_url": "https://www.youtube.com/watch?v=Uf5sTr0P5HM"}    # 안 쓴 것
    pinned = [{"episode": 1, "used": 3, "source_url": hi["source_url"]}]
    # 등록 순서(하이라이트가 앞) — 종전에도 맞았다
    assert pick_from_rows([dict(hi), dict(a)], pinned)["source_url"] == a["source_url"]
    # 업로드 순으로 뒤집혀도(안 쓴 것이 앞) 여전히 안 쓴 것을 고른다 ★이게 0039 의 값
    assert pick_from_rows([dict(a), dict(hi)], pinned)["source_url"] == a["source_url"]
    # 못박지 않으면 앞선 행이 차감돼 뒤집힌 순간 엉뚱한 영상이 소진된다(종전 동작)
    loose = [{"episode": 1, "used": 3}]
    assert pick_from_rows([dict(a), dict(hi)], loose)["source_url"] == hi["source_url"]
    # 못박힌 몫이 한도를 넘어도 다른 영상으로 흘러넘치지 않는다
    over = [{"episode": 1, "used": 9, "source_url": hi["source_url"]}]
    assert pick_from_rows([dict(hi), dict(a)], over)["source_url"] == a["source_url"]
    # 못박힌 것과 회차 단위 기록이 섞여 있으면 둘 다 센다
    mixed = [{"episode": 1, "used": 3, "source_url": hi["source_url"]},
             {"episode": 1, "used": 3}]
    assert pick_from_rows([dict(hi), dict(a)], mixed) is None      # 3+3 = 두 영상 다 소진
    assert pick_from_rows([], pinned) is None


def test_episode_trend_reads_list_direction():
    """8/14: --flat-playlist 가 업로드 시각을 안 줘서 URL 추측만 남아 있었다.
    제목의 회차 증감으로 목록 방향을 직접 읽는다(tvN 재생목록은 최신순이었다)."""
    from ves.adapters.register_sources import chronological, episode_trend
    newest_first = [{"id": str(i), "title": f"본편 EP.{n}"} for i, n in enumerate([4, 4, 3, 2, 1, 0])]
    oldest_first = [{"id": str(i), "title": f"본편 EP.{n}"} for i, n in enumerate([0, 1, 2, 2, 3, 4])]
    assert episode_trend(newest_first) == -1     # 뒤집어야 한다
    assert episode_trend(oldest_first) == 1      # 그대로 둔다
    # 재생목록 URL 이라 종전 규칙은 '뒤집지 않음'이었다 — 이제 데이터가 이긴다
    pl = "https://www.youtube.com/playlist?list=PL1"
    assert [e["id"] for e in chronological(newest_first, pl)] == ["5", "4", "3", "2", "1", "0"]
    assert [e["id"] for e in chronological(oldest_first, pl)] == ["0", "1", "2", "3", "4", "5"]
    # 판단 불가일 때는 종전 규칙(URL 모양)으로 돌아간다
    noeps = [{"id": str(i), "title": "회차 없는 제목"} for i in range(6)]
    assert episode_trend(noeps) == 0
    assert [e["id"] for e in chronological(noeps, pl)] == ["0", "1", "2", "3", "4", "5"]
    assert [e["id"] for e in chronological(noeps, "https://youtube.com/@ch/videos")][0] == "5"
    # 표본이 적거나 뒤죽박죽이면 판단하지 않는다
    assert episode_trend([{"id": "a", "title": "EP.1"}, {"id": "b", "title": "EP.2"}]) == 0
    assert episode_trend([{"id": str(i), "title": f"EP.{n}"}
                          for i, n in enumerate([1, 5, 2, 4, 3, 3])]) == 0
    # 업로드 시각이 다 있으면 그게 최우선이다(종전 규칙 유지)
    stamped = [{"id": "new", "title": "EP.9", "timestamp": 200},
               {"id": "old", "title": "EP.1", "timestamp": 100}]
    assert [e["id"] for e in chronological(stamped, pl)] == ["old", "new"]


def test_start_episode_keeps_only_operating_range():
    """0041: 장수 방영작의 운영 시작점 — 놀라운 토요일 410화(재생목록엔 344화부터 있다)."""
    from ves.adapters import base
    from ves.adapters.register_sources import out_of_range, plan_rows, unusable_urls
    rx = base.compile_episode_regex(r"amazingsaturday\s*EP[.\s]?(\d{1,3})\b")
    old = "옛 회차 #amazingsaturday EP.344"
    new = "쓰는 회차 #amazingsaturday EP.410"
    assert out_of_range(old, rx, 410)
    assert not out_of_range(new, rx, 410)
    assert not out_of_range(old, rx, None)          # 미설정이면 아무것도 안 거른다
    # ★회차를 못 읽으면 제외한다 — 서수는 1부터라 시작 회차보다 늘 작아 먼저 뽑힌다
    assert out_of_range("회차 표기 없는 제목", rx, 410)
    assert not out_of_range("회차 표기 없는 제목", rx, None)

    entries = [{"id": "a", "title": old, "duration": 600},
               {"id": "b", "title": new, "duration": 600},
               {"id": "c", "title": "표기 없음", "duration": 600}]
    rows = plan_rows("놀라운 토요일", entries, title_episode_regex=rx, start_episode=410)
    assert [r["url"][-1] for r in rows] == ["b"]              # 410화만 남는다
    assert [r["episode"] for r in rows] == [410]
    # 등록에서 뺀 것과 비활성으로 내리는 것이 같아야 한다(0037 과 같은 규율)
    assert sorted(unusable_urls(entries, None, None, rx, 410)) == [
        "https://www.youtube.com/watch?v=a", "https://www.youtube.com/watch?v=c"]
    # 미설정이면 종전대로 전부 등록된다
    assert len(plan_rows("놀라운 토요일", entries, title_episode_regex=rx)) == 3
    assert unusable_urls(entries, None, None, rx, None) == []


def test_dead_entry_detects_none_title():
    """비공개 항목의 title 은 None 으로 온다(8/13 실측) — 문자열 대조만으로는 못 걸렀다."""
    from ves.adapters.register_sources import is_dead_entry, plan_rows
    assert is_dead_entry({"id": "x", "title": None})              # ← 종전에 통과하던 구멍
    assert is_dead_entry({"id": "x", "title": "[Private video]"})
    assert is_dead_entry({"id": "x", "title": "[Deleted video]"})
    assert is_dead_entry(None)
    assert not is_dead_entry({"id": "x", "title": "1화 하이라이트"})
    # 사멸 항목은 등록 행이 되지 않는다 — 길이도 None 이라 3분 규칙으로는 안 걸린다
    rows = plan_rows("작품", [{"id": "p", "title": None},
                             {"id": "a", "title": "1화", "duration": 600}])
    assert [r["url"][-1] for r in rows] == ["a"]


def test_unusable_urls_for_deactivation():
    """0027 이전 등록분 정리용 — 사멸·하한 이하만 고른다(필터 제외분은 남의 작품일 수 있다)."""
    from ves.adapters.register_sources import unusable_urls
    entries = [
        {"id": "dead", "title": None},                            # 비공개
        {"id": "short", "title": "예고", "duration": 68},          # 기본 하한(180) 이하
        {"id": "ok", "title": "1화", "duration": 600},             # 정상 — 건드리지 않는다
        {"id": "unknown", "title": "길이 미상"},                    # 미상은 판단 보류
        {"title": "id 없음", "duration": 10},                      # id 없으면 URL 을 못 만든다
    ]
    assert unusable_urls(entries) == ["https://www.youtube.com/watch?v=dead",
                                      "https://www.youtube.com/watch?v=short"]
    assert unusable_urls(None) == []
    # 작품별 하한(0031)을 올리면 그 아래가 함께 내려간다 — plan_rows 가 등록에서 빼는
    # 기준(base.is_usable)과 같은 규칙이라야 매 실행마다 등록·해제가 오가지 않는다
    assert unusable_urls(entries, 900) == ["https://www.youtube.com/watch?v=dead",
                                           "https://www.youtube.com/watch?v=short",
                                           "https://www.youtube.com/watch?v=ok"]


def test_title_exclude_pattern_drops_promos_only():
    """0037: 예고·선공개·티저는 빼고 본편·미방분은 남긴다 (8/14 실제 제목으로 대조)."""
    from ves.adapters.base import compile_exclude_regex, title_excluded
    rx = compile_exclude_regex(r"\[(?:[^\]]*\s)?(?:예고|선공개|티저|하이라이트)\]")
    for t in ["[4화 예고] 윷놀이부터 자전거 타기에", "[최종회 예고] 도파민 집라인부터",
              "[3회 선공개] 제1회 밥상예술대상", "[1차 티저] 모두 지쳤나요",
              "[하이라이트] 이게 어떻게 휴가야"]:
        assert title_excluded(t, rx), t
    for t in ["[3회 미방분] 건강파 정아 VS 자극파 준면",      # 미방분은 쓴다(운영 결정)
              "왔다 내 밥 친구 #highlight #언니네산지직송",   # 해시태그 highlight = 본편
              "윷놀이 하고, 자전거 타고 #highlight #도깨비10주년여행 EP.4"]:
        assert not title_excluded(t, rx), t
    # NFD(자모 분해형) 제목도 걸러야 한다 — 맥 경유 제목이 그렇게 온다
    import unicodedata
    assert title_excluded(unicodedata.normalize("NFD", "[2회 예고] 노동 끝"), rx)
    # 미지정이면 아무것도 안 거른다 · 어떤 입력에도 죽지 않는다
    assert compile_exclude_regex("") is None
    assert not title_excluded("[3회 예고] …", None)
    assert not title_excluded(None, rx)


def test_exclude_regex_syntax_error_is_permanent():
    """깨진 제외 패턴은 항목을 돌기 전에 끊는다 — transient 로 흘리면 무한 재시도가 된다."""
    import pytest
    from ves.adapters import base
    from ves.adapters.register_sources import plan_rows
    with pytest.raises(base.PermanentError):
        base.compile_exclude_regex(r"\[(?:예고")
    with pytest.raises(base.PermanentError):
        plan_rows("작품", [{"id": "a", "title": "1화", "duration": 600}],
                  title_exclude_regex=r"[예고")
    # 캡처그룹은 요구하지 않는다(회차 정규식과 다른 점)
    assert base.compile_exclude_regex(r"\[예고\]") is not None


def test_plan_rows_and_unusable_share_exclude_rule():
    """등록에서 뺀 것과 비활성으로 내리는 것이 같아야 한다 — 어긋나면 매 실행마다 오간다."""
    from ves.adapters.register_sources import plan_rows, unusable_urls
    entries = [
        {"id": "a", "title": "본편 하이라이트 #highlight", "duration": 900},
        {"id": "b", "title": "[3화 예고] 다음 주에", "duration": 900},   # 길이는 충분하나 예고
        {"id": "c", "title": "[3회 미방분] 남은 이야기", "duration": 900},
    ]
    rx = r"\[(?:[^\]]*\s)?(?:예고|선공개|티저)\]"
    rows = plan_rows("작품", entries, title_exclude_regex=rx)
    assert [r["url"][-1] for r in rows] == ["a", "c"]          # 예고만 빠진다
    assert unusable_urls(entries, None, __import__("re").compile(rx)) == [
        "https://www.youtube.com/watch?v=b"]                    # 같은 항목만 내려간다


def test_summarize_episodes_speaks_korean():
    """등록 결과 요약(0028) — 대시보드 작업내역에서 정규식 문제를 바로 알아채게."""
    from ves.adapters.register_sources import summarize_episodes
    rows = [{"episode_source": "parsed"}, {"episode_source": "parsed"},
            {"episode_source": "ordinal"}]
    parsed, ordinal, note = summarize_episodes(rows)
    assert (parsed, ordinal) == (2, 1)
    assert "제목에서 읽음 2개" in note and "순번 폴백 1개" in note
    assert "설명란에 회차를 적지 않습니다" in note      # 폴백의 의미를 그 자리에서 설명
    p, o, note = summarize_episodes([])
    assert (p, o) == (0, 0) and "설명란" not in note   # 폴백 0개면 경고문 없음


def test_guess_episode_title():
    """제목 → 원본 방송 회차. 확장자 절단 없음('EP.410' 보호) · 작품별 정규식 우선."""
    from ves.adapters.base import guess_episode_title
    assert guess_episode_title("놀라운 토요일 EP.410 레전드") == 410
    assert guess_episode_title("언더커버셰프 12화 풀버전") == 12
    assert guess_episode_title("하트시그널5 제2회") == 2         # '시즌5' 오인 금지
    assert guess_episode_title("도레미마켓 레전드 모음") is None
    assert guess_episode_title("놀토 [410-2]", regex=r"\[(\d+)-\d+\]") == 410
    assert guess_episode_title("놀토 스페셜", regex=r"\[(\d+)-\d+\]") is None  # 정규식 지정 시 그것만
    import unicodedata
    assert guess_episode_title(unicodedata.normalize("NFD", "샤먼 3화")) == 3  # NFD 제목


def test_pick_from_rows_per_row_and_legacy():
    """0027: 행 단위 소진 + 회차 단위 레거시를 앞선 행부터 차감."""
    from ves.scheduler.planner import pick_from_rows
    # 같은 회차 두 행 — A(한도1) 소진이어도 B(한도3)는 살아 있다
    rows = [{"episode": 5, "use_limit": 1, "used_wo": 1, "id": "A"},
            {"episode": 5, "use_limit": 3, "used_wo": 0, "id": "B"}]
    assert pick_from_rows(rows)["id"] == "B"
    # 레거시 3(회차 단위)은 앞선 행부터 차감: A 남은 0 → B 가 3 전부 흡수해 소진 → 6화로
    rows = [{"episode": 5, "use_limit": 1, "used_wo": 1, "id": "A"},
            {"episode": 5, "use_limit": 3, "used_wo": 0, "id": "B"},
            {"episode": 6, "use_limit": 3, "used_wo": 0, "id": "C"}]
    assert pick_from_rows(rows, [{"episode": 5, "used": 3}])["id"] == "C"
    # 회차에 행이 하나면 종전 동작 그대로 — 레거시 2 + WO 0 < 3 → 그 행
    rows = [{"episode": 3, "use_limit": 3, "used_wo": 0, "id": "D"}]
    assert pick_from_rows(rows, [{"episode": 3, "used": 2}])["id"] == "D"
    assert pick_from_rows(rows, [{"episode": 3, "used": 3}]) is None
    assert pick_from_rows([], []) is None


def test_storage_4xx_permanent_except_429():
    from ves.adapters.upload_artifacts import _is_permanent_storage_error
    assert _is_permanent_storage_error('storage upload 400: {"error":"InvalidKey"}')
    assert _is_permanent_storage_error("storage upload 404: not found")
    assert not _is_permanent_storage_error("storage upload 429: rate limited")
    assert not _is_permanent_storage_error("storage upload 544: DatabaseTimeout")
    assert not _is_permanent_storage_error("Connection reset by peer")


# ── 0024: 관제 '작업 실행' + 소스 소진 수정 (사용자 요청 8/12) ──
def _mig(name):
    import pathlib
    return pathlib.Path("ves/control/migrations", name).read_text(encoding="utf-8")


def _live_mig(ddl: str):
    """그 객체를 **마지막으로** 재정의한 마이그레이션 텍스트. 파일명이 NNNN_ 로
    시작하므로 정렬의 마지막이 곧 라이브 정의다.

    🛑 가드가 폐기된 파일을 붙들고 초록불을 내는 사고를 막는다. 0027 이
    run_channel_now 를 통째로 다시 쓰며 priority 150 · 멱등키 'manual:' 접두사 ·
    반환 'channel' 키를 흘렸는데, 0024 를 고정으로 읽던 가드는 그대로 통과했다
    (0029 로 복구). 재정의되는 객체를 검사할 때는 이 헬퍼를 쓸 것.

    ⚠ ddl 은 **정의 구문 전체**를 넘긴다("CREATE OR REPLACE FUNCTION public.X").
      함수 이름만 넘기면 REVOKE/GRANT 같은 단순 언급에도 걸려 엉뚱한 파일을 집는다
      — 0029 의 anon 권한 회수 줄이 실제로 그렇게 잡혔다."""
    import pathlib
    d = pathlib.Path("ves/control/migrations")
    hits = sorted(p for p in d.glob("*.sql") if ddl in p.read_text(encoding="utf-8"))
    assert hits, f"'{ddl}' 를 정의하는 마이그레이션이 없다"
    return hits[-1].read_text(encoding="utf-8")


def test_planner_keeps_daily_idempotence_without_on_conflict():
    """0024 부터 유일 제약이 origin='planner' 부분 인덱스다 — ON CONFLICT (4컬럼) 은
    그 인덱스를 추론하지 못한다. 존재 검사로 바뀌었는지, origin 을 박는지 본다."""
    import inspect
    from ves.scheduler import planner
    src = inspect.getsource(planner._create_work_order)
    wo_insert = src.split("job_queue", 1)[0]      # 잡 큐 쪽 ON CONFLICT(멱등키)는 그대로 쓴다
    assert "ON CONFLICT (service_date" not in src, "부분 유니크 인덱스는 ON CONFLICT 추론 불가"
    assert "NOT EXISTS" in wo_insert
    assert "'planner'" in wo_insert and "w.origin" in wo_insert


def test_channels_sync_mirrors_country_and_pipeline():
    """run_channel_now 가 SQL 안에서 파이프라인을 판정하려면 미러에 두 컬럼이 있어야 한다."""
    import inspect
    from ves.scheduler import channels_sync
    sql = inspect.getsource(channels_sync.run)
    assert "country" in sql and "pipeline" in sql
    assert 'r.get("country")' in sql and 'r.get("pipeline")' in sql


def test_manual_run_chain_matches_planner():
    """관제 '작업 실행'의 잡 체인이 planner.job_chain 과 어긋나면 같은 일을 두 곳에서
    다르게 만들게 된다 — 캡이 틀리면 산출물 없는 맥에서 즉사하고, lease 가 짧으면
    reaper 가 산 잡을 회수한다(8/12 현지화 무한반복 사고).

    ★ run_channel_now 를 **마지막으로 재정의한** 마이그레이션을 본다. 0024 를 고정으로
      읽던 종전 판은 0027 이 그 함수를 다시 쓰며 흘린 것들을 못 잡았다(_live_mig 주석)."""
    import re
    from ves.scheduler import planner
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.run_channel_now")
    chain = planner.job_chain({"work_title": "W", "episode": 1, "channel_slug": "S",
                               "channel_name": "N", "pipeline": "shorts_jp_localized"})
    assert [k for k, *_ in chain] == ["acquire", "generate", "upload_artifacts",
                                      "ingest", "evaluate", "localize"]
    body = re.sub(r"\s+", " ", sql.split("FOR v_step IN", 1)[1].split(") AS t(kind", 1)[0])
    for i, (kind, _p, caps, ttl) in enumerate(chain, start=1):
        pat = ("'" + re.escape(kind) + r"'(?:::text)?.*?ARRAY\["
               + ", ".join("'" + c + "'" for c in caps)
               + r"\](?:::text\[\])?, *" + str(ttl) + r"(?:::int)?, *" + str(i) + r"(?:::int)?\)")
        assert re.search(pat, body), f"{kind} 체인이 라이브 SQL 과 다르다"
    # KR 채널은 localize 가 빠져야 한다
    assert "t.kind <> 'localize' OR v_pipe = 'shorts_jp_localized'" in sql
    # 사람이 눌러 기다리는 일 — claim 은 priority DESC 라 100 보다 커야 앞선다
    assert re.search(r"v_step\.ttl,\s*\n?\s*150\)", sql)
    # 잡 큐에서 planner/manual 을 구분하는 멱등키 접두사
    assert "'manual:' ||" in sql
    # 대시보드 작업 실행 성공 토스트가 읽는 키 — 빠지면 "undefined" 가 뜬다
    assert "'channel', v_ch.name" in sql
    # scene_rerender 컷오버(0031) — localize 는 mode 하나로 라우팅된다
    assert "'mode', 'scene_rerender'" in sql
    # 등급 J 플래그가 되살아나면 generate 가 내용만 만들고 재렌더 원료가 빈다
    for flag in ("no_tts_subtitles", "no_title_overlay", "no_tts_audio"):
        assert flag not in sql, f"등급 J 플래그 {flag} 가 남아 있다(0031 이후 금지)"


def test_legacy_waterfall_matches_between_python_and_sql():
    """레거시(회차 단위)를 앞선 행부터 차감하는 규칙이 planner 와 SQL 에서 같아야 한다.

    0027 의 SQL 은 앞 행의 **한도 합**을 뺐는데 pick_from_rows 는 앞 행이 실제로 흡수한
    **남은 여유 합**만 뺀다. SQL 이 늘 더 느슨해 회차 총한도를 넘겨 한 편 더 만들었다
    (0029 에서 free_before 로 교정). 아래 두 반례는 종전 SQL 만 통과시켰다."""
    from ves.scheduler.planner import pick_from_rows
    # ① 앞 행에 이미 발주가 물려 레거시를 다 흡수하지 못한다
    rows = [{"episode": 5, "use_limit": 2, "used_wo": 1, "id": "A"},
            {"episode": 5, "use_limit": 1, "used_wo": 0, "id": "B"}]
    assert pick_from_rows(rows, [{"episode": 5, "used": 2}]) is None
    # ② 앞 행이 완전히 소진 — 여유 0 이라 레거시가 그대로 뒤로 넘어온다
    rows2 = [{"episode": 5, "use_limit": 3, "used_wo": 3, "id": "A"},
             {"episode": 5, "use_limit": 2, "used_wo": 0, "id": "B"}]
    assert pick_from_rows(rows2, [{"episode": 5, "used": 3}]) is None
    # SQL 도 '여유' 누적이어야 한다 — '한도' 누적(limit_before)이면 위 두 건을 통과시킨다
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.run_channel_now")
    assert "GREATEST(b.use_limit - b.used_wo, 0)" in sql, "free_before 가 여유 누적이 아니다"
    assert "GREATEST(r.legacy_ep - r.free_before, 0)" in sql
    assert "AS limit_before" not in sql, "0027 의 한도 합 방식이 남아 있다"


def test_source_edit_rpcs_are_episode_scoped():
    """레거시 장부(source_usage_legacy)는 (작품·채널·회차) PK 라 구조가 회차 단위다 —
    set_source_used 는 그대로 회차로 건다.
    ⚠ set_source_limit 은 0027 이 행 단위로 뒤집었다(같은 회차의 다른 영상 한도까지
      바뀌면 안 된다). 그쪽은 test_set_source_limit_touches_only_chosen_row 가 본다."""
    used = _live_mig("CREATE OR REPLACE FUNCTION public.set_source_used") \
        .split("FUNCTION public.set_source_used", 1)[1].split("$$;", 1)[0]
    assert "l.episode IS NOT DISTINCT FROM v_s.episode" in used
    assert "p_used < v_wo" in used            # 발주 기록 아래로는 못 내린다(이중장부 방지)
    assert "DELETE FROM public.source_usage_legacy" in used   # 0 이면 보정 행을 지운다


def test_migration_0024_restores_view_security():
    """0022 의 CREATE OR REPLACE VIEW 가 security_invoker 를 날려 anon 이 소스 창고를
    통째로 읽고 있었다(실측 248행). anon key 는 대시보드에 박힌 공개값이다."""
    sql = _mig("0024_manual_run_and_source_edit.sql")
    for v in ("source_usage", "source_usage_by_channel"):
        assert f"ALTER VIEW public.{v}" in sql and "security_invoker = true" in sql
        assert f"REVOKE ALL ON public.{v}" in sql
    assert "GRANT SELECT ON public.source_usage_by_channel TO authenticated" in sql


# ── 0025: Gemini 예비 키 슬롯 (429 는 rate limit 이 아니라 결제 상한이었다, 8/12) ──
def test_account_exhausted_vs_rate_limit():
    """예비 키는 '기다려도 안 풀리는' 계정 소진일 때만 태운다. 분당 초과는 기다리면 풀린다."""
    from ves.agent.gemini_key import is_account_exhausted as ex
    spend = ("google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, "
             "'message': 'Your billing account has exceeded its monthly spending cap. "
             "Please go to AI Studio at https://ai.studio/billing to manage your billing.'}}")
    assert ex(spend)                                            # 8/12 실측 원문
    assert ex("429 You exceeded your current quota, please check your plan and billing details")
    # 분당 rate limit — 넘기지 않는다(백업 계정을 공짜로 태우지 않는다)
    assert not ex("429 RESOURCE_EXHAUSTED: Quota exceeded for quota metric "
                  "'Generate requests per minute'. Retry in 31s")
    assert not ex("500 internal error") and not ex("") and not ex(None)


def test_gemini_apply_is_noop_on_primary():
    """평상시(주 키)에는 env 를 한 글자도 건드리지 않는다 — None 도 None 그대로."""
    from ves.agent import gemini_key as g
    base = {"GEMINI_API_KEY": "K1", "GEMINI_API_KEY_FALLBACK": "K2"}
    env = {"GEMINI_API_KEY": "K1", "X": "1"}
    assert g.apply(env, g.PRIMARY, base=base) is env
    assert g.apply(None, g.PRIMARY, base=base) is None
    assert g.apply(env, "이상한값", base=base) is env


def test_gemini_apply_swaps_only_when_fallback_exists():
    from ves.agent import gemini_key as g
    base = {"GEMINI_API_KEY": "K1", "GEMINI_API_KEY_FALLBACK": "K2"}
    out = g.apply({"GEMINI_API_KEY": "K1", "X": "1"}, g.FALLBACK, base=base)
    assert out["GEMINI_API_KEY"] == "K2" and out["X"] == "1"
    assert "GOOGLE_API_KEY" not in out          # 없던 이름을 새로 만들지 않는다
    # GOOGLE_API_KEY 가 이미 있으면 같이 갈아끼운다(google-genai 는 둘 다 본다)
    out2 = g.apply({"GEMINI_API_KEY": "K1", "GOOGLE_API_KEY": "K1"}, g.FALLBACK, base=base)
    assert out2["GOOGLE_API_KEY"] == "K2"
    # 예비 키가 없는 맥 — 종전대로 주 키로 돈다(조용히 무키가 되지 않는다)
    nofb = {"GEMINI_API_KEY": "K1"}
    env = {"GEMINI_API_KEY": "K1"}
    assert g.apply(env, g.FALLBACK, base=nofb) is env
    assert g.available_slots(nofb) == ["primary"]
    assert g.available_slots(base) == ["primary", "fallback"]
    assert g.available_slots({"GEMINI_API_KEY_FALLBACK": "  "}) == []   # 공백은 없는 것


def test_executor_applies_slot_and_fails_over():
    """두 배선이 executor 한 곳에 있어야 ai-video·brain 이 함께 덮인다."""
    import inspect
    from ves.agent import executor
    run = inspect.getsource(executor._run_subprocess)
    assert "gemini_key.apply(env, gemini_key.active(conn))" in run
    src = inspect.getsource(executor.run_job)
    assert "gemini_key.failover(conn, cfg, str(e))" in src
    assert src.index("gemini_key.failover") < src.index('lease.fail(conn, job, str(e), "quota"')


def test_migration_0025_switch_requeues_waiters():
    """키를 갈아끼우고 run_after 를 안 당기면 전환 효과가 최대 한 시간 뒤에 나온다."""
    sql = _mig("0025_gemini_key_slot.sql")
    fn = sql.split("FUNCTION public.set_gemini_key", 1)[1].split("$$;", 1)[0]
    assert "p_slot NOT IN ('primary','fallback')" in fn
    assert "has_role(auth.uid(),'operator')" in fn
    assert "run_after = now()" in fn and "error_class = 'quota'" in fn
    # 키 값 자체는 DB 에 절대 넣지 않는다(ARCHITECTURE §5) — 슬롯 이름만 오간다
    assert "GEMINI_API_KEY=" not in sql


# ── 0026: 잔망루피 검수함 승인 → 업로드 (사용자 요청 8/12) ──
def test_loopy_decision_plan_is_idempotent():
    """같은 결정을 두 번 눌러도, 잡이 중간에 죽어 재시도돼도 안전해야 한다.
    특히 uploaded 재업로드는 절대 금지 — 같은 영상이 두 번 올라간다."""
    from ves.adapters.zanmang_decision import plan
    assert plan("pending_approval", "publish") == ["approve", "upload"]
    assert plan("approved", "publish") == ["upload"]      # 패키지는 있다 — 업로드만
    assert plan("uploaded", "publish") == []              # 재업로드 금지
    assert plan("pending_approval", "skip") == ["mark"]
    assert plan("skipped", "skip") == [] and plan("uploaded", "skip") == []
    assert plan("processing", "publish") == []            # 손대지 않는다
    import pytest
    with pytest.raises(Exception):
        plan("pending_approval", "이상한결정")


def test_loopy_action_argv_is_whitelisted():
    """사람 결정을 원장에 쓰는 명령이라 허용 목록을 좁게 둔다."""
    from ves.adapters import zanmang
    import pytest
    assert zanmang.action_argv("/r", "approve", "v1")[1:] == ["-m", "src.autopilot", "approve", "v1"]
    assert zanmang.action_argv("/r", "mark", "v1", state="skipped")[-2:] == ["--state", "skipped"]
    for bad in ("daily", "rm", "upload; rm -rf /"):
        with pytest.raises(Exception):
            zanmang.action_argv("/r", bad, "v1")
    with pytest.raises(Exception):
        zanmang.action_argv("/r", "mark", "v1", state="uploaded")   # 허용 state 밖
    with pytest.raises(Exception):
        zanmang.action_argv("/r", "approve", "")                    # video_id 필수


def test_loopy_final_video_matches_upstream_routes():
    """src/autopilot.py final_video_for 와 같은 규약 — 어긋나면 검수 프리뷰가 빈다."""
    import pathlib, tempfile
    from ves.adapters.zanmang import final_video, FINAL_BY_ROUTE
    assert FINAL_BY_ROUTE["B"] == ["final_draft.mp4"]
    assert FINAL_BY_ROUTE["C"][0] == "final_dubbed_subbed.mp4"
    with tempfile.TemporaryDirectory() as d:
        assert final_video("B", d) is None                  # 아직 산출 전
        (pathlib.Path(d) / "final_draft.mp4").write_text("x")
        assert final_video("B", d).endswith("final_draft.mp4")
        assert final_video("A", d) is None                  # 무변환 — 원본을 쓴다
        assert final_video(None, d) is None
        # BJ(병기) = final_draft.mp4 — 지도에 없으면 검수 카드 프리뷰가 빈다(8/14 실측)
        assert final_video("BJ", d).endswith("final_draft.mp4")


def test_loopy_parse_youtube_url():
    from ves.adapters.zanmang_decision import parse_youtube_url
    assert parse_youtube_url("업로드 완료: https://youtu.be/aB3_x-9Q (예약 공개 …)") \
        == "https://youtu.be/aB3_x-9Q"
    assert parse_youtube_url("아무것도 없음") is None and parse_youtube_url(None) is None


def test_migration_0026_decide_loopy():
    sql = _mig("0026_loopy_review.sql")
    fn = sql.split("FUNCTION public.decide_loopy", 1)[1].split("$$;", 1)[0]
    assert "has_role(auth.uid(),'reviewer')" in fn
    assert "kind = 'localization_qa'" in fn and "status = 'waiting'" in fn
    assert "zanmang_video_id" in fn
    # 반려도 잡을 만들어야 한다 — skipped 로 안 찍으면 다음 daily 가 같은 건을 또 올린다
    assert "'skip'" in fn and "zanmang_decision" in fn
    assert "'node:' || v_node" in fn          # mm-06 전용(원장·토큰·가중치가 거기 있다)
    assert "ON CONFLICT (idempotency_key) DO UPDATE" in fn   # 두 번 눌러도 안전


def test_localize_level_per_channel():
    """오디오 현지화 여부가 채널마다 다르다(사용자 결정 8/12):
    ショトコン은 오디오 현지화 불필요(B — 번인 제거+자막), 잔망루피는 전부 현지화(C — 더빙).
    종전엔 전 JP 채널이 B 하드코딩이라 루피만 따로 줄 방법이 없었다."""
    from ves.scheduler.planner import job_chain, localize_level_for
    lv = {"SHOTCONE": "BJ", "LOOPY": "C"}
    assert localize_level_for("SHOTCONE", lv) == "BJ"   # 번인 유지 + 일본어 병기
    assert localize_level_for("LOOPY", lv) == "C"
    assert localize_level_for("SHOTCONE", {"SHOTCONE": "c"}) == "C"       # 대소문자 무관
    assert localize_level_for("모르는채널", lv) == "B"                     # 기본 B
    assert localize_level_for("X", {"X": "더빙"}) == "B"                   # 이상값 → 안전측
    assert localize_level_for("X", None) == "B" and localize_level_for("X", {}) == "B"
    # scene_rerender 컷오버(8/13): planner 체인의 localize 는 등급이 아니라 mode 다.
    # 등급은 zanmang_daily 등 완성-mp4 경로(어댑터 레거시)에만 남는다.
    wo = {"work_title": "혜미리예채파", "episode": 5, "channel_slug": "SHOTCONE",
          "channel_name": "ショトコン", "pipeline": "shorts_jp_localized",
          "localize_level": "B"}
    loc = dict((k, p) for k, p, *_ in job_chain(wo))["localize"]
    assert loc["mode"] == "scene_rerender" and "level" not in loc
    # 등급 설정이 없어도 체인은 동일 — mode 하나로 정해진다
    assert dict((k, p) for k, p, *_ in job_chain({**wo, "localize_level": None}))["localize"]["mode"] == "scene_rerender"


# ── 8/13: 채널별 인페인트 백엔드·더빙 목소리 + VES 경로 더빙 배선 ──
def test_localize_params_carry_backend_and_voice():
    """scene_rerender 컷오버(8/13): planner 체인은 backend/voice_id 를 싣지 않는다 —
    재렌더 엔진이 자기 config 로 정한다. 등급 설정이 있어도 mode 가 이긴다
    (level 이 섞여 들어가면 어댑터가 완성-mp4 경로로 오라우팅될 수 있다)."""
    from ves.scheduler.planner import job_chain
    wo = {"work_title": "혜미리예채파", "episode": 2, "channel_slug": "SHOTCONE",
          "channel_name": "ショトコン", "pipeline": "shorts_jp_localized",
          "localize_level": "C", "localize_backend": "opencv", "localize_voice": "V123"}
    loc = dict((k, p) for k, p, *_ in job_chain(wo))["localize"]
    assert loc["mode"] == "scene_rerender"
    assert "level" not in loc and "backend" not in loc and "voice_id" not in loc


def test_localize_runs_dub_only_for_dubbing_levels():
    """process_video 는 더빙을 안 한다(그 스크립트 머리말 명시). VES 경로엔 그 배선이
    없어서 등급 C 를 줘도 오디오가 한국어 그대로였다(8/12 사용자 지적)."""
    from ves.adapters.localize import needs_dub
    assert needs_dub("C") and needs_dub("BC") and needs_dub("c")
    assert not needs_dub("B") and not needs_dub("BJ") and not needs_dub("A")
    assert not needs_dub(None) and not needs_dub("")


def test_dub_argv_requires_voice():
    """목소리를 안 실으면 dub 이 전역 config 로 떨어지는데 그 값은 잔망루피 클론 보이스다.
    다른 채널이 루피 목소리로 더빙돼 나가는 사고를 막는다."""
    import pytest
    from ves.adapters.localize import dub_argv
    argv = dub_argv("/py", "/v.mp4", "run1", "VOICE9")
    assert argv[1:] == ["-m", "src.dub", "--video-id=run1", "--video=/v.mp4",
                        "--level=C", "--voice=VOICE9"]
    assert dub_argv("/py", "/v.mp4", "r", "V", config_path="/c.yaml")[-1] == "--config=/c.yaml"
    for bad in (None, "", "   "):
        with pytest.raises(Exception):
            dub_argv("/py", "/v.mp4", "r", bad)


# ── 8/13 심야: 등급 J — JP 변환은 vlp(convert_short)가 담당, ai-video 무변경 ──
def test_level_j_uses_convert_not_process_video():
    """J 는 process_video(화면 지우기)를 타면 안 된다 — 사용자 결정: 한글을 지우는 게
    아니라 edit_plan 원문을 일본어로 재렌더한다. 더빙도 convert_short 안에서 나레이션
    구간만 한다(전체 더빙 아님)."""
    import inspect
    from ves.adapters import localize
    from ves.scheduler.planner import localize_level_for
    assert localize.is_jp_convert("J") and not localize.is_jp_convert("B")
    assert localize_level_for("SHOTCONE", {"SHOTCONE": "J"}) == "J"
    argv = localize.convert_argv("/py", "/v.mp4", "/plan.json", "/out.mp4", "V9")
    assert argv[1:4] == ["-m", "src.convert_short", "--video=/v.mp4"]
    import pytest
    with pytest.raises(Exception):
        localize.convert_argv("/py", "/v", "/p", "/o", None)   # 목소리 없으면 거부
    src = inspect.getsource(localize.run)
    assert "is_jp_convert" in src and "edit_plan.json" in src
    # J 는 needs_dub(별도 dub 단계) 대상이 아니다 — convert 안에서 끝낸다
    assert not localize.needs_dub("J")


def test_upload_artifacts_ships_edit_plan():
    """edit_plan 이 스토리지에 없으면 mm-06 의 vlp 가 JP 변환 원료를 못 받는다."""
    import inspect
    from ves.adapters import upload_artifacts
    src = inspect.getsource(upload_artifacts.run)
    assert '"edit_plan.json"' in src and '"run_log.json"' in src


def test_level_j_generates_without_text_overlays():
    """scene_rerender 컷오버(8/13): planner 는 더 이상 등급 J 의 '내용만 생성' 플래그를
    발행하지 않는다 — 재렌더가 체크포인트에서 일본어판을 새로 그리므로 generate 는
    완전 렌더다. 어댑터의 플래그 매핑 능력은 남는다(과도기 수동 체인·롤백 대비)."""
    from ves.adapters.aivideo import build_argv_pure
    from ves.scheduler.planner import job_chain
    wo = {"work_title": "혜미리예채파", "episode": 3, "channel_slug": "SHOTCONE",
          "channel_name": "ショトコン", "pipeline": "shorts_jp_localized",
          "localize_level": "J", "has_subtitle": True}
    gen = dict((k, p) for k, p, *_ in job_chain(wo))["generate"]
    assert gen["no_subtitles"] is False                 # has_subtitle=True → 자막 켬(완전 렌더)
    for k in ("no_tts_subtitles", "no_title_overlay", "no_tts_audio"):
        assert k not in gen, f"planner 가 {k} 를 다시 발행한다(컷오버 위반)"
    # 어댑터는 params 에 실려오면 여전히 CLI 로 넘긴다 — 수동 J 체인 호환
    argv = build_argv_pure("/py", {**gen, "no_tts_subtitles": True,
                                   "no_title_overlay": True, "no_tts_audio": True},
                           "/cache/x")
    assert "--no-tts-subtitles" in argv and "--no-title-overlay" in argv \
        and "--no-tts-audio" in argv
    kr = dict((k, p) for k, p, *_ in job_chain(
        {**wo, "pipeline": "shorts_kr", "localize_level": None}))["generate"]
    assert "no_tts_subtitles" not in kr and kr["no_subtitles"] is False


# ── 8/13: 대용량 마스터 TUS 업로드 (피의 게임 X 413 전멸 실측) ──
def test_large_upload_routes_to_tus():
    """표준 POST 는 5GB 게이트웨이 하드캡 — 4.73GB 까지만 실증됐다. 그 위는 TUS."""
    from ves.storage.supabase_storage import TUS_CHUNK, use_tus
    assert not use_tus(25_000_000)            # shorts — 종전 경로 유지
    assert not use_tus(4_400_000_000)         # 실증 범위 안 — 종전 경로 유지
    assert use_tus(4_600_000_000) and use_tus(9_000_000_000)
    assert not use_tus(None) and not use_tus("x")
    assert TUS_CHUNK == 6 * 1024 * 1024       # Supabase TUS 계약: 6MB 고정 청크


def test_tus_metadata_encoding():
    import base64
    from ves.storage.supabase_storage import tus_metadata
    md = tus_metadata("ves-sources", "masters/abc123")
    # 구분자는 반드시 ","(공백 없음) — ", " 는 Supabase 400 Invalid upload-metadata (8/13 실측)
    parts = dict(kv.split(" ", 1) for kv in md.split(","))
    assert base64.b64decode(parts["bucketName"]).decode() == "ves-sources"
    assert base64.b64decode(parts["objectName"]).decode() == "masters/abc123"
    assert base64.b64decode(parts["contentType"]).decode() == "application/octet-stream"
    # upsert 는 메타데이터에 있어야 한다(8/15) — 없으면 재시도가 기존 객체에 409 로 막힌다
    assert base64.b64decode(parts["upsert"]).decode() == "true"


def test_413_is_permanent():
    """413 은 기다려도 안 풀린다 — transient 로 attempt 를 태우고 GB 재다운로드하던 것 차단."""
    from ves.adapters.base import classify_by_patterns
    assert classify_by_patterns("EP03: storage upload 413: <html> 413 Payload Too Large") \
        == "permanent"
    assert classify_by_patterns("storage upload 502: Bad Gateway") == "transient"  # 이건 재시도


def test_localize_run_has_no_unbound_r():
    """8/13 실측: 등급 J 경로는 r(process_video 결과)이 정의되지 않는데 검수 등록부가
    r.stdout 을 참조해 — 변환이 다 끝나고도 UnboundLocalError 로 잡이 죽었다.
    두 분기 모두 note_tail 로 수렴하는지 소스로 고정한다."""
    import inspect
    from ves.adapters import localize
    src = inspect.getsource(localize.run)
    import re
    tail = src.split("# 더빙(TTS 일본어)", 1)[1]
    assert not re.search(r"\b(?<![a-z])r\.stdout", tail), \
        "더빙 이후 구간에 분기 종속 변수 r 참조가 남아 있다"
    assert tail.count("note_tail") >= 2
    assert src.count("note_tail = (cr.stdout") == 1 and src.count("note_tail = (r.stdout") == 1


def test_preview_stale_regenerates_after_rerender(tmp_path):
    """🛑 회귀 방지 — 재렌더로 shorts 가 갱신되면 preview 도 재생성 대상이어야 한다.

    존재 여부만 보던 구현은 템플릿 변경 재렌더 후 옛 preview 를 그대로 재업로드해
    검수함이 재렌더 전 영상을 계속 재생했다(2026-08-12 B급_스튜디오_4bf13c55 실측)."""
    import os, time
    from ves.adapters.upload_artifacts import _preview_stale
    shorts = tmp_path / "shorts.mp4"; preview = tmp_path / "preview.mp4"
    shorts.write_bytes(b"v1")
    assert _preview_stale(preview, shorts) is True          # 없음 → 생성
    preview.write_bytes(b"p1")
    os.utime(preview, (time.time(), time.time()))
    os.utime(shorts, (time.time() - 100, time.time() - 100))
    assert _preview_stale(preview, shorts) is False         # preview 가 더 최신 → 유지
    os.utime(shorts, (time.time() + 100, time.time() + 100))  # 재렌더로 shorts 갱신
    assert _preview_stale(preview, shorts) is True          # 낡은 preview → 재생성


def test_convert_argv_carries_sub_sources():
    """8/13 v2: 자막·나레이션 원료 ASS 를 vlp 로 넘긴다 — 없으면 그 요소만 생략."""
    from ves.adapters.localize import convert_argv
    a = convert_argv("/py", "/v.mp4", "/p.json", "/o.mp4", "V1",
                     subs="/s.ass", tts_subs="/t.ass")
    assert a[-2:] == ["--subs=/s.ass", "--tts-subs=/t.ass"]
    b = convert_argv("/py", "/v.mp4", "/p.json", "/o.mp4", "V1")
    assert not any(x.startswith("--subs") or x.startswith("--tts-subs") for x in b)


# ── 0027 리뷰 후속: 행 단위 집계 통일 · 정규식 안전망 · 카드 부분 갱신 ──
def test_compile_episode_regex_rejects_broken_patterns():
    """🛑 잘못된 작품 카드 정규식은 PermanentError 로 즉시 끊는다.

    그냥 흘리면 re.search 의 re.error 를 executor 가 transient 로 분류해 백오프
    재시도만 무한히 돈다 — 사람이 카드를 고쳐야 풀리는 문제라 재시도로는 안 풀린다."""
    import pytest
    from ves.adapters.base import PermanentError, compile_episode_regex
    assert compile_episode_regex("") is None and compile_episode_regex(None) is None
    assert compile_episode_regex(r"EP\.?(\d+)").search("EP.410") is not None
    with pytest.raises(PermanentError):
        compile_episode_regex(r"EP\.?((\d+")          # 괄호 불균형 — 문법 오류
    with pytest.raises(PermanentError):
        compile_episode_regex(r"EP\.?\d+")            # 캡처그룹 없음 — 회차를 못 뽑는다
    with pytest.raises(PermanentError):
        compile_episode_regex(r"(?:EP)\.?\d+")        # '(' 는 있지만 캡처는 아님
    pat = compile_episode_regex(r"\[(\d+)-\d+\]")
    assert compile_episode_regex(pat) is pat          # 이미 컴파일된 것은 그대로


def test_guess_episode_title_never_raises():
    """회차를 못 읽으면 None(=서수 폴백)이지, 잡을 죽이지 않는다."""
    import re
    from ves.adapters.base import guess_episode_title
    # 캡처그룹이 숫자가 아닌 것을 잡는다 — int('EP') ValueError 가 새어나가면 안 된다
    assert guess_episode_title("EP.410 레전드", r"(EP)\.?\d+") is None
    # 그룹 없는 컴파일된 패턴이 검증 전 경로로 들어와도(IndexError) None
    assert guess_episode_title("EP.410", re.compile(r"EP\.?\d+")) is None
    assert guess_episode_title("놀라운 토요일 EP.410", re.compile(r"EP\.?(\d+)")) == 410
    assert guess_episode_title(None) is None


def test_plan_rows_stops_on_broken_regex():
    """등록 진입점에서 한 번만 컴파일 — 항목을 돌기 전에 끊는다(무한 재시도 방지)."""
    import pytest
    from ves.adapters.base import PermanentError
    from ves.adapters.register_sources import plan_rows
    entries = [{"id": "a", "title": "5화", "duration": 600}]
    with pytest.raises(PermanentError):
        plan_rows("작품", entries, title_episode_regex=r"EP((\d+")
    # 정상 정규식은 종전대로
    rows = plan_rows("작품", entries, title_episode_regex=r"(\d+)화")
    assert rows[0]["episode"] == 5 and rows[0]["episode_source"] == "parsed"


def test_row_level_usage_has_one_matching_rule():
    """🛑 사용량을 세는 곳이 여섯이다 — 전부 wo_matches_source 정본을 쓰는지 고정한다.

    하나라도 (작품, 회차) 조인으로 남으면 planner 와 관제가 서로 다른 숫자를 본다:
    같은 회차 영상 A·B 중 A 만 소진돼도 회차 전체가 소진으로 보여, planner 는 B 를
    배정하는데 run_channel_now 는 '쓸 수 있는 소스가 없습니다'로 막힌다."""
    import inspect
    from ves.scheduler import planner, source_watch
    mig = _mig("0027_episode_per_video.sql")
    # 정본 함수가 work_title 까지 본다 — 같은 URL 이 두 작품에 등록될 수 있다(새 멱등키)
    assert "CREATE OR REPLACE FUNCTION public.wo_matches_source" in mig
    assert "SELECT w_work = s_work" in mig
    # 코드 쪽 두 곳
    src = inspect.getsource(planner._pick_source)
    assert "wo_matches_source" in src
    assert "w.episode IS NOT DISTINCT FROM s.episode" not in src
    assert "wo_matches_source" in source_watch.REMAIN_SQL
    assert "w.episode IS NOT DISTINCT FROM s.episode" not in source_watch.REMAIN_SQL
    # 0027 이 SQL 쪽 네 소비처를 같이 갱신한다
    for obj in ("CREATE OR REPLACE VIEW public.source_usage",
                "CREATE OR REPLACE VIEW public.source_usage_by_channel",
                "CREATE OR REPLACE FUNCTION public.run_channel_now",
                "CREATE OR REPLACE FUNCTION public.set_source_limit"):
        assert obj in mig, f"0027 이 {obj} 를 갱신하지 않는다 — 회차 단위로 남는다"
    # run_channel_now 의 소스 선택에서 회차 조인이 사라졌는지
    body = mig.split("CREATE OR REPLACE FUNCTION public.run_channel_now", 1)[1]
    pick = body.split("IF NOT v_found", 1)[0]
    assert "wo_matches_source" in pick
    assert "w.episode IS NOT DISTINCT FROM s.episode" not in pick
    assert "coalesce(s2.published_ts, s2.created_at)" in pick   # planner 와 같은 정렬


def test_view_rewrites_keep_columns_and_security_invoker():
    """🛑 뷰를 다시 쓸 때 컬럼과 security_invoker 를 잃으면 안 된다(실적용에서 걸렸다).

    · CREATE OR REPLACE VIEW 는 컬럼을 못 지운다 — 0010 정의만 보고 쓰면
      'cannot drop columns from view' 로 마이그레이션이 중간에 멈춘다.
      duration_sec 는 0022 가 맨 뒤에 붙인 컬럼이다.
    · security_invoker 를 빠뜨리면 조회자 권한이 아니라 뷰 소유자 권한으로 돌아
      RLS 를 우회한다(0024 가 일부러 복구해 둔 값이다)."""
    mig = _mig("0027_episode_per_video.sql")
    su = mig.split("CREATE OR REPLACE VIEW public.source_usage\n", 1)[1] \
            .split("CREATE OR REPLACE VIEW public.source_usage_by_channel", 1)[0]
    assert "s.duration_sec" in su, "0022 가 붙인 duration_sec 가 빠졌다"
    assert "security_invoker = true" in su
    bych = mig.split("CREATE OR REPLACE VIEW public.source_usage_by_channel", 1)[1]
    assert "security_invoker = true" in bych.split("SELECT", 1)[0], \
        "source_usage_by_channel 이 security_invoker 없이 재정의된다 — RLS 우회"


def test_set_source_limit_touches_only_chosen_row():
    """0024 는 회차 전체에 한도를 걸었다(소진이 회차 단위였으니 맞았다). 0027 이 전제를
    뒤집었으므로 고른 행만 고친다 — 안 그러면 같은 회차 남의 영상 한도까지 바뀐다."""
    lim = _live_mig("CREATE OR REPLACE FUNCTION public.set_source_limit").split(
        "CREATE OR REPLACE FUNCTION public.set_source_limit", 1)[1]
    assert "WHERE id = p_source" in lim
    assert "s.episode IS NOT DISTINCT FROM v_s.episode" not in lim


def test_set_work_card_keeps_unspecified_fields():
    """🛑 정규식만 고쳤는데 title_filter·playlist_url 이 날아가면 안 된다.

    놀라운 토요일처럼 필터가 필수인 작품은 필터가 사라지는 순간 다음 등록에서
    그 채널의 다른 프로그램 영상까지 전부 소스로 들어온다."""
    wc = _mig("0028_work_cards.sql")
    body = wc.split("CREATE OR REPLACE FUNCTION public.set_work_card", 1)[1]
    # NULL = 미변경 (기존 값 유지), '' = 지우기
    for col in ("title_episode_regex", "title_filter", "playlist_url", "note"):
        assert f"CASE WHEN p_" in body and f"wc.{col}" in body, f"{col} 이 보존되지 않는다"
    assert "excluded.title_filter" not in body, "안 넘긴 인자를 NULL 로 덮어쓴다"
    # 카드 삭제는 '아무것도 안 넘김'이 아니라 명시적 플래그로
    assert "p_clear boolean DEFAULT false" in body
    assert "IF p_clear THEN" in body
    # 초판(5인자)이 남아 있으면 기본값이 겹쳐 호출이 모호해진다
    assert "DROP FUNCTION IF EXISTS public.set_work_card(text, text, text, text, text)" in wc


def test_dashboard_sums_usable_rows_only():
    """대시보드 소스 지도가 planner 와 같은 숫자를 보여야 한다.

    · 행 단위 합산 — 5화에 8분·40분 영상이 하나씩이면 한도는 1+3=4편이다(max 면 3).
    · 단 **쓸 수 있는 행만** 더한다. 비활성·3분 이하까지 더하면 화면이 부풀어
      '남음 27' 이라고 해놓고 실행하면 RPC 가 거절한다 — 개편이 없애려던 증상이
      반대 방향으로 되살아난다(실측: 국대 단편 한도 33 vs 실제 6).
    · 회차 사용가능 판정은 '행 중 하나라도 쓸 수 있으면'이다. 종전처럼 아무 행에서나
      길이를 집으면 비활성 57초 클립 하나가 회차 전체를 화면에서 숨긴다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    m = html.split("function buildEpMap", 1)[1].split("\n}", 1)[0]
    assert "e.limit   += " in m and "e.usedAny += " in m
    assert "Math.max(e.limit" not in m and "Math.max(e.usedAny" not in m
    assert "if (!srcUsable(r)) return;" in m          # 쓸 수 있는 행만 합산
    assert m.count("if (!srcUsable(r)) return;") == 2  # 한도 쪽·채널 사용량 쪽 모두
    # 레거시는 회차 단위 장부라 행마다 같은 값이 반복된다 — 합치면 부풀어서 한 번만 센다
    assert "Math.max(c.lg" in m
    # 사용가능 판정은 행 기준
    assert "const epUsable = e => e.usable > 0;" in html
    assert "(r.duration_sec == null || Number(r.duration_sec) > 180)" in html
    # 한도 편집은 그 회차의 행 전부에 건다(set_source_limit 이 행 단위가 됐으므로)
    assert 'data-sids=' in html and "el.dataset.sids" in html


# ── 0029 후속: 드라이브 등록 정합 · 작품 카드 시드 ──
def test_register_source_cli_keys_on_sha_not_episode():
    """🛑 (작품, 회차)로 기존 행을 찾아 PATCH 하면 같은 회차의 **다른 파일**을 덮어쓴다.

    0027 부터 한 회차에 영상이 여럿이다. sha256·object_key 가 바뀌는 순간 그 행에
    물려 있던 work_orders 매칭(wo_matches_source)이 통째로 끊겨 소진 카운트가 조용히
    0 으로 리셋된다 — 데이터 파괴형이라 수동 CLI 라도 막아야 한다."""
    import pathlib
    src = pathlib.Path("deploy/register_source.py").read_text(encoding="utf-8")
    reg = src.split("[3/3] 카탈로그", 1)[1].split("def summary", 1)[0]
    assert "sources?sha256=eq." in reg, "기존 행을 sha 로 찾지 않는다"
    assert "episode=is.null" not in reg, "회차로 찾던 조회가 남아 있다"
    assert '"episode_source"' in reg     # 파일명 파싱 회차는 방송 회차다


def test_register_drive_stamps_episode_source():
    """0027 백필은 그때 있던 행만 채웠다 — 이후 등록분도 parsed 를 달아야
    설명란 'N화' 표기 판정(approve_and_publish)이 옳게 간다."""
    import inspect
    from ves.adapters import register_drive
    src = inspect.getsource(register_drive)
    assert "episode_source" in src
    assert '"parsed" if ep is not None else None' in src


def test_work_card_seed_is_usable():
    """시드 정규식이 깨지거나 캡처그룹이 없으면 register_playlist 가 PermanentError 로
    죽는다(base.compile_episode_regex). 실제로 컴파일하고 표본을 파싱해 본다."""
    from ves.adapters.base import compile_episode_regex, guess_episode_title
    seed = _mig("0030_work_cards_seed.sql")
    for rx in (r"#언니네산지직송in칼라페\s*EP[.\s]?(\d{1,3})\b",
               r"#스트릿레스토랑파이터\s*EP[.\s]?(\d{1,3})\b",
               r"#언더커버셰프\s*EP[.\s]?(\d{1,3})\b",
               r"amazingsaturday\s*EP[.\s]?(\d{1,3})\b",
               r"\bEP[.\s]?(\d{1,3})\b"):
        assert rx in seed, f"시드에 없는 정규식: {rx}"
        assert compile_episode_regex(rx).groups == 1
    # 실제 제목 형태로 뽑히는지
    assert guess_episode_title("#언더커버셰프 EP.7 풀버전",
                               r"#언더커버셰프\s*EP[.\s]?(\d{1,3})\b") == 7
    assert guess_episode_title("#amazingsaturday EP.412 도레미마켓",
                               r"amazingsaturday\s*EP[.\s]?(\d{1,3})\b") == 412
    # tvN Joy 공식채널은 세 작품이 공유한다 — 필터가 없으면 남의 회차를 집는다
    joy = [ln for ln in seed.splitlines() if "@tvNJoy_official" in ln]
    assert len(joy) == 3, f"tvN Joy 공유 작품 수가 다르다: {len(joy)}"
    for name in ("언니네산지직송in칼라페", "스트릿레스토랑파이터", "언더커버셰프"):
        assert f"'{name}'," in seed, f"{name} 제목 필터가 빠졌다"
    # 사람이 관제에서 채운 카드를 시드가 덮으면 안 된다
    assert "ON CONFLICT (work_title) DO NOTHING" in seed


def test_reparse_tool_is_dry_run_by_default_and_guards_legacy():
    """회차 재파싱은 되돌리기 어려운 데이터 변경이다 — 기본은 dry-run 이어야 하고,
    레거시 장부가 물린 회차를 바꾸려 하면 --apply 라도 멈춰야 한다.
    (episode 를 바꾸면 source_usage_legacy 의 (작품·채널·회차) 매칭이 끊겨, 구
    시스템이 이미 쓴 몫이 planner 에 반영되지 않아 중복 생산이 난다)"""
    import pathlib
    src = pathlib.Path("deploy/reparse_youtube_episodes.py").read_text(encoding="utf-8")
    assert '"--apply", action="store_true"' in src        # 기본 False = dry-run
    assert "if not apply:" in src and "return len(plan), 0" in src
    # 레거시 충돌이면 apply 여도 건너뛴다
    hit = src.split("legacy_eps = {", 1)[1]
    assert "if apply:" in hit and "return 0, 1" in hit
    # 제목을 못 읽으면 손대지 않는다(서수 유지) — 추측으로 회차를 박지 않는다
    assert "if new_ep is None:" in src and "unchanged += 1" in src
    # 회차 파싱 규칙은 base.guess_episode_title 과 같아야 한다(무의존 사본)
    from ves.adapters.base import guess_episode_title as canon
    ns = {}
    exec(src.split("def guess_episode_title", 1)[1].split("\ndef fetch_titles", 1)[0]
         .join(["def guess_episode_title", ""]), {"re": __import__("re"),
                                                  "unicodedata": __import__("unicodedata")}, ns)
    copy = ns["guess_episode_title"]
    for t, rx in [("놀라운 토요일 EP.410 레전드", ""), ("언더커버셰프 12화", ""),
                  ("하트시그널5 제2회", ""), ("도레미마켓 모음", ""),
                  ("#언더커버셰프 EP.7", r"#언더커버셰프\s*EP[.\s]?(\d{1,3})\b")]:
        assert copy(t, rx) == canon(t, rx), f"사본이 정본과 다르다: {t!r}"


# ── 0031: 작품별 소스 길이 하한 ──
def test_min_duration_falls_back_to_default():
    """작품 카드에 값이 없거나 이상하면 종전 기본값(180) — 설정 오류가 등록을 막지 않는다."""
    from ves.adapters.base import MIN_USABLE_SEC, min_duration_for
    assert MIN_USABLE_SEC == 180
    assert min_duration_for(None) == 180
    assert min_duration_for(600) == 600 and min_duration_for("500") == 500
    assert min_duration_for(0) == 180 and min_duration_for(-1) == 180
    assert min_duration_for("이상한값") == 180 and min_duration_for("") == 180


def test_is_usable_respects_per_work_floor():
    """하한은 작품마다 다르다(놀토 600 · 커리어데이 300). 길이 미상은 종전대로 사용."""
    from ves.adapters.base import is_usable
    assert is_usable(181) and not is_usable(180)              # 기본 하한
    assert not is_usable(500, 600) and is_usable(601, 600)    # 작품 하한 600
    assert is_usable(301, 300) and not is_usable(300, 300)
    # 길이를 모르면(프로브 실패·0·음수) 막지 않는다 — 하한이 있어도 마찬가지
    for bad in (None, "", 0, -1):
        assert is_usable(bad) and is_usable(bad, 600)
    # register_drive 는 base 를 그대로 재수출한다(규칙이 갈라지면 안 된다)
    from ves.adapters import register_drive as rd
    from ves.adapters.base import is_usable as canon, MIN_USABLE_SEC as canon_min
    assert rd.is_usable is canon and rd.MIN_USABLE_SEC == canon_min


def test_plan_rows_uses_work_card_floor():
    """0031: 하한 이하는 등록 자체를 건너뛴다 — 번호도 안 준다."""
    from ves.adapters.register_sources import plan_rows
    entries = [{"id": "a", "title": "5화", "duration": 400, "timestamp": 100},
               {"id": "b", "title": "6화", "duration": 700, "timestamp": 200}]
    assert [r["url"][-1] for r in plan_rows("작품", entries)] == ["a", "b"]          # 기본 180
    assert [r["url"][-1] for r in plan_rows("작품", entries, min_duration=600)] == ["b"]
    assert plan_rows("작품", entries, min_duration=900) == []
    # 카드가 없으면(None) 종전 동작
    assert len(plan_rows("작품", entries, min_duration=None)) == 2


def test_min_duration_has_one_rule_everywhere():
    """🛑 하한을 보는 곳이 여섯이다 — 전부 정본(source_min_duration / base)을 쓰는지 고정한다.
    하나라도 180 을 직접 들고 있으면 작품별 하한이 그 경로에서만 무시된다."""
    import inspect
    from ves.scheduler import planner
    mig = _mig("0032_work_card_min_duration.sql")
    assert "CREATE OR REPLACE FUNCTION public.source_min_duration" in mig
    assert "min_source_duration_sec" in mig
    # planner 는 SQL 정본 함수를 쓴다
    src = inspect.getsource(planner._pick_source)
    assert "public.source_min_duration(s.work_title)" in src
    assert "> 180" not in src, "planner 에 하한이 하드코딩돼 있다"
    # run_channel_now 도(0031 이 마지막 재정의본)
    rcn = _live_mig("CREATE OR REPLACE FUNCTION public.run_channel_now")
    body = rcn.split("CREATE OR REPLACE FUNCTION public.run_channel_now", 1)[1]
    pick = body.split("IF NOT v_found", 1)[0]
    assert "public.source_min_duration(s2.work_title)" in pick
    assert "> 180" not in pick, "run_channel_now 에 하한이 하드코딩돼 있다"
    # 앞선 판이 넣은 것을 뒤 판이 또 흘리지 않았는지 — run_channel_now 는 지금까지
    # 0024→0027→0029→0031(scene_rerender)→0032 로 다섯 번 통째로 다시 쓰였고,
    # 그때마다 앞 판의 수정이 하나씩 사라졌다. 라이브 정의에 전부 살아 있어야 한다.
    for must in ("'manual:' ||", "'channel', v_ch.name", "free_before",      # 0029 복구분
                 "'mode', 'scene_rerender'"):                                 # 0031 컷오버
        assert must in body, f"run_channel_now 재정의에서 유실: {must}"
    assert re_search_priority(body), "priority 150 이 유실됐다"
    # 0031 이 등급 J 플래그를 걷어냈다 — 0029 판을 기반으로 다시 쓰면 되살아난다
    assert "no_tts_subtitles" not in body, "0031 이 제거한 등급 J 플래그가 되살아났다"
    # 뷰 2개가 usable 을 내려준다 — 대시보드가 숫자를 알 필요가 없다
    assert mig.count("AS usable") == 2
    assert mig.count("security_invoker = true") == 2
    # 등록 경로는 base 정본
    import ves.adapters.register_sources as rs
    assert "base.is_usable(dur, min_duration)" in inspect.getsource(rs.plan_rows)


def test_no_two_migrations_redefine_the_same_object():
    """🛑 같은 객체를 두 파일이 재정의하면 나중 것이 앞엣것을 통째로 되돌린다.

    번호가 같으면 특히 위험하다 — 적용 순서도 _live_mig 의 선택도 알파벳순이라
    사람이 의도한 순서와 무관해진다. 실제로 0031 이 두 개가 될 뻔했다:
    scene_rerender 컷오버(run_channel_now 를 새 체인으로)와 길이 하한이 같은 번호를
    썼고, 뒤엣것이 앞엣것의 체인 변경을 통째로 되돌리는 상태였다.
    (번호가 다른 재정의는 정상이다 — 0024→0027→0029→0031→0032 처럼 쌓인다)"""
    import collections
    import pathlib
    import re
    seen = collections.defaultdict(set)
    for p in sorted(pathlib.Path("ves/control/migrations").glob("*.sql")):
        for m in re.finditer(r"CREATE OR REPLACE (?:FUNCTION|VIEW)\s+(public\.\w+)",
                             p.read_text(encoding="utf-8")):
            seen[(p.name[:4], m.group(1))].add(p.name)
    clash = {f"{num} {obj}": sorted(files) for (num, obj), files in seen.items()
             if len(files) > 1}
    assert not clash, f"같은 번호의 두 파일이 같은 객체를 재정의한다: {clash}"


def re_search_priority(s):
    import re
    return bool(re.search(r"v_step\.ttl,\s*\n?\s*150\)", s))


def test_dashboard_reads_usable_from_view():
    """0031: 하한이 작품마다 다르므로 화면이 숫자를 알면 또 어긋난다 — 뷰의 usable 을 읽는다.
    단 0031 적용 전(컬럼 없음)에는 종전 규칙으로 폴백해야 배포 순서가 안전하다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    fn = html.split("const srcUsable", 1)[1].split(";", 1)[0]
    assert "r.usable === true" in fn
    assert "r.usable != null" in fn, "폴백 없이 usable 만 보면 0031 전에 전부 사용불가로 보인다"
    assert "> 180" in fn, "폴백 경로가 사라졌다"


def test_register_drive_uses_work_card_floor():
    """드라이브 등록도 작품별 하한을 쓴다(0032) — 유튜브·planner 와 같은 규칙.

    하한을 코드가 직접 들고 있으면 그 경로에서만 작품 설정이 무시된다. 카드를 루프
    바깥에서 한 번 읽고(파일마다 조회하지 않는다), 0032 미적용 DB 에서는 조회가
    실패하므로 기본값으로 내려가야 인입이 멈추지 않는다."""
    import inspect
    from ves.adapters import register_drive
    src = inspect.getsource(register_drive.run)
    assert "min_source_duration_sec FROM public.work_cards" in src
    assert "base.is_usable(dur, min_by_work.get(work))" in src
    assert "is_usable(dur)" not in src, "기본값 하한이 그대로 남아 있다"
    # 카드 조회는 파일 루프 **밖**에서 한 번만
    head, loop = src.split("for fid, work, rel in todo:", 1)
    assert "min_by_work = {" in head and "work_cards" not in loop
    # 0032 이전 DB 호환 — 조회 실패가 인입을 멈추지 않는다
    assert "except Exception" in head.split("min_by_work = {}", 1)[1]


# ── B안 1단계(8/14): run 번들 — 아무 맥에서나 scene_rerender ──
def test_bundle_files_filters_text_only():
    """번들 = 텍스트 산출물만(복원 필요집합의 상위집합) — 미디어·출력 디렉토리 제외."""
    import pathlib, tempfile
    from ves.adapters.upload_artifacts import bundle_files
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "run_log.json").write_text("{}")
        (root / "checkpoint_story.json").write_text("{}")
        (root / "crop_hook_0.json").write_text("{}")
        (root / "work_title.txt").write_text("혜미리예채파")
        (root / "subtitles.ass").write_text("[Events]")
        (root / "shorts.mp4").write_bytes(b"x" * 10)              # 미디어 제외
        (root / "localize_ja").mkdir()
        (root / "localize_ja" / "translation.json").write_text("{}")   # 출력 제외
        (root / "renders").mkdir()
        (root / "renders" / "meta.json").write_text("{}")          # 렌더 중간물 제외
        rels = [r for r, _ in bundle_files(root)]
        assert "run_log.json" in rels and "crop_hook_0.json" in rels
        assert "work_title.txt" in rels and "subtitles.ass" in rels
        assert "shorts.mp4" not in rels
        assert not any(r.startswith("localize_ja") or r.startswith("renders") for r in rels)
        assert bundle_files(root / "없는디렉토리") == []


def test_source_sha_from_runlog():
    """run_log 의 소스 경로 → 내용주소 sha 추출 — 규약 밖(URL 소스)은 None."""
    from ves.adapters.localize import source_sha_from_runlog
    sha = "e4d5527699ab4c0ed39c80ec17978381499164c67da01da834035247aee7bdac"
    assert source_sha_from_runlog(
        {"input": {"video_path": f"/opt/ves/cache/sources/{sha}"}}) == sha
    assert source_sha_from_runlog({"input": {"video_path": "/tmp/영상.mp4"}}) is None
    assert source_sha_from_runlog({}) is None and source_sha_from_runlog(None) is None


def test_loopy_ledger_row_params_shape():
    """원장 미러(0034) — sqlite 행 → upsert 파라미터. scores 는 유효 JSON 만 jsonb 로."""
    from ves.adapters.zanmang import ledger_row_params, _MIRROR_SQL
    r = {"video_id": "abc", "title": "볼살 뀨~", "state": "pending_approval",
         "score": 0.69, "scores": '{"llm":0.7}', "notes": None}
    params = ledger_row_params(r)
    assert params[0] == "abc" and params[8] == "pending_approval"
    assert params[11] == '{"llm":0.7}'
    # 깨진 JSON 은 NULL 로 — jsonb 캐스트에서 upsert 전체가 죽으면 안 된다
    assert ledger_row_params({**r, "scores": "{broken"})[11] is None
    # 파라미터 수가 SQL 플레이스홀더 수(17 + now())와 맞아야 한다
    assert len(params) == 17 and _MIRROR_SQL.count("%s") == 17


def test_loopy_upload_argv_privacy():
    """관제 3택(8/14): upload argv 에 공개 방식 전달 — public·형식오류는 차단."""
    import pytest
    from ves.adapters.base import PermanentError
    from ves.adapters.zanmang import action_argv
    a = action_argv("/r", "upload", "vid1", privacy="unlisted")
    assert "--privacy" in a and "unlisted" in a and "--publish-at" not in a
    a2 = action_argv("/r", "upload", "vid1", privacy="schedule",
                     publish_at="2026-08-15T10:00:00Z")
    assert "--publish-at" in a2 and "2026-08-15T10:00:00Z" in a2
    assert "--privacy" not in action_argv("/r", "upload", "vid1")   # 미지정 = 종전 기본
    with pytest.raises(PermanentError):
        action_argv("/r", "upload", "vid1", privacy="public")       # R9
    with pytest.raises(PermanentError):
        action_argv("/r", "upload", "vid1", publish_at="내일 저녁")  # ISO 아님


def test_loopy_review_meta_reads_ko_glosses(tmp_path):
    """검수 카드 한글 대역(8/14) — metadata_draft(_ko) + 자막 쌍(C: ko_ja_pairs,
    B/BJ 폴백: translations.json). 파일이 없거나 깨져도 빈 dict 로 조용히."""
    import json
    from ves.adapters.zanmang import review_meta
    d = tmp_path / "vid1"; d.mkdir()
    (d / "metadata_draft.json").write_text(json.dumps({
        "title_candidates": ["ルーピーの日常"], "title_candidates_ko": ["루피의 일상"],
        "description": "説明です", "description_ko": "설명입니다"}, ensure_ascii=False))
    (d / "ko_ja_pairs.json").write_text(json.dumps({
        "subs": [{"start": 1.0, "ko": "안녕", "ja": "こんにちは"}]}, ensure_ascii=False))
    m = review_meta(d)
    assert m["youtube_title"] == "ルーピーの日常" and m["youtube_title_ko"] == "루피의 일상"
    assert m["description_ko"] == "설명입니다"
    assert m["ko_ja_pairs"]["subs"][0]["ja"] == "こんにちは"
    # C 쌍이 없으면 translations.json(B/BJ)로 폴백. use=False(소프트 삭제 — E6-0,
    # vlp 1ece879)는 다음 카드에서 빠지고, 남은 줄은 필터 전 좌표(idx)를 유지한다.
    (d / "ko_ja_pairs.json").unlink()
    (d / "translations.json").write_text(json.dumps({
        "entries": [{"source": "지운 줄", "target": "消した", "use": False},
                    {"source": "안녕", "target": "こんにちは"}]}, ensure_ascii=False))
    m2 = review_meta(d)
    assert [(s["idx"], s["ko"]) for s in m2["ko_ja_pairs"]["subs"]] == [(1, "안녕")]
    assert review_meta(tmp_path / "없음") == {} or "youtube_title" not in review_meta(tmp_path / "없음")


def test_loopy_store_key_and_text_files():
    """2단계 ③: 산출물 지속화 키 규약 — 복원(zanmang_decision)과 같은 함수를 쓴다."""
    from ves.adapters.zanmang import LOOPY_TEXT_FILES, loopy_store_key
    assert loopy_store_key("o3HEuV8iNPE", "metadata_draft.json") \
        == "loopy/o3HEuV8iNPE/metadata_draft.json"
    assert "metadata_draft.json" in LOOPY_TEXT_FILES
    assert "ja_dub.srt" in LOOPY_TEXT_FILES        # C 루트 자막도 패키지 원료다


def test_rerender_plan_and_argv():
    """반려-수정 재렌더(0038): 원장 정상 전이로만 — approved/uploaded 는 거부."""
    import pytest
    from ves.adapters import zanmang
    from ves.adapters import zanmang_decision as zd
    assert zd.plan("pending_approval", "rerender") == ["mark_skip", "mark_select", "process"]
    assert zd.plan("skipped", "rerender") == ["mark_select", "process"]
    assert zd.plan("failed", "rerender") == ["mark_select", "process"]
    assert zd.plan("selected", "rerender") == ["process"]
    assert zd.plan("processing", "rerender") == []          # 진행 중 — 손대지 않는다
    for st in ("approved", "uploaded"):
        with pytest.raises(Exception):
            zd.plan(st, "rerender")
    argv = zanmang.process_argv("/r", "vid1")
    assert argv[0] == "/r/.venv/bin/python" and argv[-2:] == ["--video-id", "vid1"]
    assert "process" in argv
    # task 이름 → argv 매핑(멱등 체인의 배선)
    assert zd._task_argv("/r", "mark_skip", "v", {})[-2:] == ["--state", "skipped"]
    assert zd._task_argv("/r", "mark_select", "v", {})[-2:] == ["--state", "selected"]
    assert zd._task_argv("/r", "process", "v", {}) == zanmang.process_argv("/r", "v")


def test_scene_rerender_argv_overrides():
    """SHOTCONE 재렌더: overrides 경로가 있으면 --overrides 로 엔진에 전달."""
    from ves.adapters.localize import scene_rerender_argv
    a = scene_rerender_argv("/py", "/eng", "/job")
    assert "--overrides" not in a and a[-2:] == ["--job-dir", "/job"]
    b = scene_rerender_argv("/py", "/eng", "/job", "/job/localize_overrides.json")
    assert b[-2:] == ["--overrides", "/job/localize_overrides.json"]
    assert b[:len(a)] == a                          # 기존 인자 앞부분은 불변


def test_review_meta_translations_fallback_has_idx(tmp_path):
    """B/BJ 폴백 자막 쌍에 idx(0038 오버라이드 좌표) — entries 순번, 필터 전에 매긴다."""
    import json as _json
    from ves.adapters.zanmang import review_meta
    d = tmp_path / "v"; d.mkdir()
    (d / "translations.json").write_text(_json.dumps({
        "entries": [{"source": "하나", "target": "一"}, {"source": "", "target": "x"},
                    {"source": "셋", "target": "三"}]}, ensure_ascii=False))
    subs = review_meta(d)["ko_ja_pairs"]["subs"]
    assert subs[0]["idx"] == 0 and subs[1]["idx"] == 2   # 빈 source 를 걸러도 좌표 유지


# ───────── 편집실 1단계 (0042 · editor_assets) ─────────
def test_sprite_layout_grid_math():
    """화면이 'n번째 썸네일 = 몇 번 시트의 몇 행 몇 열'을 계산한다 — 규약을 고정."""
    from ves.adapters.editor_assets import sprite_layout
    lay = sprite_layout(14400)                 # 4시간
    assert lay["interval"] == 10.0 and lay["grid"] == 10
    assert lay["count"] == 1441                # 0초 포함
    assert lay["sheets"] == 15                 # 100장/시트
    assert sprite_layout(0)["count"] == 0 and sprite_layout(0)["sheets"] == 0
    assert sprite_layout(None)["count"] == 0
    assert sprite_layout(95)["count"] == 10 and sprite_layout(95)["sheets"] == 1


def test_edge_windows_merge_and_clamp():
    """경계 ±15초만 밀집 — 겹치면 합치고, 0 미만·길이 초과는 자른다."""
    from ves.adapters.editor_assets import edge_windows
    clips = [{"start_sec": 5, "end_sec": 20}, {"start_sec": 100, "end_sec": 130}]
    got = edge_windows(clips, window=15, duration_sec=140)
    # 5±15 → [0,20], 20±15 → [5,35] : 겹쳐서 [0,35] 하나로
    assert got[0] == {"start_sec": 0.0, "end_sec": 35.0}
    # 100±15 → [85,115], 130±15 → [115,140(클램프)] : 115 에서 맞닿으므로 한 구간으로 합친다
    # (붙어 있는 두 구간을 따로 뜨면 ffmpeg 를 두 번 돌리고 경계에서 프레임이 겹친다)
    assert got[1] == {"start_sec": 85.0, "end_sec": 140.0}
    assert len(got) == 2
    assert edge_windows([]) == []


def test_timeline_from_plan_dual_coordinates():
    """clips 는 원본 절대초, subtitles 는 편집본 시각 + 역산한 원본 시각."""
    from ves.adapters.editor_assets import timeline_from_plan
    plan = {"layout": {"top_title": "제목\n2줄", "bottom_label": "작품"},
            "timeline": [{"role": "hook", "clip_start_sec": 100.0, "clip_end_sec": 130.0,
                          "use_original_audio": True, "subtitle": "장면 묘사"},
                         {"role": "payoff", "clip_start_sec": 500.0, "clip_end_sec": 520.0,
                          "use_original_audio": False}]}
    segs = [{"start_sec": 2.0, "end_sec": 4.0, "text": "첫 자막"},
            {"start_sec": 31.0, "end_sec": 33.0, "text": "둘째 클립 자막"},
            {"start_sec": 999.0, "end_sec": 1000.0, "text": "범위 밖"}]
    tl = timeline_from_plan(plan, segs, duration_sec=3600)
    assert tl["top_title"] == "제목\n2줄" and tl["duration_sec"] == 3600.0
    assert tl["total_clip_sec"] == 50.0
    assert tl["clips"][0]["offset_sec"] == 0.0 and tl["clips"][1]["offset_sec"] == 30.0
    assert tl["clips"][1]["use_original_audio"] is False
    # 편집본 2초 = 첫 클립 시작(100) + 2 = 원본 102초
    assert tl["subtitles"][0]["source_sec"] == 102.0
    # 편집본 31초 = 둘째 클립 offset 30 → 원본 500 + 1 = 501초
    assert tl["subtitles"][1]["source_sec"] == 501.0
    assert tl["subtitles"][2]["source_sec"] is None        # 클립 밖 = 매핑 없음


def test_tts_from_checkpoints_prefers_resources():
    """resources 의 cue 가 정본 — 실제 합성·렌더된 문구(fit 반영)와 편집본 시각을 가진다."""
    from ves.adapters.editor_assets import tts_from_checkpoints
    resources = {"tts_cue_files": [
        {"cue_index": 0, "cue": {"text": "합성된 문구", "source_time_sec": 743.0,
                                 "duration_sec": 3.5, "start_sec": 1.2, "end_sec": 4.7,
                                 "voice": "ko_male", "speed": "fast"}},
        {"cue_index": 1, "cue": {"text": "구 스키마 cue", "start_sec": 10.0,
                                 "end_sec": 13.0}},                 # source_time 없음 → 제외
    ]}
    silence = {"variants": [{"tts_cues": [
        {"text": "silence_cut 판", "source_time_sec": 743.0, "duration_sec": 3.5}]}]}
    got = tts_from_checkpoints(resources, silence)
    assert len(got) == 1                                    # resources 우선 + 구 스키마 제외
    assert got[0]["text"] == "합성된 문구" and got[0]["source_sec"] == 743.0
    assert got[0]["edited_start"] == 1.2 and got[0]["voice"] == "ko_male"
    assert got[0]["idx"] == 0


def test_tts_from_checkpoints_fallback_and_sort():
    """resources 가 없으면 silence_cut 앵커 cue 로 — 편집본 시각은 모른다(None)."""
    from ves.adapters.editor_assets import tts_from_checkpoints
    silence = {"variants": [{"tts_cues": [
        {"text": "뒤", "source_time_sec": 1195.5, "duration_sec": 4.0},
        {"text": "앞", "source_time_sec": 743.0, "duration_sec": 3.5,
         "voice": "ko_female_high"}]}]}
    got = tts_from_checkpoints(None, silence)
    assert [c["text"] for c in got] == ["앞", "뒤"]          # source_sec 정렬
    assert got[0]["edited_start"] is None
    assert got[0]["voice"] == "ko_female_high" and got[1]["voice"] == "ko_female"
    assert [c["idx"] for c in got] == [0, 1]
    assert tts_from_checkpoints(None, None) == []
    assert tts_from_checkpoints({}, {"variants": []}) == []


def test_sprite_and_wave_cmd():
    """긴 소스 탐색을 위해 -ss/-to 는 입력 **앞**에 와야 한다."""
    from ves.adapters.editor_assets import sprite_cmd, sprite_key, wave_cmd
    c = sprite_cmd("/p/proxy_480.mp4", "/tmp/g_%03d.jpg", 10.0)
    assert "fps=1/10.0" in " ".join(c) and "tile=10x10" in " ".join(c)
    assert c[c.index("-i") + 1] == "/p/proxy_480.mp4"
    e = sprite_cmd("/p/x.mp4", "/tmp/e_%03d.jpg", 2.0, start=100.0, end=130.0)
    assert e.index("-ss") < e.index("-i") and e.index("-to") < e.index("-i")
    assert sprite_key("작품_abc123", "g", 7).endswith("/editor/g_007.jpg")
    assert "showwavespic" in " ".join(wave_cmd("/p/x.mp4", "/tmp/w.png"))


def test_pick_scrub_source_prefers_proxy(tmp_path):
    """프록시(480p·4fps)가 마스터보다 훨씬 빨리 훑힌다 — 타임코드는 1:1."""
    from ves.adapters.editor_assets import pick_scrub_source
    d = tmp_path / "run"; d.mkdir()
    master = tmp_path / "master.mp4"; master.write_bytes(b"x")
    assert pick_scrub_source(str(d), str(master)) == str(master)   # 프록시 없으면 마스터
    proxy = d / "피의 게임 X_480.mp4"; proxy.write_bytes(b"x")
    assert pick_scrub_source(str(d), str(master)) == str(proxy)
    assert pick_scrub_source(str(d), None) == str(proxy)
    assert pick_scrub_source(str(tmp_path / "없음"), None) is None


def test_editor_assets_registered():
    from ves.adapters import base as abase
    assert abase.get("editor_assets") is not None


# ───────── 편집실 2단계 (0043 · 고친 제목·자막으로 재렌더) ─────────
def test_edit_overrides_argv_is_additive():
    """오버라이드가 없으면 종전과 **완전히 같은** 명령이어야 한다(하위호환).
    localize.scene_rerender_argv 와 같은 규약 — 앞부분 불변, 뒤에만 붙인다."""
    from ves.adapters.aivideo import edit_overrides_argv
    base_argv = ["/py", "-m", "app.cli", "create_shorts", "--job-id", "가왕쇼_df50a39c"]
    assert edit_overrides_argv(base_argv, None) == base_argv
    assert edit_overrides_argv(base_argv, "") == base_argv
    got = edit_overrides_argv(base_argv, "/runs/x/edit_overrides.json")
    assert got[:len(base_argv)] == base_argv
    assert got[-2:] == ["--edit-overrides", "/runs/x/edit_overrides.json"]


def test_edit_overrides_written_to_run_dir(tmp_path):
    """오버라이드는 파일로 넘긴다 — 자막 수십 줄이 argv 인용 한계에 걸리지 않게.
    run_dir 에 남으므로 '무엇을 보냈는지'가 그 맥에 증거로 남는다."""
    import json as _json
    from ves.adapters.aivideo import _write_edit_overrides
    ov = {"schema": "edit_overrides/v1", "subtitles": [
        {"start_sec": 0.2, "end_sec": 2.3, "text": '따옴표 "있는" 줄\n줄바꿈도'}]}
    p = _write_edit_overrides(tmp_path, ov)
    assert p == tmp_path / "edit_overrides.json"
    assert _json.loads(p.read_text(encoding="utf-8")) == ov      # 왕복 무손실
    assert _write_edit_overrides(tmp_path, None) is None          # 없으면 파일도 안 만든다


def test_edit_overrides_require_resume_run():
    """새 run 에 편집 오버라이드는 좌표계가 맞지 않는다 — 조용히 무시하지 말고 즉시 실패.
    (사람이 고친 값이 빠진 영상이 나가는 것이 최악이라는 edit_overrides 모듈 원칙)"""
    from ves.adapters import aivideo, base as abase
    job = {"params": {"work_title": "가왕쇼", "edit_overrides": {"schema": "edit_overrides/v1"}}}
    try:
        aivideo._build_argv_fresh(None, job)
    except abase.PermanentError as e:
        assert "resume_run_id" in str(e)
    else:
        raise AssertionError("새 run + edit_overrides 는 반드시 PermanentError 여야 한다")


def test_0054_v3_stamp_and_anchor_carryover():
    """0054(F-401·F-407): 스탬프는 병합 결과 기준 내용 기반 3단 — 자막에 앵커
    (source_time_sec)나 style 이 있으면 v3. 승계 예외 정교화: 구간이 바뀌어도 앵커
    있는 승계 자막은 살아남는다(원본 좌표). images 조기 거절은 0057 이 개방(별도 테스트).
    전환은 ops_config 'editor_v3' 플래그 — 화면이 안 보내는 동안 v1/v2 유지(안전)."""
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.submit_editor_render")
    assert "source_time_sec' OR s ? 'style'" in sql          # 내용 기반 v3 판정
    assert "이미지 오버레이는 아직 렌더 미구현" not in sql    # 0057 개방 — 조기 거절 소멸
    # 0059: 앵커 없는 승계 자막(신규·시각 고정)은 사람 값이라 **버리지 않는다** —
    # 0054 의 생존 필터(jsonb_set 재조립)는 제거됐다(구간만 재제출 시 고정 줄 소실 방지)
    assert "jsonb_set(v_prev, '{subtitles}', v_subs)" not in sql
    assert "사람이 의도한 고정 시각" in sql
    # 0053 승계·0050 F-302 계약 유지(전문 재정의라 빠뜨리기 쉽다)
    assert "v_prev || p_overrides" in sql
    assert "draft_sent_at=now()" in sql
    assert "FUNCTION public.retry_editor_chain" not in sql   # retry 는 불변(0050) — 재정의 금지
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "editor_v3" in html and "edV3()" in html          # 플래그 게이트
    assert "o.source_time_sec" in html                       # 앵커는 받은 src 를 되돌려 보낸다


def test_0043_submit_editor_render_contract():
    """RPC 계약: reviewer 게이트 · publish_gate/waiting 한정 · 체인 4잡 · 생성 노드 핀."""
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.submit_editor_render")
    assert "has_role(auth.uid(),'reviewer')" in sql
    # 대상 카드 — 일본어(localization_qa)는 0038 담당이라 여기서 받으면 안 된다.
    # 0050: rejected 는 재제출 경로(F-302) — 가드(새 waiting 카드 없음 + 보낸 초안)가 있어야 한다.
    # kind 핀은 계속 필수 — 흘리면 localization_qa(0038 담당)까지 받는다.
    assert "rq.kind = 'publish_gate'" in sql
    assert "rq.status IN ('waiting','rejected')" in sql
    assert "이미 새 검수 카드가 있습니다" in sql
    assert "보낸 초안이 없습니다" in sql
    # 스키마 주입: 화면이 빠뜨려도 엔진 계약이 성립해야 한다.
    # 0053: 스탬프·재개 단계 판정 기준은 **병합 결과(v_ov)** — 승계된 clips/tts 도
    # resources 재개·v2 스탬프를 받아야 한다. 0054: 내용 기반 3단(v3 = 자막 앵커/style·images).
    assert "WHEN v_v3 THEN 'edit_overrides/v3'" in sql
    assert "WHEN v_ov ? 'tts' THEN 'edit_overrides/v2'" in sql
    assert "ELSE 'edit_overrides/v1' END" in sql
    # 재개 단계: 구간·내레이션(승계분 포함)이 있으면 resources, 아니면 render
    assert "v_ov ? 'clips' OR v_ov ? 'tts'" in sql
    assert "THEN 'resources' ELSE 'render' END" in sql
    # 내레이션 허용 키 + 빈 배열(전부 삭제) 유효
    assert "p_overrides ? 'tts'" in sql
    assert "빈 배열 = 내레이션 전부 삭제" in sql
    # 옛 카드를 닫아야 evaluate 가 새 카드를 넣는다(brain.py 의 waiting 중복 방지)
    assert "SET status = 'rejected'" in sql
    # 체인 4잡 + 생성 노드 핀 + 멱등키
    for k in ("'generate'", "'upload_artifacts'", "'ingest'", "'evaluate'"):
        assert k in sql, k
    assert "ARRAY['generate', 'node:' || v_gen.node_id]" in sql
    assert "'editrender:' || p_review_id" in sql
    # 이중 렌더 방지(0050: generate 만이 아니라 살아있는 editrender 꼬리 전체) + 재료 무효화
    assert "이미 렌더 체인이 대기·진행 중입니다" in sql
    assert "idempotency_key LIKE 'editrender:%'" in sql
    # 재료 무효화 — 0050 부터 초안은 지우지 않고 보낸 표시(draft_sent_at)만 찍는다
    assert "UPDATE public.editor_assets" in sql and "SET status='pending'" in sql
    assert "_audit('editor_render'" in sql
    assert "REVOKE ALL     ON FUNCTION public.submit_editor_render(uuid, jsonb, text) FROM public, anon;" in sql
    assert "GRANT  EXECUTE ON FUNCTION public.submit_editor_render(uuid, jsonb, text) TO authenticated;" in sql


def test_dashboard_editor_edit_ui_wired():
    """화면 배선: 편집 폼 → submit_editor_render. 고치지 않은 항목은 키를 빼야 한다
    (자막을 안 건드렸는데 subtitles 를 보내면 전량 교체로 재매핑 결과가 못박힌다)."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert 'sb.rpc("request_editor_assets"' in html          # 1단계 유지
    assert '"submit_editor_render"' in html
    assert "p_overrides" in html and "p_review_id: edRid" in html
    # 권한·카드 게이트가 화면에도 있어야 한다(서버가 최종 방어선이지만 버튼부터 안 보이게)
    # 0050(F-302)부터 edCanEdit 이 waiting + '재제출 가능한 rejected' 를 받는다 —
    # reviewer·publish_gate 핀과 waiting 허용은 계속 필수
    assert 'if (!can("reviewer") || r.kind !== "publish_gate") return false;' in html
    assert 'if (r.status === "waiting") return true;' in html
    # draft 분리 — 화면이 다시 그려져도 고치던 문장이 살아남는다
    assert "dTitle" in html and "dSubs" in html
    # 자막 전량 삭제 방어
    assert "자막을 전부 지울 수는 없습니다" in html
    # 내레이션 탭(0047) — src 신원 매칭 · 전량 교체 수집 · 전부 삭제 확인 · orphan 경고
    assert "edPaneTts" in html and "edTtsChanged" in html
    assert "source_time_sec" in html
    assert "내레이션을 전부 삭제한 채 다시 렌더합니다" in html
    assert "edTtsOrphan" in html


# ───────── 0044: 편집 초안 · 발행 전 채널 안내 ─────────
def test_0044_draft_rpc_and_geoblock_notice():
    """초안은 reviewer 만 저장하고, 빈 값은 '삭제'다 — 빈 초안이 남으면 편집실 목록에
    '아직 안 보낸 것'으로 계속 떠서 사람을 혼란시킨다."""
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.save_editor_draft")
    assert "has_role(auth.uid(),'reviewer')" in sql
    assert "ADD COLUMN IF NOT EXISTS draft" in sql
    assert "SET draft=NULL, draft_at=NULL, draft_by=NULL" in sql          # 빈 초안 = 삭제
    assert "편집실 재료가 없는 run 입니다" in sql                          # 없는 run 은 거부
    assert "REVOKE ALL     ON FUNCTION public.save_editor_draft(text, jsonb) FROM public, anon;" in sql
    assert "GRANT  EXECUTE ON FUNCTION public.save_editor_draft(text, jsonb) TO authenticated;" in sql
    # 발행 전 안내는 코드가 아니라 설정에 둔다 — 채널이 계속 늘기 때문
    assert "'geoblock_notice'" in sql and "JAEMISHOTS" in sql


def test_0044_submit_marks_draft_sent():
    """0050(F-302): 성공하면 지우고 실패하면 남긴다 — 제출은 draft_sent_at 만 찍고
    초안을 지우지 않는다(지우면 체인 실패 시 복구 재료가 없다). 성공 청소는 새 카드를
    만드는 brain.post_success 가 한다."""
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.submit_editor_render")
    assert "draft_sent_at=now()" in sql
    assert "draft=NULL" not in sql                    # 제출 경로는 초안을 지우지 않는다
    # 0043 계약은 그대로 유지돼야 한다(전문 재정의라 빠뜨리기 쉽다)
    assert "ARRAY['generate', 'node:' || v_gen.node_id]" in sql
    assert "이미 렌더 체인이 대기·진행 중입니다" in sql
    # 성공 청소 짝 — post_success 가 보낸 초안만 지운다
    import pathlib
    brain = pathlib.Path("ves/adapters/brain.py").read_text(encoding="utf-8")
    assert "draft_sent_at IS NOT NULL" in brain


# ───────── 0046: 편집 재렌더 앞 소스 재가열 ─────────
def test_0046_editor_render_rewarms_source_on_same_node():
    """🛑 재렌더는 며칠 뒤에 눌린다 — 그 사이 노드 캐시는 GC 된다.

    2026-08-18 02:38 실측: '국대: 로드 투 노스 아메리카' ep4 의 첫 실사용 재렌더가
    `소스 캐시 없음: …/cff7c45f… — acquire 선행 확인` 로 즉사했다(원본 회전은 08-16
    01:47 mm-03 정상 완주). 체인 맨 앞에 acquire 를 세우되 **같은 노드에 핀**해야 한다 —
    다른 노드에서 성공하면 acquire.post_success 가 generate 에 두 번째 node: 캡을 붙여
    영원히 못 잡는 잡이 된다(required_caps <@ effective_caps 는 전량 포함 조건)."""
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.submit_editor_render")
    assert "0053" in sql, "submit_editor_render 의 라이브 정의가 0053 이상이어야 한다"
    assert "'acquire'" in sql, "재렌더 체인 맨 앞에 acquire 가 있어야 한다"
    assert "ARRAY['network', 'node:' || v_gen.node_id]" in sql, "acquire 도 같은 노드에 핀"
    assert "'editrender:' || p_review_id || ':acq'" in sql
    # generate 는 그 acquire 를 기다려야 한다 — 핀만으로는 순서가 안 잡힌다
    assert "ARRAY[v_acq], ARRAY['generate', 'node:' || v_gen.node_id]" in sql
    # 재시도(ON CONFLICT) 경로에서도 의존이 되살아나야 한다
    gen_block = sql.split("'editrender:' || p_review_id,", 1)[1].split("RETURNING id INTO v_gen_job", 1)[0]
    assert "depends_on=excluded.depends_on" in gen_block
    # 반환 chain 에도 acquire 를 실어 화면이 진행을 따라갈 수 있게 한다
    assert "jsonb_build_array(v_acq, v_gen_job, v_up, v_in, v_ev)" in sql


# ───────── 잡 서브프로세스 환경: env 파일 재읽기 ─────────
def test_job_env_rereads_env_files_without_restart(tmp_path, monkeypatch):
    """🛑 에이전트는 기동 때 딱 한 번 env 파일을 읽는다(load_env) — 사람이 노드에
    시크릿을 새로 넣으면 **재기동 전까지 잡이 그것을 못 본다**.

    이 함정에 두 번 연달아 빠졌다: 한 입 주막 발행 토큰(2026-08-17)과 YouTube
    쿠키(08-18). 두 번 다 '파일엔 분명히 있는데 동작만 옛날'이라 코드에서 원인을
    찾을 수 없었고, 그게 이 함정의 비용이다. 잡을 띄울 때 다시 읽어 계열을 없앤다.

    단 **프로세스 환경이 우선**이어야 한다 — 셸에서 임시로 덮어쓴 값을 파일이
    되돌리면 그것대로 함정이 된다."""
    import os
    import types
    from ves import config as cfgmod

    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "ves.env").write_text(
        "YTDLP_COOKIES=/opt/ves/secrets/yt_cookies.txt\n"
        'SHADOWED="파일값"\n', encoding="utf-8")
    monkeypatch.setenv("VES_HOME", str(tmp_path))
    monkeypatch.setenv("SHADOWED", "프로세스값")
    monkeypatch.delenv("YTDLP_COOKIES", raising=False)

    e = cfgmod.job_env(types.SimpleNamespace(home="/opt/ves"))
    assert e["YTDLP_COOKIES"] == "/opt/ves/secrets/yt_cookies.txt"   # 재기동 없이 닿는다
    assert e["SHADOWED"] == "프로세스값"                              # 프로세스 환경 우선
    assert e["AI_VIDEO_ROOT"] == "/opt/ves/engines/ai-video"
    assert "YTDLP_COOKIES" not in os.environ    # 에이전트 프로세스는 오염시키지 않는다


def test_both_adapters_use_job_env():
    """한쪽만 고치면 그 엔진의 잡만 새 시크릿을 본다 — 둘 다 같은 통로여야 한다."""
    import inspect
    from ves.adapters import aivideo, brain
    for name, fn in (("aivideo.env", aivideo.env), ("brain._env", brain._env)):
        src = inspect.getsource(fn)
        assert "job_env" in src, name
        assert "dict(os.environ)" not in src, name


def test_dashboard_geoblock_modal_and_draft_list():
    """발행 전 안내는 채널 목록을 코드에 박지 않고 ops_config 에서 읽는다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "geoblock_notice" in html and "askNotice(" in html
    assert "JAEMISHOTS" not in html, "대상 채널을 화면 코드에 박으면 안 된다(설정으로 관리)"
    assert '"save_editor_draft"' in html and "edQueueSave" in html
    assert "edDraftList" in html
    assert 'editor_assets:"편집실 준비"' in html


# ───────── 편집 프리뷰(구간 편집용 영상) ─────────
def test_scan_bitrate_scales_with_length():
    """전체 훑기는 **총 용량 목표에서 역산**한다 — CRF 로 뜨면 길이에 따라 크기가
    폭발한다(2026-08-17 실측: 47분 리먹스 = 418MB → 4시간이면 2GB 로 못 씀)."""
    from ves.adapters.editor_assets import scan_bitrate_kbps, SCAN_TARGET_MB
    short, long_ = scan_bitrate_kbps(2829), scan_bitrate_kbps(13499)
    assert short > long_                                   # 길수록 낮은 화질
    for dur in (600, 2829, 13499, 30000):
        kbps = scan_bitrate_kbps(dur)
        assert 120 <= kbps <= 900                          # 하한·상한을 벗어나지 않는다
        if 120 < kbps < 900:                               # 클램프에 안 걸린 구간이면
            mb = (kbps + 40) * dur / 8192                  # 오디오 포함 실제 크기
            assert abs(mb - SCAN_TARGET_MB) < 1            # 목표 용량에 맞는다
    assert scan_bitrate_kbps(0) == 900                     # 길이 미상이면 상한(짧다고 본다)


def test_scan_cmd_is_abr_and_faststart():
    """ABR 로 크기를 예측 가능하게, faststart 로 중간 재생 가능하게, 2초 키프레임으로
    스크럽이 붙게. 셋 중 하나만 빠져도 편집기로 못 쓴다."""
    from ves.adapters.editor_assets import scan_cmd
    s = " ".join(scan_cmd("/runs/x/작품_480.mp4", "/tmp/scan.mp4", 2829))
    assert "-b:v" in s and "-maxrate" in s and "-bufsize" in s
    assert "+faststart" in s and "scale=-2:360" in s
    assert "expr:gte(t,n_forced*2)" in s                    # 2초마다 키프레임
    assert "-crf" not in s                                  # CRF 는 크기 예측 불가


def test_pick_scan_source_prefers_master():
    """scan 은 사람이 **재생**하는 영상 — 마스터 우선(F-206). 프록시로 뜨면 4fps 를
    물려받아 끊긴다. 스프라이트용 pick_scrub_source(프록시 우선)와 반대가 맞고,
    반환은 항상 튜플 — 호출부가 언팩하므로 None 을 돌려주면 안 된다."""
    from ves.adapters.editor_assets import pick_scan_source
    assert pick_scan_source("/m.mp4", "/runs/x/작품_480.mp4") == ("/m.mp4", True)
    assert pick_scan_source(None, "/runs/x/작품_480.mp4") \
        == ("/runs/x/작품_480.mp4", False)
    assert pick_scan_source(None, None) == (None, False)


def test_scan_cmd_fps_and_budget_follow_source():
    """fps 필터는 마스터 소스일 때만 — 4fps 프록시에 fps=24 를 걸면 같은 그림을
    여섯 번 복제해 비트레이트만 낭비한다(F-206). fps 는 scale 보다 앞 — 버릴
    프레임까지 스케일하지 않는다. 용량 예산도 소스를 따른다(폴백은 150MB)."""
    from ves.adapters.editor_assets import scan_cmd, scan_bitrate_kbps, SCAN_FPS
    hq = " ".join(scan_cmd("/m.mp4", "/tmp/scan.mp4", 2829, fps=SCAN_FPS))
    lo = " ".join(scan_cmd("/runs/x/작품_480.mp4", "/tmp/scan.mp4", 2829,
                           target_mb=150))
    assert f"fps={SCAN_FPS},scale=-2:360" in hq             # fps 먼저 — 스케일 낭비 방지
    assert "fps=" not in lo                                 # 폴백은 소스 fps 그대로
    assert f"-b:v {scan_bitrate_kbps(2829, 150)}k" in lo    # 폴백은 낮은 예산으로 역산


def test_editor_draft_recovery_contract():
    """F-302: 성공하면 지우고 실패하면 남긴다 — 0050 은 제출 시 draft_sent_at 만 찍고,
    성공 청소는 새 카드를 만드는 post_success 가 한다. 재제출은 rejected 카드 중
    '보낸 초안 있음 + 새 waiting 카드 없음' 만."""
    import pathlib
    sql = pathlib.Path("ves/control/migrations/0050_editor_draft_recovery.sql").read_text(encoding="utf-8")
    assert "draft_sent_at" in sql and "IN ('waiting','rejected')" in sql
    assert "draft=NULL" not in sql.replace(" ", "")            # 제출은 초안을 지우지 않는다
    assert "status = 'waiting'" in sql                         # 카드 닫기는 waiting 만
    brain = pathlib.Path("ves/adapters/brain.py").read_text(encoding="utf-8")
    assert "draft_sent_at IS NOT NULL" in brain                # 성공 청소는 post_success
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edResubmit" in html and "edRetryChain" in html
    assert "실패 지점부터 재시도" in html                     # 인프라 실패의 정석 복구
    assert '"retry_editor_chain"' in html
    assert "retry_editor_chain" in sql                         # 0050 의 재시도 RPC


def test_dashboard_rerender_progress_and_continue():
    """F-301·F-304: 제출 후 편집실에 남아 체인(editrender:*)을 표적 폴링으로 보여주고,
    새 카드가 오면 그 자리에서 잇는다 — 전체 refresh 는 video·편집 상태를 파괴한다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edChainPoll" in html and '"editrender:" + edChain.rid' in html
    assert "방금 렌더 결과 열기" in html and "edOpenNew" in html  # F-304 — refresh 후 열기
    assert "outerHTML = edChainHtml()" in html               # 부분 갱신(무렌더)
    assert '"dead", "cancelled", "blocked"' in html          # failed 외 종단 상태 인지
    assert "edForm.sent" in html                             # 제출 후 초안 부활 방지


def test_tts_from_checkpoints_carries_audio_file():
    """F-204: cue 에 합성 mp3 경로(file/path)가 있으면 미리듣기용으로 실어 나른다 —
    경로 필드가 없는 구 스키마는 그대로(미리듣기만 빠지고 편집실은 정상)."""
    from ves.adapters.editor_assets import tts_from_checkpoints
    res = {"tts_cue_files": [
        {"file": "tts_000.mp3",
         "cue": {"source_time_sec": 10, "text": "가", "start_sec": 1, "end_sec": 3}},
        {"cue": {"source_time_sec": 20, "text": "나"}}]}
    out = tts_from_checkpoints(res, None)
    assert out[0].get("file") == "tts_000.mp3"
    assert "file" not in out[1]


def test_dashboard_tts_preview_and_conflicts():
    """F-204 미리듣기(저장된 합성본만 — 새 문구는 재렌더 후) · F-205 충돌 검사(자막↔
    내레이션 겹침·원본 구간 중복·창 경계 이탈)."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edTtsPlay" in html and '"key": c.key' not in html  # 키는 timeline.tts 에서
    assert "edConflicts" in html and "ttsClash" in html
    assert "재렌더 후 합성" in html                            # 정직한 라벨
    sql = pathlib.Path("ves/control/migrations/0049_editor_tts_audio.sql").read_text(encoding="utf-8")
    assert "tts_gen" in sql and ">= 1" in sql                  # 세대 마커 캐시 판정


def test_dashboard_editor_preview_modes():
    """P2-a: 완성본 preview.mp4 재생(F-201, 서버 작업 0)·가상 시퀀스(F-202)·
    제목·자막·내레이션 오버레이(F-203). 오버레이는 근사임을 화면에 명시한다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edStageSet" in html and "edPrevKey" in html      # 완성본/가상 모드 전환
    assert "edSeqToggle" in html and "edSeqTick" in html     # 가상 시퀀스 재생
    assert 'id="edov"' in html and "edStagePaint" in html    # 오버레이 레이어
    assert "근사 미리보기" in html                           # 정직한 라벨


def test_dashboard_editor_shorts_stage():
    """편집실 개편: 좌측은 쇼츠 스테이지(9:16 완성본 화면), 원본 스크럽 플레이어는
    원본 타임라인 아래로 — 두 플레이어가 분리돼 각자 소스·세대표를 가진다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert 'class="edstage"' in html and 'id="edvid"' in html   # 좌측 9:16 스테이지
    assert "object-fit:cover" in html                           # 16:9 소스 중앙 크롭
    assert 'id="edsrcv"' in html and "edsrcstrip" in html       # 원본은 타임라인 아래
    assert "edMountStage" in html and "edMountSrc" in html      # 플레이어 분리 마운트
    assert "edStageLoad" in html and "edStageGen" in html       # 스테이지 전용 로더+세대표
    assert "edStageSeeking" in html                             # 파일 전환 중 틱 오염 방지
    assert "edStageBtnsSync" in html                            # 모드 전환 무렌더 갱신


def test_0057_images_open_contract():
    """0057(F-408 완성): images 개방 — 검증(배열·객체·file 거절·key prefix·png/jpg·
    범위) + 빈 배열=전량 삭제(병합 후 키 제거) + 편집 항목 목록 포함 + prev_images
    노출 + 0056 정책 webp 제거. 어댑터엔 F-409 title_y_fixed 스위치."""
    import pathlib
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.submit_editor_render")
    assert "빈 배열 = 이미지 전부 삭제" in sql
    assert "images[].file 은 어댑터가 만드는 값입니다" in sql      # PR #28 M2 서버측 방어
    assert "NOT LIKE 'editor_uploads/%'" in sql                    # 0056 prefix 정합
    assert r"\.(png|jpe?g)$" in sql                                # 엔진 dc1060f 실측
    assert "v_ov := v_ov - 'images'" in sql                        # 빈 배열 → 병합 후 제거
    assert "편집 항목(title/subtitles/clips/design/tts/images)" in sql
    assert "'images', jsonb_array_length" in sql                   # audit 건수
    req = _live_mig("CREATE OR REPLACE FUNCTION public.request_editor_assets")
    assert req.count("'prev_images', v_gen.prev_images") == 2      # 캐시·신규 두 반환 모두
    assert "j.params->'edit_overrides'->'images'" in req
    mig = pathlib.Path("ves/control/migrations/0057_editor_images_open.sql") \
        .read_text(encoding="utf-8")
    assert r"\.(png|jpg|jpeg)$" in mig and "webp" not in \
        mig.split("ves_reviewer_upload_editor_images ON storage.objects")[-1]
    from ves.adapters import aivideo
    assert aivideo.CHANNEL_DESIGN_SWITCHES["title_y_fixed"] == ("--design-title-y-fixed", True)


def test_editor_image_upload_policy_0056():
    """F-408 파트 1: 브라우저→스토리지 쓰기 표면 최초 신설 — reviewer 이상,
    ves-outputs 의 editor_uploads/ prefix, 이미지 확장자만. INSERT 뿐(불변 업로드)."""
    import pathlib
    sql = pathlib.Path("ves/control/migrations/0056_editor_image_upload.sql") \
        .read_text(encoding="utf-8")
    assert "FOR INSERT" in sql and "FOR UPDATE" not in sql and "FOR DELETE" not in sql
    assert "public.has_role(auth.uid(), 'reviewer')" in sql
    assert "name LIKE 'editor_uploads/%'" in sql
    assert r"\.(png|jpg|jpeg|webp)$" in sql
    assert "bucket_id = 'ves-outputs'" in sql


def test_aivideo_localize_edit_images(tmp_path):
    """F-408 어댑터: images[].key(스토리지) → run_dir 상대 file 치환. 엔진은 로컬만
    받는다(계약) — prefix 밖 키·키 없음은 즉시 실패(fail-loud), 재시도 재진입(file
    이미 있음)은 재다운로드 없이 통과한다."""
    import pytest
    from ves.adapters import aivideo, base
    calls = []
    ov = {"title": {"top_title": "t"},
          "images": [{"key": "editor_uploads/r1/a.png", "source_time_sec": 743.0,
                      "duration_sec": 3.0, "x": 0.1, "y": 0.2, "w": 0.3}]}
    out = aivideo.localize_edit_images(ov, tmp_path, lambda k, d: calls.append((k, d)))
    assert calls and calls[0][0] == "editor_uploads/r1/a.png"
    assert out["images"][0]["file"] == "editor_images/00_a.png"
    assert "key" not in out["images"][0]              # 엔진 계약엔 key 가 없다
    assert "key" in ov["images"][0]                   # 원본 dict 은 불변(사본 반환)
    assert out["title"] == {"top_title": "t"}         # 다른 키는 그대로
    # 허용 prefix 밖·경로 탈출·키 없음 → 즉시 실패
    with pytest.raises(base.PermanentError):
        aivideo.localize_edit_images(
            {"images": [{"key": "outputs/r1/x.png"}]}, tmp_path, lambda k, d: None)
    with pytest.raises(base.PermanentError):
        aivideo.localize_edit_images(
            {"images": [{"key": "editor_uploads/../x.png"}]}, tmp_path, lambda k, d: None)
    with pytest.raises(base.PermanentError):
        aivideo.localize_edit_images({"images": [{"x": 0.1}]}, tmp_path, lambda k, d: None)
    # file 은 어댑터 산출물 — 클라이언트가 실어 보내면 prefix 검증 우회라 즉시 거절
    with pytest.raises(base.PermanentError):
        aivideo.localize_edit_images(
            {"images": [{"file": "editor_images/00_a.png"}]}, tmp_path, lambda k, d: None)
    with pytest.raises(base.PermanentError):
        aivideo.localize_edit_images(
            {"images": [{"key": "editor_uploads/r1/a.png", "file": "final/preview.mp4"}]},
            tmp_path, lambda k, d: None)
    # run_dir 없음 — mkdir 가 만들어버리면 뒤따르는 fail-loud 가드가 무력화된다
    with pytest.raises(base.PermanentError):
        aivideo.localize_edit_images(ov, tmp_path / "없는run", lambda k, d: None)
    assert not (tmp_path / "없는run").exists()
    # 404 는 영구 오류(없는 키는 재시도해도 안 생긴다) · 그 외 오류는 재시도 대상 그대로
    def gone(k, d):
        raise RuntimeError("storage download 404: not found")
    with pytest.raises(base.PermanentError):
        aivideo.localize_edit_images(ov, tmp_path, gone)
    def flaky(k, d):
        raise RuntimeError("storage download 503: busy")
    with pytest.raises(RuntimeError):
        aivideo.localize_edit_images(ov, tmp_path, flaky)
    # images 없음 — 원본 그대로(다운로드 주입자도 안 부른다)
    same = {"title": {"top_title": "t"}}
    assert aivideo.localize_edit_images(same, tmp_path, gone) is same


def test_dashboard_editor_v3b_tracks():
    """V3-b: 완성본 타임라인 멀티트랙(V·자막·내레이션·이미지) — 블록 이동·트리밍·
    인스펙터. 자막 타이밍을 손대면 그 줄은 시각 고정(pin — 앵커를 빼고 보냄, 계약 내),
    내레이션·이미지는 출력→원본 절대초 역산(edSrcAtOut — 출력은 간극 없는 결합)."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert 'class="edlane v"' in html and 'class="edlane s"' in html   # 4레인
    assert "edOutElDown" in html and "edOutElApply" in html            # 이동·트리밍
    assert "edSrcAtOut" in html                                        # 출력→원본 역산
    assert "edSubOutPos" in html                                       # 자막 출력좌표 단일 규약
    assert "edInspHtml" in html and "edInspSet" in html                # 인스펙터
    assert "edInspRepin" in html                                       # 앵커 복원
    # pin 규약: 앵커를 빼고 보낸다 + 초안 왕복 + 경고 목록 합류 + 고아 검사 제외
    assert "s.src != null && !s.pin" in html
    assert "if (forDraft && s.pin) o.pin = true;" in html
    assert "(s.src == null || s.pin)" in html
    assert "s.src == null || s.pin) return;" in html
    # 길이(끝)만 고친 편집도 dirty — end 비교가 있어야 인스펙터 길이 편집이 나간다
    assert "Math.abs(s.end - edForm.subs[i].end) > 0.001" in html
    # 리뷰 반영(V3-b 2차): 초안 신원(i0 — 시각 매칭은 타이밍 편집에 깨짐), 트랙 삭제
    # 라우팅(Delete = 보이는 선택 우선), v2 잠금 게이트, 길이 밖 고정 줄 가시화
    assert "o.i0 = i" in html and "x.i0 === i" in html
    assert "if (edOutSel && edOutSelObj()){" in html
    assert "edSubsTimingLocked" in html
    assert '"oob"' in html and ".edoel.oob" in html
    # 드래그 동결 가드 — V 구간 드래그와 같은 규약
    assert html.count("edDrag = { out: true }") >= 2


def test_dashboard_editor_jp3_parity():
    """JP-3a: 일본 채널 편집실 KR 동등화(대시보드 단독분) — 완성본 타임라인 레인,
    같은 카드 재진입 폼 보존, undo/redo, 체인 새로고침 복구, 텔롭 use:false 삭제,
    설명(description_ja) 편집, 겹침 경고, tts 타이밍 표시 전용(엔진이 거절 — E6 전)."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    # 같은 카드 재진입 = 안 보낸 편집 보존(무조건 리셋이 편집을 증발시키던 것)
    assert "if (!edJpForm || edJpForm.rid !== rid){" in html
    # 타임라인: 자막·텔롭은 편집, 내레이션은 표시 전용(ro)
    assert 'lane(f.subs, "sub", "osub", "s", "자막", true)' in html
    assert 'lane(f.tts, "tts", "ocue", "n", "내레이션", false)' in html
    assert 'lane(f.telops, "tel", "otel", "i", "텔롭", true)' in html
    assert "edJpTlDown" in html and "edJpInspFlush();" in html
    # tts 타이밍은 폼에 startCur/endCur 자체가 없고(계약 안전장치), 수집도 끈다
    assert "rich(f.tts, false, false, false)" in html
    tts_map = html.split("tts: (pr.tts || []).map", 1)[1].split("telops:", 1)[0]
    assert "startCur" not in tts_map and "endCur" not in tts_map
    # 소프트 삭제 — use:false(0038 원계약)는 다른 diff 를 이긴다. 행 ✕ 는
    # 자막·텔롭 공용 edJpDel (KR 동등화 — test_dashboard_editor_jp_subs_kr_parity)
    assert "tel[s.idx] = { use: false };" in html
    assert "window.edJpDel" in html
    # undo/redo + keydown JP 분기(기존 가드가 edForm 없음으로 전체 침묵하던 것).
    # 리뷰 반영: edJpMode(KR 화면 오발동 방지)·edJpDrag(드래그 찢김 방지) 가드,
    # 스냅샷은 스타일·타이밍·삭제만(텍스트는 네이티브 undo — 타이핑 소실 방지)
    assert "edJpUndoStk" in html and "window.edJpUndoOp" in html
    assert "if (edJpMode && edJpForm && !edJpDrag" in html
    snap = html.split("function edJpSnapJson()", 1)[1].split("}\n", 2)[0]
    assert "titleCur" not in snap and "s.cur" not in snap
    # KR 카드 경유가 JP 폼을 지우지 않는다(무경고 전량 소실 — 리뷰 high)
    assert "edJpForm 은 지우지 않는다" in html
    # 종결된 옛 체인 소생 금지(48h) + 겹침 검사는 최대 끝 스윕
    assert '["pending", "running", "blocked"].includes(j.status)' in html
    assert "if (rows[k].b > mb){ mb = rows[k].b; mi = rows[k].i; }" in html
    # undo·삭제의 render 가 재생 위치를 보존한다
    assert "edJpSeekTo = jv.currentTime" in html or "edJpSeekTo = jv0.currentTime" in html
    # 체인 새로고침 복구 — 멱등키는 rid/vid 만으로 재구성(0038 정본)
    assert "async function edJpChainRecover(r)" in html
    assert "else edJpChainRecover(r0);" in html
    # 설명 편집 + 한국어 병기(제목·설명·행 아래 ko 는 기존 유지, 검수함 내레이션 쌍 추가)
    assert "ed.description_ja = f.descCur;" in html
    assert 'grab("jpdesc", f.desc, v => f.descCur = v, true);' in html
    assert '내레이션 ${pr.tts.length}건' in html          # 검수함 병기에 tts 추가
    # 겹침 경고 + 시각 입력 빈 문자열 가드(Number("")=0 이 시작을 0 으로 박던 것)
    assert "function edJpConflicts()" in html
    assert 'String(v).trim() === "" || !isFinite(num) || num < 0' in html


def test_dashboard_editor_jp_subs_kr_parity():
    """JP-3b(사용자 요청 8/20): 일본어 편집 행을 KR 자막 행과 완전 동일하게 —
    .edsub 재사용(시각 배지 클릭=완성본 이동 · ✎ 그 줄 스타일 · ✕ 삭제/되살리기),
    '비우면 그 줄이 빠집니다'(KR 의미). 유일한 추가는 입력 바로 아래 한국어 원문.
    자막 use:false 존중은 엔진 몫(E6-0)이라 신형 배포 표식(edJpStyleOn)과 함께
    연다(구 엔진 조용한 무시 방지) — 텔롭 ✕ 는 0038 원계약이라 게이트 없음."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    # KR 행 부품 재사용 — JP 전용 행 CSS(.jprow·.jptm)는 제거됐다
    assert ".jprow" not in html and ".jptm" not in html
    assert ".edsub .jpcol" in html and ".edsub .ko" in html
    # 시각 배지·✎·✕ — KR edSeek/edSubStage/edDelSub 상당
    assert "window.edJpSeek" in html and "window.edJpSubStage" in html
    assert "window.edJpDel" in html and "edJpTelDel" not in html
    assert "edJpDel('${t}',${s.idx})" in html
    # 수집: 삭제·비움 = use:false(삭제가 다른 diff 를 이긴다) · 비움 판정은 원문이
    # 있던 줄만 · 자막은 게이트 뒤
    assert 'const emptied = s => String(s.ja || "").trim() && !String(s.cur || "").trim();' \
        in html
    assert "if (s.del || emptied(s)) subs[s.idx] = { use: false };" in html
    # 유령 자막이 뺀 줄을 건너뛰고, 스냅샷(Cmd+Z)이 자막 삭제도 되돌린다
    assert "if (s.del) return false;" in html
    snap = html.split("function edJpSnapJson()", 1)[1].split("});", 1)[0]
    assert snap.count("d: !!s.del") == 2
    # 타임라인 선택 블록 Delete(KR 과 동일) + 삭제 시 선택 해제
    assert "edJpDel(edJpTlSel.t, edJpTlSel.i)" in html
    assert "if (s.del && edJpTlSel && edJpTlSel.t === t && edJpTlSel.i === idx)" in html


def test_editor_uploads_gc_plan():
    """업로드 GC 순수 판정 — 2회 스캔 규칙: 처음 본 고아는 기록만, 유예 지나
    연속 미참조 확인된 키만 삭제, 다시 참조되면 사면."""
    import datetime as dt

    from ves.scheduler.editor_uploads_gc import plan
    now = dt.datetime(2026, 8, 20, tzinfo=dt.timezone.utc)
    g = dt.timedelta(days=14)
    old = now - dt.timedelta(days=15)
    fresh = now - dt.timedelta(days=1)
    keys = ["editor_uploads/r/a.png", "editor_uploads/r/b.png",
            "editor_uploads/r/c.png", "editor_uploads/r/d.png"]
    protected = ["editor_uploads/r/a.png"]
    marked = {"editor_uploads/r/b.png": old,        # 유예 경과 고아 → 삭제
              "editor_uploads/r/c.png": fresh,      # 아직 유예 중 → 대기
              "editor_uploads/r/a.png": old,        # 다시 참조됨 → 사면
              "editor_uploads/r/gone.png": old}     # 실물 사라짐 → 대장 정리
    pardon, mark, due = plan(keys, protected, marked, now, g)
    assert pardon == ["editor_uploads/r/a.png", "editor_uploads/r/gone.png"]
    assert mark == ["editor_uploads/r/d.png"]       # 첫 목격 — 기록만, 삭제 없음
    assert due == ["editor_uploads/r/b.png"]
    # 첫 스캔(대장 비었음)은 무조건 삭제 0 — 1회 판정 금지의 형태 그 자체
    pardon, mark, due = plan(keys, [], {}, now, g)
    assert due == [] and len(mark) == 4 and pardon == []


def test_0061_editor_uploads_gc_contract():
    """0056 후속 GC 계약: 보호 술어는 단일 문장(스냅샷 경합 방지), cancelled 포함
    전 비성공 상태 + 작업지시별 최신 succeeded 보호, 세그먼트 역산 금지(정확한
    키 대조만), 삭제 먼저·대장 정리 나중, 스케줄러 등록."""
    import pathlib

    from ves.scheduler.editor_uploads_gc import BUCKET, PREFIX, PROTECTED_SQL
    assert BUCKET == "ves-outputs" and PREFIX == "editor_uploads/"
    # 한 문장: 세미콜론 없음 + 잡 갈래(UNION 앞)와 초안 갈래가 같은 문장에
    assert ";" not in PROTECTED_SQL and "UNION" in PROTECTED_SQL
    assert "gen.status <> 'succeeded' OR gen.id IN (SELECT id FROM latest_ok)" \
        in PROTECTED_SQL                              # cancelled 포함 전 비성공 보호
    assert "DISTINCT ON (work_order_id)" in PROTECTED_SQL
    assert "ORDER BY work_order_id, created_at DESC" in PROTECTED_SQL  # 0055 규약
    assert "ea.draft->'images'" in PROTECTED_SQL
    assert PROTECTED_SQL.count("LIKE 'editor_uploads/%'") == 2
    sql = pathlib.Path("ves/control/migrations/0061_editor_upload_orphans.sql") \
        .read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS public.editor_upload_orphans" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql         # 정책 없음 = 대시보드 비노출
    src = pathlib.Path("ves/scheduler/editor_uploads_gc.py").read_text(encoding="utf-8")
    assert "삭제 먼저, 대장 정리는 성공분만" in src
    # 스냅샷→삭제 사이 재참조 창: due 는 삭제 직전 보호 술어로 한 번 더 걸러진다
    assert "due = [k for k in due if k not in alive]" in src
    assert src.find("plan(keys, protected, marked") < src.find("if k not in alive")
    main_src = pathlib.Path("ves/scheduler/main.py").read_text(encoding="utf-8")
    assert "editor_uploads_gc.run(conn, cfg)" in main_src
    assert '_due_daily(last.get("editor_uploads_gc"), now, 6)' in main_src


def test_dashboard_editor_inspector_flush():
    """JP-1 L3: 인스펙터 onchange 커밋은 트랙 mousedown(preventDefault + 동기
    innerHTML 교체)에 blur 기회를 뺏겨 타이핑이 소실된다 — 선택 교체 전 플러시.
    리뷰 반영: 빈 입력(Number("")=0)·표시값 경계(toFixed 부동소수) 무행동,
    잠금 토스트는 실변경 시도에만, 재그림은 제스처 종료 후 지연 render."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "function edInspFlush()" in html
    assert "if (!edInspSet(a.id.slice(-1), a.value, true)) return;" in html
    assert "window.edInspSet = (k, v, quiet)" in html
    # 인스펙터를 파괴하는 세 제스처 전부에서, 선택 교체 **전에** 플러시
    assert html.count("edInspFlush();") == 3
    for fn in ("edOutElDown", "edOutDown", "edClipDown"):
        body = html.split(f"window.{fn} = (ev", 1)[1][:400]
        flush = body.find("edInspFlush()")
        assert 0 <= flush < body.find("ev.preventDefault()"), fn
    fset = html.split("window.edInspSet = (k, v, quiet)", 1)[1]
    fset = fset.split("window.edInspRepin", 1)[0]
    # 빈 입력 = 무행동(0 커밋 방지) — 유효성 가드가 잠금 토스트보다 앞
    assert 'String(v).trim() === ""' in fset
    # 표시 표현(toFixed(2)) 그대로면 무변화 — 경계값(예: 10.375→"10.38")이
    # 부동소수로 < 0.005 가드를 뚫고 앵커 자막을 조용히 pin 하면 안 된다
    assert "num === +cur.toFixed(2)" in fset
    # 잠금 안내는 무변화 가드 뒤 — 포커스만 얹은 플러시가 토스트를 남발하지 않게
    assert fset.find("cur.toFixed(2)") < fset.find("edSubsTimingLocked()")
    # quiet(플러시) 커밋은 render 를 즉시 부르지 않고, 부분 패치로 흉내내지도
    # 않는다(OOB 특수 배치·충돌색은 전체 재그림만이 진실) — 제스처 종료 후 지연
    assert "if (!quiet) render();" in fset and "el.style.left" not in fset
    assert 'document.addEventListener("mouseup",' in html
    assert "setTimeout(() => { if (!edDrag) render(); }, 0), { once: true });" in html


def test_0060_editor_templates_contract():
    """F-508: 쇼츠 템플릿 — 읽기는 authenticated RLS, 쓰기는 reviewer RPC 만.
    저장 = 유효 디자인 스냅샷, 적용 = 편당 오버라이드 통째 교체(화면). 리뷰 반영:
    목록은 state 밖(refresh 의 state 재구성이 지우던 H1), 선택 유지, 저장·적용
    양쪽 화이트리스트(채널 정체성 키가 타 채널로 새던 M2), 서버 크기 상한."""
    import pathlib
    sql = pathlib.Path("ves/control/migrations/0060_editor_templates.sql") \
        .read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS public.editor_templates" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FOR SELECT TO authenticated" in sql
    assert sql.count("has_role(auth.uid(),'reviewer')") == 2   # save·delete 둘 다
    assert "템플릿 이름은 1~40자" in sql
    assert "pg_column_size(p_design) > 16384" in sql
    assert "ON CONFLICT (name) DO UPDATE" in sql               # 같은 이름 = 덮어쓰기
    assert "_audit('template_save'" in sql and "_audit('template_delete'" in sql
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edTplApply" in html and "edTplSave" in html and "edTplDelete" in html
    assert 'rpc("save_editor_template"' in html and 'rpc("delete_editor_template"' in html
    # H1: 목록은 state 가 아니라 모듈 변수 — refresh() 의 state 통재구성에 안 지워진다
    assert "let edTpls = [], edTplLoaded = false, edTplSel = " in html
    assert "state.edTemplates" not in html
    # M2: 저장·적용 모두 화이트리스트 경유(edTplPick) — 통째 교체는 그 안에서
    assert "edForm.design = edTplPick(t.design);" in html
    assert "p_design: edTplPick(edDesign())" in html
    assert 'concat(["title_y_fixed"])' in html                 # 드래그 산물도 템플릿 대상
    # M1: 선택이 render 마다 첫 항목으로 리셋되지 않는다
    assert 'onchange="edTplSel=this.value"' in html
    assert 't.name === edTplSel ? " selected" : ""' in html
    # 목록 로드 실패는 알리되(무음 금지) 재시도 루프는 안 만든다
    assert "템플릿 목록을 못 불러왔습니다" in html
    assert "edTplLoaded = true;" in html


def test_zanmang_review_meta_ja_events(tmp_path):
    """JP-2(E5): B/BJ 자막 쌍에 ja_events.json 의 타이밍·스타일을 entry_idx 로 합류.
    없으면(구 산출) 텍스트만 — 카드 등록은 계속돼야 한다."""
    import json
    from ves.adapters import zanmang
    (tmp_path / "translations.json").write_text(json.dumps({
        "entries": [{"source": "가", "target": "ア"}, {"source": "나", "target": "イ"}]
    }), encoding="utf-8")
    (tmp_path / "ja_events.json").write_text(json.dumps({
        "events": [{"entry_idx": 1, "start": 2.0, "end": 5.5,
                    "style": {"size": 52}, "end_fixed": False},
                   {"entry_idx": None, "start": 9.0, "end": 10.0}]   # 미매칭은 버린다
    }), encoding="utf-8")
    meta = zanmang.review_meta(tmp_path)
    subs = meta["ko_ja_pairs"]["subs"]
    assert subs[0] == {"idx": 0, "ko": "가", "ja": "ア"}              # 이벤트 없음 = 텍스트만
    assert subs[1]["start"] == 2.0 and subs[1]["end"] == 5.5
    assert subs[1]["style"] == {"size": 52}
    # ja_events 가 깨져도 조용히 텍스트만 — 카드 등록이 죽으면 안 된다.
    # 문법 오류뿐 아니라 **형태 오염**(최상위 배열, entry_idx 비정수)도 못 죽인다(리뷰 3)
    for bad in ("{broken", '[{"entry_idx": 1}]', '{"events": [{"entry_idx": [1]}]}'):
        (tmp_path / "ja_events.json").write_text(bad, encoding="utf-8")
        meta2 = zanmang.review_meta(tmp_path)
        assert meta2["ko_ja_pairs"]["subs"][1] == {"idx": 1, "ko": "나", "ja": "イ"}, bad
    assert "ja_events.json" in zanmang.LOOPY_TEXT_FILES               # 지속화 목록 합류


def test_dashboard_editor_jp2_style_timing():
    """JP-2 화면: 유령 자막(타이밍 동기) 드래그·크기·색·회전 + 행 시각 입력.
    수집 값은 문자열(텍스트만) 또는 dict {ja?, style?, start_sec?, end_sec?} —
    전부 editor_jp_style 게이트(구 엔진은 ja 외 키를 조용히 무시)."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edJpStyleOn" in html and "editor_jp_style" in html        # 플래그 게이트
    assert "edJpPaint" in html and "edJpSubDragDown" in html          # 유령 자막
    assert "edJpSize" in html and "edJpColor" in html and "edJpRotate" in html
    # 시각 편집은 KR 처럼 타임라인·인스펙터로(행 시각 입력은 KR 동등화 때 배지로 교체)
    assert "edJpTime" in html and 'id="jpi_s"' in html and 'id="jpi_e"' in html
    # 수집: 텍스트만이면 종전 문자열(하위호환), 그 외 dict — 게이트 확인
    assert "o.start_sec = +(+s.startCur).toFixed(3)" in html
    # JP-3a: withTiming 파라미터 추가(tts 타이밍 전송 차단) — 플래그 게이트는 유지
    assert "if (edJpStyleOn() && withTiming !== false){" in html
    assert '(Object.keys(o).length === 1 && o.ja && !alwaysObj) ? o.ja : o' in html
    # y 시맨틱은 v3 와 동일(0=상단, 1=하단) — JP 기본값 0.87(하단 근사)과 (1−y) 환산
    assert "sty.y != null ? +sty.y : 0.87" in html
    # 리뷰 반영: 피커 arm(잘못된 줄 오염 방지), 편집 판정 단일화, diff 스타일의
    # 명시값 전송(rotate 0 유실 방지), 오염 ja_events 무해화
    assert "edJpColorArm" in html and "edJpEditable" in html
    assert "const has = k => sc[k] != null || base[k] != null;" in html


def test_dashboard_editor_v3c_frames():
    """V3-c: 프레임 단위 정밀 — 스냅 1/24s(edQF), 선택 블록 ←→ 프레임 이동(무렌더 —
    render 는 스테이지 video 를 파괴한다), 트랙 바닥 클릭 = 그 순간부터 가상 미리보기,
    인스펙터 프레임 번호, Esc 선택 해제."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "const ED_FPS = 24" in html and "edQF" in html
    assert "edQ20" not in html                       # 0.05s 스냅은 프레임 스냅으로 대체
    assert "edOutNudge" in html and "edOutClickTl" in html and "edOutSeek" in html
    assert 'ev.target.closest(".edoclip,.edoel")' in html   # 블록 클릭과 바닥 클릭 분리
    assert "Math.round(st.p * ED_FPS)" in html              # 인스펙터 프레임 표시
    assert "else if (edOutSel){ edOutSel = null; edOutSync(); }" in html


def test_0058_rotate_contract():
    """F-410 오케스트레이터 파트: 0058 이 images[].rotate 를 제출에서 검증(-180~180,
    숫자)하고, 화면은 editor_rotate 플래그 뒤에서만 회전을 만든다 — dc1060f 엔진은
    images 의 모르는 키를 조용히 무시하므로(회전 없이 나감) 전 노드 69e5c06 이 선행."""
    import pathlib
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.submit_editor_render")
    assert "images[].rotate 는 -180~180 도(숫자)여야 합니다" in sql
    # 0057 계약 보존(전문 재정의 회귀 방지 — 빈 배열 규약·file 거절·prefix)
    assert "빈 배열 = 이미지 전부 삭제" in sql
    assert "images[].file 은 어댑터가 만드는 값입니다" in sql
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edRotOn" in html and "editor_rotate" in html            # 플래그 게이트
    assert "edImgRotateDown" in html and "edImgRotateReset" in html # 이미지 ↻ 핸들
    assert "edOvRotate" in html                                     # 자막 줄 ↺↻
    # 수집: 이미지 rotate 클램프, 자막 style.rotate 정제(0 은 기본값이라 뺀다)
    assert "o.rotate = Math.max(-180, Math.min(180, Math.round(+m.rotate)))" in html
    assert "st.rotate = Math.max(-180, Math.min(180, Math.round(+s.style.rotate)))" in html
    # 미리보기 원점 = 중심(엔진 계약과 동일 — CSS 기본값), 회전 0 은 transform 제거
    assert 'rotate(${Math.round(+m.rotate)}deg)' in html
    assert 'rotate(${Math.round(+sub.style.rotate)}deg)' in html


def test_dashboard_editor_jp_mode():
    """JP-1: localization_qa 카드(SHOTCONE·잔망루피)의 편집실 — 서버·엔진 무변경.
    카드 payload(ko_ja_pairs)가 재료, 계약은 0038 reject_and_rerender 텍스트 치환
    (idx 좌표, diff 만 전송), 한국어 원문 병기. 재료 RPC 는 부르지 않는다(LOOPY 는
    작업지시가 없어 거절되는 카드)."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edJpKind" in html and "renderEditJp" in html and "edJpResetForm" in html
    assert "if (edJpMode){ renderEditJp(); return; }" in html   # KR 편집실과 분기
    assert 'rpc("reject_and_rerender"' in html                  # 0038 계약 재사용
    assert "p_edits: ed" in html
    # 편집실 단일화 — 인라인 수정 재렌더 패널은 제거됐다(계약은 edJpSubmit 이 승계)
    assert "rerenderPanel" not in html and "submitRerender" not in html
    assert "✏️ 수정 재렌더" not in html
    # KR 편집실과 같은 탭 구성 + 같은 제출 문구
    assert "edJpPane" in html and "edJpPaneHtml" in html
    assert "✏️ 고친 내용으로 다시 렌더" in html
    # 한국어 병기 + dirty diff — 행은 KR .edsub 재사용, ko 는 입력 바로 아래
    assert ".edsub .ko" in html and "jpko" in html
    assert "edJpCollect" in html and "edJpMark" in html
    # 잔망루피 카드에서 편집실 진입 가능 + 체인 폴링(잡 멱등키·새 카드 감지).
    # 멱등키는 0038 SQL 이 정본 — LOOPY 는 zanmang_rerender:<vid>:<review_id>
    assert "🎬 편집실" in html
    assert "edJpChainPoll" in html
    assert "zanmang_rerender:${f.vid}:${f.rid}" in html
    assert "zanmang_decide:" not in html.split("edJpChain = {")[1][:400]
    assert "rerender:${f.rid}" in html
    assert 'contains("payload", { zanmang_video_id: c.vid })' in html
    assert '.gt("created_at", c.sinceIso)' in html          # 옛 카드 오인 방지
    assert '"failed", "dead", "cancelled", "blocked"' in html  # KR 과 같은 종결 어휘
    # 새 카드 열기는 refresh 선행(edOpenNew) — stale state 로 KR 경로 추락 금지
    assert "edOpenNew('${c.newRid}')" in html
    # 입력은 폼(cur)에 산다 — 재렌더에도 타이핑 보존
    assert "titleCur" in html and "s.cur = v" in html
    # idx 없는 옛 텔롭 제외(좌표 안전 규약 — 인라인 패널 제거 후 JP 폼 한 곳)
    assert html.count("filter(x => x.idx != null)") >= 1


def test_dashboard_editor_images_wired():
    """F-408 화면: 업로드(0056 경로 규약)·스테이지 배치·수집·초안 왕복이 배선됐고,
    전부 editor_images 플래그 뒤에 있다(엔진 E2 배포 전에는 탭 자체가 안 보인다)."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edImagesOn" in html and "editor_images" in html      # 플래그 게이트
    assert "edImgUpload" in html and "editor_uploads/" in html   # 0056 경로 규약
    assert 'id="edovimgs"' in html and "edImgDragDown" in html   # 스테이지 배치
    assert "edImgResizeDown" in html                             # 모서리 크기
    # 수집: 제출은 key 만(어댑터가 file 로 치환), name·del 은 초안 전용.
    # 초안은 플래그와 무관(자동 저장이 이미지를 지우면 안 된다) · 달라졌을 때만 싣고
    # (그대로면 키 생략 = 승계) · 전량 삭제는 빈 배열(0057 규약)
    assert "if ((edImagesOn() || forDraft) && edImagesChanged()){" in html
    assert "key: m.key, source_time_sec:" in html
    assert 'o.name = m.name || ""' in html
    # 이전 라운드 이미지 시드(0057 prev_images) — 보여야 지울 수 있다
    assert "edPrevImages" in html and "prev_images" in html
    assert "images0: imgs0" in html
    # webp 는 업로드부터 막는다(엔진 png/jpg 만) · 자막 위/아래 layer 토글
    assert 'accept="image/png,image/jpeg"' in html and "image/webp" not in html
    assert "edImgLayer" in html
    # 업로드 키는 안전 문자만 — run_id 의 한글 작품명이 스토리지 "Invalid key" 를 냈다.
    # 점(.)도 제외 — 제목 "..." 가 키에 ".." 을 만들면 어댑터 경로 탈출 거절에 걸린다
    assert 'replace(/[^A-Za-z0-9_-]/g, "_")' in html
    # 스냅샷(undo)·초안 복원에 images 포함
    assert "images: edForm.images || []" in html
    assert "if (Array.isArray(d.images))" in html


def test_dashboard_editor_sub_style_wysiwyg():
    """F-407 화면: 스테이지에서 자막을 끌어 위치(y)·크기(size)·색(color)을 줄 단위로
    고친다 — 값은 subtitles[].style 로 나가고(v3 계약), 초안에도 왕복 저장된다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edSubDragDown" in html and "edStyleToolToggle" in html  # 드래그 + ✎ 토글
    assert "edSubSize" in html and "edSubColor" in html             # 크기·색
    assert "edSubStyleReset" in html                                # 채널 기본값 복귀
    # F-409(엔진 dc1060f): 제목 드래그 = title_y + title_y_fixed(고정 배치 전환)
    assert "edTitleDragDown" in html and "title_y_fixed: true" in html
    assert "edTitleAutoY" in html                                   # 자동 배치 복귀
    # 대상 선택형 도구(제목|자막|TTS) — 크기·색이 각 대상의 design/줄 style 로 간다
    assert 'id="edovselseg"' in html and "edOvPick" in html
    assert "edOvSize" in html and "edOvColor" in html and "edOvReset" in html
    # 가상 시퀀스 영상 밴드(V3-a) — 실제 렌더 수식 그대로: 높이 = 화면비, 위치 = video_y
    # (없으면 중앙), 밴드 안 cover 크롭. ⇕ 드래그·스타일 탭과 동기.
    assert "edStageBandGeom" in html and "edStageBandSync" in html
    assert "(rh / rw) * (1080 / 1920)" in html
    assert "edBandDragDown" in html
    assert '"aspect_ratio",     "영상 화면비"' in html
    assert 'classList.toggle("seqfit"' in html
    # v3 계약: style.y 는 0=상단, 1=하단(자막 하단 위치) — 화면은 bottom 이라 (1−y).
    # 기본값은 채널 subtitle_y_margin 역산. (첫 판의 '하단 비율' 해석은 상하 반전 버그)
    assert "edSubYDef" in html
    assert "1 - ((+d.subtitle_y_margin || 380) / 1920)" in html
    assert "(1 - yv) * 100" in html
    # TTS(내레이션) 자막 — 위치는 이 편 전체 공통(design.tts_y_margin, 하단 px 드래그)
    assert "edTtsDragDown" in html
    assert "tts_y_margin: Math.round(nb * 1920)" in html
    assert '"tts_y_margin"' in html or "'tts_y_margin'" in html or "edd_tts_y_margin" in html
    # 수집: 아는 키(size·y·color)만 정제해 싣는다 — 플래그 게이트 없음(전량 교체라
    # 빼면 스타일 있는 카드의 재제출이 스타일을 조용히 벗긴다)
    assert "if (s.style){" in html
    assert "st.size = Math.round(+s.style.size)" in html
    assert "st.y = +(+s.style.y).toFixed(4)" in html
    # 스타일 변경도 '자막이 달라졌다'로 판정 — 비교는 키 순서 무관 정규화(edStyleSig)
    assert "edStyleSig(s.style) !== edStyleSig(edForm.subs[i].style)" in html


def test_dashboard_editor_drag_and_output_track():
    """구간은 드래그로 다듬는다(F-102: 몸통 이동·양끝 트리밍 핸들·스냅·Alt 해제) —
    출력 타임라인(F-105)이 완성본 순서와 59.7초 상한을 그리고 순서 드래그를 받는다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edClipDown" in html and 'class="hL"' in html    # 몸통·핸들 드래그
    assert "edSnapSec" in html and "altKey" in html         # 스냅 + Alt 해제
    assert 'id="edouttl"' in html and "edOutDown" in html   # 출력 트랙 + 순서 드래그
    assert "edolim" in html and "edoover" in html           # 59.7초 상한선·초과 표시


def test_dashboard_editor_undo_and_soft_delete():
    """편집 실수 복구(F-104·F-106): Cmd+Z 스냅샷 스택 + 구간·자막 소프트 삭제.
    타이핑 스냅샷은 값이 바뀌기 **전**(beforeinput)에 잡아야 한다 — 바뀐 뒤에 잡으면
    그 타이핑은 영영 못 되돌린다. 제출 검증은 계약 필드명(start_sec/end_sec)으로."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "edUndoOp" in html and "edRedoOp" in html         # Cmd+Z / Shift+Cmd+Z
    assert 'e.code === "KeyZ"' in html
    assert "beforeinput" in html                             # 타이핑 스냅샷 시점
    assert "edRestoreClip" in html and "edRestoreSub" in html  # 소프트 삭제 되살리기
    assert "c.end_sec <= c.start_sec" in html                # 죽어 있던 제출 검증 소생
    assert "draftMismatch" not in html                       # 초안 복원은 start 매칭으로
    assert "edCollect(true)" in html                         # 초안엔 del 마커 포함 저장


def test_reuse_assets_partial_regen():
    """F-303: 재렌더 후 재생성에서 원본 불변 재료(전역 스프라이트·파형·scan)는
    재사용한다 — 단 길이·시트 수가 정확히 같고 scan 은 신 세대일 때만."""
    from ves.adapters.editor_assets import (reuse_assets, sprite_layout, scan_over_cap,
                                            SCAN_GEN, GLOBAL_INTERVAL, GRID, THUMB_W)
    def sp(dur, media):
        lay = sprite_layout(dur)
        return {"duration_sec": dur, "sprites": {
            "count": lay["count"], "interval": GLOBAL_INTERVAL, "grid": GRID,
            "thumb_w": THUMB_W,
            "assets": {"global": ["a/g_0.jpg"], "wave": "a/wave.png", "media": media}}}
    dur = 3600.0
    prev = sp(dur, {"scan": "a/scan.mp4", "scan_bytes": 100, "scan_gen": SCAN_GEN})
    r = reuse_assets(prev, dur)
    assert r["global"] == ["a/g_0.jpg"] and r["wave"] == "a/wave.png"
    assert r["scan"]["scan"] == "a/scan.mp4"
    assert reuse_assets(prev, dur + 5) == {}               # 길이 다르면 전부 재생성
    prev["sprites"]["grid"] = 8                            # 규격 상수가 다르면 좌표가 깨진다
    assert reuse_assets(prev, dur) == {}
    assert "scan" not in reuse_assets(
        sp(dur, {"scan": "a/scan.mp4", "scan_gen": 1}), dur)  # 구 세대 scan 재사용 금지
    # over_cap 마커: 길이 예측이 지금도 참일 때만 승계 — 잘못 박힌 마커는 재시도된다
    long_dur = 30000.0
    assert scan_over_cap(long_dur) and not scan_over_cap(dur)
    assert reuse_assets(sp(long_dur, {"scan_skip": "over_cap", "scan_gen": SCAN_GEN}),
                        long_dur)["scan"]["scan_skip"] == "over_cap"
    assert "scan" not in reuse_assets(
        sp(dur, {"scan_skip": "over_cap", "scan_gen": SCAN_GEN}), dur)


def test_0051_cache_accepts_scan_attempt():
    """0051(F-303): 상한 초과 run 은 '시도 마커'로 캐시를 인정한다 — 안 하면 5.7시간+
    원본이 열 때마다 재생성하고도 영상 없는 무한 루프(0045 의 418MB 실측 패턴)."""
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.request_editor_assets")
    assert "scan_skip" in sql and "OR v_ex.scan_skip IS NOT NULL" in sql
    assert "v_ex.tts_gen >= 1" in sql and "v_ex.scan_gen >= 2" in sql   # 기존 조건 유지
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "over_cap" in html                              # 상한 초과의 정직한 안내


def test_dashboard_editor_zoom_and_shortcuts():
    """편집실 타임라인은 줌·팬(F-101)과 키보드 단축키(F-103)를 갖는다 — [ 시작 버튼
    툴팁의 (I)/(O) 표기는 이제 실제 바인딩이다. 10등분 고정 눈금은 폐지."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert 'id="edtlc"' in html and "edZoomSet" in html      # 캔버스 + 줌
    assert "edDrawTicks" in html and "edTicks(" not in html  # 눈금 동적화(고정 10등분 제거)
    assert 'id="edmm"' in html and "edMmSync" in html        # 미니맵 + 뷰포트 동기화
    assert 'e.code === "KeyI"' in html                       # I/O 는 자판 위치 기준(한글 IME)
    assert 'k === " "' in html                               # Space 재생/정지
    assert "edSelSync" in html                               # 키보드 내비의 무렌더 하이라이트


def test_dashboard_scan_fps_label_reads_meta():
    """전체 훑기 라벨은 재료 메타(scan_fps)를 읽는다 — 구 재료(0048 전)엔 메타가
    없으므로 프록시 산출물은 4fps 로, 마스터 산출물은 fps 미상(숫자 없음)으로 폴백."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "scan_fps" in html
    assert "전체 훑기(4fps)" in html                        # 구 프록시 재료 폴백
    assert '=== "master"' in html                           # 구 마스터 재료는 숫자를 뺀다


def test_closeup_cmd_seeks_before_input_and_uses_duration():
    """-ss 는 입력 앞(빠른 탐색), 길이는 -t 로 입력 뒤 — -to 를 뒤에 두면 기준이 달라져
    엉뚱한 구간이 잘린다."""
    from ves.adapters.editor_assets import closeup_cmd
    a = closeup_cmd("/m.mp4", "/tmp/c0.mp4", 100.0, 160.0)
    i_in = a.index("-i")
    assert a.index("-ss") < i_in                            # 탐색은 입력 앞
    assert a.index("-t") > i_in and a[a.index("-t") + 1] == "60.000"
    s = " ".join(a)
    assert "fps=24" in s and "scale=-2:480" in s and "+faststart" in s
    assert "expr:gte(t,n_forced*2)" in s                    # 2초 키프레임 — 스크럽 seek


def test_closeup_cmd_fps_follows_source():
    """fps 필터는 마스터 소스일 때만 — 4fps 프록시에 fps=24 를 걸면 같은 그림을 여섯 번
    복제해 '정밀 구간(24fps)'을 사칭한다(scan 의 F-206 과 같은 결). fps 는 scale 보다
    앞 — 버릴 프레임까지 스케일하지 않는다. 키프레임은 프레임(-g)이 아니라 시간 기준 —
    폴백에선 소스 fps 를 모르는데 -g 48 이면 4fps 에서 GOP 12초가 된다."""
    from ves.adapters.editor_assets import closeup_cmd, CLOSEUP_FPS
    hq = " ".join(closeup_cmd("/m.mp4", "/tmp/c0.mp4", 100.0, 160.0))
    lo = " ".join(closeup_cmd("/runs/x/작품_480.mp4", "/tmp/c0.mp4", 100.0, 160.0,
                              fps=None))
    assert f"fps={CLOSEUP_FPS},scale=-2:480" in hq          # fps 먼저 — 스케일 낭비 방지
    assert "fps=" not in lo                                 # 폴백은 소스 fps 그대로
    assert "expr:gte(t,n_forced*2)" in lo and "-g " not in lo


def test_dashboard_closeup_fps_label_reads_meta():
    """클로즈업 라벨은 재료 메타(closeup_fps)를 읽는다 — 구 재료엔 메타가 없고, 폴백은
    scan 과 반대다: 마스터 산출물의 24 는 사실이지만 프록시 산출물의 24 는 거짓
    (4fps 프레임 복제)이라 closeup_source 로 갈라 4fps 로 바로잡는다."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    assert "closeup_fps" in html
    assert "정밀 구간(4fps)" in html                        # 구 프록시 재료 폴백
    assert "정밀 구간(24fps)" in html                       # 구 마스터 재료 폴백
    assert "closeup_source" in html                         # 폴백 판정 재료


def test_closeup_windows_merge_and_cap():
    """클립 앞뒤를 감싸 병합하되, 총합이 상한을 넘으면 **긴 것부터** 버린다 —
    남은 것이 촘촘한 구간이어야 편집에 쓸모가 있다."""
    from ves.adapters.editor_assets import closeup_windows
    clips = [{"start_sec": 100, "end_sec": 130}, {"start_sec": 200, "end_sec": 210},
             {"start_sec": 5000, "end_sec": 5020}]
    w = closeup_windows(clips, pad=90, duration_sec=6000)
    assert len(w) == 2                                       # 앞 둘은 병합(10~300)
    assert w[0] == {"start_sec": 10.0, "end_sec": 300.0}
    assert w[1] == {"start_sec": 4910.0, "end_sec": 5110.0}
    assert w[0]["start_sec"] >= 0                            # 0 아래로 안 내려간다
    capped = closeup_windows(clips, pad=90, duration_sec=6000, max_total=250)
    assert capped == [{"start_sec": 4910.0, "end_sec": 5110.0}]   # 290초짜리가 먼저 탈락
    # 끝이 원본 길이를 넘지 않는다
    assert closeup_windows([{"start_sec": 10, "end_sec": 20}], pad=90,
                           duration_sec=60)[0]["end_sec"] == 60.0


def test_pick_master_falls_back_to_none(tmp_path):
    """마스터가 GC 됐으면 None — 호출부가 프록시로 떨어진다(4fps 한계를 알고 쓴다)."""
    from ves.adapters.editor_assets import pick_master
    assert pick_master({"input": {"video_path": "/없는/경로.mp4"}}, str(tmp_path)) is None
    real = tmp_path / "m.mp4"; real.write_bytes(b"x")
    assert pick_master({"input": {"video_path": str(real)}}, str(tmp_path)) == str(real)
    assert pick_master({}, str(tmp_path)) is None


# ───────── 편집실 스타일(design 오버라이드) ─────────
def test_edit_design_merges_not_replaces():
    """편집실 스타일은 채널 디자인 **위에 얹는다**. 통째 교체하면 자막 크기 하나 고쳤다고
    채널 폰트·색이 기본값으로 돌아간다(채널 정체성 상실)."""
    from ves.adapters.aivideo import edit_design
    base = {"title_font": "채널폰트", "subtitle_size": 65, "subtitle_color": "#FFF"}
    got = edit_design(base, {"subtitle_size": 80})
    assert got == {"title_font": "채널폰트", "subtitle_size": 80, "subtitle_color": "#FFF"}
    assert base["subtitle_size"] == 65                    # 원본 불변(부작용 금지)
    # 빈 값은 '안 건드림' — 화면의 빈 입력칸이 기본값 강제로 둔갑하면 안 된다
    assert edit_design(base, {"subtitle_size": "", "title_font": None}) == base
    assert edit_design(base, None) is base
    assert edit_design(None, {"title_y": 120}) == {"title_y": 120}


def test_edit_design_keys_are_known_flags():
    """화면이 보내는 스타일 키는 전부 CLI 플래그로 번역돼야 한다 — 모르는 키가 오면
    어댑터가 PermanentError 를 내므로(registry 원칙) 화면 목록과 계약이 어긋나면 잡이 죽는다."""
    import pathlib, re
    from ves.adapters.aivideo import CHANNEL_DESIGN_FLAGS, channel_design_flags
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    block = html.split("const ED_STYLE_FIELDS = [", 1)[1].split("];", 1)[0]
    keys = re.findall(r'\["(\w+)"', block)
    assert keys, "화면 스타일 목록을 찾지 못했다"
    for k in keys:
        assert k in CHANNEL_DESIGN_FLAGS, f"화면이 보내는 {k!r} 를 어댑터가 모른다"
    # 실제로 argv 로도 나오는지(플래그 이름 오타 방어)
    flags = channel_design_flags({k: "1" for k in keys}, "TEST")
    assert len(flags) == len(keys) * 2


def test_dashboard_editor_v2_wired():
    """구간·자막·스타일 편집이 화면에 배선됐는지 — 특히 '구간을 바꾸면 자막은 안 보낸다'."""
    import pathlib
    html = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")
    for fn in ("edSourceAt", "edMountSrc", "edAddClip", "edDelClip", "edMove",
               "edAddSub", "edDelSub", "edStyleSet", "edParseTime"):
        assert fn in html, fn
    # 0054: v3 플래그가 꺼져 있으면 종전 잠금(구간 변경 시 자막 제외) 유지, 켜지면 앵커로 동시 편집
    assert "if (!clipsDirty || edV3()){" in html
    assert "closeups" in html and "scan" in html   # 두 층 프리뷰를 화면이 안다


def test_edit_subtitles_turn_captions_on():
    """자막을 고쳐 보내면 그 편만 --no-subtitles 를 뗀다.

    2026-08-17 실측: 활성 소스 486개가 전부 has_subtitle=false 라 모든 영상이
    --no-subtitles 로 렌더된다. 그 상태에서 편집실 자막 수정을 받으면 subtitles.ass 만
    바뀌고 mp4 는 그대로여서, 사람 눈에는 '고쳤는데 안 바뀌는' 버그로 보인다.
    사용자 결정: 평상시는 지금대로, 사람이 손대면 그 편만 켠다."""
    from ves.adapters.aivideo import build_argv_pure, subtitles_requested
    base = {"work_title": "피의 게임 X", "no_subtitles": True}
    assert "--no-subtitles" in build_argv_pure("/py", base, "/s.mp4")
    assert subtitles_requested(base) is False
    withsub = {**base, "edit_overrides": {"schema": "edit_overrides/v1",
                                          "subtitles": [{"start_sec": 0, "end_sec": 1,
                                                         "text": "고친 자막"}]}}
    assert subtitles_requested(withsub) is True
    assert "--no-subtitles" not in build_argv_pure("/py", withsub, "/s.mp4")
    # 제목·구간만 고친 요청은 종전대로(자막을 켜지 않는다)
    titleonly = {**base, "edit_overrides": {"schema": "edit_overrides/v1",
                                            "title": {"top_title": "새 제목"}}}
    assert subtitles_requested(titleonly) is False
    assert "--no-subtitles" in build_argv_pure("/py", titleonly, "/s.mp4")
    # 원래 자막이 켜진 작품은 아무 영향 없다
    assert "--no-subtitles" not in build_argv_pure("/py", {"work_title": "x"}, "/s.mp4")


def test_0045_cache_requires_editing_video():
    """캐시는 '있다/없다'가 아니라 '지금 화면이 요구하는 것을 갖췄는가'로 판정한다.

    2026-08-17 실측: 재료 6건 중 4건에 편집용 영상이 없고 1건은 상한 초과(418MB)였는데,
    옛 조건(ready + 만료 전)은 그것들을 전부 재사용해 **영상 없는 편집실**을 열었다.
    재료 구성이 늘 때마다 이 조건에 한 줄씩 붙인다."""
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.request_editor_assets")
    assert "0045" in sql, "request_editor_assets 의 라이브 정의가 0045 여야 한다"
    assert "v_ex.scan_key IS NOT NULL" in sql
    assert "v_ex.scan_bytes <= 400 * 1024 * 1024" in sql
    # 0042 계약은 유지 — 전문 재정의라 빠뜨리기 쉽다
    assert "has_role(auth.uid(),'reviewer')" in sql
    assert "작업지시 없는 카드는 편집실 대상이 아닙니다" in sql
    assert "'editor_assets:' || v_gen.run_id" in sql
    assert "ARRAY['generate', 'node:' || v_gen.node_id]" in sql
    assert "_audit('editor_open'" in sql


# ───────── 0053: 편집 라운드 누적 승계 ─────────
def test_0053_editor_overrides_carryover():
    """🛑 2026-08-19 실측(커리어데이_ae71b530): 1라운드 제목+구간 편집 후 2라운드에서
    내레이션만 고쳐 보냈더니 제목·구간이 초기 버전으로 되돌아갔다.

    화면은 '이번에 만진 키만' 보내고(설계), 엔진은 매 라운드 원본 체크포인트에서
    다시 시작한다. 따라서 RPC 가 직전 generate 의 edit_overrides 를 **키 단위로
    승계**한 위에 새 오버라이드를 얹어야 라운드가 누적된다. 예외: 새 payload 에
    clips 가 있는데 subtitles 가 없으면 승계 subtitles 는 버린다 — 자막 좌표는
    편집본 시간축이라 구간이 바뀌면 통째로 어긋난다."""
    sql = _live_mig("CREATE OR REPLACE FUNCTION public.submit_editor_render")
    # 승계 원본: 직전 generate 잡의 edit_overrides (schema 스탬프는 벗겨서)
    assert "coalesce(v_gen.params->'edit_overrides', '{}'::jsonb) - 'schema'" in sql
    # 새 값이 이긴다 — 승계분 || 새 payload 순서여야 한다
    assert "v_ov := v_prev || p_overrides" in sql
    # 0059 개정: 구간이 바뀌어도 승계 자막을 버리지 않는다 — 앵커 줄은 재매핑되고,
    # 앵커 없는 줄(신규·시각 고정)은 사람이 정한 값이다(V3-b). 0054 의 '앵커만 생존'
    # 필터는 고정 줄을 소리 없이 지우는 구멍이라 제거됐다.
    assert "사람이 의도한 고정 시각" in sql
    assert "p_overrides ? 'clips' AND NOT p_overrides ? 'subtitles'" not in sql
    # 감사에 승계 키가 남아야 한다 — '왜 이 값이 들어갔나'를 추적할 유일한 곳
    assert "'carried'" in sql


# ───────── storage_gc — 편집실 접두사 행의 실물 확장 (2026-08-19) ─────────
def test_gc_expand_keys_expands_prefix_rows():
    """'/' 로 끝나는 카탈로그 행은 실물 목록으로 확장, 정확한 키는 그대로 —
    Storage delete 가 이름 정확 일치만 지우기 때문(접두사 그대로면 조용한 무동작)."""
    from ves.scheduler.storage_gc import expand_keys
    listed = {"ab12/editor/": ["ab12/editor/g_000.jpg", "ab12/editor/scan.mp4"]}
    calls = []

    def lister(p):
        calls.append(p)
        return listed.get(p, [])

    items = [{"object_key": "cd34/shorts.mp4"},
             {"object_key": "ab12/editor/"},
             {"object_key": "ef56/editor/"}]           # 이미 비어 있는 접두사
    keys = expand_keys(items, lister)
    assert keys == ["cd34/shorts.mp4", "ab12/editor/g_000.jpg", "ab12/editor/scan.mp4"]
    assert calls == ["ab12/editor/", "ef56/editor/"]   # 정확한 키는 조회하지 않는다


def test_storage_page_keys_joins_prefix_and_finds_folders():
    """list 응답의 name 은 잎 이름뿐 — prefix 를 붙여 완전한 키로. id 가 null 인 행은
    가상 폴더라 하위 접두사로 돌려준다(재귀 조회 대상)."""
    from ves.storage.supabase_storage import page_keys
    batch = [{"name": "g_000.jpg", "id": "u1"},
             {"name": "tts0.mp3", "id": "u2"},
             {"name": "sub", "id": None},
             {"name": "", "id": "u3"}]                 # 방어: 이름 없는 행은 버린다
    keys, subdirs = page_keys("ab12/editor/", batch)
    assert keys == ["ab12/editor/g_000.jpg", "ab12/editor/tts0.mp3"]
    assert subdirs == ["ab12/editor/sub/"]
    assert page_keys("ab12/editor", batch)[0] == keys  # 슬래시 유무 무관


def test_gc_run_expands_lists_and_batches():
    """run 배선 검사 — 접두사 확장(list_keys) 없이 delete 로 직행하면 0042 무동작이
    재발한다. 확장 결과는 DELETE_BATCH 로 나눠 보낸다."""
    import inspect
    from ves.scheduler import storage_gc
    src = inspect.getsource(storage_gc.run)
    assert "expand_keys" in src and "list_keys" in src
    assert "DELETE_BATCH" in src


def test_catalog_upsert_extends_ttl():
    """재워밍(0045/0048)이 화면 TTL 을 다시 밀 때 카탈로그 TTL 도 같이 밀려야 한다 —
    DO NOTHING 이면 GC(수선 후 실동작)가 화면이 아직 쓰는 재료를 지운다."""
    import inspect
    from ves.adapters import editor_assets
    src = inspect.getsource(editor_assets._catalog)
    assert "ON CONFLICT (sha256, kind) DO UPDATE" in src
    assert "excluded.expires_at" in src
    assert "ON CONFLICT (sha256, kind) DO NOTHING" not in src


def test_drive_watch_use_limit_from_work_card():
    """작품 카드 use_limit 이 드라이브 등록 한도를 정한다 (가왕쇼 10, 2026-08-19).

    길이 비례 기본은 '30분↑ 3편' 이라 47분짜리 경연물도 3편에서 막힌다. 작품별 예외는
    brain works.json 이 정본 — 스케줄러에 하드코딩하지 않는다.
    """
    from ves.scheduler.drive_watch import use_limit_of, DEFAULT_USE_LIMIT
    cards = {"가왕쇼": {"use_limit": 10}, "도깨비 10주년 여행": {}}
    assert use_limit_of(cards, "가왕쇼") == 10
    # 카드에 없으면 종전값 — 다른 작품의 동작이 바뀌면 안 된다
    assert use_limit_of(cards, "도깨비 10주년 여행") == DEFAULT_USE_LIMIT
    assert use_limit_of(cards, "없는작품") == DEFAULT_USE_LIMIT
    # 외부폴더 모드는 작품명이 None 이다
    assert use_limit_of(cards, None) == DEFAULT_USE_LIMIT
    # 잘못된 값은 조용히 기본값으로 — set_source_limit 과 같은 0<v<=20 범위
    for bad in ("열", None, 0, -1, 21):
        assert use_limit_of({"X": {"use_limit": bad}}, "X") == DEFAULT_USE_LIMIT
    assert use_limit_of({"X": {"use_limit": "10"}}, "X") == 10   # JSON 문자열도 받아준다
    assert use_limit_of(None, "가왕쇼") == DEFAULT_USE_LIMIT     # 카드 로드 실패
