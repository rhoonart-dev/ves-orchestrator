"""P6 — 편집실이 overlay(잔망루피 쇼츠) 카드를 실제로 고칠 수 있게 (2026-08-26).

세 조각이 한 계약이다:
  ① 0098   reject_and_rerender 에 overlay 갈래 — 종전엔 generate 결과를 요구하다
            '재렌더 불가'로 죽었다(overlay 체인엔 generate 가 없다).
  ② 어댑터  write_overlay_overrides — overlay 엔진은 rerender 와 달리 overrides 를
            인자로 안 받는다. outputs/<id>/overrides.json 을 스스로 읽으므로 실행
            **전에** 그 자리에 놔야 한다.
  ③ 대시보드 edJpKind 가 **채널이 아니라 mode 로** 갈리고, 멱등키 세 벌이
            서버(0038·0098)와 같아야 진행 표시가 잡을 찾는다.
"""
import inspect
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ves.adapters import localize  # noqa: E402

MIG = pathlib.Path("ves/control/migrations/0098_overlay_rerender.sql") \
    .read_text(encoding="utf-8")
HTML = pathlib.Path("dashboard/index.html").read_text(encoding="utf-8")


# ── ② 어댑터 — overrides 파일 내려놓기 ─────────────────────────────────
def test_overrides_written_to_engine_outputs(tmp_path):
    ov = {"subs": {"3": "直した行"}, "youtube_title_ja": "新しい題"}
    got = localize.write_overlay_overrides(str(tmp_path), "vid123", ov)
    path = tmp_path / "outputs" / "vid123" / "overrides.json"
    assert got == str(path)
    assert json.loads(path.read_text(encoding="utf-8")) == ov


def test_no_overrides_writes_nothing(tmp_path):
    """첫 현지화(overrides 없음)는 파일이 없어야 정상이다 — 회귀 0."""
    assert localize.write_overlay_overrides(str(tmp_path), "vid123", None) is None
    assert localize.write_overlay_overrides(str(tmp_path), "vid123", {}) is None
    assert not (tmp_path / "outputs").exists()


def test_overrides_not_ascii_escaped(tmp_path):
    """일본어가 \\uXXXX 로 저장되면 vlp 엔진 쪽 diff·사람 확인이 불가능해진다."""
    localize.write_overlay_overrides(str(tmp_path), "v", {"subs": {"0": "翻訳"}})
    raw = (tmp_path / "outputs" / "v" / "overrides.json").read_text(encoding="utf-8")
    assert "翻訳" in raw


def test_run_writes_overrides_before_engine_argv():
    """실행 순서가 계약이다 — 엔진이 스스로 읽는 파일이라 프로세스를 띄우기 전에
    있어야 한다. run() 소스에서 호출이 argv 구성보다 앞이어야 한다."""
    src = inspect.getsource(localize.run)
    tail = src.split('write_overlay_overrides(eng, run_id, p.get("overrides"))', 1)[1]
    assert "aivideo_overlay_argv" in tail and "localize_argv" in tail, \
        "overrides 를 argv 구성(=실행 직전)보다 먼저 내려놓아야 한다"


def test_overlay_qa_card_carries_mode():
    """편집실·0098 이 보는 갈래 열쇠 — overlay 카드 payload 에 mode 가 실린다.
    없으면 id 모양으로 추측하게 되고, 잔망루피 롱폼(scene_rerender)이 오인된다."""
    src = inspect.getsource(localize.run)
    assert '"mode": "overlay"' in src


# ── ① 0098 — 갈래 순서·멱등키·잡 모양 ──────────────────────────────────
def test_branch_order_zanmang_then_overlay_then_generate():
    """순서가 계약이다: 구 vlp 카드(zanmang_video_id) → overlay(신규) → generate 기반.
    overlay 검사가 zanmang 앞에 오면 구 카드가 새 길로 새고, generate 검사 뒤에 오면
    영영 도달하지 못한다(거기서 RAISE 로 끝난다)."""
    i_vid = MIG.index("v_rq.payload->>'zanmang_video_id'")
    i_ext = MIG.index("v_rq.payload->>'external_video_id'")
    i_gen = MIG.index("j.kind = 'generate'")
    assert i_vid < i_ext < i_gen


def test_scene_rerender_cards_skip_the_overlay_branch():
    """잔망루피 **롱폼**은 external_video_id 가 있어도 우리 타임라인이 있다 —
    mode='scene_rerender' 면 overlay 갈래를 지나쳐 generate 기반으로 가야 한다.
    mode 없는 옛 overlay 카드는 coalesce 로 overlay 취급(이미 큐에 선 카드도 살린다)."""
    assert "coalesce(v_mode, 'overlay') <> 'scene_rerender'" in MIG


