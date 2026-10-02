#!/usr/bin/env python3
"""새 파이프라인(맥미니) 영상 검수 흐름의 맥미니 쪽 일(0120 tikitaka_reviews).

tikitaka_publish(네이티브 잡) — 워크스페이스에서 내부 승인하면 걸린다.
  · 권리사 검수가 필요한 작품: 일부공개로 올린다 → stage 'submitting' (아래 스케줄러가 레이블리에 신청)
  · 검수가 필요 없는 작품: 비공개 + 예약 시각(publishAt)으로 올린다 → stage 'scheduled'(유튜브가 그 시각에 공개)
  유튜브 연결이 '올리기' 권한뿐인 채널이 많아 올린 뒤에는 상태를 못 바꾼다 — 그래서 올릴 때 한 번에 건다.
  다시 시도하지 않는다(max_attempts 1): 저쪽에서 올라갔는데 답만 잃었을 수 있어 같은 영상이 두 번 올라간다.

submit_inspections(스케줄러 · 1분마다) — 'submitting' 인 편을 레이블리에 권리사 검수로 신청한다.
  완성본은 workspace-inspections 저장소에 사본을 두고 1년 서명 링크를 붙인다(편이 다시 렌더되면 원래 자리는 덮인다).
  레이블리 쪽이 먼저 커밋되고 우리 쪽이 실패해도 다시 돌 때 같은 신청을 찾도록 비고에 표시를 남긴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from ves import config as cfgmod
from ves.adapters import base

YT_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
YT_THUMB = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId="
THUMB_MAX = 2 * 1024 * 1024          # 유튜브 맞춤 썸네일 한도(2MB)
CATEGORY_ENTERTAINMENT = "24"
INSPECTION_BUCKET = "workspace-inspections"


# ───────── 순수 — 테스트 대상 ─────────
def client_env_names(gcp_project):
    """채널 gcp_project → (client_id 키, client_secret 키). brain channel_registry 와 같은 규칙."""
    if not gcp_project or gcp_project == "DEFAULT":
        return "YT_CLIENT_ID", "YT_CLIENT_SECRET"
    return f"YT_CLIENT_ID_{gcp_project}", f"YT_CLIENT_SECRET_{gcp_project}"


def youtube_body(meta: dict, privacy: str, publish_at: str | None) -> dict:
    """videos.insert 본문. 제목은 줄바꿈을 공백으로(100자), 태그는 # 를 떼고 15개까지."""
    title = " ".join(str((meta or {}).get("title") or "").split())[:100] or "shorts"
    tags = [str(t).lstrip("#").strip() for t in (meta or {}).get("tags") or [] if str(t).strip()][:15]
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if publish_at:
        status["privacyStatus"] = "private"       # publishAt 은 비공개에서만 — 그 시각에 유튜브가 공개로 바꾼다
        status["publishAt"] = publish_at
    if status["privacyStatus"] == "public":
        raise ValueError("공개로 바로 올리지 않는다(일부공개 · 비공개 · 예약만)")
    return {"snippet": {"title": title, "description": str((meta or {}).get("description") or ""),
                        "tags": tags, "categoryId": CATEGORY_ENTERTAINMENT},
            "status": status}


def inspection_marker(video_id: str, fingerprint: str) -> str:
    """레이블리 비고에 남기는 표시 — 같은 판의 신청을 다시 찾는 열쇠."""
    return f"[VES tikitaka {video_id} {str(fingerprint)[:12]}]"


# ───────── 유튜브 ─────────
def _http_json(req, timeout=60):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), r
    except urllib.error.HTTPError as e:
        body = re.sub(r"ya29[\w.-]+", "…", e.read()[:400].decode("utf-8", "replace"))   # 토큰은 남기지 않는다
        raise base.PermanentError(f"유튜브가 거절했어요 (HTTP {e.code}): {body}") from None


