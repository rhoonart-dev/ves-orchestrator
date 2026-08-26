#!/usr/bin/env python3
"""외부 완성본(현지화판) 발행 — 아카이브에서 고른 편을 유튜브에 올린다 (L-P5-발행).

## 왜 brain 의 publish 를 못 쓰는가

`publish` 어댑터(brain `publish_youtube.py`)는 **우리가 만든 클립**을 전제한다:
`--clip-id` 가 필수이고, 그 앞에 안전 게이트가 `judge_runs` 의 판정을 요구한다
(`gate_ok`: "judge 안전판정 없음"이면 차단). 외부 완성본에는 clip 도 judge 도 없다 —
있지도 않은 안전 판정을 지어내는 것은 게이트를 없애는 것과 같으므로 그 길을 안 쓴다.

여기서는 **사람의 검수 승인이 게이트**다(localization_qa 카드). 그 위에 기계적인
두 가지만 더 지킨다: 공개 직행 금지(R9)와 **재업로드 금지**(원장에 youtube_id 가
있으면 아무것도 안 한다).

## 자격증명

함대 규약을 먼저 본다(brain `channel_registry` 와 같은 이름):

    YT_CLIENT_ID_<gcp_project> · YT_CLIENT_SECRET_<gcp_project> · YT_REFRESH_TOKEN_<slug>

없으면 vlp 가 쓰던 이름으로 폴백한다(`YT_OAUTH_CLIENT_ID`·`YT_OAUTH_CLIENT_SECRET`
+ 리프레시 토큰 파일). ⚠ 어느 쪽도 없으면 **어느 키가 비었는지 이름으로** 알린다 —
폴백이 미설정을 조용히 삼키면 밤중에 `unauthorized_client` 로 터진다(brain 이 2026-07-29
에 겪은 것과 같은 함정).

vlp `src/uploader.py` 이식: `next_publish_at`·resumable 업로드는 그 코드 그대로다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

from ves.adapters import base
from ves.storage.supabase_storage import Store

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
              "?part=snippet,status&uploadType=resumable")
VLP_TOKEN_CACHE = "engines/video-localization-project/outputs/yt_oauth_token.json"
DEFAULT_PROJECT = "DEFAULT"
MAX_TITLE = 100
MAX_DESC = 4900
MAX_TAGS = 20


# ───────── 순수 (테스트 대상) ─────────

def credential_keys(gcp_project, token_slug: str) -> tuple:
    """(client_id 키, client_secret 키, refresh token 키). brain 과 **같은 이름**이다.

    이름이 갈리면 같은 채널에 두 벌의 시크릿을 넣어야 한다."""
    if not gcp_project or gcp_project == DEFAULT_PROJECT:
        cid, cs = "YT_CLIENT_ID", "YT_CLIENT_SECRET"
    else:
        cid, cs = f"YT_CLIENT_ID_{gcp_project}", f"YT_CLIENT_SECRET_{gcp_project}"
    return cid, cs, f"YT_REFRESH_TOKEN_{token_slug}"


def pick_title(draft: dict, override=None) -> str:
    """발행 제목 — 사람이 고른 값 > 초벌 1안. 순수.

    ⚠ 원제(한국어)로 폴백하지 않는다. 일본 채널에 한국어 제목이 뜨던 사고(0075)와
    같은 자리다 — 제목이 없으면 발행 자체를 하지 않는다."""
    if str(override or "").strip():
        return str(override).strip()[:MAX_TITLE]
    for t in (draft or {}).get("title_candidates") or []:
        if str(t).strip():
            return str(t).strip()[:MAX_TITLE]
    return ""


def build_snippet(draft: dict, *, title=None, category_id: str = "24",
                  audio_ja: bool = False) -> dict:
    """videos.insert 의 snippet. vlp `build_upload_meta` 와 같은 값이다."""
    snippet = {
        "title": pick_title(draft, title),
        "description": str((draft or {}).get("description") or "")[:MAX_DESC],
        "tags": [str(t) for t in ((draft or {}).get("tags") or [])][:MAX_TAGS],
        "categoryId": str(category_id),          # 24 = Entertainment
        "defaultLanguage": "ja",
    }
    if audio_ja:                                  # 더빙본만 오디오 언어 ja
        snippet["defaultAudioLanguage"] = "ja"
    return snippet


def build_status(privacy: str, publish_at=None, made_for_kids: bool = False) -> dict:
    """status. 예약 공개는 **private + publishAt** 이다(YouTube 규약).

    🛑 public 직행은 없다(R9) — RPC 가 걸러야 하지만 여기서도 막는다(이중 방어)."""
    if privacy not in ("private", "unlisted"):
        raise base.PermanentError(
            f"R9: 외부 발행은 private|unlisted 만 (받은 값: {privacy!r}). "
            f"예약 공개는 private + publish_at 조합이다")
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": bool(made_for_kids)}
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    return status


def next_publish_at(now_utc: dt.datetime, taken: set, hhmm: str = "19:00",
                    tz_name: str = "Asia/Tokyo", min_lead_h: float = 1.0) -> str:
    """다음 빈 일일 슬롯(RFC3339 UTC). vlp `uploader.next_publish_at` 그대로.

    하루 1편 페이스 — 잡힌 슬롯은 다음 날로. 같은 시각 대량 공개를 피한다."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(tz_name)
    hh, mm = (int(x) for x in hhmm.split(":"))
    local = now_utc.astimezone(tz)
    slot = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    for _ in range(370):
        slot_utc = slot.astimezone(dt.timezone.utc)
        iso = slot_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        if slot_utc >= now_utc + dt.timedelta(hours=min_lead_h) and iso not in taken:
            return iso
        slot += dt.timedelta(days=1)
    raise RuntimeError("빈 예약 슬롯을 찾지 못함(1년 초과)")


