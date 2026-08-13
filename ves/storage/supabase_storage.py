#!/usr/bin/env python3
"""Supabase Storage 클라이언트 — 워커/스케줄러용 (service key, RLS 우회).

업로드는 두 경로다(2026-08-13):
  · 표준 POST — shorts(25MB)·preview(6MB)·마스터 ~4.5GB. 단순하고 수백 회 검증됨.
  · TUS 재개형 — 4.5GB 초과 마스터. 표준 POST 는 5GB 가 게이트웨이 하드캡이라
    피의 게임 X 마스터(회당 5GB↑)가 전부 413 으로 죽었다(8/13 실측, 배치 전멸 → dead).
    6MB 청크 PATCH + 끊기면 HEAD 로 오프셋 조회 후 이어올림 — 대용량 장시간 전송에서
    한 번의 네트워크 딸꾹질로 수 GB 를 재전송하지 않는다.
전제: 프로젝트 전역 업로드 한도(대시보드 Storage 설정)가 파일보다 커야 한다 — 8/13 상향 완료.
대시보드(브라우저)는 이 모듈이 아니라 supabase-js + RLS + createSignedUrl 을 쓴다(R12).
"""
from __future__ import annotations

import base64
import os
import time

TUS_THRESHOLD = 4_500_000_000   # 이 크기부터 TUS. 표준 POST 는 4.73GB 까지 실증(그 아래는 종전 경로 유지)
TUS_CHUNK = 6 * 1024 * 1024     # Supabase TUS 계약: 마지막을 제외한 청크는 6MB 고정
TUS_RETRIES = 5                 # 청크 전송 실패 시 HEAD 재조회 → 이어올림 횟수


def use_tus(size_bytes) -> bool:
    """이 크기면 TUS 로 올려야 하는가. 순수 — 테스트 대상."""
    try:
        return int(size_bytes) >= TUS_THRESHOLD
    except (TypeError, ValueError):
        return False


def tus_metadata(bucket: str, key: str, content_type: str = "application/octet-stream") -> str:
    """TUS Upload-Metadata 헤더값(키 공백 b64 쌍, 콤마 구분). 순수 — 테스트 대상."""
    def b64(v: str) -> str:
        return base64.b64encode(v.encode("utf-8")).decode("ascii")
    return ", ".join([f"bucketName {b64(bucket)}", f"objectName {b64(key)}",
                      f"contentType {b64(content_type)}", f"cacheControl {b64('3600')}"])


class Store:
    def __init__(self, url: str | None, service_key: str | None):
        if not (url and service_key):
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY 필요 (secrets/ves.env)")
        self.base = url.rstrip("/") + "/storage/v1"
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def upload(self, bucket: str, key: str, path: str) -> None:
        if use_tus(os.path.getsize(path)):
            return self._upload_tus(bucket, key, path)
        import requests
        with open(path, "rb") as f:
            r = requests.post(f"{self.base}/object/{bucket}/{key}",
                              headers={**self.headers, "x-upsert": "true",
                                       "Content-Type": "application/octet-stream"},
                              data=f, timeout=600)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"storage upload {r.status_code}: {r.text[:200]}")

    def _upload_tus(self, bucket: str, key: str, path: str) -> None:
        """TUS 재개형 업로드 — 4.5GB 초과 마스터용(모듈 머리말 참조)."""
        import requests
        size = os.path.getsize(path)
        r = requests.post(f"{self.base}/upload/resumable",
                          headers={**self.headers, "Tus-Resumable": "1.0.0",
                                   "Upload-Length": str(size), "x-upsert": "true",
                                   "Upload-Metadata": tus_metadata(bucket, key)},
                          timeout=60)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"storage tus create {r.status_code}: {r.text[:200]}")
        url = r.headers.get("Location") or ""
        if url.startswith("/"):
            url = self.base.rsplit("/storage/v1", 1)[0] + url
        if not url:
            raise RuntimeError("storage tus create: Location 헤더 없음")

        offset, tries = 0, 0
        with open(path, "rb") as f:
            while offset < size:
                f.seek(offset)
                chunk = f.read(TUS_CHUNK)
                try:
                    pr = requests.patch(
                        url, data=chunk,
                        headers={**self.headers, "Tus-Resumable": "1.0.0",
                                 "Upload-Offset": str(offset),
                                 "Content-Type": "application/offset+octet-stream"},
                        timeout=300)
                    if pr.status_code != 204:
                        raise RuntimeError(f"tus patch {pr.status_code}: {pr.text[:150]}")
                    offset = int(pr.headers.get("Upload-Offset") or (offset + len(chunk)))
                    tries = 0
                except Exception as e:  # noqa: BLE001 — 끊김: 서버 오프셋 재조회 후 이어올림
                    tries += 1
                    if tries > TUS_RETRIES:
                        raise RuntimeError(f"storage tus upload 중단({tries}회 실패): {e}")
                    time.sleep(min(2 ** tries, 30))
                    hr = requests.head(url, headers={**self.headers, "Tus-Resumable": "1.0.0"},
                                       timeout=30)
                    if hr.status_code == 200 and hr.headers.get("Upload-Offset"):
                        offset = int(hr.headers["Upload-Offset"])

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