def access_token(env: dict, gcp_project: str | None, slug: str) -> str:
    cid_key, cs_key = client_env_names(gcp_project)
    keys = [cid_key, cs_key, f"YT_REFRESH_TOKEN_{slug}"]
    missing = [k for k in keys if not env.get(k)]
    if missing:
        raise base.PermanentError("이 맥미니에 그 채널의 유튜브 연결이 없어요: " + ", ".join(missing))
    data = urllib.parse.urlencode({"client_id": env[cid_key], "client_secret": env[cs_key],
                                   "refresh_token": env[keys[2]], "grant_type": "refresh_token"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30) as r:
            return json.load(r)["access_token"]
    except Exception:
        raise base.PermanentError("유튜브 연결을 새로 받지 못했어요. 채널 연결(토큰)을 확인해 주세요") from None


def upload_video(token: str, path: str, body: dict) -> dict:
    """재개 가능 업로드 — 세션을 열고 파일을 한 번에 보낸다. 응답(영상 id · 채널 id)을 돌려준다."""
    size = os.path.getsize(path)
    start = urllib.request.Request(YT_UPLOAD, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    try:
        with urllib.request.urlopen(start, timeout=60) as r:
            where = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        raise base.PermanentError(f"유튜브 올리기를 시작하지 못했어요 (HTTP {e.code}): {e.read()[:300].decode('utf-8', 'replace')}") from None
    if not where:
        raise base.PermanentError("유튜브가 올릴 자리를 주지 않았어요")
    with open(path, "rb") as f:
        put = urllib.request.Request(where, data=f.read(), method="PUT", headers={"Content-Type": "video/mp4"})
    out, _ = _http_json(put, timeout=3600)
    return out


def thumb_file(src: str, d: str) -> tuple[str, str]:
    """2MB 를 넘으면 JPEG 로 줄인다 → (경로, content-type)."""
    import subprocess
    if os.path.getsize(src) <= THUMB_MAX:
        return src, ("image/png" if src.endswith(".png") else "image/jpeg")
    for q, w in ((3, None), (5, 1280)):
        out = os.path.join(d, f"thumb_{q}.jpg")
        vf = ["-vf", f"scale={w}:-2"] if w else []
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src, *vf, "-q:v", str(q), out],
                       check=True, timeout=60)
        if os.path.getsize(out) <= THUMB_MAX:
            return out, "image/jpeg"
    raise base.PermanentError("썸네일 파일이 2MB 를 넘어서 줄이지 못했어요")


def set_thumbnail(token: str, yt_id: str, path: str, ctype: str) -> None:
    with open(path, "rb") as f:
        req = urllib.request.Request(YT_THUMB + urllib.parse.quote(yt_id), data=f.read(), method="POST",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": ctype})
    _http_json(req, timeout=120)


def put_publish_thumb(cfg, conn, vid: str, yt_id: str, token: str) -> dict | None:
    """작업 화면에서 발행용으로 고른 썸네일(0129 tikitaka_thumbnails.publish)을 올린 영상에 넣는다.
    못 넣어도 영상은 그대로 둔다(전화 인증이 안 된 채널 · 권한 부족) — 검수 카드가 '스튜디오에서 넣어 주세요'로 알린다."""
    from ves.storage.supabase_storage import Store
    with conn.cursor() as c:
        c.execute("SELECT publish FROM public.tikitaka_thumbnails WHERE video_id = %s", (vid,))
        row = c.fetchone()
    pub = (row or {}).get("publish") or {}
    if not pub.get("key"):
        return None
    rank = pub.get("rank")
    try:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, os.path.basename(str(pub["key"])) or "thumb.png")
            Store(cfg.supabase_url, cfg.supabase_service_key).download("ves-outputs", pub["key"], src)
            path, ctype = thumb_file(src, d)
            set_thumbnail(token, yt_id, path, ctype)
        print(f"[tikitaka_publish] {vid} 썸네일 {rank}번 → {yt_id}")
        return {"state": "set", "rank": rank}
    except Exception as e:                      # 영상은 이미 올라갔다 — 잡을 실패로 돌리지 않는다
        print(f"[tikitaka_publish] {vid} 썸네일을 넣지 못함: {e}")
        return {"state": "todo", "rank": rank, "reason": str(e)[:300]}