# 한글 문자군 — 음절(가~힣) · 자모(ㄱ~ㆎ) · 호환 자모. 일본 채널 문구에는 들어갈 자리가 없다.
_HANGUL = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F\uA960-\uA97F\uD7B0-\uD7FF]")


def hangul_bits(text) -> list:
    """문구에서 한글이 든 **토막**들. 순수 — 테스트 대상.

    글자 하나가 아니라 그것이 낀 공백 토큰을 돌려준다 — 사람이 무엇을 지워야 하는지
    (`#닛몰캐쉬`) 알아야 고칠 수 있기 때문이다.

    ⚠ 실측(2026-08-26 첫 실물 2편): 번역이 원제의 한국어 해시태그를 그대로 남겼다.
    프롬프트로 줄일 수는 있어도 LLM 출력이라 **보장은 안 된다** — 그래서 여기서 센다."""
    return [tok for tok in str(text or "").split() if _HANGUL.search(tok)]


def publishable_snippet(snippet: dict) -> bool:
    """이 snippet 으로 올려도 되는가 — 제목·설명이 있어야 한다. 순수."""
    return bool(str(snippet.get("title") or "").strip()
                and str(snippet.get("description") or "").strip())


# ───────── IO ─────────

def _resolve_credentials(cfg, gcp_project, token_slug: str) -> tuple:
    """(client_id, client_secret, refresh_token, 출처). 못 찾으면 PermanentError."""
    cid_key, cs_key, rt_key = credential_keys(gcp_project, token_slug)
    cid, cs, rt = os.environ.get(cid_key), os.environ.get(cs_key), os.environ.get(rt_key)
    if cid and cs and rt:
        return cid, cs, rt, f"env({cid_key}·{rt_key})"

    # 폴백 — vlp 가 쓰던 이름(잔망루피는 그 토큰으로 올라가고 있다)
    v_cid = os.environ.get("YT_OAUTH_CLIENT_ID")
    v_cs = os.environ.get("YT_OAUTH_CLIENT_SECRET")
    cache = pathlib.Path(cfg.home) / VLP_TOKEN_CACHE
    v_rt = None
    if cache.exists():
        try:
            v_rt = json.loads(cache.read_text(encoding="utf-8")).get("refresh_token")
        except (OSError, ValueError) as e:
            print(f"[publish_external] vlp 토큰 캐시를 못 읽었다({cache}): {e}")
    if v_cid and v_cs and v_rt:
        return v_cid, v_cs, v_rt, f"vlp({cache})"

    missing = [k for k, v in ((cid_key, cid), (cs_key, cs), (rt_key, rt)) if not v]
    raise base.PermanentError(
        f"유튜브 OAuth 미설정 — 이 노드 env 에 없음: {', '.join(missing)}. "
        f"(폴백도 없음: YT_OAUTH_CLIENT_ID·YT_OAUTH_CLIENT_SECRET + {cache})")


