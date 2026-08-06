#!/usr/bin/env python3
"""Supabase Storage 클라이언트 — 워커/스케줄러용 (service key, RLS 우회).

노드가 다루는 파일은 shorts(25MB)·preview(6MB)·마스터 다운로드 — 업로드는 표준 POST 로 충분.
마스터 업로드(2.9GB)는 대시보드→브라우저 TUS 경로(§9-2)라 여기 없다.
대시보드(브라우저)는 이 모듈이 아니라 supabase-js + RLS + createSignedUrl 을 쓴다(R12).
"""
from __future__ import annotations


class Store:
    def __init__(self, url: str | None, service_key: str | None):
        if not (url and service_key):
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY 필요 (secrets/ves.env)")
        self.base = url.rstrip("/") + "/storage/v1"
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def upload(self, bucket: str, key: str, path: str) -> None:
        import requests
        with open(path, "rb") as f:
            r = requests.post(f"{self.base}/object/{bucket}/{key}",
                              headers={**self.headers, "x-upsert": "true",
                                       "Content-Type": "application/octet-stream"},
                              data=f, timeout=600)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"storage upload {r.status_code}: {r.text[:200]}")

    def download(self, bucket: str, key: str, dest: str) -> None:
        import requests
        with requests.get(f"{self.base}/object/{bucket}/{key}",
                          headers=self.headers, stream=True, timeout=3600) as r:
            if r.status_code != 200:
                raise RuntimeError(f"storage download {r.status_code}: {r.text[:200]}")
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)

    def signed_url(self, bucket: str, key: str, expires_sec: int = 900) -> str:
        import requests
        r = requests.post(f"{self.base}/object/sign/{bucket}/{key}",
                          headers=self.headers, json={"expiresIn": expires_sec}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"storage sign {r.status_code}: {r.text[:200]}")
        return self.base.rsplit("/storage/v1", 1)[0] + "/storage/v1" + r.json()["signedURL"]

    def delete(self, bucket: str, keys: list) -> None:
        import requests
        r = requests.delete(f"{self.base}/object/{bucket}",
                            headers=self.headers, json={"prefixes": keys}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"storage delete {r.status_code}: {r.text[:200]}")