# ───────── 잡: tikitaka_publish ─────────
class Publish:
    @staticmethod
    def resource(cfg, job):
        return "yt_upload:_global"      # 예전 발행 잡과 같은 자물쇠 — 한 번에 하나씩 올린다

    @staticmethod
    def is_already_done(cfg, job):
        return False                    # 아래 run 이 검수 기록의 youtube_id 로 판단한다(DB 가 필요해서)

    @staticmethod
    def run(cfg, conn, job, deps):
        from ves.storage.supabase_storage import Store
        p = job.get("params") or {}
        vid, fp = p.get("video_id"), p.get("fingerprint")
        with conn.cursor() as c:
            c.execute("SELECT fingerprint, stage, youtube_id, upload_job_id FROM public.tikitaka_reviews WHERE video_id = %s", (vid,))
            rev = c.fetchone()
            c.execute("SELECT render_fingerprint, files FROM public.tikitaka_videos WHERE id = %s", (vid,))
            video = c.fetchone()
            c.execute("SELECT gcp_project, channel_id FROM public.channels_mirror WHERE token_slug = %s", (p.get("channel_slug"),))
            ch = c.fetchone()
        if not rev or str(rev.get("upload_job_id")) != str(job["id"]) or rev["fingerprint"] != fp:
            raise base.PermanentError("검수 기록이 이 올리기와 맞지 않아요(그 사이 다시 승인 · 반려됐어요)")
        if rev.get("youtube_id"):
            return {"youtube_id": rev["youtube_id"], "skipped": "already_uploaded"}
        if not video or video["render_fingerprint"] != fp:
            raise base.PermanentError("영상이 그 사이 새로 만들어졌어요. 새 판에서 다시 승인해 주세요")
        if not ch or ch.get("channel_id") != p.get("channel_id"):
            raise base.PermanentError("채널 정보가 바뀌었어요. 채널 관리에서 확인해 주세요")
        key = ((video.get("files") or {}).get("shorts.mp4") or {}).get("key")
        if not key:
            raise base.PermanentError("완성본(shorts.mp4)이 저장소에 없어요")
        body = youtube_body(p.get("meta") or {}, p.get("privacy") or "unlisted", p.get("publish_at"))
        token = access_token(cfgmod.job_env(cfg), ch.get("gcp_project"), p["channel_slug"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shorts.mp4")
            Store(cfg.supabase_url, cfg.supabase_service_key).download("ves-outputs", key, path)
            out = upload_video(token, path, body)
        yt = out.get("id")
        if not yt:
            raise base.PermanentError("유튜브가 영상 id 를 주지 않았어요")
        got_channel = (out.get("snippet") or {}).get("channelId")
        stage = "submitting" if p.get("purpose") == "inspection" else "scheduled"
        err = None
        if got_channel and got_channel != p.get("channel_id"):
            # 지울 권한이 없다 — 사람이 스튜디오에서 정리해야 한다. 다음 단계로 넘기지 않는다
            stage, err = "needs_attention", f"다른 채널({got_channel})에 올라갔어요. 스튜디오에서 확인해 주세요"
        with conn.cursor() as c:
            c.execute("""UPDATE public.tikitaka_reviews SET youtube_id = %s, stage = %s, error = %s, updated_at = now()
                          WHERE video_id = %s AND upload_job_id = %s""", (yt, stage, err, vid, job["id"]))
        conn.commit()
        thumb = put_publish_thumb(cfg, conn, vid, yt, token) if stage != "needs_attention" else None
        if thumb is not None:
            with conn.cursor() as c:
                c.execute("""UPDATE public.tikitaka_reviews SET meta = coalesce(meta, '{}'::jsonb) || jsonb_build_object('thumb', %s::jsonb),
                              updated_at = now() WHERE video_id = %s AND upload_job_id = %s""", (json.dumps(thumb), vid, job["id"]))
            conn.commit()
        print(f"[tikitaka_publish] {vid} → {yt} ({body['status']['privacyStatus']}{' · ' + body['status'].get('publishAt', '') if body['status'].get('publishAt') else ''})")
        return {"youtube_id": yt, "privacy": body["status"]["privacyStatus"], "publish_at": body["status"].get("publishAt"),
                "stage": stage, "thumb": thumb}


# ───────── 스케줄러: 레이블리 권리사 검수 신청 ─────────
def _copy_for_inspection(cfg, video_id: str, src_key: str) -> tuple[str, str]:
    """완성본을 검수용 자리로 복사하고 1년 서명 링크를 만든다 → (사본 열쇠, 링크)."""
    from ves.storage.supabase_storage import Store
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "shorts.mp4")
        store.download("ves-outputs", src_key, path)
        sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
        key = f"{video_id}/{sha}.mp4"
        try:
            store.upload(INSPECTION_BUCKET, key, path, content_type="video/mp4")
        except Exception as e:                      # 같은 열쇠가 이미 있으면(지난번 시도) 그대로 쓴다
            if "exists" not in str(e).lower() and "409" not in str(e):
                raise
    return key, store.signed_url(INSPECTION_BUCKET, key, 365 * 24 * 3600)


def submit_one(conn, cfg, r: dict) -> None:
    from ves.db import connect
    vid = str(r["video_id"])
    with conn.cursor() as c:
        c.execute("""SELECT v.files, v.work_title, v.render_fingerprint, m.channel_id, u.email AS actor_email
                       FROM public.tikitaka_videos v JOIN public.channels_mirror m ON m.token_slug = v.channel_slug
                       LEFT JOIN auth.users u ON u.id = %s WHERE v.id = %s""", (r.get("decided_by"), vid))
        v = c.fetchone()
    if not v or v["render_fingerprint"] != r["fingerprint"]:
        raise base.PermanentError("영상이 그 사이 새로 만들어졌어요. 새 판에서 다시 승인해 주세요")
    src = ((v.get("files") or {}).get("shorts.mp4") or {}).get("key")
    key, link = _copy_for_inspection(cfg, vid, src)
    marker = inspection_marker(vid, r["fingerprint"])
    yt_url = "https://www.youtube.com/watch?v=" + r["youtube_id"]
    lae = connect(cfg.laeebly_url)
    try:
        with lae.cursor() as c:
            c.execute("""SELECT a.id, a.channel_id, a.company, c.channel_title, c."user" AS owner_email
                           FROM public.channel_to_video a JOIN public.channel c ON c.id = a.channel_id
                          WHERE a.video_id = %s AND c.channel_id = %s AND c.deleted_at IS NULL""", (r["work_id"], v["channel_id"]))
            apps = c.fetchall()
            if len(apps) != 1 or apps[0]["id"] != r.get("application_id"):
                raise base.PermanentError("레이블리 사용 신청을 하나로 찾지 못했어요. 레이블리에서 확인해 주세요")
            app = apps[0]
            c.execute("SELECT id, title FROM public.licensed_video WHERE id = %s", (r["work_id"],))
            work = c.fetchone()
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (app["id"],))
            c.execute("SELECT id, round, youtube_url FROM public.video_inspection WHERE channel_to_video_id = %s AND remarks LIKE %s",
                      (app["id"], "%" + marker + "%"))
            found = c.fetchall()
            if len(found) > 1:
                raise base.PermanentError("레이블리에 같은 신청이 여러 개 있어요. 레이블리에서 확인해 주세요")
            if found:
                done = found[0]
                if done["youtube_url"] != yt_url:
                    raise base.PermanentError("레이블리의 이전 신청과 영상 링크가 달라요. 신청 이력을 확인해 주세요")
            else:
                remarks = ((r.get("remarks") or "").strip() + "\n" + marker).strip()
                c.execute("SELECT public.submit_video_inspection(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS result",
                          (app["id"], app["channel_id"], work["id"], app["owner_email"], v.get("actor_email") or "",
                           app["channel_title"], work["title"], app["company"], yt_url, link,
                           r["episode"], r["episode_part"], remarks))
                done = c.fetchone()["result"]
                prev = r.get("prev_inspection_id")
                if prev:
                    c.execute("SELECT status, channel_to_video_id FROM public.video_inspection WHERE id = %s", (prev,))
                    pr = c.fetchone()
                    if pr and pr["channel_to_video_id"] == app["id"] and pr["status"] in ("revision_requested", "resubmit_requested"):
                        c.execute("UPDATE public.video_inspection SET supersedes_inspection_id = %s WHERE id = %s", (prev, done["id"]))
        lae.commit()
    finally:
        lae.close()
    with conn.cursor() as c:
        c.execute("""UPDATE public.tikitaka_reviews SET stage = 'rights_pending', inspection_id = %s, inspection_round = %s,
                       attachment_key = %s, error = NULL, updated_at = now() WHERE video_id = %s AND stage = 'submitting'""",
                  (str(done["id"]), done.get("round"), key, vid))
    conn.commit()
    print(f"[tikitaka_review] {vid} → 레이블리 검수 신청 {done['id']} ({done.get('round')}차)")