def _access_token(cid: str, cs: str, rt: str) -> str:
    data = urllib.parse.urlencode({"client_id": cid, "client_secret": cs,
                                   "refresh_token": rt,
                                   "grant_type": "refresh_token"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data),
                                    timeout=30) as r:
            tok = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise base.PermanentError(
            f"토큰 갱신 거부 HTTP {e.code}: {e.read().decode()[:300]} — 재인증 필요") from e
    if "access_token" not in tok:
        raise base.PermanentError(f"토큰 갱신 실패: {json.dumps(tok)[:300]}")
    return tok["access_token"]


def upload_video(video_path, body: dict, token: str) -> str:
    """resumable 업로드(init→bytes) → YouTube video id. vlp uploader 이식."""
    video_path = pathlib.Path(video_path)
    size = video_path.stat().st_size
    init = urllib.request.Request(
        UPLOAD_URL, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4",
                 "X-Upload-Content-Length": str(size)})
    try:
        with urllib.request.urlopen(init, timeout=60) as r:
            session_url = r.headers.get("Location")
    except urllib.error.HTTPError as e:
        blob = e.read().decode()[:400]
        if e.code in (401, 403) or "quotaExceeded" in blob or "uploadLimitExceeded" in blob:
            raise base.QuotaError(f"업로드 거부 HTTP {e.code}: {blob}") from e
        raise RuntimeError(f"업로드 세션 실패 HTTP {e.code}: {blob}") from e
    if not session_url:
        raise RuntimeError("업로드 세션 URL 없음")

    put = urllib.request.Request(session_url, data=video_path.read_bytes(), method="PUT",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "video/mp4"})
    try:
        with urllib.request.urlopen(put, timeout=1800) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"업로드 실패 HTTP {e.code}: {e.read().decode()[:400]}") from e
    vid = res.get("id")
    if not vid:
        raise RuntimeError(f"업로드 응답에 id 없음: {json.dumps(res)[:300]}")
    return vid


def _taken_slots(conn, channel_slug: str) -> set:
    """이 채널이 이미 잡아 둔 예약 시각들. 하루 1편 페이스를 지키는 재료다.

    원장(발행 완료분)과 아직 안 돈 발행 잡을 **둘 다** 본다 — 잡만 보면 어제 올린 것을
    잊고, 원장만 보면 지금 큐에 선 것과 같은 슬롯을 준다."""
    taken = set()
    with conn.cursor() as c:
        c.execute("""SELECT flags->>'publish_at' AS at FROM public.external_shorts
                      WHERE channel_slug = %s AND flags ? 'publish_at'""", (channel_slug,))
        taken |= {r["at"] for r in c.fetchall() if r.get("at")}
        c.execute("""SELECT params->>'publish_at' AS at FROM public.job_queue
                      WHERE kind = 'publish_external' AND status IN ('pending','leased','running')
                        AND params->>'publish_at' IS NOT NULL""")
        taken |= {r["at"] for r in c.fetchall() if r.get("at")}
    return taken


def _already_uploaded(conn, ext_vid: str):
    with conn.cursor() as c:
        c.execute("SELECT youtube_id, state FROM public.external_shorts WHERE video_id = %s",
                  (ext_vid,))
        return c.fetchone() or {}


def _mark_uploaded(conn, ext_vid: str, yt_id: str, snippet: dict, publish_at) -> None:
    with conn.cursor() as c:
        c.execute("""UPDATE public.external_shorts
                        SET youtube_id = %s, state = 'uploaded', updated_at = now(),
                            flags = coalesce(flags,'{}'::jsonb)
                                    || jsonb_build_object('published_snippet', %s::jsonb)
                                    || CASE WHEN %s::text IS NULL THEN '{}'::jsonb
                                            ELSE jsonb_build_object('publish_at', %s::text) END
                      WHERE video_id = %s""",
                  (yt_id, json.dumps(snippet, ensure_ascii=False),
                   publish_at, publish_at, ext_vid))