def test_overlay_rerender_job_shape():
    """재투입 잡은 첫 현지화와 같은 어댑터 계약이어야 한다 — kind=localize ·
    mode=overlay · 캡 localize(OCR·인페인팅 스택 노드) · overrides=p_edits."""
    body = MIG.split("-- ── overlay", 1)[1].split("-- ── SHOTCONE", 1)[0]
    assert "'localize', v_rq.work_order_id" in body
    assert "jsonb_build_object('mode', 'overlay'" in body
    assert "'overrides', p_edits" in body
    assert "ARRAY['localize']" in body
    assert "'level', v_route" in body, "route 가 안 실리면 기본 B 로 돌아 C 편이 더빙을 잃는다"


def test_overlay_rerender_idempotency_key():
    assert "'overlay_rerender:' || v_ext || ':' || p_review_id" in MIG


def test_overlay_conflict_refreshes_params():
    """같은 카드를 두 번 고쳐 보내면 **나중 수정본**이 실려야 한다 — params 를
    갈아끼우지 않으면 재시도가 첫 판 overrides 로 돈다."""
    body = MIG.split("-- ── overlay", 1)[1].split("-- ── SHOTCONE", 1)[0]
    assert "SET params=EXCLUDED.params" in body


def test_legacy_branches_unchanged():
    """0038 의 두 갈래는 문자열까지 그대로 — 구 카드 경로가 움직이면 안 된다."""
    base = pathlib.Path("ves/control/migrations/0038_reject_and_rerender.sql") \
        .read_text(encoding="utf-8")
    for frag in ("'zanmang_rerender:' || v_vid || ':' || p_review_id",
                 "'rerender:' || p_review_id",
                 "'generate 결과(run_id/run_dir/node) 없음 — 재렌더 불가'"):
        assert frag in base and frag in MIG


def test_ledger_row_0098():
    assert "VALUES ('orchestrator','0098'" in MIG


# ── ③ 대시보드 — mode 분기·멱등키 사본 ─────────────────────────────────
def _fn(name):
    return HTML.split(f"function {name}(", 1)[1].split("\nfunction ", 1)[0]


def test_dashboard_kind_branches_on_mode():
    fn = _fn("edJpKind")
    assert 'pay.mode === "scene_rerender"' in fn and '"rerender"' in fn
    assert 'pay.mode === "overlay"' in fn
    # mode 없는 옛 카드(vlp 원장·8/26 이전 overlay)는 id 모양 폴백
    assert "pay.zanmang_video_id || pay.external_video_id" in fn


def test_dashboard_chain_keys_match_server():
    """서버(0038·0098)가 정본, 대시보드 셋은 사본 — 갈리면 진행 표시가 잡을 영영
    못 찾는다('보냈는데 아무 일도 안 남'). 문자열로 묶는다."""
    fn = _fn("edJpChainKey")
    assert "`zanmang_rerender:${f.vid}:${f.rid}`" in fn
    assert "`overlay_rerender:${f.ext}:${f.rid}`" in fn
    assert "`rerender:${f.rid}`" in fn
    # 서버 쪽 세 키(0038 둘 + 0098 하나)와 접두가 같은가
    assert "'overlay_rerender:' || v_ext" in MIG
    assert "'zanmang_rerender:' || v_vid" in MIG


def test_dashboard_key_built_only_by_helper():
    """제출·복구 두 곳이 같은 함수를 써야 한다 — 한쪽만 고치면 새로고침 뒤 키가
    갈린다. 인라인 키 조립이 남아 있으면 실패."""
    assert HTML.count("edJpChainKey(f)") >= 2      # submit + recover
    # 함수 정의 밖에 인라인 zanmang_rerender 템플릿이 없어야 한다
    outside = HTML.replace(_fn("edJpChainKey"), "")
    assert "`zanmang_rerender:" not in outside


def test_dashboard_form_carries_ext_and_overlay_flag():
    fn = _fn("edJpResetForm")
    assert "ext: pay.external_video_id || null" in fn
    assert 'overlay: edJpMode === "overlay"' in fn
    assert "f.loopy" not in HTML, "옛 이름이 남으면 절반만 갈아탄 화면이 된다"


def test_chain_poll_finds_new_card_without_work_order():
    """새 카드 탐지 열쇠가 카드마다 다르다 — 구 vlp 카드는 work_order_id 가 없고
    (vid 로), overlay 는 woId 로, 그것도 없으면 ext 로. 셋 다 없으면 찾지 않는다
    (엉뚱한 카드를 '새 카드'로 열면 남의 편을 승인한다)."""
    assert re.search(r"c\.vid \? q\.contains.*zanmang_video_id[\s\S]*?"
                     r"c\.woId \? q\.eq\(\"work_order_id\"[\s\S]*?"
                     r"c\.ext \? q\.contains.*external_video_id", HTML)
    assert "ext: f.ext" in HTML   # 체인 상태에 ext 가 실려야 폴이 쓸 수 있다
