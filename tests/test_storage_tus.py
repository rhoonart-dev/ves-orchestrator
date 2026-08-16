#!/usr/bin/env python3
"""TUS 메타데이터 형식 회귀 방지 — 8/13 실측: ', ' 구분자가 400 Invalid upload-metadata."""
import base64
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ves.storage.supabase_storage import tus_metadata  # noqa: E402


def test_tus_metadata_comma_no_space():
    md = tus_metadata("ves-sources", "masters/abc")
    assert ", " not in md, "구분자에 공백 금지 — Supabase 가 400 으로 거부한다(8/13 실측)"
    pairs = md.split(",")
    # 5쌍(8/15): bucketName·objectName·contentType·cacheControl + upsert —
    # upsert 는 TUS 커밋의 409(기존 객체 충돌)를 막는 재시도 멱등의 핵심이라 빠지면 안 된다.
    assert len(pairs) == 5
    kv = dict(p.split(" ", 1) for p in pairs)
    assert not any(k.startswith(" ") for k in kv), "키 앞 공백 = Invalid upload-metadata"
    assert base64.b64decode(kv["bucketName"]).decode() == "ves-sources"
    assert base64.b64decode(kv["objectName"]).decode() == "masters/abc"
    assert base64.b64decode(kv["upsert"]).decode() == "true"