def submit_inspections(conn, cfg) -> int:
    """'submitting' 인 편을 하나씩 신청한다. 실패하면 그 편만 needs_attention 으로 — 화면에서 다시 시도한다."""
    if not (cfg.laeebly_url and cfg.supabase_url and cfg.supabase_service_key):
        return 0
    with conn.cursor() as c:
        c.execute("SELECT * FROM public.tikitaka_reviews WHERE stage = 'submitting' AND youtube_id IS NOT NULL ORDER BY updated_at LIMIT 10")
        rows = c.fetchall()
    n = 0
    for r in rows:
        try:
            submit_one(conn, cfg, dict(r))
            n += 1
        except Exception as e:   # noqa: BLE001 — 한 편이 막혀도 나머지는 간다
            msg = str(e) if isinstance(e, base.PermanentError) else f"레이블리 신청을 마치지 못했어요: {type(e).__name__}"
            try:
                conn.rollback()
                with conn.cursor() as c:
                    c.execute("UPDATE public.tikitaka_reviews SET stage = 'needs_attention', error = %s, updated_at = now() WHERE video_id = %s AND stage = 'submitting'",
                              (msg[:500], r["video_id"]))
                conn.commit()
            except Exception:    # noqa: BLE001
                conn.rollback()
            print(f"[tikitaka_review] {r['video_id']} 신청 실패: {msg}")
    return n
