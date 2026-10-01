import pytest

from ves.adapters.tikitaka_review import client_env_names, inspection_marker, youtube_body


def test_client_env_names():
    assert client_env_names(None) == ("YT_CLIENT_ID", "YT_CLIENT_SECRET")
    assert client_env_names("DEFAULT") == ("YT_CLIENT_ID", "YT_CLIENT_SECRET")
    assert client_env_names("P2") == ("YT_CLIENT_ID_P2", "YT_CLIENT_SECRET_P2")


def test_youtube_body_unlisted_for_inspection():
    b = youtube_body({"title": "남편 지갑 뜯어\n위치추적기 심은 아내", "description": "설명", "tags": ["#쿠팡플레이", " ", "김혜수"]}, "unlisted", None)
    assert b["snippet"]["title"] == "남편 지갑 뜯어 위치추적기 심은 아내"
    assert b["snippet"]["tags"] == ["쿠팡플레이", "김혜수"]
    assert b["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}


def test_youtube_body_schedule_is_private_with_publish_at():
    b = youtube_body({"title": "t"}, "private", "2026-10-03T10:00:00Z")
    assert b["status"]["privacyStatus"] == "private" and b["status"]["publishAt"] == "2026-10-03T10:00:00Z"


def test_youtube_body_limits_and_never_public():
    b = youtube_body({"title": "가" * 150, "tags": [str(i) for i in range(30)]}, "unlisted", None)
    assert len(b["snippet"]["title"]) == 100 and len(b["snippet"]["tags"]) == 15
    with pytest.raises(ValueError):
        youtube_body({"title": "t"}, "public", None)


def test_inspection_marker_is_stable():
    m = inspection_marker("1199da3a-8a1a-4a2d-aba5-1e9ba06318bd", "2ec7b7a4814c38beacd4d181751cf350")
    assert m == "[VES tikitaka 1199da3a-8a1a-4a2d-aba5-1e9ba06318bd 2ec7b7a4814c]"
