"""L-P3b — 소재 선별기의 판단을 고정한다.

이 파일이 지키는 것은 세 가지다:
  ① 이미 올린 것·내용 중복은 **절대** 후보가 안 된다 (사용자 지시)
  ② 차단은 사람이 뒤집을 수 있고, 게이트 0 은 못 뒤집는다
  ③ '옛날 것부터'가 순위로 지켜진다 (diversity)
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ves.scheduler import loopy_picker  # noqa: E402
from ves.scheduler.loopy_picker import (  # noqa: E402
    combine_scores, denylist_hit, diversity_signal, gate_block, like_norm, log_norm,
    rank, score_row, season_ok, timing_signal, warn_penalty,
)

TODAY = dt.date(2026, 8, 23)


def _row(**kw):
    base = {"video_id": "v1", "state": "discovered", "duration_sec": 45.0,
            "title": "루피 먹방", "view_count": 100000, "like_count": 5000,
            "published_at": dt.date(2025, 1, 1)}
    base.update(kw)
    return base


# ── ① 이미 올린 것은 절대 안 나온다 ────────────────────────────────────
def test_uploaded_is_excluded():
    assert gate_block(_row(state="uploaded"), today=TODAY) == "이미 발행됨"


def test_publish_history_excludes_even_if_state_looks_fresh():
    """상태가 어긋나도 발행 이력이 있으면 후보가 아니다 — 이중 안전장치."""
    assert "발행" in gate_block(_row(youtube_id="abc123"), today=TODAY)


def test_content_duplicate_is_excluded():
    r = gate_block(_row(dup_of="old_vid"), today=TODAY)
    assert "내용 중복" in r and "old_vid" in r


def test_allowed_by_cannot_override_gate_zero():
    """사람이 허용해도 이미 올린 것은 못 되살린다 — 게이트 0 은 뒤집을 수 없다."""
    assert gate_block(_row(state="uploaded", allowed_by="사람"), today=TODAY) == "이미 발행됨"


def test_busy_and_terminal_states():
    assert "진행 중" in gate_block(_row(state="processing"), today=TODAY)
    assert "제외됨" in gate_block(_row(state="skipped"), today=TODAY)


def test_out_of_spec_length():
    assert "규격 밖" in gate_block(_row(duration_sec=None), today=TODAY)
    assert "규격 밖" in gate_block(_row(duration_sec=120.0), today=TODAY)
    assert gate_block(_row(duration_sec=61.0), today=TODAY) is None      # 경계 포함


def test_clean_row_passes():
    assert gate_block(_row(), today=TODAY) is None


# ── ② 게이트 1 — 차단과 뒤집기 ─────────────────────────────────────────
def test_denylist_matches_ignoring_spaces_and_case():
    assert denylist_hit("루피 X 브랜드 콜라보", ["X브랜드"]) == "X브랜드"
    assert denylist_hit("깨끗한 제목", ["X브랜드"]) is None


def test_denylist_blocks():
    assert "차단 목록" in gate_block(_row(title="루피 콜라보 편"),
                                  denylist=["콜라보"], today=TODAY)


def test_rights_flags_block():
    for flag in ("collab", "sponsored", "music", "event"):
        r = gate_block(_row(flags={flag: True}), today=TODAY)
        assert r and flag in r, flag


def test_warning_flags_do_not_block():
    """topical·wordplay 는 경고다 — 막지 않고 뒤로 민다."""
    assert gate_block(_row(flags={"topical": True, "wordplay": True}), today=TODAY) is None
    assert warn_penalty({"topical": True, "wordplay": True}) == 0.20


def test_out_of_season_blocks_but_in_season_passes():
    xmas = _row(flags={"seasonal": True, "season": "christmas"})
    assert "철 지난" in gate_block(xmas, today=dt.date(2026, 8, 23))
    assert gate_block(xmas, today=dt.date(2026, 12, 20)) is None


def test_season_window_wraps_the_year():
    """연말·연시 창이 해를 넘어도 맞아야 한다."""
    assert season_ok("newyear", dt.date(2026, 12, 28)) is True
    assert season_ok("newyear", dt.date(2026, 1, 10)) is True
    assert season_ok("newyear", dt.date(2026, 6, 1)) is False


def test_unknown_season_is_not_judged():
    assert season_ok(None, TODAY) is True
    assert season_ok("모르는철", TODAY) is True


def test_person_can_overturn_gate_one():
    """LLM 이 막은 것은 사람이 뒤집을 수 있다."""
    blocked = _row(flags={"collab": True})
    assert gate_block(blocked, today=TODAY) is not None
    assert gate_block({**blocked, "allowed_by": "운영자"}, today=TODAY) is None


# ── ③ 순위 — '옛날 것부터'를 지킨다 ────────────────────────────────────
def test_diversity_favours_unused_periods():
    recent = [dt.date(2026, 8, 1), dt.date(2026, 7, 20)]
    near = diversity_signal(dt.date(2026, 8, 5), recent)
    far = diversity_signal(dt.date(2024, 1, 1), recent)
    assert far > near


def test_diversity_neutral_without_history():
    assert diversity_signal(dt.date(2024, 1, 1), []) == 1.0
    assert diversity_signal(None, [dt.date(2026, 1, 1)]) == 0.5


def test_missing_signal_is_renormalized_not_zeroed():
    """댓글이 꺼진 영상이 '나쁘다'로 밀리면 안 된다."""
    w = {"a": 0.5, "b": 0.5}
    assert combine_scores({"a": 1.0, "b": None}, w) == 1.0
    assert combine_scores({"a": 1.0, "b": 0.0}, w) == 0.5


def test_signal_normalizers():
    assert log_norm(0, 100) == 0.0
    assert log_norm(100, 100) == 1.0
    assert like_norm(5, 100) == 1.0          # 5% = 상한
    assert like_norm(0, 100) == 0.0


def test_timing_neutral_without_season_tag():
    assert timing_signal({}, TODAY) == 0.5
    assert timing_signal({"seasonal": True, "season": "christmas"},
                         dt.date(2026, 12, 25)) == 1.0


def test_score_returns_breakdown_for_human_review():
    """점수만 보여주면 사람이 승인할 근거가 없다."""
    score, parts = score_row(_row(), max_views=200000, today=TODAY)
    assert 0.0 <= score <= 1.0
    assert "views" in parts and "like_ratio" in parts


def test_warning_flags_lower_the_score():
    clean, _ = score_row(_row(), max_views=200000, today=TODAY)
    warned, _ = score_row(_row(flags={"wordplay": True}), max_views=200000, today=TODAY)
    assert warned < clean


# ── 전체 순위 ───────────────────────────────────────────────────────────
def test_rank_splits_picked_and_blocked_with_reasons():
    rows = [_row(video_id="ok", view_count=200000),
            _row(video_id="dup", dup_of="ok"),
            _row(video_id="done", state="uploaded")]
    picked, blocked = rank(rows, today=TODAY)
    assert [p["video_id"] for p in picked] == ["ok"]
    assert {b["video_id"] for b in blocked} == {"dup", "done"}
    assert all(b["block_reason"] for b in blocked)      # 사유가 항상 있다


def test_rank_orders_by_score_and_caps_top_n():
    rows = [_row(video_id=f"v{i}", view_count=1000 * (i + 1)) for i in range(8)]
    picked, _ = rank(rows, today=TODAY, top_n=3)
    assert len(picked) == 3
    assert picked[0]["score"] >= picked[-1]["score"]


def test_rank_is_deterministic_on_ties():
    rows = [_row(video_id="b"), _row(video_id="a")]
    picked, _ = rank(rows, today=TODAY)
    assert [p["video_id"] for p in picked] == ["a", "b"]


# ── DB 층 — 순수하지 않은 자리에서 지켜야 할 것 ─────────────────────────
class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self._rows: list = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.log.append((" ".join(sql.split()), params))
        self._rows = self.conn.answers.pop(0) if self.conn.answers else []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.log: list = []

    def cursor(self):
        return _Cur(self)


def test_disabled_switch_touches_nothing():
    """enabled=false 면 후보를 읽지도 않는다 — 켜는 것은 사람이다."""
    conn = _Conn([[{"value": '{"enabled": false}'}]])
    loopy_picker.run(conn, {})
    assert len(conn.log) == 1                      # 설정 한 번만 읽었다


def test_broken_config_does_not_enable():
    """깨진 JSON 이 '켜짐'으로 읽히면 사람 모르게 돈다."""
    assert loopy_picker.merge_config("{{ 깨짐").get("enabled") is False
    assert loopy_picker.merge_config(None) == loopy_picker.DEFAULTS


def test_candidates_exclude_terminal_and_busy_states():
    """게이트 0 의 절반은 SQL 이 진다 — 진행 중·발행 완료는 읽지도 않는다."""
    conn = _Conn([[]])
    loopy_picker.load_candidates(conn, "LOOPY")
    sql, params = conn.log[0]
    assert "NOT (state = ANY(%s))" in sql
    states = params[1]
    assert "uploaded" in states and "processing" in states and "approved" in states


def test_write_results_never_pushes_past_scored():
    """🛑 선별기가 상태를 selected 이상으로 밀면 사람 승인 전에 체인이 돈다."""
    conn = _Conn()
    loopy_picker.write_results(conn, [{"video_id": "a", "score": 0.9, "scores": {}}], [])
    sql, _ = conn.log[0]
    assert "'scored'" in sql
    assert "selected" not in sql and "processing" not in sql


def test_write_results_only_touches_undecided_rows():
    """사람이 손댄 편(skipped·selected…)을 선별기가 되돌리면 안 된다."""
    conn = _Conn()
    loopy_picker.write_results(conn, [{"video_id": "a", "score": 0.5, "scores": {}}],
                               [{"video_id": "b", "block_reason": "차단"}])
    for sql, _ in conn.log:
        assert "state IN ('discovered','scored')" in sql


def test_every_clean_row_gets_a_score_but_only_top_n_is_promoted():
    """점수는 정렬 재료(전량), 추천은 상태(상위). 상위만 점수를 가지면 '점수순'이
    top_n 개짜리 목록이 되어 아카이브를 훑는 쓸모가 없다."""
    rows = [{"video_id": f"v{i}", "score": 1.0 - i / 10, "scores": {}} for i in range(5)]
    conn = _Conn()
    loopy_picker.write_results(conn, rows, [], top_n=2)
    assert len(conn.log) == 5                        # 전부 점수를 받는다
    promote = [params[2] for _, params in conn.log]  # CASE WHEN %s …
    assert promote == [True, True, False, False, False]


def test_dropping_out_of_top_n_takes_the_recommendation_away():
    """어제 추천이던 편이 오늘 밀리면 추천 표시가 걷혀야 한다 — 안 걷으면 추천이 쌓인다."""
    conn = _Conn()
    loopy_picker.write_results(conn, [{"video_id": "a", "score": 0.1, "scores": {}}], [], top_n=0)
    sql, _ = conn.log[0]
    assert "WHEN NOT %s AND state = 'scored' THEN 'discovered'" in sql


def test_blocked_row_loses_its_score():
    """사유가 붙었는데 점수가 남아 있으면 추천 정렬에 다시 올라온다."""
    conn = _Conn()
    loopy_picker.write_results(conn, [], [{"video_id": "b", "block_reason": "콜라보"}])
    sql, params = conn.log[0]
    assert "score = NULL" in sql and params[0] == "콜라보"


def test_recent_published_reads_original_dates():
    """다양성 신호의 재료는 **원본 공개일**이지 우리 발행일이 아니다."""
    conn = _Conn([[]])
    loopy_picker.recent_published_dates(conn, "LOOPY")
    sql, _ = conn.log[0]
    assert "SELECT published_at" in sql
    assert "state = 'uploaded' OR youtube_id IS NOT NULL" in sql


def test_run_writes_both_picked_and_blocked():
    conn = _Conn([
        [{"value": '{"enabled": true, "channel_slug": "LOOPY", "top_n": 2}'}],
        [{"value": "[]"}],                                    # denylist
        [_row(video_id="ok", view_count=90000),                # 후보
         _row(video_id="dup", dup_of="ok")],
        [],                                                   # recent_published
    ])
    loopy_picker.run(conn, {})
    updates = [s for s, _ in conn.log if s.startswith("UPDATE")]
    assert len(updates) == 2                                  # 추천 1 + 제외 1