def resource(cfg, job):
    """업로드는 채널 단위로 직렬화한다 — 같은 채널에 동시 업로드는 쿼터만 태운다."""
    return "yt_upload:_global"


def run(cfg, conn, job, deps):
    p = job["params"]
    ext_vid = p.get("external_video_id")
    if not ext_vid:
        raise base.PermanentError("params.external_video_id 없음")

    # 🛑 재업로드 금지 — 원장에 id 가 있으면 아무것도 하지 않는다(멱등).
    row = _already_uploaded(conn, ext_vid)
    if row.get("youtube_id"):
        print(f"[publish_external] 이미 발행됨 — https://youtu.be/{row['youtube_id']} (건너뜀)")
        return {"youtube_id": row["youtube_id"], "skipped": "already_uploaded"}

    draft = p.get("metadata") or {}
    snippet = build_snippet(draft, title=p.get("title"),
                            category_id=p.get("category_id", "24"),
                            audio_ja=bool(p.get("audio_ja")))
    if p.get("description"):
        snippet["description"] = str(p["description"])[:MAX_DESC]
    if p.get("tags"):
        snippet["tags"] = [str(t) for t in p["tags"]][:MAX_TAGS]
    if not publishable_snippet(snippet):
        raise base.PermanentError(
            "일본어 제목·설명이 없습니다 — 메타 초벌(metadata_draft.json)이 비었거나 "
            "검수 카드에 실리지 않았습니다. 현지화를 다시 돌리거나 제목을 직접 지정하세요")
    # 마지막 그물. 승인 RPC 가 먼저 막지만(사람이 고칠 수 있는 자리), 자동 경로가
    # 생기거나 옛 잡이 되살아나면 여기가 유일한 방어선이다. 조용히 지우지 않는다 —
    # 문구를 고치는 것은 사람의 결정이다.
    bad = hangul_bits(snippet["title"]) + hangul_bits(snippet["description"])
    if bad:
        raise base.PermanentError(
            f"일본 채널 문구에 한글이 남아 있습니다: {' · '.join(bad[:8])} — "
            f"검수 카드에서 지운 뒤 다시 승인하세요")
    publish_at = p.get("publish_at")
    if not publish_at and p.get("schedule"):
        # 사람이 '예약 공개'만 고르고 시각을 안 정했다 — 다음 빈 일일 슬롯(19:00 JST).
        publish_at = next_publish_at(dt.datetime.now(dt.timezone.utc),
                                     _taken_slots(conn, p.get("channel_slug")))
        print(f"[publish_external] 예약 슬롯 자동 배정: {publish_at}")
    status = build_status(p.get("privacy", "private"), publish_at)

    # ⚠ 자격증명은 **내려받기 전**에 본다. L-P4 실측의 교훈이다: vlp 는 18분짜리
    # 인페인팅을 다 하고 나서 번역에서 401 로 죽었다("비싼 단계 뒤에 자격증명 검사").
    # 여기서 미리 보면 키가 없는 노드는 몇 초 만에, 파일을 만지지 않고 실패한다.
    cid, cs, rt, whence = _resolve_credentials(cfg, p.get("gcp_project"),
                                               p.get("channel_slug"))
    print(f"[publish_external] 자격증명 {whence} · {snippet['title']!r} "
          f"({status['privacyStatus']}{', 예약 ' + status['publishAt'] if status.get('publishAt') else ''})")

    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    work = pathlib.Path(cfg.home) / "cache" / "publish_external"
    work.mkdir(parents=True, exist_ok=True)
    local = work / f"{base.storage_key(str(ext_vid), 'out.mp4').split('/')[0]}.mp4"
    try:
        store.download(p.get("bucket") or "ves-localized", p["key"], str(local))
        yt_id = upload_video(local, {"snippet": snippet, "status": status},
                             _access_token(cid, cs, rt))
    finally:
        local.unlink(missing_ok=True)          # 편당 수 MB~수백 MB — 남기지 않는다

    _mark_uploaded(conn, ext_vid, yt_id, snippet, status.get("publishAt"))
    print(f"[publish_external] 발행 완료 https://youtu.be/{yt_id}")
    return {"youtube_id": yt_id, "url": f"https://youtu.be/{yt_id}",
            "title": snippet["title"], "privacy": status["privacyStatus"],
            "publish_at": status.get("publishAt")}
