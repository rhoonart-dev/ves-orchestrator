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
    # ⚠ 구분자는 공백 없는 콤마다. ", " 로 이었더니 Supabase 가 400 Invalid upload-metadata
    #   로 전부 거부했다(8/13 실측: 피의 게임 X EP06~08 — 5GB 벽을 넘기도 전에 create 에서).
    # ⚠ upsert 는 **여기(메타데이터)** 에 넣어야 한다 — x-upsert 헤더는 표준 POST 전용이라
    #   TUS 커밋이 기존 객체와 충돌하면 409 The resource already exists 로 죽는다
    #   (8/15 실측: sync_drive_folder 3건 dead — 이전 시도가 올려둔 마스터에 재시도가 막혀
    #   폴더의 '신규' 파일 인입까지 통째로 중단됐다).
    return ",".join([f"bucketName {b64(bucket)}", f"objectName {b64(key)}",
                     f"contentType {b64(content_type)}", f"cacheControl {b64('3600')}",
                     f"upsert {b64('true')}"])


def page_keys(prefix: str, batch: list) -> tuple:
    """list 응답 한 페이지 → (실물 키 목록, 더 내려갈 하위 접두사 목록). 순수 — 테스트
    대상. 응답의 name 은 그 단계의 잎 이름뿐이라 prefix 를 붙여 완전한 키로 만든다."""
    root = prefix.rstrip("/")
    keys, subdirs = [], []
    for it in batch or []:
        name = it.get("name")
        if not name:
            continue
        if it.get("id") is None:                 # 가상 폴더 행
            subdirs.append(f"{root}/{name}/")
        else:
            keys.append(f"{root}/{name}")
    return keys, subdirs


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

    def _object_size(self, bucket: str, key: str):
        """객체가 있으면 바이트 크기, 없으면 None — 재업로드 생략 판단용(TUS 멱등)."""
        import requests
        r = requests.head(f"{self.base}/object/{bucket}/{key}",
                          headers=self.headers, timeout=30)
        if r.status_code != 200:
            return None
        try:
            return int(r.headers.get("Content-Length") or -1)
        except (TypeError, ValueError):
            return -1

    def _upload_tus(self, bucket: str, key: str, path: str) -> None:
        """TUS 재개형 업로드 — 4.5GB 초과 마스터용(모듈 머리말 참조)."""
        import requests
        size = os.path.getsize(path)
        # 멱등(8/15): 같은 키에 같은 크기가 이미 있으면 완주분 — 수 GB 재전송을 생략한다.
        # ves-sources 는 내용주소 키(sha256)라 '같은 키 = 같은 내용'이 보장된다. 재시도가
        # 절반쯤 올린 폴더를 다시 훑을 때 이 분기가 앞선 완주 파일들을 몇 초에 통과시킨다.
        if self._object_size(bucket, key) == size:
            print(f"[storage] tus 생략 — 동일 크기 객체 존재: {bucket}/{key}")
            return
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
        """정확한 오브젝트 이름 목록 삭제. ⚠ body 필드명(prefixes)과 달리 접두사/폴더
        재귀 삭제가 **아니다** — 서버(storage-api deleteObjects)가 name 정확 일치로만
        지우고, 일치 0건이어도 200 을 준다(2026-08-19 확인: supabase-js remove() 와
        같은 계약, 폴더 삭제는 미지원 — supabase/storage#207). 접두사를 그대로 넘기면
        조용한 무동작이 되므로 반드시 list_keys 로 실물 이름을 얻어 넘길 것."""
        import requests
        r = requests.delete(f"{self.base}/object/{bucket}",
                            headers=self.headers, json={"prefixes": keys}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"storage delete {r.status_code}: {r.text[:200]}")

    def list_keys(self, bucket: str, prefix: str, page: int = 1000) -> list:
        """prefix 아래 실물 오브젝트 키 전량 — 페이지네이션·하위 폴더 재귀 포함.

        delete 가 정확한 이름만 받으므로(위 참조) 접두사 삭제는 이 목록을 거친다.
        폴더는 가상이라 list 응답에 id 가 null 인 행으로만 나타난다 — 그 행은 한
        단계 내려가 다시 조회한다. 페이지 분해는 page_keys(순수)가 한다."""
        import requests
        keys, offset = [], 0
        while True:
            r = requests.post(f"{self.base}/object/list/{bucket}",
                              headers=self.headers,
                              json={"prefix": prefix.rstrip("/"), "limit": page,
                                    "offset": offset,
                                    "sortBy": {"column": "name", "order": "asc"}},
                              timeout=60)
            if r.status_code != 200:
                raise RuntimeError(f"storage list {r.status_code}: {r.text[:200]}")
            batch = r.json() or []
            got, subdirs = page_keys(prefix, batch)
            keys += got
            for sub in subdirs:
                keys += self.list_keys(bucket, sub, page)
            if len(batch) < page:
                return keys
            offset += page
