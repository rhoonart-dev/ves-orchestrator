"""L-P5-발행 ② — 외부 완성본 발행 어댑터.

이 파일이 지키는 것:
  ① **재업로드 없음** — 원장에 youtube_id 가 있으면 아무것도 안 한다
  ② **공개 직행 없음**(R9) — private|unlisted 만, 예약은 private+publishAt
  ③ **한국어 제목이 조용히 나가지 않는다** — 일본어 제목이 없으면 발행 자체를 안 한다
  ④ 자격증명 이름이 brain 과 같다(같은 채널에 두 벌의 시크릿을 넣게 하지 않는다)
"""
import datetime as dt
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from ves.adapters import base, publish_external as px  # noqa: E402

DRAFT = {"title_candidates": ["日本語タイトル", "第2案"], "description": "本文\n\n© X",
         "tags": [f"t{i}" for i in range(30)]}


# ── ③ 제목 ────────────────────────────────────────────────────────────────
def test_title_prefers_the_human_choice_then_the_first_candidate():
    assert px.pick_title(DRAFT) == "日本語タイトル"
    assert px.pick_title(DRAFT, "사람이 고른 제목") == "사람이 고른 제목"


def test_title_never_falls_back_to_the_korean_source():
    """🛑 0075 사고와 같은 자리 — 일본 채널에 한국어 제목이 뜨면 안 된다.

    후보가 없으면 빈 문자열이고, 빈 제목은 발행 자체를 막는다(publishable_snippet)."""
    assert px.pick_title({"title_candidates": []}) == ""
    assert px.pick_title({}) == ""
    assert not px.publishable_snippet(px.build_snippet({}, title=None))


def test_snippet_caps_and_language():
    s = px.build_snippet(DRAFT)
    assert len(s["tags"]) == px.MAX_TAGS
    assert s["defaultLanguage"] == "ja"
    assert "defaultAudioLanguage" not in s            # 더빙이 아니면 오디오는 한국어다
    assert px.build_snippet(DRAFT, audio_ja=True)["defaultAudioLanguage"] == "ja"


# ── ② 공개 규칙 ───────────────────────────────────────────────────────────
def test_public_is_refused():
    with pytest.raises(base.PermanentError) as e:
        px.build_status("public")
    assert "R9" in str(e.value)


def test_schedule_is_private_plus_publish_at():
    st = px.build_status("unlisted", "2026-08-27T10:00:00Z")
    assert st["privacyStatus"] == "private" and st["publishAt"] == "2026-08-27T10:00:00Z"


def test_plain_privacy_has_no_publish_at():
    assert "publishAt" not in px.build_status("unlisted")


# ── 예약 슬롯(vlp 이식) ───────────────────────────────────────────────────
def test_next_slot_skips_taken_days():
    now = dt.datetime(2026, 8, 26, 0, 0, tzinfo=dt.timezone.utc)   # 09:00 JST
    first = px.next_publish_at(now, set())
    second = px.next_publish_at(now, {first})
    assert first.endswith("Z") and second > first
    assert (dt.datetime.strptime(second, "%Y-%m-%dT%H:%M:%SZ")
            - dt.datetime.strptime(first, "%Y-%m-%dT%H:%M:%SZ")).days == 1


def test_next_slot_respects_the_lead_time():
    """이미 지난 오늘 19:00 은 못 쓴다 — 예약은 미래여야 한다."""
    now = dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.timezone.utc)  # 21:00 JST
    assert px.next_publish_at(now, set()).startswith("2026-08-27")


# ── ④ 자격증명 이름 ───────────────────────────────────────────────────────
def test_credential_keys_match_brain():
    assert px.credential_keys("JMLP", "LOOPY") == (
        "YT_CLIENT_ID_JMLP", "YT_CLIENT_SECRET_JMLP", "YT_REFRESH_TOKEN_LOOPY")
    assert px.credential_keys(None, "LOOPY")[:2] == ("YT_CLIENT_ID", "YT_CLIENT_SECRET")


def test_missing_credentials_name_the_missing_keys(tmp_path, monkeypatch):
    """폴백이 미설정을 삼키면 밤중에 unauthorized_client 로 터진다(brain 2026-07-29)."""
    for k in ("YT_CLIENT_ID_JMLP", "YT_CLIENT_SECRET_JMLP", "YT_REFRESH_TOKEN_LOOPY",
              "YT_OAUTH_CLIENT_ID", "YT_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    cfg = type("C", (), {"home": str(tmp_path)})()
    with pytest.raises(base.PermanentError) as e:
        px._resolve_credentials(cfg, "JMLP", "LOOPY")
    assert "YT_REFRESH_TOKEN_LOOPY" in str(e.value) and "YT_CLIENT_ID_JMLP" in str(e.value)


# ── ① 재업로드 금지 ───────────────────────────────────────────────────────
class _Cur:
    def __init__(self, row): self.row = row
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, *a, **k): pass
    def fetchone(self): return self.row


