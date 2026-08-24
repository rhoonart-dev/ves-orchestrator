"""L-P3 — 외부 쇼츠 아카이브 수집기의 순수 로직.

수집기는 YouTube 를 읽고 아카이브를 쓴다. 여기서 고정하는 것은 **판단**뿐이다 —
길이 분류·중복 판정·설정 병합. 네트워크·DB 는 대상이 아니다.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ves.scheduler.loopy_scout import (  # noqa: E402
    DEFAULTS, classify_kind, find_duplicates, merge_config, normalize_title,
    parse_iso8601_duration, shorts_playlist_id,
)


# ── 길이 파싱 (vlp 에서 이식 — 값까지 그대로) ──────────────────────────
def test_parse_duration():
    assert parse_iso8601_duration("PT1M3S") == 63.0
    assert parse_iso8601_duration("PT59S") == 59.0
    assert parse_iso8601_duration("P0D") == 0.0            # 라이브
    assert parse_iso8601_duration("P1DT2H3M4S") == 93784.0
    assert parse_iso8601_duration("") is None
    assert parse_iso8601_duration("garbage") is None


def test_shorts_playlist_trick():
    assert shorts_playlist_id("UCabc123") == "UUSHabc123"


def test_shorts_playlist_rejects_bad_id():
    import pytest
    with pytest.raises(ValueError):
        shorts_playlist_id("PLabc")


# ── 두 선반 (수집기는 하나, 선반이 둘) ──────────────────────────────────
def test_classify_short_and_longform():
    assert classify_kind(45.0) == "short"
    assert classify_kind(61.0) == "short"                  # 경계 포함
    assert classify_kind(61.1) == "longform"
    assert classify_kind(1800.0) == "longform"


def test_classify_rejects_unknown_and_tiny():
    """길이 미상이 쇼츠 선반에 섞이면 고른 뒤에야 규격 밖인 걸 안다 — fail-closed."""
    assert classify_kind(None) is None
    assert classify_kind(0.0) is None                      # 라이브 잔재
    assert classify_kind(2.0) is None


def test_classify_respects_custom_threshold():
    assert classify_kind(70.0, shorts_max_sec=90.0) == "short"


# ── 중복 판정 (§5-7 — 원장이 못 막는 구멍) ─────────────────────────────
def test_normalize_title_drops_hashtags_wholesale():
    """`#` 만 지우면 `#shorts` 가 `shorts` 로 남아 원본과 안 맞는다 — 단어째 걷어낸다."""
    assert normalize_title("루피 먹방 #shorts #귀여움") == normalize_title("루피 먹방")


def test_normalize_title_strips_noise():
    assert normalize_title("잔망루피 (재업로드)") == normalize_title("잔망루피재업로드")
    assert normalize_title("A  B") == normalize_title("a-b")
    assert normalize_title("루피 🍜 먹방") == normalize_title("루피먹방")


def test_finds_reupload_with_same_title_and_length():
    rows = [{"video_id": "old", "title": "루피 먹방", "duration_sec": 45.0,
             "published_at": "2024-01-01T00:00:00Z"},
            {"video_id": "new", "title": "루피 먹방 #shorts", "duration_sec": 46.0,
             "published_at": "2026-01-01T00:00:00Z"}]
    assert find_duplicates(rows) == {"new": "old"}          # 나중 것이 중복으로 표시된다


def test_earlier_upload_is_the_original():
    """'먼저 올라온 것'이 원본이다 — 순서가 뒤집히면 이미 올린 편을 원본으로 오인한다."""
    rows = [{"video_id": "b", "title": "같은 제목", "duration_sec": 30.0,
             "published_at": "2026-05-05T00:00:00Z"},
            {"video_id": "a", "title": "같은 제목", "duration_sec": 30.0,
             "published_at": "2024-01-01T00:00:00Z"}]
    assert find_duplicates(rows) == {"b": "a"}


def test_same_title_different_length_is_not_duplicate():
    rows = [{"video_id": "a", "title": "루피", "duration_sec": 30.0,
             "published_at": "2024-01-01T00:00:00Z"},
            {"video_id": "b", "title": "루피", "duration_sec": 55.0,
             "published_at": "2026-01-01T00:00:00Z"}]
    assert find_duplicates(rows) == {}


def test_unknown_length_is_never_a_duplicate():
    rows = [{"video_id": "a", "title": "루피", "duration_sec": None,
             "published_at": "2024-01-01T00:00:00Z"},
            {"video_id": "b", "title": "루피", "duration_sec": None,
             "published_at": "2026-01-01T00:00:00Z"}]
    assert find_duplicates(rows) == {}


def test_empty_title_is_skipped():
    rows = [{"video_id": "a", "title": "", "duration_sec": 10.0},
            {"video_id": "b", "title": "   ", "duration_sec": 10.0}]
    assert find_duplicates(rows) == {}


def test_three_reuploads_all_point_at_the_first():
    rows = [{"video_id": f"v{i}", "title": "같은 것", "duration_sec": 20.0,
             "published_at": f"202{i}-01-01T00:00:00Z"} for i in range(3)]
    assert find_duplicates(rows) == {"v1": "v0", "v2": "v0"}


# ── 설정 병합 ───────────────────────────────────────────────────────────
def test_config_defaults_are_off():
    """수집기는 사람이 켠다 — 기본 off."""
    assert merge_config(None)["enabled"] is False
    assert DEFAULTS["enabled"] is False


def test_config_merge_and_unknown_keys_ignored():
    cfg = merge_config('{"enabled": true, "handle": "@other", "junk": 1}')
    assert cfg["enabled"] is True and cfg["handle"] == "@other"
    assert "junk" not in cfg
    assert cfg["channel_slug"] == DEFAULTS["channel_slug"]   # 안 준 값은 기본


def test_broken_config_falls_back_to_defaults():
    """설정 오류가 관제를 막지 않는다 — 수집이 안 돌 뿐이다."""
    assert merge_config("{not json") == DEFAULTS
    assert merge_config("[1,2]") == DEFAULTS
