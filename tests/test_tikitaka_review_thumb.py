"""발행용 썸네일을 예약 업로드 때 같이 넣기(tikitaka_review.put_publish_thumb)."""
import os
import subprocess

from ves.adapters import tikitaka_review as R


class _Cur:
    def __init__(self, row): self.row = row
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a): pass
    def fetchone(self): return self.row


class _Conn:
    def __init__(self, row): self.row = row
    def cursor(self): return _Cur(self.row)


def test_no_pick_means_nothing_to_do():
    assert R.put_publish_thumb(None, _Conn({"publish": None}), "v", "yt", "t") is None
    assert R.put_publish_thumb(None, _Conn(None), "v", "yt", "t") is None


def test_small_png_goes_as_is(tmp_path):
    p = tmp_path / "thumb_1.png"
    p.write_bytes(b"\\x89PNG" + b"0" * 100)
    assert R.thumb_file(str(p), str(tmp_path)) == (str(p), "image/png")


def test_big_file_becomes_jpeg_under_2mb(tmp_path):
    src = tmp_path / "big.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=3840x2160,noise=alls=100:allf=t", "-frames:v", "1", str(src)], check=False)
    if not src.exists() or os.path.getsize(src) <= R.THUMB_MAX:
        import pytest; pytest.skip("큰 PNG 를 만들지 못함")
    out, ctype = R.thumb_file(str(src), str(tmp_path))
    assert ctype == "image/jpeg" and os.path.getsize(out) <= R.THUMB_MAX