class _Conn:
    def __init__(self, row): self.row = row
    def cursor(self): return _Cur(self.row)


def test_already_published_is_a_noop():
    got = px.run(None, _Conn({"youtube_id": "abc123", "state": "uploaded"}),
                 {"params": {"external_video_id": "drive:x", "key": "k"}}, {})
    assert got["youtube_id"] == "abc123" and got["skipped"] == "already_uploaded"


def test_the_guard_runs_before_anything_else():
    """🛑 다운로드·업로드보다 **먼저** 봐야 한다 — 같은 영상을 두 번 올리면 되돌릴 수 없다."""
    src = pathlib.Path("ves/adapters/publish_external.py").read_text(encoding="utf-8")
    body = src.split("def run(", 1)[1]
    assert body.index("_already_uploaded(") < body.index("store.download(")


def test_adapter_is_registered():
    assert base.get("publish_external") is px


# ── ⑤ 승인 RPC — 같은 버튼이 두 카드 모양을 받는다 (0094) ──────────────────

def _mig() -> str:
    import pathlib
    d = pathlib.Path("ves/control/migrations")
    files = sorted(p for p in d.glob("*.sql")
                   if "CREATE OR REPLACE FUNCTION public.decide_loopy" in p.read_text(encoding="utf-8"))
    return files[-1].read_text(encoding="utf-8")


def test_new_cards_route_to_publish_external():
    sql = _mig()
    assert "v_ext := v_rq.payload->>'external_video_id'" in sql
    assert "'publish_external'" in sql


def test_old_zanmang_cards_still_go_the_old_way():
    """회귀 0 — vlp 원장 카드는 종전 잡·종전 멱등키 그대로다."""
    sql = _mig()
    assert "'zanmang_decision'" in sql
    assert "'zanmang_decide:' || v_vid || ':' || v_action" in sql
    assert "ARRAY['localize', 'node:' || v_node]" in sql


def test_publish_is_refused_without_a_japanese_title():
    """🛑 빈 초벌로 올리면 한국어 원제가 일본 채널 제목이 된다(0075 사고)."""
    sql = _mig()
    assert "일본어 제목이 없습니다" in sql
    assert "v_meta->'title_candidates'->>0" in sql


def test_reject_on_the_new_path_makes_no_job():
    """새 경로의 상태는 이 DB 에 있다 — vlp 원장에 찍을 것이 없으므로 잡도 없다."""
    sql = _mig()
    new_path = sql.split("IF v_ext IS NOT NULL THEN", 1)[1].split("-- ── 종전 경로", 1)[0]
    reject = new_path.split("IF NOT coalesce(p_approve,false) THEN", 1)[1].split("END IF;", 1)[0]
    assert "state = 'skipped'" in reject and "INSERT INTO public.job_queue" not in reject


def test_dub_routes_declare_japanese_audio():
    """route C·BC 만 오디오가 일본어다 — 그 외는 한국어 소리 위에 자막이다."""
    assert "IN ('C','BC')" in _mig()


def test_publish_external_job_is_idempotent_per_video():
    """재합격이 두 번째 업로드를 만들면 안 된다 — 멱등키는 영상 하나에 하나."""
    sql = _mig()
    assert "'publish_external:' || v_ext" in sql
    assert "ON CONFLICT (idempotency_key) DO UPDATE" in sql


# ── ⑥ 검수 화면 — 사람이 무엇을 승인하는지 보여야 한다 ─────────────────────

def _html() -> str:
    import pathlib
    return pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")


def test_new_cards_render_on_the_same_screen():
    html = _html()
    assert "pay.zanmang_video_id || pay.external_video_id" in html
    assert "function loopyPayload(pay)" in html


def test_the_screen_shows_the_title_that_will_actually_be_published():
    """🛑 화면이 2안을 보여주면서 1안이 올라가면 승인한 것과 다른 것이 나간다.

    RPC 도 `title_candidates->>0` 을 쓴다 — 두 곳이 같은 규칙이어야 한다."""
    html = _html()
    assert "youtube_title: cand[0]" in html
    assert "_alt_titles: cand.slice(1)" in html
    assert "v_meta->'title_candidates'->>0" in _mig()


