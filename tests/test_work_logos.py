from ves.adapters.work_logos import logoish, need_folder_reason, order, parse_drive_link, sniff


def test_parse_drive_link():
    assert parse_drive_link("다운로드: <a href='https://drive.google.com/drive/folders/1nbob1KhTt-x68xKUKb8P8GoHfo2uqKSj?usp=x'>") == \
        ("folder", "1nbob1KhTt-x68xKUKb8P8GoHfo2uqKSj")
    assert parse_drive_link("https://drive.google.com/file/d/13jl66cvM83h3_WWDNVWbtmhizi-Qqtrx/view") == \
        ("file", "13jl66cvM83h3_WWDNVWbtmhizi-Qqtrx")
    assert parse_drive_link("https://drive.google.com/open?id=1nkECbVZKvldPIf6wknPZFXVs06xS2dd1&usp=drive_fs") == \
        ("open", "1nkECbVZKvldPIf6wknPZFXVs06xS2dd1")
    assert parse_drive_link("") == (None, None) and parse_drive_link(None) == (None, None)


def test_sniff():
    assert sniff(b"\x89PNG\r\n\x1a\n0000") == ("image/png", "png")
    assert sniff(b"\xff\xd8\xff\xe0") == ("image/jpeg", "jpg")
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("image/webp", "webp")
    assert sniff(b"GIF89a") is None and sniff(b"8BPS") is None


def test_logoish_and_order():
    assert logoish("홍보물/로고_화이트.png") and logoish("etc/LOGO-old.jpg") and logoish("타이틀/세로.png")
    assert logoish("brand/CI_white.png") and not logoish("스틸컷/still_01.jpg")
    got = order([{"path": "b/still.jpg", "logoish": False}, {"path": "z/로고.png", "logoish": True},
                 {"path": "a/still.jpg", "logoish": False}])
    assert [c["path"] for c in got] == ["z/로고.png", "a/still.jpg", "b/still.jpg"]


def test_need_folder_reason():
    assert "링크가 없어요" in need_folder_reason(None, False)
    assert "파일 하나" in need_folder_reason("file", False)
    assert "이미 다 넣었어요" in need_folder_reason("folder", True)
    assert "찾지 못했어요" in need_folder_reason("open", False)
