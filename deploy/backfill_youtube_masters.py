#!/usr/bin/env python3
"""YouTube URL 소스를 파일 마스터로 선제 보관 — 노드에서 실행.

  ssh mm-02
  cd /opt/ves && .venv/bin/python3 deploy/backfill_youtube_masters.py [--dry-run] \
      [--limit N] [--sleep SEC] [--work "작품명"]

무엇을 하는가: sources 에서 origin='youtube' AND source_url IS NOT NULL AND sha256 IS NULL
인 행을 골라(대상 범위는 is_target 참고) 한 편씩 내려받는다(app.modules.youtube_downloader —
generate 가 쓰는 것과 완전히 같은 코드 경로 · 같은 403 회피 옵션). 받은 파일을
ves-sources/masters/<sha256> 에 올리고 **같은 행**(work_title+source_url 로 이미 유일)의
sha256/object_key/bytes 를 채운다.

deploy/register_source.py 와 다른 점: 그건 새 sha 를 새 행으로 등록한다(Drive 원본용).
여기선 새 행을 만들지 않는다 — sha256 이 아니라 **기존 행의 id** 로 갱신해야, 그 행에
걸린 work_orders 매칭·source_usage 사용 이력이 끊기지 않는다(register_sources.py 머리말의
경고와 같은 이유: 다른 행으로 갈아타면 소진 카운트가 조용히 0 으로 리셋된다).

성공하면 is_active=true 도 같이 켠다 — 다운로드 성공 자체가 "지금 살아있고 이제 Storage 에
있어 YouTube 라이브 없이도 쓸 수 있다"는 증거이기 때문이다(2026-08-18 403 사태로 채널째
내려간 5개 작품의 복구가 목적). 그 5개 작품은 is_active 와 무관하게 전량 대상에 넣는다
(WORKS_TO_REVIVE — 실측: 이 다섯은 활성 행이 0건이라 채널 단위로 죽어 있었다). 그 밖의
작품에서 is_active=false 인 행(예: 언더커버셰프 14건, 길이 16~295초 — 예고 등 내용 사유로
register_playlist 가 내린 것)은 대상에서 뺀다: 다운로드가 성공해도 그게 '쓸만한 소스'라는
뜻은 아니다.

속도조절: 영상 사이 --sleep 초 대기(기본 20). 오늘 403 사태의 정체가 "그 IP 에서의 재생
요청 자체를 막은 것"이었던 만큼, 짧은 시간에 몰아 받는 행위 자체가 재발 위험이다 — 여러
노드에서 동시에 돌리지 말 것(사무실 회선이 같다면 노드를 나눠도 한 IP 에서 나간다).

멱등 · 이어달리기: Ctrl-C 로 아무 때나 멈춰도 안전하다 — 대상 조건이 sha256 IS NULL 이라
다음 실행이 이미 된 것은 건너뛰고 이어받는다. 실패한 편(사멸 등)은 sha256 이 안 채워지니
계속 대상에 남는다 — 사람이 확인할 때까지 조용히 계속 재시도되는 게 아니라, 실행할 때마다
로그에 실패로 다시 찍혀 눈에 띈다. 다만 "받아보니 다른 행과 바이트가 같더라"(같은 영상의
재업로드 URL 등, sources.sha256 UNIQUE 위반)는 `x 실패`가 아니라 `= ` 로 따로 표시한다 —
그 회차는 이미 다른 행이 커버하고 있어 재시도해도 매번 같은 결과가 나오는, 무해한 중복이다.

deploy/register_source.py 와 같은 이유로 이 파일도 단위 테스트가 없다 — 표준 라이브러리
+ ves.config/ves.db 만 쓰는 사람 실행 도구(§ deploy/ 관례).
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from ves import config as cfgmod
from ves import db as dbmod

CHUNK = 1 << 20

# 2026-08-18 403 사태로 채널째 내려간 작품 — is_active 와 무관하게 전량 대상(머리말 참고).
WORKS_TO_REVIVE = (
    "놀라운 토요일",
    "도깨비 10주년 여행",
    "스트릿 레스토랑 파이터",
    "언니네 산지직송 in 칼라페",
    "커리어데이",
)


def is_target(row: dict, revive_works=WORKS_TO_REVIVE) -> bool:
    """이 sources 행을 백필 대상으로 볼 것인가. 순수.

    이미 파일이 있으면(sha256) 제외 — 호출부 SQL 이 먼저 거르지만 이중 방어.
    활성 행은 항상 대상(캐시를 데워 두면 다음 generate 부터 YouTube 라이브 의존이 준다).
    비활성 행은 채널째 내려간 작품(WORKS_TO_REVIVE)일 때만 — 내용 사유로 내려간 행은
    다운로드 성공 여부와 무관하게 그대로 둔다(머리말 참고)."""
    if not row or row.get("sha256") or not row.get("source_url"):
        return False
    if row.get("is_active"):
        return True
    return row.get("work_title") in set(revive_works or ())


def select_targets(conn, limit=None, works=None):
    """대상 행 조회. DB 1차 필터 + is_target 로 이중 확인(경계 사례 방어)."""
    sql = """SELECT id, work_title, episode, source_url, duration_sec, is_active
               FROM public.sources
              WHERE origin='youtube' AND source_url IS NOT NULL AND sha256 IS NULL
                AND (is_active OR work_title = ANY(%s))"""
    params: list = [list(WORKS_TO_REVIVE)]
    if works:
        sql += " AND work_title = ANY(%s)"
        params.append(list(works))
    sql += " ORDER BY work_title, episode NULLS LAST, id"
    if limit:
        sql += " LIMIT %s"
        params.append(int(limit))
    with conn.cursor() as c:
        c.execute(sql, params)
        rows = c.fetchall()
    return [r for r in rows if is_target(r)]


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _req(url, method="GET", headers=None, data=None, timeout=120):
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def upload_master(base, key, sha, path) -> str:
    """ves-sources/masters/<sha> 로 업로드(이미 있으면 스킵 — content-addressed). object_key 반환."""
    H = {"Authorization": f"Bearer {key}", "apikey": key}
    okey = f"masters/{sha}"
    st, _ = _req(f"{base}/storage/v1/object/info/ves-sources/{okey}", headers=H)
    if st == 200:
        return okey
    size = pathlib.Path(path).stat().st_size
    st, body = _req(f"{base}/storage/v1/object/ves-sources/{okey}", method="POST",
                    headers={**H, "Content-Type": "application/octet-stream",
                             "x-upsert": "true", "Content-Length": str(size)},
                    data=open(path, "rb"), timeout=3600 * 6)
    if st not in (200, 201):
        raise RuntimeError(f"업로드 실패 {st}: {body[:300]}")
    return okey


def upload_subtitle(base, key, sha, path) -> str:
    H = {"Authorization": f"Bearer {key}", "apikey": key}
    okey = f"masters/{sha}.srt"
    size = pathlib.Path(path).stat().st_size
    st, body = _req(f"{base}/storage/v1/object/ves-sources/{okey}", method="POST",
                    headers={**H, "Content-Type": "application/octet-stream",
                             "x-upsert": "true", "Content-Length": str(size)},
                    data=open(path, "rb"), timeout=600)
    if st not in (200, 201):
        raise RuntimeError(f"자막 업로드 실패 {st}: {body[:200]}")
    return okey


def download_one(cfg, url: str, out_dir: pathlib.Path):
    """generate 와 같은 코드 경로로 내려받는다 — ai_video venv 서브프로세스."""
    argv = [cfgmod.engine_py(cfg, "ai_video"), "-u", "-c",
            "import sys\n"
            "from pathlib import Path\n"
            "from app.modules.youtube_downloader import download_youtube_assets\n"
            "a = download_youtube_assets(sys.argv[1], Path(sys.argv[2]))\n"
            "print('VIDEO_PATH=' + str(a.video_path))\n"
            "print('SUBTITLE_PATH=' + str(a.subtitle_path or ''))\n",
            url, str(out_dir)]
    proc = subprocess.run(argv, cwd=cfgmod.engine_dir(cfg, "ai_video"),
                          env=cfgmod.job_env(cfg), capture_output=True,
                          text=True, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "")[-800:])
    video_path = subtitle_path = None
    for line in proc.stdout.splitlines():
        if line.startswith("VIDEO_PATH="):
            video_path = line[len("VIDEO_PATH="):]
        elif line.startswith("SUBTITLE_PATH="):
            subtitle_path = line[len("SUBTITLE_PATH="):] or None
    if not video_path or not pathlib.Path(video_path).is_file():
        raise RuntimeError("다운로드 결과 파일 없음 — youtube_downloader 출력 계약 확인")
    return video_path, subtitle_path


def process_one(cfg, conn, row) -> None:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ytbackfill_"))
    try:
        video_path, subtitle_path = download_one(cfg, row["source_url"], tmp)
        sha = sha256_of(video_path)
        size = pathlib.Path(video_path).stat().st_size
        okey = upload_master(cfg.supabase_url, cfg.supabase_service_key, sha, video_path)
        skey = None
        if subtitle_path and pathlib.Path(subtitle_path).is_file():
            skey = upload_subtitle(cfg.supabase_url, cfg.supabase_service_key, sha, subtitle_path)
        try:
            with conn.cursor() as c:
                c.execute("""UPDATE public.sources
                                SET sha256=%s, object_key=%s, bytes=%s,
                                    subtitle_key=COALESCE(%s, subtitle_key),
                                    has_subtitle = has_subtitle OR %s,
                                    is_active=true
                              WHERE id=%s""",
                          (sha, okey, size, skey, bool(skey), row["id"]))
        except Exception as e:  # noqa: BLE001
            from psycopg.errors import UniqueViolation
            if not isinstance(e, UniqueViolation):
                raise
            # 이 URL 이 받아온 내용이 다른 행과 바이트가 같다(같은 영상의 재업로드 URL,
            # 혹은 이미 손으로 구제해둔 파일과 동일) — sources.sha256 은 UNIQUE 라 이 행에
            # 또 채울 수 없다. 그 다른 행이 이미 이 회차를 커버하므로 실패가 아니라 중복
            # 발견이다 — 이 행은 그대로 두고(재시도해도 매번 같은 결과) 다르게 알린다.
            with conn.cursor() as c:
                c.execute("SELECT work_title, episode, is_active FROM public.sources "
                          "WHERE sha256=%s", (sha,))
                owner = c.fetchone() or {}
            print(f"  = 다른 행과 내용 동일(sha 일치) — {owner.get('work_title')} "
                  f"{owner.get('episode')}화(is_active={owner.get('is_active')})가 이미 이 영상을 "
                  f"갖고 있음. 이 행은 그대로 둠(정상 — 재시도 대상에서 빠지지 않으니 "
                  f"매번 다시 받겠지만 무해함)")
            return
        print(f"  -> 등록 완료 sha={sha[:16]}... ({size >> 20}MB)" + (" +자막" if skey else ""))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="이번 실행에서 처리할 최대 건수")
    ap.add_argument("--sleep", type=float, default=20.0, help="영상 사이 대기(초, 기본 20)")
    ap.add_argument("--work", action="append", default=None, help="이 작품만(반복 가능)")
    ap.add_argument("--dry-run", action="store_true", help="대상만 나열하고 받지 않음")
    a = ap.parse_args(argv)

    cfg = cfgmod.get_config()
    conn = dbmod.connect(cfg.db_url or None)
    rows = select_targets(conn, a.limit, a.work)
    print(f"대상 {len(rows)}건"
          + (f" (총 {round(sum((r.get('duration_sec') or 0) for r in rows) / 3600, 1)}시간)"
             if rows else ""))
    if a.dry_run:
        for r in rows:
            print(f"  {r['work_title']} {r.get('episode')}화"
                  f"{' [비활성->복원 시도]' if not r['is_active'] else ''} — {r['source_url']}")
        return 0

    ok = fail = 0
    for i, r in enumerate(rows, start=1):
        print(f"\n[{i}/{len(rows)}] {r['work_title']} {r.get('episode')}화 — {r['source_url']}")
        try:
            process_one(cfg, conn, r)
            ok += 1
        except Exception as e:  # noqa: BLE001 — 한 편 실패가 배치를 죽이지 않는다
            # 메시지의 뒤쪽(진짜 오류가 있는 곳)을 보여준다 — download_one 이 이미 stderr
            # 뒤 800자로 잘라 담아오므로, 여기서 또 앞 300자를 자르면 트레이스백 중간(코드
            # 컨텍스트 줄)만 보이고 정작 원인 줄은 잘려나간다(8/19 실측: UniqueViolation·
            # 403 모두 원인이 안 보였다).
            print(f"  x 실패(건너뜀, 다음 실행에 재시도됨): {type(e).__name__} {str(e)[-300:]}")
            fail += 1
        if i < len(rows):
            time.sleep(a.sleep)

    print(f"\n완료: 성공 {ok} · 실패 {fail} / 총 {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