def test_empty_draft_is_visible_before_approving():
    """초벌이 비면 승인해도 발행 잡이 안 선다 — 그 사실을 카드에서 미리 알린다."""
    assert "_meta_warning" in _html()


def test_route_labels_match_the_engine_levels():
    """라벨이 틀리면 검수자가 안 본 것을 봤다고 믿는다(종전 A='무변환'은 오기였다)."""
    html = _html()
    block = html.split("const LOOPY_ROUTE", 1)[1].split("};", 1)[0]
    for route in ("A:", "B:", "BJ:", "C:", "BC:"):
        assert route in block
    assert "무변환" not in block


# ── ⑦ 재실행하면 검수 카드도 새 산출을 가리켜야 한다 ───────────────────────

def test_rerun_refreshes_the_waiting_card_instead_of_skipping():
    """🛑 종전엔 대기 카드가 있으면 **건너뛰었다** — 다시 돌려도 사람은 옛 자료를 본다.

    0075 가 잡은 함정과 같은 부류다(새 카드의 ko_ja_pairs 가 직전 카드와 바이트 단위로
    동일했다). 결정된 카드는 감사 기록이라 손대지 않는다(status='waiting' 조건)."""
    src = pathlib.Path("ves/adapters/localize.py").read_text(encoding="utf-8")
    fn = src.split("def _enqueue_qa(", 1)[1].split("\ndef ", 1)[0]
    assert "UPDATE public.review_queue" in fn
    assert "status='waiting'" in fn
    assert fn.index("UPDATE public.review_queue") < fn.index("INSERT INTO public.review_queue")


def test_both_modes_use_the_same_card_helper():
    """overlay 와 rerender 가 각자 INSERT 하면 한쪽만 고쳐진다(실제로 그랬다)."""
    src = pathlib.Path("ves/adapters/localize.py").read_text(encoding="utf-8")
    assert src.count("INSERT INTO public.review_queue") == 1
    calls = src.count("_enqueue_qa(conn, job,") - src.count("def _enqueue_qa(conn, job,")
    assert calls == 2, f"호출부 {calls}곳"


# ── ⑧ 검수에서 문구를 고칠 수 있다 (0095) ─────────────────────────────────

def _mig95() -> str:
    import pathlib
    return pathlib.Path("ves/control/migrations/0095_review_title_edit.sql").read_text(encoding="utf-8")


def test_human_title_wins_over_the_draft():
    """🛑 실물 1편에서 바로 필요해졌다 — 자동 제목에 한국어 해시태그가 남았다."""
    sql = _mig95()
    assert "coalesce(nullif(btrim(coalesce(p_title,'')), '')," in sql
    assert "v_meta->'title_candidates'->>0, '')" in sql


def test_empty_edit_falls_back_to_the_draft():
    """빈칸으로 지웠다고 제목 없는 발행이 되면 안 된다 — nullif+coalesce 가 그것이다."""
    sql = _mig95()
    block = sql.split("v_title := coalesce(", 1)[1].split(";", 1)[0]
    assert "nullif(btrim" in block and "title_candidates" in block


def test_youtube_title_limit_is_enforced_before_upload():
    """100자를 넘기면 유튜브가 거부한다 — 업로드까지 가기 전에 막는다."""
    assert "length(v_title) > 100" in _mig95()


def test_the_approved_wording_is_recorded_on_the_card():
    """카드를 나중에 보면 초벌이 아니라 **실제로 올라간 문구**가 보여야 한다."""
    sql = _mig95()
    assert "'approved_title', v_title" in sql and "'approved_description', v_desc" in sql


def test_one_body_two_signatures():
    """구현이 두 벌이면 한쪽만 고쳐진다 — 5-인자는 7-인자에 위임한다(0088 규약)."""
    sql = _mig95()
    assert sql.count("CREATE OR REPLACE FUNCTION public.decide_loopy") == 2
    wrapper = sql.split("-- 5-인자 판", 1)[1]
    assert "SELECT public.decide_loopy(p_review_id, p_approve, p_note, p_privacy, p_publish_at," in wrapper
    assert "publish_external" not in wrapper          # 본문은 위 한 벌뿐


def test_the_edit_fields_are_only_on_our_cards():
    """vlp 원장 카드는 그쪽이 문구를 든다 — 여기서 고칠 수 있게 하면 거짓말이 된다."""
    html = _html()
    assert "const editable = !!pay.metadata;" in html
    assert 'id="ltit_${r.id}"' in html and 'maxlength="100"' in html


def test_the_edited_wording_is_sent_to_the_rpc():
    html = _html()
    assert "p_title: ok && ti ?" in html and "p_description: ok && de ?" in html
