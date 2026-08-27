#!/usr/bin/env python3
"""zanmang_decision 어댑터 — 관제 검수함의 잔망루피 결정을 원장에 확정한다 (2026-08-12).

검수함에서 사람이 누른 것을 video-localization-project 원장에 반영하는 실행부다.
그 레포는 재작성하지 않는다 — 이미 승인과 업로드가 나뉘어 있어서 CLI 를 그대로 부른다.

  승인: `approve <id>`(업로드 패키지 생성 → approved) → `upload <id>`(비공개 업로드 +
        19:00 JST 다음 빈 슬롯으로 예약 공개). 공개 '결정'은 사람이 이미 했고 여기는 기계적 실행.
  반려: `mark --state skipped <id>` — 안 하면 다음 daily 가 같은 건을 또 검수함에 올린다.

네이티브형인 이유: 승인은 두 명령(approve→upload)을 순서대로 돌려야 하고, 그 사이에
원장 상태를 봐야 하기 때문이다(중간에 죽어도 다시 돌릴 수 있게 — 아래 멱등 규칙).

멱등(재시도 안전):
  · 이미 approved 면 approve 를 건너뛰고 upload 만 — 패키지 재생성으로 시간 낭비하지 않는다.
  · 이미 uploaded 면 아무것도 하지 않고 성공 — 같은 영상을 두 번 올리지 않는다(R10 사고 방지).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from ves import config as cfgmod
from ves.adapters import base
from ves.adapters import zanmang

TIMEOUT_SEC = 60 * 30          # 패키지 생성 + 업로드. 현지화(수십 분)는 이미 끝난 뒤다.
TIMEOUT_PROCESS = 3600 * 3     # rerender 의 process 는 현지화 전체(다운로드·demucs·더빙 포함)
GATE_TIMEOUT = 20              # 오채널 게이트 HTTP 호출당(초)
_URL_RE = re.compile(r"https://youtu\.be/([A-Za-z0-9_-]{6,})")


# ───────── 순수 (테스트 대상) ─────────
def plan(state: str, action: str) -> list:
    """원장 상태 + 결정 → 실행할 task 목록. 순수 — 테스트 대상.

    이 표가 멱등의 전부다. 알 수 없는 상태면 빈 목록(사람이 봐야 한다)."""
    if action == "skip":
        return [] if state in ("skipped", "uploaded") else ["mark"]
    if action == "rerender":
        # 반려-수정 재렌더(8/14, 0038): 원장 **정상 전이로만** 되돌려 다시 돌린다 —
        # pending_approval→skipped→selected→(process: processing→…→pending_approval).
        # force 전이는 쓰지 않는다(감사 추적·상태기계 보존). 이미 승인/게시된 건은 거부 —
        # 게시물 교체는 사람이 원장·Studio 에서 직접 푸는 영역이다.
        if state == "pending_approval":
            return ["mark_skip", "mark_select", "process"]
        if state in ("skipped", "failed"):
            return ["mark_select", "process"]      # 재시도(첫 실행이 죽었을 때) 멱등 경로
        if state == "selected":
            return ["process"]
        if state in ("approved", "uploaded"):
            raise base.PermanentError(
                f"원장 상태 '{state}' — 재렌더 불가(이미 승인/게시됨). 원장을 직접 되돌린 뒤 다시.")
        return []                       # processing 등 — 손대지 않는다(진행 중)
    if action != "publish":
        raise base.PermanentError(f"알 수 없는 결정: {action}")
    if state == "uploaded":
        return []                       # 이미 올라갔다 — 재업로드 금지
    if state == "approved":
        return ["upload"]               # 패키지는 있다 — 업로드만
    if state == "pending_approval":
        return ["approve", "upload"]
    return []                           # processing/failed 등 — 손대지 않는다


def parse_youtube_url(stdout: str):
    """upload 로그에서 게시 URL 추출. 순수 — 테스트 대상."""
    m = _URL_RE.search(stdout or "")
    return m.group(0) if m else None


# ───────── 오채널 게이트 (8/20 사고 재발 방지) ─────────
# 경위: LOOPY 토큰이 같은 구글 계정의 다른 브랜드 채널(ジャンマンルピーの日常)로 발급돼
# 발행이 오채널로 나갔다. brain 경로는 publish_youtube.py 가 최종 방어선인데 vlp 경로에는
# 그게 없어서 뚫렸다 — upload 직전에 토큰의 실채널을 channels_mirror 와 대조한다.

def client_pairs(env: dict) -> list:
    """env 에서 (client_id, client_secret) 후보 목록. 순수 — 테스트 대상.

    vlp 토큰 파일(outputs/yt_oauth_token.json)에는 클라이언트가 없어서, ves.env 의
    YT_CLIENT_ID*/SECRET* 쌍을 전부 시도한다 — 어느 gcp_project 로 발급했는지 몰라도 된다."""
    out = []
    for k in sorted(env):
        if k.startswith("YT_CLIENT_ID"):
            sec = (env.get(k.replace("YT_CLIENT_ID", "YT_CLIENT_SECRET")) or "").strip()
            if (env[k] or "").strip() and sec:
                out.append((env[k].strip(), sec))
    return out


def find_token_file(repo):
    """vlp 레포의 refresh_token JSON 경로(실측 8/21: outputs/yt_oauth_token.json).
    이동을 대비해 outputs/·config/ 의 *.json 도 훑는다. 없으면 None. 순수 — 테스트 대상."""
    root = pathlib.Path(repo)
    cands = [root / "outputs" / "yt_oauth_token.json"]
    for pat in ("outputs/*.json", "config/*.json"):
        cands += sorted(root.glob(pat))
    for p in cands:
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("refresh_token"):
            return p
    return None


def _bound_channel(refresh_token: str, pairs: list):
    """토큰이 실제 바인딩된 (channel_id, title). 어떤 후보로도 확인 못 하면 None.

    invalid_grant(그 클라이언트로 발급된 토큰이 아님 — 영구)와 네트워크 장애(일시)를
    가른다: 전 후보가 네트워크로만 실패하면 RuntimeError 로 올려 재시도에 태운다."""
    net_fail = 0
    for cid, sec in pairs:
        body = urllib.parse.urlencode({
            "client_id": cid, "client_secret": sec,
            "refresh_token": refresh_token, "grant_type": "refresh_token"}).encode()
        try:
            r = urllib.request.urlopen(urllib.request.Request(
                "https://oauth2.googleapis.com/token", data=body), timeout=GATE_TIMEOUT)
            access = json.loads(r.read())["access_token"]
        except urllib.error.HTTPError:
            continue                       # invalid_grant 등 — 다음 클라이언트
        except (OSError, ValueError):
            net_fail += 1
            continue
        try:
            req = urllib.request.Request(
                "https://www.googleapis.com/youtube/v3/channels?part=id,snippet&mine=true",
                headers={"Authorization": f"Bearer {access}"})
            items = json.loads(urllib.request.urlopen(req, timeout=GATE_TIMEOUT).read()) \
                .get("items") or []
        except (OSError, ValueError) as e:
            raise RuntimeError(f"오채널 게이트: 채널 조회 실패(일시로 간주) — {e}")
        if items:
            return items[0]["id"], items[0]["snippet"]["title"]
        return None                        # 토큰은 유효한데 채널이 없다 — 검증 불가로 차단
    if pairs and net_fail == len(pairs):
        raise RuntimeError("오채널 게이트: 전 클라이언트 네트워크 장애 — 재시도")
    return None


def assert_upload_channel(conn, repo) -> str:
    """upload 직전 게이트: 불일치·검증불가는 PermanentError(발행 차단), 장애는 재시도.

    미발급이 발행 하드실패(R10)이듯 '어느 채널인지 모르는 토큰'도 하드실패다 —
    조용히 통과시키면 오채널 발행이 성공으로 남는다."""
    with conn.cursor() as c:
        c.execute("SELECT channel_id, name FROM public.channels_mirror WHERE token_slug=%s",
                  (zanmang.CHANNEL,))
        row = c.fetchone()
    if not row or not row["channel_id"]:
        raise base.PermanentError(
            "오채널 게이트: channels_mirror 에 LOOPY channel_id 없음 — channels.json 확인")
    tf = find_token_file(repo)
    if tf is None:
        raise base.PermanentError(f"오채널 게이트: vlp 토큰 파일 못 찾음({repo}) — 업로드 차단")
    refresh = str(json.loads(tf.read_text(encoding="utf-8")).get("refresh_token") or "")
    env = dict(os.environ)                 # job_env 와 같은 우선순위 — 파일은 지금 다시
    for k, v in cfgmod.file_env().items():  # 읽는다(08-18 함정: 기동 때 값이 낡는다)
        env.setdefault(k, v)
    pairs = client_pairs(env)
    if not pairs:
        raise base.PermanentError("오채널 게이트: ves.env 에 YT_CLIENT_ID*/SECRET* 쌍 없음 — 검증 불가")
    got = _bound_channel(refresh, pairs)
    if got is None:
        raise base.PermanentError(
            "오채널 게이트: 어떤 클라이언트로도 토큰 검증 실패(invalid_grant) — 토큰 재발급/클라이언트 확인")
    cid, title = got
    if cid != row["channel_id"]:
        raise base.PermanentError(
            f"오채널 게이트: 토큰이 다른 채널에 바인딩됨 — 실채널 {cid}({title}) ≠ "
            f"기대 {row['channel_id']}({row['name']}). 업로드 차단, 토큰 재발급 필요")
    return f"{cid} {title}"


# ───────── 실행부 ─────────
def _ledger_state(repo, video_id):
    rows = zanmang.pending_rows(pathlib.Path(repo) / zanmang.LEDGER_REL)
    if any(r["video_id"] == video_id for r in rows):
        return "pending_approval"
    import sqlite3
    p = pathlib.Path(repo) / zanmang.LEDGER_REL
    if not p.exists():
        raise base.PermanentError(f"원장 없음: {p}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT state FROM videos WHERE video_id=?", (video_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise base.PermanentError(f"원장에 없는 video_id: {video_id}")
    return row[0]


def _task_argv(repo: str, task: str, vid: str, p: dict) -> list:
    """plan 의 task 이름 → CLI argv. 순수 — 테스트 대상."""
    if task == "process":
        return zanmang.process_argv(repo, vid)
    if task in ("mark", "mark_skip", "mark_select"):
        return zanmang.action_argv(repo, "mark", vid,
                                   state="selected" if task == "mark_select" else "skipped")
    return zanmang.action_argv(repo, task, vid,
                               privacy=p.get("privacy") if task == "upload" else None,
                               publish_at=p.get("publish_at") if task == "upload" else None)


def run(cfg, conn, job, deps):
    # P8(2026-08-27): vlp 동결 — 레거시 카드 drain 후 어떤 잡도 vlp 로 보내지 않는다.
    # 코드는 남긴다(감사 이력 재현용) — 켜고 끄는 것은 ops_config 한 줄(0102).
    if base.ops_on(conn, "vlp_frozen"):
        raise base.PermanentError(
            "vlp 동결됨(P8, ops_config vlp_frozen=on) — 이 잡은 실행되지 않습니다. "
            "필요한 소재는 새 파이프라인(overlay/롱폼)으로 재생산하세요. docs/P8_VLP_FREEZE.md")
    p = job["params"] or {}
    vid = p.get("video_id")
    action = p.get("action") or "publish"
    repo = p.get("repo") or zanmang.DEFAULT_REPO
    if not vid:
        raise base.PermanentError("params.video_id 없음")
    if not pathlib.Path(f"{repo}/.venv/bin/python").exists():
        raise base.PermanentError(f"잔망루피 레포 .venv 없음: {repo}")

    state = _ledger_state(repo, vid)
    tasks = plan(state, action)
    if "approve" in tasks:
        # 산출물 복원(2단계 ③): approve 는 outputs/<vid> 로 패키지를 만든다 — 처리한
        # 맥이 아니면(또는 정리됐으면) ves-runs/ves-localized 에서 재구성한다.
        _restore_outputs(cfg, repo, vid)
    if action == "rerender" and tasks:
        # 반려-수정 재렌더(8/14, 0038): 검수함에서 고친 텍스트를 파이프라인이 읽는 자리
        # (outputs/<vid>/overrides.json)에 내려놓는다 — dub(C)·process_video(B/BJ)가
        # 렌더 직전에 병합한다. 좌표는 카드 ko_ja_pairs 의 idx.
        ov = p.get("overrides") or {}
        if not ov:
            raise base.PermanentError("rerender 인데 params.overrides 없음 — 0038 RPC 확인")
        import json as _json
        out_dir = pathlib.Path(repo) / "outputs" / str(vid)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "overrides.json").write_text(
            _json.dumps(ov, ensure_ascii=False, indent=2), encoding="utf-8")
    if not tasks:
        return {"video_id": vid, "action": action, "state": state, "skipped": True,
                "note": f"원장 상태 '{state}' — 할 일 없음(이미 반영됨)"}

    out = {"video_id": vid, "action": action, "from_state": state, "ran": []}
    if "upload" in tasks:
        # 오채널 게이트 — approve(패키지 생성, 수 분)보다 먼저 확인해 헛일을 막는다.
        out["channel_gate"] = assert_upload_channel(conn, repo)
        print(f"[zanmang_decision] 오채널 게이트 통과: {out['channel_gate']}")
    for task in tasks:
        argv = _task_argv(repo, task, vid, p)
        r = subprocess.run(argv, cwd=repo, capture_output=True, text=True,
                           timeout=TIMEOUT_PROCESS if task == "process" else TIMEOUT_SEC)
        tail = ((r.stdout or "") + "\n" + (r.stderr or ""))[-500:]
        if r.returncode != 0:
            cls = base.classify_by_patterns(r.stderr or "", r.stdout or "")
            msg = f"{task} 실패: {tail}"
            if cls == "permanent":
                raise base.PermanentError(msg)
            if cls == "quota":
                raise base.QuotaError(msg)     # 유튜브 업로드 한도 — 내일 다시
            raise RuntimeError(msg)
        out["ran"].append(task)
        if task == "upload":
            url = parse_youtube_url(r.stdout or "")
            if url:
                out["youtube_url"] = url
        out[f"{task}_tail"] = tail[-200:]

    if action == "rerender" and "process" in out["ran"]:
        # 업로드 제목·설명은 process 가 LLM 으로 초안을 다시 뽑는다(비결정) — 운영자가
        # 고친 값이 이겨야 하므로 metadata_draft 를 사후 패치한다. 자막은 파이프라인이
        # overrides.json 으로 이미 반영했다.
        _patch_meta(repo, vid, p.get("overrides") or {})
        out["rerendered"] = True
        try:
            # 새 검수 카드 즉시 등록 — 다음 daily(내일 10시)를 기다리지 않는다.
            # post_success 는 pending_approval 전수를 훑고 대기 카드 중복을 걸러 멱등.
            zanmang.post_success(cfg, conn,
                                 {"id": job["id"], "params": {"task": "daily", "repo": repo}},
                                 {})
            out["card_registered"] = True
        except Exception as e:  # noqa: BLE001 — 카드 등록 실패는 비치명(다음 daily 가 등록)
            print(f"[zanmang_decision] 재렌더 후 카드 등록 실패(비치명): {e}")
    return out


def _patch_meta(repo, vid: str, ov: dict) -> None:
    """운영자가 고친 업로드 제목·설명을 metadata_draft.json 에 반영 — uploader 가
    title_candidates[0]·description 을 쓴다. 실패는 비치명(새 카드에서 다시 고치면 된다)."""
    title = str(ov.get("youtube_title_ja") or "").strip()
    desc = str(ov.get("description_ja") or "").strip()
    if not (title or desc):
        return
    import json as _json
    f = pathlib.Path(repo) / "outputs" / str(vid) / "metadata_draft.json"
    try:
        md = _json.loads(f.read_text(encoding="utf-8"))
        if title:
            cands = md.get("title_candidates") or []
            md["title_candidates"] = [title] + [c for c in cands if c != title]
        if desc:
            md["description"] = desc
        f.write_text(_json.dumps(md, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[zanmang_decision] metadata_draft 패치(운영자 수정 반영): "
              f"제목 {'O' if title else '-'} 설명 {'O' if desc else '-'}")
    except (OSError, ValueError) as e:
        print(f"[zanmang_decision] metadata_draft 패치 실패(비치명): {e}")


def _restore_outputs(cfg, repo, vid: str) -> None:
    """outputs/<vid> 가 없거나 최종 산출 영상이 없으면 스토리지에서 복원.

    원료: ves-runs loopy/<vid>/*(텍스트 — post_success 가 올림) +
          ves-localized <key>/loopy_ja.mp4(최종 영상 — 프리뷰와 같은 파일).
    최종 영상 파일명은 라우트 규약(FINAL_BY_ROUTE)을 따라야 approve 가 찾는다.
    이미 로컬에 있으면 아무것도 안 한다(처리 맥에서의 승인 = 종전과 동일)."""
    import pathlib as _pl
    out = _pl.Path(repo) / "outputs" / str(vid)
    rows = zanmang.pending_rows(_pl.Path(repo) / zanmang.LEDGER_REL)
    row = next((r for r in rows if r["video_id"] == vid), None)
    route = str((row or {}).get("level_guess") or "B").upper()
    finals = zanmang.FINAL_BY_ROUTE.get(route, ["final_draft.mp4"])
    if any((out / n).exists() for n in finals):
        return
    from ves.storage.supabase_storage import Store
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    out.mkdir(parents=True, exist_ok=True)
    for name in zanmang.LOOPY_TEXT_FILES:
        try:
            store.download("ves-runs", zanmang.loopy_store_key(vid, name), str(out / name))
        except RuntimeError:
            (out / name).unlink(missing_ok=True)      # 없던 파일 — 흔적 제거
    try:
        store.download("ves-localized", base.storage_key(vid, "loopy_ja.mp4"),
                       str(out / finals[0]))
    except RuntimeError as e:
        raise base.PermanentError(
            f"산출물 복원 실패({vid}) — ves-localized 에 최종 영상 없음: {e}")
    print(f"[zanmang_decision] outputs/{vid} 복원(route={route}) — 다른 맥 승인 경로")
