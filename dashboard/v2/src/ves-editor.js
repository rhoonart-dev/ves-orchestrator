// VES Studio 편집실 — Workspace 코드다. 2026-09-29 까지는 ves-orchestrator/dashboard/index.html 의 타임라인 편집기를
// 가져와(원본 sha256 61a439e3…) 패치로 고쳤고, 이제는 이 파일을 직접 고친다. 본 편집실의 새 기능은 필요할 때 손으로 옮긴다.
(function(){
const tlRoot = document.getElementById("tlRoot");

"use strict";
const sb = window.__sbMain;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = s => { s = Math.max(0, Number(s) || 0);
  const m = Math.floor(s / 60), x = (s % 60).toFixed(1);
  return m + ":" + String(x).padStart(4, "0"); };

// ── 인증 ──────────────────────────────────────────────────────────────
async function doLogin(){
  $("#err").textContent = "";
  const { error } = await sb.auth.signInWithPassword({
    email: $("#em").value.trim(), password: $("#tlPw").value });
  if (error){ $("#err").textContent = error.message; return; }
  boot();
}
async function boot(){
  const { data: { user } } = await sb.auth.getUser();
  if (!user){ $("#tlLogin").style.display = "flex"; $("#tlApp").style.display = "none"; return; }
  $("#tlLogin").style.display = "none"; $("#tlApp").style.display = "flex";
  $("#who").textContent = user.email; $("#logout").style.display = "";
  showRunLabel();
  // 편집실 주소의 ?run=<작업>/<vN> 을 바로 연다
  const qp = new URLSearchParams(location.search);
  if (!window.__qpOpened && qp.get("run")){
    window.__qpOpened = true;
    openRun(qp.get("run"));
  }
}

// ── run 목록 (읽기만) ─────────────────────────────────────────────────
let cur = null;   // {row, tl, merged}
// run 드롭다운 폐지(2026-08-26) — 목록의 정본은 편집함 하나다. 다른 편으로는
// [← 목록] 으로 돌아가 고른다(재료만 있고 반려·발행된 편까지 섞여 헷갈렸다).
// 자리는 '지금 열린 편'을 보여주는 이름표로 쓴다.
function loadRuns(){ showRunLabel(); }
function showRunLabel(){
  const el = $("#runs"); if (!el) return;
  if (!cur || !cur.row){ el.innerHTML = ""; return; }
  const wo = cur.wo || {};
  const name = cur.row.run_id.replace(/_[0-9a-f]{6,}$/, "").replace(/_/g, " ");
  el.innerHTML = `<b class="runname">${esc(name)}</b>` +
    (cur.row.status !== "ready"
      ? ` <span class="small faint" title="마지막 재료 기준으로 열림">⏳ 재료 재생성 대기</span>` : "");
}

async function openRun(runId, btn){
  autoSaveStop();                        // 이전 run 의 타이머는 여기서 끝난다
  // ⚠ 저장 안 된 편집 위에 덮어쓰지 않는다 — buildModel 은 모델을 통째로 갈아끼우므로
  // 여기서 막지 않으면 고친 제목·구간이 흔적 없이 사라진다(2026-08-27 유실 사고).
  if (dirty && cur && cur.model && !confirm(
      "저장하지 않은 편집이 있어요.\n\n지금 다시 열면 고친 내용이 사라져요. 그래도 열까요?")) return;
  document.querySelectorAll(".runbtn.on").forEach(b => b.classList.remove("on"));
  if (btn) btn.classList.add("on");
  // 1파: 재료 + ops_config(서로 무관) 동시에
  const [{ data, error }, opsRes] = await Promise.all([
    sb.from("editor_assets").select("*").eq("run_id", runId).maybeSingle(),
    Object.keys(opsCfg).length ? Promise.resolve({ data: null })
      : sb.from("ops_config").select("key,value")
          .in("key", ["editor_tts_voices", "editor_tts_elevenlabs"]),
  ]);
  ((opsRes || {}).data || []).forEach(o => { opsCfg[o.key] = o.value; });
  if (error || !data){
    alert(error ? error.message
      : "이 run 의 편집 재료가 아직 없습니다.\n본 대시보드 검수함에서 [🎬 편집실] 을 한 번 열어 재료를 만든 뒤 다시 여세요.");
    return; }
  cur = { row: data };
  showRunLabel();
  // 자유 텍스트·이미지의 정본은 이전 라운드 제출값(edit_overrides) — 본 편집실과
  // 같은 소스(generate 잡 params)를 읽기만 한다.
  // 2파: 이전 라운드 오버라이드(job_queue) + AI 연출 요약·채널(review_queue) 동시에
  cur.prevOv = {}; cur.style = null; cur.chDesign = {};
  const [gjRes, rvRes] = await Promise.all([
    data.work_order_id
      ? sb.from("job_queue").select("params").eq("kind", "generate").eq("status", "succeeded")
          .eq("work_order_id", data.work_order_id)
          .order("created_at", { ascending: false }).limit(1).maybeSingle()
      : Promise.resolve({ data: null }),
    sb.from("review_queue").select("payload,channel_slug,created_at")
      .eq("payload->>run_id", runId)
      .order("created_at", { ascending: false }).limit(1).maybeSingle(),
  ]);
  cur.prevOv = (((gjRes || {}).data || {}).params || {}).edit_overrides || {};
  const rv = (rvRes || {}).data;
  cur.style = ((rv || {}).payload || {}).style || null;
  cur.channel = (rv || {}).channel_slug || null;
  // 3파: 채널 디자인(채널을 알아야 물을 수 있다)
  if (cur.channel){
    const { data: cd } = await sb.from("channel_design_overrides")
      .select("design").eq("token_slug", cur.channel).maybeSingle();
    cur.chDesign = (cd || {}).design || {};
  }
  buildModel(); $("#stage").style.display = "flex"; $("#empty").style.display = "none";
  if (window.__railOn && window.renderRailPanel) renderRailPanel(window.__railOn);
  // 어디서 만든 영상인지 알약으로(작업 컴퓨터 · 맥미니 N) + 이름 — editor-boot 가 __edRunLabel 로 준다
  const rl = window.__edRunLabel;
  $("#runname").innerHTML = (rl ? `<span class="srcpill">${esc(rl.pill)}</span>${esc(rl.name)}` : esc(runId))
    + (data.status !== "ready" ? " 재료 재생성 대기 중(마지막 재료 기준)" : "");
  await mountVideo(); draw();
}

// ── 모델: 타임라인 + 초안 병합 ────────────────────────────────────────
// ── 구간 배속·붙잡기(새 파이프라인) — 편집본 길이 = (끝-시작)/배속 + 붙잡기.
// timeline.clip_fps 가 있으면 그 격자에 맞춘다(app.v3.assemble 과 같은 자). 없으면 종전 그대로 끝-시작.
const clipSpd = c => (+c.speed > 0 ? +c.speed : 1);
const clipGrid = () => (cur && cur.row && cur.row.timeline && +cur.row.timeline.clip_fps) || 0;
function clipDur(c){
  const raw = (c.end - c.start) / clipSpd(c) + (+c.hold || 0), g = clipGrid();
  return g ? Math.round(raw * g) / g : raw;
}
// 완성본 시각 → 이 구간의 원본 시각(붙잡은 꼬리는 구간 끝)
const clipSrcAt = (c, out0, outT) => Math.min(c.end, c.start + Math.max(0, outT - out0) * clipSpd(c));
// 초안 자막이 렌더 자막과 '사람이 고친' 차이가 있는지 — 문구·삭제·추가·스타일·장면 따라가기 끔(그때만 시각도)
function subsEdited(ds, base){
  if (!Array.isArray(ds)) return false;
  if (ds.filter(x => !x.del).length !== base.length) return true;
  return ds.some(x => { const b = base[x.i0];
    if (!b || x.del || (x.style && Object.keys(x.style).length)) return true;
    if (String(x.text || "") !== String(b.text || "")) return true;
    const follow = x.source_time_sec != null;
    if (follow !== !!b.follow) return true;
    return !follow && (Math.abs(+x.start_sec - b.start) > 0.01 || Math.abs(+x.end_sec - b.end) > 0.01); });
}
function buildModel(){
  const tl = cur.row.timeline || {}, d = cur.row.draft || {};
  // 구간: 초안이 있으면 그것이 '보낼 값'
  // frame_x = 구간 화면(가로) 위치 0~1. 없으면 자동(얼굴 따라가기). 렌더 값은 framing.json 의 manual 구간(src/editor-frame.js)
  const fxBase = i => window.__edFrame ? window.__edFrame.baseX(i) : null;
  const clips = (d.clips ? d.clips.map(c => ({ start: +c.start_sec, end: +c.end_sec,
                  role: c.role || "build", speed: +c.playback_speed || 1, hold: +c.hold_sec || 0,
                  frame_x: c.frame_x != null ? +c.frame_x : null }))
                : (tl.clips || []).map((c, i) => ({ start: +c.start_sec || 0,
                  end: +c.end_sec || 0, role: c.role || "build", speed: +c.playback_speed || 1, hold: +c.hold_sec || 0,
                  frame_x: fxBase(i) })))
    .filter(c => c.end > c.start);
  // key = 렌더가 만든 mp3(F-204). 이게 있어야 미리보기 소리가 **즉시** 난다 —
  // 없으면 매 줄마다 엣지 함수로 즉석 합성해서 첫 마디가 잘린다(본 편집실과 같은 규약).
  // 초안 행은 원본 타임라인과 src 로 맞춰 키를 물려받되, 문구·목소리·속도가 바뀐
  // 줄은 그 키가 '옛 소리'이므로 stale 로 표시해 즉석 합성 쪽으로 보낸다.
  const tlTts = tl.tts || [];
  // 완성본 내레이션 자막 구절(서버가 tts_caption_segments.json 에서 줄마다 붙인 것) — 목소리·속도·문구가 같은 줄에만 쓴다
  cur.phrases = new Map(tlTts.filter(t => t.phrases && t.phrases.length)
    .map(t => [phraseKey(t), t.phrases]));
  const keyAt = (src, text, voice, speed) => {
    const o = tlTts.find(x => Math.abs((+x.source_sec || 0) - src) < 0.01);
    if (!o || !o.key) return { key: null, stale: false };
    const same = String(o.text || "") === String(text || "")
      && (o.voice || "") === (voice || "")
      && (o.speed || "normal") === (speed || "normal");
    return { key: o.key, stale: !same };
  };
  const tts = (d.tts ? d.tts.map(t => { const src = +t.source_time_sec,
                 text = t.text || "", voice = t.voice || "", speed = t.speed || "normal";
                 return { src, dur: +t.duration_sec || 3, text, voice, speed,
                          ...keyAt(src, text, voice, speed) }; })
               : tlTts.map(t => ({ src: +t.source_sec || 0, dur: +t.duration_sec || 3,
                 text: t.text || "", voice: t.voice || "", speed: t.speed || "normal",
                 key: t.key || null, stale: false })));
  // follow = 장면 따라가기(앵커 유지). 끄면 완성본 시각에 못박힌다.
  // 앵커가 없는 줄은 따라갈 장면이 없으므로 기본이 '시각 고정'이다.
  const subs = (tl.subtitles || []).map((s, i) => ({ start: +s.edited_start || 0,
    end: +s.edited_end || 0, src: s.source_sec, text: s.text || "", i0: i, del: false,
    follow: s.source_sec != null }));
  const title = (d.title && d.title.top_title) || tl.top_title || "";
  // 시간대별 제목(E8) — 초안 > 이전 라운드 제출 > AI 연출(타임라인이 실어 준 edit_plan 창).
  // 실험실은 창의 **문구를 고치는 화면은 아니지만**, 창이 있다는 사실과 그 창이 완성본을
  // 다 덮는지를 알아야 한다 — 안 그러면 제목을 고쳐도 조용히 무시된다(2026-09-01 실사고).
  const rawSegs = (d.title && Array.isArray(d.title.segments) && d.title.segments)
    || ((cur.prevOv.title || {}).segments) || tl.title_segments || [];
  const titleSegs = rawSegs.map(x => ({ text: String(x.text || ""),
    start: +x.start_sec || 0, end: +x.end_sec || 0 }))
    .filter(x => x.text.trim() && x.end > x.start)
    .sort((a, b) => a.start - b.start);
  // 자유 텍스트(F-411) — 초안 > 이전 라운드 제출값. 좌표는 내레이션과 같은 원본 앵커.
  // 자막 초안 되살리기 — i0(원본 줄 번호)로 줄을 찾아 문구·시각·스타일·삭제를 얹고, i0 없는 줄(새로 추가)은 뒤에 붙인다.
  // 종전에는 '장면 따라가기' 여부만 읽어서 다시 열면 자막 수정이 화면에서 사라지고, 그대로 제출하면 빠졌다(본 편집실 규약과 같게).
  if (Array.isArray(d.subtitles) && d.subtitles.length){
    const ds = d.subtitles, used = new Set();
    const put = (su, x) => Object.assign(su, { start: +x.start_sec || 0, end: +x.end_sec || 0,
      text: String(x.text ?? su.text), del: !!x.del, follow: x.source_time_sec != null,
      ...(x.source_time_sec != null ? { src: +x.source_time_sec } : {}),
      ...(x.style && typeof x.style === "object" ? { style: { ...x.style } } : {}) });
    subs.forEach((su, i) => {
      const j = ds.findIndex((x, k) => !used.has(k) && x.i0 === i);
      if (j < 0){ su.del = true; return; }          // 초안에 없는 원본 줄 = 뺀 줄
      used.add(j); put(su, ds[j]);
    });
    ds.forEach((x, k) => { if (!used.has(k) && x.i0 == null)
      subs.push(put({ src: null, text: "", del: false }, x)); });
  }
  const rawTexts = d.texts || cur.prevOv.texts || [];
  // _raw: x·y·크기·색 등 실험실이 안 만지는 필드 — 저장 때 그대로 되돌려 보낸다
  const texts = rawTexts.map(t => ({ src: +t.source_time_sec || 0,
    dur: +t.duration_sec || 2, text: t.text || "", voice: "", speed: "",
    _raw: { ...t } }));
  cur.model = { clips, tts, subs, title, texts, titleSegs,
    fromDraft: { clips: !!d.clips, tts: !!d.tts, title: !!(d.title),
                 subs: !!d.subtitles, texts: !!d.texts, sfx: !!d.sfx } };
  // 변경 감지 기준(초안 저장은 바뀐 섹션만 싣는다 — 안 바뀐 자막까지 실으면
  // '자막을 고친 편'으로 읽혀 자막 끔 채널에서 자막이 켜진다, 8/17 규칙)
  //
  // ⚠ 기준선은 **오버라이드 없이 렌더하면 나올 값**(타임라인 정본)이어야 한다.
  // 초안(draft)은 '아직 안 보낸 편집'이라 기준선에 넣으면 안 된다 — 넣으면
  // model==orig 가 되어 그 섹션이 **영원히 제출되지 않는다**.
  // 실사고(커리어데이_c7e39306, 2026-08-27): 초안에 제목·구간이 들어 있었는데
  // 두 번의 재렌더(17:59·18:44) 모두 title·clips 키가 빠진 채 나갔다. 사람이
  // 고친 제목·구간이 조용히 유실됐다(제출 뒤 초안이 비워져 되돌릴 근거도 사라졌다).
  const baseClips = (tl.clips || []).map((c, i) => ({ start: +c.start_sec || 0,
    end: +c.end_sec || 0, role: c.role || "build", speed: +c.playback_speed || 1, hold: +c.hold_sec || 0,
    frame_x: fxBase(i) })).filter(c => c.end > c.start);
  const baseTts = tlTts.map(t => ({ src: +t.source_sec || 0, dur: +t.duration_sec || 3,
    text: t.text || "", voice: t.voice || "", speed: t.speed || "normal",
    key: t.key || null, stale: false }));
  const baseSubs = (tl.subtitles || []).map((sv, i) => ({ start: +sv.edited_start || 0,
    end: +sv.edited_end || 0, src: sv.source_sec, text: sv.text || "", i0: i, del: false,
    follow: sv.source_sec != null }));
  // '고친 곳: 자막'은 사람이 바꾼 게 있을 때만 — 구간을 옮기면 장면 따라가기 자막은 시각만 움직여 초안에 실리지만 고친 게 아니다
  cur.model.fromDraft.subs = !!d.subtitles && subsEdited(d.subtitles, baseSubs);
  const baseTexts = (cur.prevOv.texts || []).map(t => ({ src: +t.source_time_sec || 0,
    dur: +t.duration_sec || 2, text: t.text || "", voice: "", speed: "",
    _raw: { ...t } }));
  const baseSegs = (((cur.prevOv.title || {}).segments) || tl.title_segments || [])
    .map(x => ({ text: String(x.text || ""), start: +x.start_sec || 0, end: +x.end_sec || 0 }))
    .filter(x => x.text.trim() && x.end > x.start).sort((a, b) => a.start - b.start);
  cur.orig = { clips: JSON.stringify(baseClips), tts: JSON.stringify(baseTts),
               subs: JSON.stringify(baseSubs), texts: JSON.stringify(baseTexts),
               title: tl.top_title || "", titleSegs: JSON.stringify(baseSegs) };
  if (window.__edFx) window.__edFx.load(cur, tl, d);   // 강조·줌: 렌더 값 + 초안
  if (window.__edSfx) window.__edSfx.load(cur, d);      // 효과음: 렌더가 섞은 것(sfx.json) + 초안
  dirty = false; lastSavedAt = cur.row.draft_at ? new Date(cur.row.draft_at) : null;
  updSaveBtn(); paintSaveMsg();
  if (editMode) autoSaveStart();
  window.subCk = new Set(); window.ttsCk = new Set();
  cur.sent = false;
  runEngineRules();
}

// ── 구간·내레이션 배치 ──────────────────────────────────────────────────
// 구간은 받은 그대로 이어 붙인다(ai-video apply_edit — 예전 엔진의 겹침 절삭·짧은 조각 제거 없음).
function dedup(clips){
  return { clips: clips.map((c, i) => ({ ...c, i })), notes: [] };
}

// 2) _resolve_cue_anchors (pipeline.py:630) — 여유 0초, 포함 구간 첫 번째
function resolveCues(tts, finalClips){
  const spans = []; let base = 0;
  for (const c of finalClips.filter(c => !c.dead)){
    spans.push({ s: c.start, e: c.end, base, i: c.i, sp: clipSpd(c) });
    base += clipDur(c);
  }
  const total = base;
  return { total, cues: tts.map((t, ti) => {
    // 엔진 src_to_out 과 같이 시작에 0.001초 여유 — 초안에 저장된 구간 시각은 소수 셋째 자리로 반올림돼(2640.9666→2640.967)
    // 구간 시작에 딱 맞춘 내레이션 앵커가 '밖'으로 떨어져 빠진다고 잘못 나왔다
    const containing = spans.filter(sp => sp.s - 0.001 <= t.src && t.src < sp.e);
    if (containing.length){
      const exact = cur && cur.row && cur.row.timeline && cur.row.timeline.engine_rules === false
        && containing.find(sp => Math.abs(sp.s - t.src) < 0.002);
      const sp = exact || containing[0];
      return { ...t, ti, out: sp.base + (t.src - sp.s) / sp.sp, span: sp,
        multi: containing.length > 1, contained: true };
    }
    // 경계 밖 — 엔진 스냅: 앵커 뒤 첫 조각 시작, 없으면 마지막 조각 끝 -0.5
    const after = spans.filter(sp => sp.s >= t.src);
    if (after.length){
      const sp = after.reduce((a, b) => (b.s < a.s ? b : a));
      return { ...t, ti, out: sp.base, span: sp, snapped: true,
        gap: sp.s - t.src, contained: false };
    }
    if (spans.length){
      const sp = spans[spans.length - 1];
      return { ...t, ti, out: sp.base + (sp.e - sp.s) / sp.sp - 0.5, span: sp,
        snapped: true, tail: true, contained: false };
    }
    return { ...t, ti, dropped: true };
  }) };
}

const edH = () => ({ clipDur, clipSpd, clipSrcAt, ttsEst, cueKey, fmt, srcToOut });   // src/editor-checks.js 가 쓰는 편집실 계산
// 강조·줌은 자막·구간 객체에 붙어 다니지만 자막·구간 비교에서는 빼고 따로 보낸다(src/editor-fx.js)
const edNoFx = (k, v) => (k === "zoom" || k === "emph") ? undefined : v;
function runEngineRules(){
  const m = cur.model;
  const dd = dedup(m.clips);
  const rc = resolveCues(m.tts, dd.clips);
  m.final = dd.clips; m.dedupNotes = dd.notes; m.cues = rc.cues; m.total = rc.total;
  m.textCues = resolveCues(m.texts || [], dd.clips).cues;   // 텍스트도 같은 앵커 규칙
  // 자막(장면 따라가기 켬)도 같은 규칙으로 재배치해 **화면에 반영**한다.
  // 길이는 유지하고 시작만 앵커가 가리키는 자리로 — 엔진이 렌더 때 하는 일과 같다.
  // 같은 원본 장면을 두 번 쓴 편(앞은 내레이션 덮개·소리 끔, 뒤는 대사와 함께)에서 '첫 구간'에 붙이면 대사 자막이
  // 덮개 쪽 내레이션 위로 간다. 그래서 담은 구간이 여럿이면 ① 내레이션과 안 겹치는 구간 ② 지금(원래) 자리에서 가장 가까운 구간.
  // 그런 줄은 _amb 로 표시해 제출 때 원본 시각 대신 이 완성본 시각을 보낸다(엔진 src_to_out 도 첫 구간 규칙이다).
  {
    const spans = []; let b0 = 0;
    for (const c of dd.clips.filter(c => !c.dead)){ spans.push({ s: c.start, e: c.end, base: b0, sp: clipSpd(c) }); b0 += clipDur(c); }
    const voiced = (m.cues || []).filter(q => !q.dropped).map(q => [q.out, q.out + q.dur]);
    const quiet = (a, b) => !voiced.some(([x, y]) => Math.min(b, y) - Math.max(a, x) > 0.1);
    (m.subs || []).forEach(su => {
      Object.defineProperty(su, "_amb", { value: false, writable: true, enumerable: false, configurable: true });
      if (su.del || !su.follow || su.src == null) return;
      const len = su.end - su.start, src = +su.src;
      const hits = spans.filter(sp => sp.s - 0.001 <= src && src < sp.e)
        .map(sp => ({ out: sp.base + Math.max(0, src - sp.s) / sp.sp }));
      if (!hits.length){                              // 경계 밖 — 종전 엔진 스냅 그대로
        const q = resolveCues([{ src, dur: Math.max(0.1, len) }], dd.clips).cues[0];
        if (!q.dropped){ su.start = +q.out.toFixed(3); su.end = +(q.out + len).toFixed(3); }
        return;
      }
      let pick = hits;
      if (hits.length > 1){
        su._amb = true;
        const ok = hits.filter(h => quiet(h.out, h.out + len)); if (ok.length) pick = ok;
      }
      const h = pick.reduce((a, b) => Math.abs(b.out - su.start) < Math.abs(a.out - su.start) ? b : a);
      su.start = +h.out.toFixed(3); su.end = +(h.out + len).toFixed(3);
    });
  }
  // 완성본 출력 위치 (dead 제외 누적)
  let base = 0;
  m.final.forEach(c => { c.out = c.dead ? null : base; if (!c.dead) base += clipDur(c); });
  // 원본 사용 겹침(선공개) 감지
  m.dups = [];
  for (let a = 0; a < m.clips.length; a++)
    for (let b = a + 1; b < m.clips.length; b++){
      const s = Math.max(m.clips[a].start, m.clips[b].start),
            e = Math.min(m.clips[a].end, m.clips[b].end);
      if (e - s > 0.2) m.dups.push({ a, b, s, e });
    }
  // 새 파이프라인 검사 — 빠질 내레이션·자막, 내레이션 겹침·끝 넘김, 원음 꺼진 구간(src/editor-checks.js)
  m.checks = window.__edChecks ? window.__edChecks.analyze(cur, edH()) : null;
}

// ── 비디오 ────────────────────────────────────────────────────────────
// 한 개의 <video>(scan, 원본 시간축)를 두 모드가 공유한다.
//  · shorts 모드: 최종 구간(final, dead 제외)을 순서대로 이어 재생 + 오버레이 —
//    완성본 근사. 재생 인덱스만 굴리면 되고 인코딩이 필요 없다.
//  · src 모드: 자유 스크럽(컨트롤 노출).
let driving = false, drvIdx = -1;
const setPlay = () => {};   // 재생 라벨 폐기(하단 바 제거, 2026-08-24) — 호출부 호환용
// setMode 폐기(2026-08-24) — 원본(좌)·쇼츠(중) 두 화면이 상시 공존한다
// 붙잡기 중: 원본 영상은 끝 프레임에 멈춰 있고 편집본 시계만 흐른다. frozen 이면 일시정지 상태.
let holding = null;
function holdAt(i, outT, paused){
  const sp = liveSpans()[i]; if (!sp) return;
  const from = sp.base + (sp.e - sp.s) / sp.sp;
  holding = { idx: i, from, end: sp.base + sp.len, t0: performance.now() - Math.max(0, outT - from) * 1000,
    frozen: paused ? outT : null };
  if (!paused) holdTick();
}
// 붙잡기 시계는 자체 타이머로 돈다 — rAF 는 화면이 가려지면 멈추고, 영상이 서 있어 timeupdate 도 없다.
function holdTick(){
  if (!holding || holding.frozen != null) return;
  advance();
  const v = $("#vid"); if (v && v.ontimeupdate) v.ontimeupdate();
  if (holding && holding.frozen == null) setTimeout(holdTick, 50);
}
function curOut(){                        // 지금 완성본 시각 — 재생 중인 구간(drvIdx)을 먼저 본다
  const v = $("#vid"); if (!v) return null;
  if (holding) return holding.frozen != null ? holding.frozen
    : Math.min(holding.end, holding.from + (performance.now() - holding.t0) / 1000);
  const sp = driving && drvIdx >= 0 ? liveSpans()[drvIdx] : null;
  if (sp && v.currentTime >= sp.s - 0.05 && v.currentTime <= sp.e + 0.05)
    return sp.base + Math.min(sp.e - sp.s, Math.max(0, v.currentTime - sp.s)) / sp.sp;
  return srcToOut(v.currentTime);
}
function applyRate(){ const v = $("#vid"), sp = liveSpans()[drvIdx]; if (v) v.playbackRate = sp ? sp.sp : 1; }
function landAt(hit, outT, paused){       // 시크 착지 — 배속·붙잡기 상태를 그 자리에 맞춘다
  holding = null; applyRate();
  if (!hit.hold) return;
  const v = $("#vid");
  holdAt(hit.idx, outT, paused);
  if (!v.paused) v.pause();
}
function advance(){                       // 구간 끝 → 붙잡기 → 다음 구간
  const v = $("#vid"), spans = liveSpans();
  if (!driving || drvIdx < 0 || drvIdx >= spans.length) return;
  const sp = spans[drvIdx];
  if (holding){
    if (holding.frozen != null || curOut() < holding.end - 0.001) return;
    holding = null;
  } else {
    if (v.paused || v.currentTime < sp.e - 0.06 * sp.sp) return;
    if (sp.h > 0){ holdAt(drvIdx, sp.base + (sp.e - sp.s) / sp.sp, false); v.pause(); seqTickStart(); return; }
  }
  if (drvIdx + 1 < spans.length){
    drvIdx++; v.currentTime = spans[drvIdx].s; applyRate();
    if (v.paused) v.play().catch(() => {});
  } else { v.pause(); driving = false; setPlay("▶ 재생"); }
}
function liveSpans(){
  const out = []; let base = 0;
  for (const c of (cur.model.final || []).filter(c => !c.dead)){
    out.push({ s: c.start, e: c.end, base, sp: clipSpd(c), h: +c.hold || 0, len: clipDur(c) }); base += clipDur(c);
  }
  return out;
}
function srcToOut(t){
  for (const sp of liveSpans()) if (t >= sp.s - 0.001 && t < sp.e) return sp.base + Math.min((t - sp.s) / sp.sp, sp.len);
  return null;
}
function outToSrc(t){
  const spans = liveSpans();
  for (let i = 0; i < spans.length; i++){
    const sp = spans[i], rel = t - sp.base, moving = (sp.e - sp.s) / sp.sp;
    if (t < sp.base + sp.len) return rel >= moving
      ? { src: Math.max(sp.s, sp.e - 1 / 30), idx: i, hold: true }       // 붙잡은 꼬리
      : { src: sp.s + rel * sp.sp, idx: i };
  }
  return null;
}
// 쇼츠 실배치(2026-08-25) — 채널 디자인 + 초안 design + 미저장 변경을 합쳐
// 1080×1920 좌표로 계산해 %·cqh 로 얹는다. 엔진 기본값은 본 편집실 성분표와 동일.
function layoutShorts(){
  if (!cur) return;
  const d = { ...(cur.chDesign || {}), ...((cur.row.draft || {}).design || {}),
              ...(cur.pendingDesign || {}) };
  // 완성본이 실제로 쓴 배치(렌더 직전 폰 안전 구역 맞춤이 옮긴 영상 칸·로고 정렬, editor-boot __edRenderLayout).
  // 사람이 이 편에서 직접 바꾼 값은 그대로 두고, 렌더 원값만 실제 값으로 바꿔 그린다.
  { const rl = window.__edRenderLayout || {}, own = k => ((cur.row.draft || {}).design || {})[k] != null || (cur.pendingDesign || {})[k] != null;
    if (rl.band_y != null && !own("video_y")) d.video_y = rl.band_y;
    if (rl.work_align && !own("work_image_align")) d.work_image_align = rl.work_align; }
  const W = 1080, H = 1920, pct = (v, base) => (v / base * 100) + "%",
        cq = px2 => (px2 / H * 100) + "cqh";
  // 영상 밴드 — aspect_ratio(기본 1:1)·video_width(기본 꽉 참)·video_y(기본 중앙)
  const ar = String(d.aspect_ratio || "1:1").split(":").map(Number);
  const vw = Math.min(W, +d.video_width || W);
  const vh = ar[0] > 0 && ar[1] > 0 ? vw * ar[1] / ar[0] : vw;
  const vtop = d.video_y != null && d.video_y !== "" ? +d.video_y : (H - vh) / 2;
  const vs = $("#vslot");
  vs.style.top = pct(vtop, H); vs.style.height = pct(vh, H);
  vs.style.left = pct((W - vw) / 2, W); vs.style.width = pct(vw, W);
  // 제목 — 줄별 크기(70/90 위계)·색, title_y 고정이면 그 자리, 아니면 밴드 위 중앙
  const s1 = +d.title_size || 70;
  const s2 = +d.title_size2 || Math.round(s1 * 90 / 70);
  const c1 = d.title_color || "#FFFFFF", c2 = d.title_color2 || "#FFFF00";
  const lines = (cur.model ? cur.model.title : "").split("\n");
  const ot = $("#ovTitle");
  // 제목 글꼴 — 렌더와 같은 파일(serve.py /engine-fonts). 비우면 엔진 기본 Jalnan(ai-video config.DesignConfig.title_font)
  const TITLE_FONTS = { "Jalnan": "EngineJalnan", "여기어때 잘난체 2 TTF": "EngineJalnan",
    "JalnanGothic": "EngineJalnanGothic", "여기어때 잘난체 고딕 TTF": "EngineJalnanGothic",
    "mulmaru": "EngineMulmaru", "물마루": "EngineMulmaru", "Griun": "EngineGriun", "그리운 경찰공평체": "EngineGriun",
    "Noto Sans CJK KR": "EngineNotoBlack", "NotoSansCJKkr-Black": "EngineNotoBlack" };
  ot.style.fontFamily = `${TITLE_FONTS[d.title_font || "Jalnan"] || "EngineJalnan"},"Noto Sans KR",sans-serif`;
  ot.style.fontWeight = "400";            // 엔진 글꼴은 굵기가 하나뿐 — 브라우저가 가짜 굵게를 입히지 않게
  // 줄별 배경 박스(ai-video 8661b2ed 렌더러와 같은 자): 여백 = 0.30×글자 크기(사방), 둥근 반지름 = 0.25×글자 크기.
  // 박스 줄은 제목 블록이 2×여백만큼 높아져 그만큼 위로 올라간다.
  const boxOf = i => { const k = String(d[i ? "title_box2" : "title_box"] || "");
    return k === "round" || k === "rect" ? k : ""; };
  ot.innerHTML = lines.map((l, i) => { const sz = i ? s2 : s1, bx = boxOf(i), pad = Math.round(0.30 * sz);
    const box = bx ? `display:inline-block;padding:${cq(pad)};background:${esc(d[i ? "title_box_color2" : "title_box_color"] || "#000000")};
      border-radius:${bx === "round" ? cq(Math.round(0.25 * sz)) : "0"};line-height:1` : "";
    return `<div style="font-size:${cq(sz)};color:${esc(i ? c2 : c1)};line-height:1;${i ? `margin-top:${cq(30)}` : ""}">${bx ? `<span style="${box}">${esc(l)}</span>` : esc(l)}</div>`; }).join("");
  // 제목 자리(ai-video subtitle_region.estimate_title_block): 줄 높이 = 글자 크기(+박스 여백), 줄 사이 30px,
  // 블록 아랫변이 영상 밴드 윗변 20px 위. 그 자리가 캔버스 위 10px 보다 올라가면 기본 120.
  const blockH = lines.reduce((a, _, i) => { const sz = i ? s2 : s1;
    return a + sz + (boxOf(i) ? 2 * Math.round(0.30 * sz) : 0); }, 0) + Math.max(0, lines.length - 1) * 30;
  const dyn = vtop - blockH - 20;
  const ttop = d.title_y != null && d.title_y !== "" ? +d.title_y : dyn >= 10 ? dyn : 120;
  ot.style.top = pct(ttop, H);
  ot.style.transform = "";                // 제목 회전은 렌더가 쓰지 않는다(2026-09-29 뺐다)
  // 대사 자막 — 밴드 하단 안쪽(근사)
  const sub = $("#ovSub");
  {                                          // 렌더와 같은 폰트·크기·외곽선·자리
    const [fam, fk] = v3SubFont(d), size = (+d.subtitle_size || 62) * fk;
    const off = d.subtitle_band_offset;
    const subTop = off != null && off !== "" ? vtop + vh + +off : Math.min(H - 200, vtop + vh - 170);
    sub.dataset.top = pct(subTop, H);
    window.__lay = { ...(window.__lay || {}), subTop };
    sub.style.fontSize = cq(size);
    sub.style.color = d.subtitle_color || "#FFFFFF";
    sub.style.fontFamily = `${fam},"Noto Sans KR",sans-serif`;
    sub.style.fontWeight = "900"; sub.style.lineHeight = "1.2";
    sub.style.webkitTextStroke = cq(V3_SUB_OUTLINE * 2) + " #000"; sub.style.paintOrder = "stroke fill";
    sub.style.textShadow = "none";
  }
  sub.style.top = sub.dataset.top;
  // 내레이션 자막 — 렌더(v3_tts.ass)와 같게: 대사와 같은 글꼴(Noto Sans CJK KR Black)·외곽선 8·그림자 없음,
  // 크기 tts_size(em, 엔진이 ASS 에서 ×1.43 보정), 좌우 여백 80. 자리는 채널이 tts_y_margin 을 정했으면 밑에서 그만큼(아랫변),
  // 아니면 대사 자막과 같은 줄(ai-video finalize.base_text_margins — 대사와 내레이션은 동시에 안 나와 한 자리를 나눠 쓴다).
  const tts = $("#ovTts");
  tts.style.fontFamily = `EngineNotoBlack,"Noto Sans KR",sans-serif`;
  tts.style.fontWeight = "900"; tts.style.lineHeight = "1.2";
  tts.style.fontSize = cq(+d.tts_size || 70);
  tts.style.color = d.tts_color || "#87CEEB";
  tts.style.webkitTextStroke = cq(V3_SUB_OUTLINE * 2) + " #000"; tts.style.paintOrder = "stroke fill";
  tts.style.textShadow = "none";
  tts.style.left = pct(80, W); tts.style.right = pct(80, W);
  // 버튼으로 옮길 때 출발점(지금 보이는 아랫변 기준 하단 여백) — 1줄 높이 = 1.2×크기
  window.__lay = { ...(window.__lay || {}), vtop, vw, titleTop: ttop,
    ttsMargin: d.tts_y_margin != null && d.tts_y_margin !== "" ? +d.tts_y_margin : Math.round(H - window.__lay.subTop - 1.2 * (+d.tts_size || 70)) };
  if (d.tts_y_margin != null && d.tts_y_margin !== ""){ tts.style.top = "auto"; tts.style.bottom = pct(+d.tts_y_margin, H); }
  else { tts.style.bottom = "auto"; tts.style.top = sub.dataset.top; }
  // 작품명/작품 로고 — work_title_y(기본 하단 근처). 이미지는 자리 표시 칩으로.
  // 작품 로고/작품명 + 아래 캡션 — ai-video finalize.estimate_work_top 과 같은 자리 계산:
  // 영상 밴드 아래 20px(또는 work_band_offset) ~ 캔버스 아래 20px−캡션 줄 사이, 가운데 정렬이면 그 사이 가운데.
  // 로고 그림: 로고 탭에서 고른 파일(작품 관리 로고, __edLogoUrls 경로→주소) 또는 이 영상을 렌더한 디자인의 파일
  // (local_videos_api DESIGN_LOGOS). 파일 이름은 띄우지 않는다. 기본 크기는 ai-video DesignConfig 와 같다.
  const ow = $("#ovWork"), logos = window.__edLogos || {}, base = cur.chDesign || {};
  const logoUrl = (v, fb) => (window.__edLogoUrls || {})[v] || (v && v === base[fb === "work" ? "work_value" : "platform_image"] ? logos[fb] : null);
  window.__band = { vtop, vh, vw, W, H };
  ow.style.bottom = "auto"; ow.style.letterSpacing = "normal";
  const capTxt = String(d.work_caption || ""), capFs = +d.work_caption_font_size || 40;
  const capBlk = capTxt ? Math.floor(capFs * 1.4) + 12 : 0;
  const offSet = d.work_band_offset != null && d.work_band_offset !== "";
  const safeTop = vtop + vh + (offSet ? +d.work_band_offset : 20), wBottom = H - 20 - capBlk;
  // 하단 문구는 렌더가 제목 글꼴 파일(title_font)로 그린다(ai-video renderer drawtext font_arg) — 따로 고르는 글꼴이 없다
  const capHtml = capTxt ? `<div class="wcap" style="font-size:${cq(capFs)};margin-top:${cq(12)};color:${esc(d.work_caption_color || "#FFFFFF")};font-family:${TITLE_FONTS[d.title_font || "Jalnan"] || "EngineJalnan"},'Noto Sans KR',sans-serif;font-weight:400">${esc(capTxt)}</div>` : "";
  const wUrl = d.work_type === "image" ? logoUrl(d.work_value, "work") : null;
  let wTop, wH;
  const bw = +d.work_image_width || 395, bh0 = +d.work_image_height || 280;
  if (wUrl){
    let img = ow.querySelector("img.wlogo");
    if (!img || img.dataset.src !== wUrl){
      ow.innerHTML = `<span class="wl ovel"><img class="wlogo" alt=""></span>`; img = ow.querySelector("img.wlogo");
      img.dataset.src = wUrl; img.onload = () => layoutShorts(); img.src = wUrl;
    }
    ow.querySelectorAll(".wcap").forEach(x => x.remove()); ow.insertAdjacentHTML("beforeend", capHtml);
    const nw = img.naturalWidth, nh = img.naturalHeight;          // 엔진과 같이 박스(bw×bh) 안에 비율 유지
    const sc = nw ? Math.min(bw / nw, bh0 / nh) : 1;
    wH = nw ? Math.max(2, Math.floor(nh * sc / 2) * 2) : bh0;
    img.style.width = cq(nw ? nw * sc : bw); img.style.height = "auto"; img.style.display = "block";   // % 는 감싼 조각 폭 기준이 돼서 쓰지 않는다
    wTop = safeTop;
    if ((d.work_image_align || "center") === "center" && !offSet) wTop = safeTop + Math.floor((wBottom - safeTop - wH) / 2);
  } else if (d.work_type === "image"){
    // 로고 그림을 못 읽으면(파일이 없거나 서버가 못 읽는 폴더) 같은 크기의 자리만 보인다
    ow.innerHTML = `<span class="wl ovel"><span class="wlogo-ph" style="width:${cq(bw)};height:${cq(bh0)}">작품 로고</span></span>` + capHtml;
    wH = bh0; wTop = safeTop;
    if ((d.work_image_align || "center") === "center" && !offSet) wTop = safeTop + Math.floor((wBottom - safeTop - wH) / 2);
  } else {
    const name = String((d.work_type === "text" && d.work_value) || window.__edWorkName || "");
    ow.innerHTML = `<span class="wl ovel wtxt" style="font-size:${cq(+d.work_font_size || 40)};color:${esc(d.work_color || "#FFFFFF")}">${esc(name)}</span>` + capHtml;
    wH = Math.floor((+d.work_font_size || 40) * 1.4);
    wTop = Math.max(+d.work_title_y || 1400, safeTop);
  }
  if (wTop + wH > wBottom) wTop = wBottom - wH;
  ow.style.top = pct(Math.max(safeTop, wTop), H);
  // 플랫폼 표기 — 영상 밴드 모서리(platform_align, 기본 left), 여백 platform_x/y(기본 24)
  const op = $("#ovPlat"); op.classList.add("ovel");
  const pTxt = d.platform_text, pImg = d.platform_image;
  if (!pTxt && !pImg){ op.style.display = "none"; }
  else {
    op.style.display = "";
    op.style.top = pct(vtop + (+d.platform_y || 24), H);
    const px2 = Math.max(+d.platform_x || 24, 100);   // 렌더는 폰 안전 구역 때문에 캔버스 끝에서 100px 안쪽으로 민다
    if ((d.platform_align || "left") === "right"){
      op.style.right = pct((W - vw) / 2 + px2, W); op.style.left = "auto";
    } else {
      op.style.left = pct((W - vw) / 2 + px2, W); op.style.right = "auto";
    }
    const pUrl = pImg ? logoUrl(pImg, "platform") : null;
    if (pUrl){
      const pw = +d.platform_image_width || 150, ph2 = +d.platform_image_height || 80;
      let img = op.querySelector("img");
      if (!img || img.dataset.src !== pUrl){
        op.innerHTML = `<img alt="">`; img = op.querySelector("img");
        img.dataset.src = pUrl; img.onload = () => layoutShorts(); img.src = pUrl;
      }
      const nw = img.naturalWidth, nh = img.naturalHeight, sc = nw ? Math.min(pw / nw, ph2 / nh) : 1;   // 박스 안 비율 유지(렌더와 같다)
      img.style.cssText = `display:block;width:${cq(nw ? nw * sc : pw)};height:auto`;
    }
    else if (pImg) op.innerHTML = `<span class="imgchip">로고</span>`;
    else {
      op.textContent = pTxt;
      op.style.fontSize = cq(+d.platform_font_size || 36);
      op.style.color = d.platform_color || "#FFFFFF";
    }
  }
  ovSyncHandles();
  // 인덱스는 그대로인데 값만 바뀐 경우(디자인 칸·드래그) — 여기서 직접 다시 칠한다.
  styleOvSub(curSubIdx); styleOvTxt(ovTxtOn);
}
window.layoutShorts = layoutShorts;

// 쇼츠 화면 가운데 고정(사용자 8/25) — 서랍·인스펙터가 열고 닫혀도 제자리.
// 기준은 '레일 오른쪽 ~ 창 오른쪽' = 작업 무대. 서랍을 침범하면 그만큼 물러난다.
function centerShorts(){
  const wrap = $("#shortsWrap"), row = $("#pvRow");
  if (!wrap || !row) return;
  wrap.style.transform = "";
  const rail = document.getElementById("rail");
  const stageL = rail ? rail.getBoundingClientRect().right : 0;
  const target = (stageL + window.innerWidth) / 2;
  const box = tlRoot.querySelector(".shorts");
  if (!box) return;
  const b = box.getBoundingClientRect(), r = row.getBoundingClientRect();
  let dx = target - (b.left + b.width / 2);
  // 왼쪽 서랍은 영상 위에 뜬다(editor-shell.css) — 영상은 전체 가운데에 두고, 서랍에 닿을 때만 닿지 않을 만큼 비킨다.
  const panel = document.getElementById("railPanel");
  const drawerR = panel && panel.classList.contains("on") && rail ? rail.getBoundingClientRect().right
    + (parseFloat(getComputedStyle(document.body).getPropertyValue("--drawerw")) || 300) + 12 : 0;
  const minL = Math.max(r.left + 8, drawerR), maxR = r.right - 8;
  if (b.left + dx < minL) dx = minL - b.left;
  if (b.right + dx > maxR) dx = maxR - b.right;
  wrap.style.transform = `translateX(${Math.round(dx)}px)`;
}
window.centerShorts = centerShorts;
const reCenter = () => requestAnimationFrame(() => requestAnimationFrame(centerShorts));
window.reCenter = reCenter;

// ── 가운데 화면 직접 조작(2026-08-25) — 지금 뜬 자막을 드래그로 위치·폭·크기·회전 ──
// 좌표계는 엔진과 같은 1080×1920 캔버스: y = 자막 **하단**이 놓일 비율(0=위,1=아래),
// width = 캔버스 가로 대비 비율(0.3~1.0), size = 캔버스 기준 폰트 px.
let curSubIdx = -1;
const CANVAS_W = 1080, CANVAS_H = 1920, SUB_W_BASE = 0.852;
// ── 새 파이프라인(ai-video v3 finalize) 대사 자막 모양 — 예전 엔진과 다르다(2026-09-29 확인, v7 v3_subtitles.ass):
//  · 폰트: 비우면 Noto Sans CJK KR Black. 크기(subtitle_size)는 실제 글자 크기(em px)로 보정해 그린다.
//    채널이 폰트를 고르면 보정하지 않아 글자가 줄 높이 비율만큼 작아진다(Jalnan 계열 ≈ 1/1.38).
//  · 색: 비우면 흰색(예전 엔진은 프리셋 노랑). 검정 외곽선 8px. 프리셋(subtitle_style)은 쓰지 않는다.
//  · 자리: subtitle_band_offset 이 있으면 자막 윗변 = 영상 밴드 아랫변 + offset.
const V3_FONTS = { "": ["EngineNotoBlack", 1], "Noto Sans CJK KR": ["EngineNotoBlack", 1],
  "여기어때 잘난체 2 TTF": ["EngineJalnan", 1 / 1.38], "여기어때 잘난체 고딕 TTF": ["EngineJalnanGothic", 1 / 1.38],
  "물마루": ["EngineMulmaru", 1 / 1.38], "그리운 경찰공평체": ["EngineGriun", 1 / 1.38] };
function v3SubFont(d){ return V3_FONTS[d.subtitle_font || ""] || V3_FONTS[""]; }
const V3_SUB_OUTLINE = 8;                 // ASS Outline(px, 1920 캔버스)
function subEff(i){                       // 이 줄에 실제로 적용될 값(줄별 > 이 편 > 기본)
  const d = { ...(cur.chDesign || {}), ...((cur.row.draft || {}).design || {}),
              ...(cur.pendingDesign || {}) };
  const st = (cur.model.subs[i] || {}).style || {};
  // 줄별로는 색만 렌더된다(ai-video apply_edit editor_subtitles) — 옛 초안에 남은 크기·폭·회전·세로는 보여 주지 않는다
  return { size: +(d.subtitle_size ?? 62),
           color: st.color || d.subtitle_color || "#FFFFFF",
           width: SUB_W_BASE, rotate: 0, y: undefined };
}
function styleOvSub(i){
  const el = $("#ovSub"); if (!el) return;
  if (i < 0){ el.classList.remove("sel"); el.innerHTML = el.textContent; return; }
  const e = subEff(i);
  const fk = v3SubFont({ ...(cur.chDesign || {}), ...((cur.row.draft || {}).design || {}), ...(cur.pendingDesign || {}) })[1];
  el.style.fontSize = (e.size * fk / CANVAS_H * 100) + "cqh";
  el.style.color = e.color;
  const em = window.__edFx && window.__edFx.subLook(cur.model.subs[i]);   // 강조 줄: 렌더처럼 크게·색
  if (em){ el.style.fontSize = (e.size * fk * em.scale / CANVAS_H * 100) + "cqh"; el.style.color = em.color; }
  const w = e.width * 100;
  el.style.left = ((100 - w) / 2) + "%"; el.style.right = "auto"; el.style.width = w + "%";
  el.style.transform = e.rotate ? `rotate(${e.rotate}deg)` : "";
  if (e.y != null){ el.style.top = "auto"; el.style.bottom = ((1 - e.y) * 100) + "%"; }
  else { el.style.bottom = "auto";
    // ⚠ top 을 반드시 되돌린다 — 안 되돌리면 auto 로 남아 자막이 프레임 맨 위로
    // 튄다(8/28: "고치지도 않았는데 위로 올라간다"). layoutShorts 가 남긴 기본 자리.
    el.style.top = el.dataset.top || ""; }
  // 편집 모드면 조작 핸들을 얹는다(문구는 그대로 두고 핸들만 추가)
  el.classList.toggle("sel", editMode);
  el.querySelectorAll(".sh").forEach(x => x.remove());
  if (!editMode) return;
  [].forEach(k => {                        // 대사 자막 손잡이(폭·크기·회전) 없음 — 줄별로 렌더되지 않는다
    const b = document.createElement("b"); b.className = "sh sh-" + k; b.dataset.h = k;
    el.appendChild(b);
  });
}
window.styleOvSub = styleOvSub;

// 드래그 — 프레임(.shorts) 기준 픽셀 → 캔버스 비율로 환산해 style 에 쓴다
(function bindSubDrag(){
  const start = e => {
    if (!editMode || curSubIdx < 0 || !cur) return;
    const el = $("#ovSub"); if (!el || !el.contains(e.target)) return;
    // 대사 자막은 줄마다 옮기거나 크기를 바꿀 수 없다(렌더가 줄별로는 색만 쓴다) — 자리·크기는 [자막] 탭 공통값
    if (!el.querySelector(".sh")) return;
    e.preventDefault(); e.stopPropagation();
    const mode = e.target.dataset && e.target.dataset.h ? e.target.dataset.h : "move";
    const frame = tlRoot.querySelector(".shorts").getBoundingClientRect();
    const box = el.getBoundingClientRect();
    const i = curSubIdx, e0 = subEff(i);
    const y0 = e0.y != null ? e0.y : (box.bottom - frame.top) / frame.height;
    const cx = box.left + box.width / 2, cy = box.top + box.height / 2;
    const a0 = Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI;
    const sx = e.clientX, sy = e.clientY;
    let moved = false;
    const mv = ev => {
      moved = true;
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (mode === "move")
        setSubStyleLive(i, "y", clamp(y0 + dy / frame.height, 0, 1).toFixed(4));
      else if (mode === "w-l" || mode === "w-r"){
        const sign = mode === "w-r" ? 1 : -1;
        setSubStyleLive(i, "width",
          clamp(e0.width + sign * 2 * dx / frame.width, 0.3, 1).toFixed(4));
      } else if (mode === "size")
        setSubStyleLive(i, "size",
          Math.round(clamp(e0.size + dy / frame.height * CANVAS_H, 20, 300)));
      else if (mode === "rot"){
        const a = Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180 / Math.PI;
        setSubStyleLive(i, "rotate", Math.round(clamp(e0.rotate + (a - a0), -180, 180)));
      }
    };
    const up = () => {
      window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
      if (!moved) return;
      window.__ovDragged = true;
      markDirty();                        // 드래그 1회 = ⌘Z 1회(snap 은 시작에서 잡았다)
      if (window.__railOn === "subs") renderRailPanel("subs");
      if (document.querySelector('#inner .blk.s.sel')) select("sub", i, null, true);
    };
    snap();
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  window.clamp = clamp;
  // 드래그 중에는 refresh(전체 재그리기) 없이 화면만 갱신 — 끊김 방지
  window.setSubStyleLive = (i, k, v) => {
    const su = cur.model.subs[i]; su.style = { ...(su.style || {}) };
    su.style[k] = k === "color" ? v : +v;
    styleOvSub(i);                    // paintCues 의 인덱스 가드를 우회 — 값이 바뀌었다
  };
  document.addEventListener("mousedown", start, true);
})();

// ── 텍스트(F-411) 개별 배치 — _raw(x·y·크기·색·회전)를 화면에 그대로 ──
// 좌표는 엔진과 같은 글자 **중심** 비율(0~1). 큐가 없으면 CSS 기본으로 되돌린다.
let curTxtIdx = -1;                 // 마지막으로 고른 텍스트(드래그·인스펙터 기준)
let followClip = -1;                // 재생 중 지금 울리는 구간(자동 선택 커서)
// ⇧클릭 다중 선택 — 한 번에 한 종류만(구간·자막·내레이션·텍스트). 종류가 섞이면
// '여기부터/여기까지'가 각기 다른 좌표계를 건드려 결과를 예측할 수 없다.
let multiSel = { kind: null, idx: [] };
const clipMulti = { get length(){ return multiSel.kind === "clip" ? multiSel.idx.length : 0; } };
let ovTxtOn = [];                   // 지금 화면에 떠 있는 텍스트 인덱스들
// 한 칸의 위치·크기·색·회전 — 좌표는 엔진과 같은 글자 **중심** 비율(0~1)
function styleOvTx(el, t){
  const r = t._raw || {};
  const x = r.x != null ? +r.x : 0.5, y = r.y != null ? +r.y : 0.35;
  el.style.left = (x * 100) + "%"; el.style.top = (y * 100) + "%";
  // 새 파이프라인 라벨: 대사 자막과 같은 폰트, 크기는 ASS 글자 크기(줄 높이) 그대로라 실제 글자는 그만큼 작다
  // (Noto Sans CJK KR Black ÷1.43 · 그 밖 ÷1.38 — ai-video 라벨은 em 보정을 안 받는다, f3ab0fec). 기본 56.
  {
    const d = { ...(cur.chDesign || {}), ...((cur.row.draft || {}).design || {}), ...(cur.pendingDesign || {}) };
    const fam = v3SubFont(d)[0];
    el.style.fontFamily = `${fam},"Noto Sans KR",sans-serif`;
    el.style.fontSize = ((+r.size || 56) / (fam === "EngineNotoBlack" ? 1.43 : 1.38) / CANVAS_H * 100) + "cqh";
  }
  el.style.color = r.color || "#FFFFFF";
  const rot = Math.round(+r.rotate) || 0;
  el.style.transform = "translate(-50%,-50%)" + (rot ? ` rotate(${rot}deg)` : "");
}
// 지금 순간의 텍스트 전부를 그린다. 목록이 그대로면 위치만 갱신(DOM 안 건드림).
function styleOvTxt(list){
  const box = $("#ovTxt"); if (!box || !cur || !cur.model) return;
  const on = Array.isArray(list) ? list.filter(i => (cur.model.texts || [])[i])
                                 : (curTxtIdx >= 0 ? [curTxtIdx] : []);
  ovTxtOn = on;
  const sig = on.map(i => i + ":" + (cur.model.texts[i].text || "")).join("|")
    + (editMode ? "|e" : "");
  if (box.dataset.sig !== sig){
    box.dataset.sig = sig;
    box.innerHTML = on.map(i => `<div class="ovtx ovel" data-i="${i}">${
      esc(cur.model.texts[i].text || "")}${editMode
        ? '<b class="sh sh-size" data-h="size"></b><b class="sh sh-rot" data-h="rot"></b>' : ""
      }</div>`).join("");
    if (editMode) box.querySelectorAll(".ovtx").forEach(e => e.classList.add("sel"));
    // 고른 것 표시는 select() 가 붙인다 — 다시 그렸으니 여기서 복원한다
    if (curSel && curSel.kind === "txt"){
      const e = box.querySelector(`.ovtx[data-i="${curSel.i}"]`);
      if (e) e.classList.add("pick");
    }
  }
  on.forEach(i => { const e = box.querySelector(`.ovtx[data-i="${i}"]`);
    if (e) styleOvTx(e, cur.model.texts[i]); });
}
window.styleOvTxt = styleOvTxt;

// 제목·내레이션 핸들 — 편집 모드에서, 글자가 떠 있는 동안만
function ovSyncHandles(){
  // 작품 로고·플랫폼 표기: 끌면 자리, 모서리 손잡이로 크기(비율 유지)
  [["#ovTitle", []], ["#ovTts", ["w-l", "w-r", "size"]], ["#ovWork .wl", ["size"]], ["#ovPlat", ["size"]]].forEach(([q, ks]) => {   // 회전은 렌더가 쓰지 않는다(2026-09-29 뺐다)
    const el = $(q); if (!el) return;
    const on = editMode && (!!el.textContent.trim() || !!el.querySelector("img")) && el.style.display !== "none";
    el.classList.toggle("sel", on);
    const has = el.querySelector(".sh");
    if (on && !has) ks.forEach(k => { const h = document.createElement("b");
      h.className = "sh sh-" + k; h.dataset.h = k; el.appendChild(h); });
    if (!on && has) el.querySelectorAll(".sh").forEach(h => h.remove());
  });
}
window.ovSyncHandles = ovSyncHandles;

// ── 제목·내레이션·텍스트 드래그 — 자막(bindSubDrag)과 같은 문법 ──
// 제목·내레이션은 이 편 design 키로(전체 공통), 텍스트는 그 항목의 _raw 로.
(function bindOvDrag(){
  const start = e => {
    if (!editMode || !cur || !cur.model) return;
    const frame = tlRoot.querySelector(".shorts"); if (!frame) return;
    let kind = null, el = null;
    const hitTx = e.target.closest && e.target.closest(".ovtx");
    if (hitTx){ kind = "txt"; el = hitTx; curTxtIdx = +hitTx.dataset.i; }
    else for (const [q, k] of [["#ovTitle", "title"], ["#ovTts", "tts"], ["#ovWork .wl", "work"], ["#ovPlat", "plat"]]){
      const c = $(q); if (c && c.contains(e.target)){ kind = k; el = c; break; } }
    if (!kind || !(el.textContent.trim() || el.querySelector("img"))) return;
    if (kind === "txt" && !(cur.model.texts || [])[curTxtIdx]) return;
    e.preventDefault(); e.stopPropagation();
    const mode = e.target.dataset && e.target.dataset.h ? e.target.dataset.h : "move";
    const fr = frame.getBoundingClientRect(), box = el.getBoundingClientRect();
    const cx0 = box.left + box.width / 2, cy0 = box.top + box.height / 2;
    const a0 = Math.atan2(e.clientY - cy0, e.clientX - cx0) * 180 / Math.PI;
    const sx = e.clientX, sy = e.clientY;
    const d0 = { ...(cur.chDesign || {}), ...((cur.row.draft || {}).design || {}),
                 ...(cur.pendingDesign || {}) };
    const st = {};
    if (kind === "txt"){
      const r = (cur.model.texts[curTxtIdx] || {})._raw || {};
      st.x = r.x != null ? +r.x : 0.5; st.y = r.y != null ? +r.y : 0.35;
      st.size = +r.size || 56; st.rot = Math.round(+r.rotate) || 0;
    } else if (kind === "title"){
      st.y = (box.top - fr.top) / fr.height * CANVAS_H;   // 지금 그려진 자리(캔버스 px)
      st.rot = Math.round(+d0.title_rotate) || 0;
    } else if (kind === "work" || kind === "plat"){
      // 지금 그려진 상자(캔버스 px)에서 출발 — 엔진 키로 되돌려 적는다
      st.top = (box.top - fr.top) / fr.height * CANVAS_H; st.left = (box.left - fr.left) / fr.width * 1080;
      st.bw = box.width / fr.width * 1080; st.bh = box.height / fr.height * CANVAS_H;
      st.img = !!el.querySelector("img, .wlogo-ph");
      if (kind === "work"){ st.w = +d0.work_image_width || 395; st.h = +d0.work_image_height || 280; st.fs = +d0.work_font_size || 40; }
      else { st.w = +d0.platform_image_width || 150; st.h = +d0.platform_image_height || 80; st.fs = +d0.platform_font_size || 36; }
    } else {
      st.m = +d0.tts_y_margin || Math.round((fr.bottom - box.bottom) / fr.height * CANVAS_H); st.size = +d0.tts_size || 70;
      st.w = +d0.tts_width || 0.852; st.rot = Math.round(+d0.tts_rotate) || 0;
    }
    snap(); let moved = false;
    const rotOf = ev => { const a = Math.atan2(ev.clientY - cy0, ev.clientX - cx0) * 180 / Math.PI;
      let r = st.rot + (a - a0);
      if (ev.shiftKey) r = Math.round(r / 15) * 15; else if (Math.abs(r) < 3) r = 0;
      return Math.round(clamp(r, -180, 180)); };
    const live = (k, v) => { edDesign()[k] = v; layoutShorts(); };
    const mv = ev => {
      moved = true;
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (kind === "txt"){
        const t = cur.model.texts[curTxtIdx]; if (!t) return;
        t._raw = { ...(t._raw || {}) };
        if (mode === "move"){
          t._raw.x = +clamp(st.x + dx / fr.width, 0.02, 0.98).toFixed(4);
          t._raw.y = +clamp(st.y + dy / fr.height, 0.02, 0.98).toFixed(4);
        } else if (mode === "size")
          t._raw.size = Math.round(clamp(st.size + dy / fr.height * CANVAS_H, 28, 140));   // 엔진 허용 28~140
        else if (mode === "rot") t._raw.rotate = rotOf(ev);
        styleOvTx(el, t);                  // 잡고 있는 칸만 갱신(다시 그리지 않는다)
      } else if (kind === "title"){
        if (mode === "move"){
          live("title_y", Math.round(clamp(st.y + dy / fr.height * CANVAS_H, 0, CANVAS_H - 120)));
          edDesign().title_y_fixed = true;    // 직접 놓은 자리 = 고정 배치(F-409 규약)
        } else if (mode === "rot") live("title_rotate", rotOf(ev));
      } else if (kind === "work" || kind === "plat"){
        const b = window.__band, ddy = dy / fr.height * CANVAS_H, ddx = dx / fr.width * 1080;
        const pre = kind === "work" ? "work" : "platform";
        if (mode === "size"){                   // 모서리 — 높이 비율로 박스(가로·세로)를 같이 키운다
          const f = clamp((st.bh + ddy) / Math.max(8, st.bh), 0.2, 6);
          if (st.img){ live(pre + "_image_width", Math.round(clamp(st.w * f, 40, 1080))); live(pre + "_image_height", Math.round(clamp(st.h * f, 16, 1920))); }
          else live(pre + "_font_size", Math.round(clamp(st.fs * f, 16, 200)));
        } else if (kind === "work"){            // 작품 로고는 가운데 정렬 — 세로만 옮긴다
          const top = st.top + ddy, bb = b.vtop + b.vh;
          if (st.img) live("work_band_offset", Math.round(clamp(top - bb, 0, CANVAS_H - bb - 40)));
          else { live("work_title_y", Math.round(clamp(top, bb + 20, CANVAS_H - 60))); delete edDesign().work_band_offset; layoutShorts(); }
        } else {                                // 플랫폼 표기 — 가까운 모서리 기준 여백(렌더는 가장자리 100px 안쪽까지만)
          const L = st.left + ddx, bl = (1080 - b.vw) / 2, right = L + st.bw / 2 > 540;
          edDesign().platform_align = right ? "right" : "left";
          live("platform_x", Math.round(clamp(right ? bl + b.vw - (L + st.bw) : L - bl, 100, 1080)));
          live("platform_y", Math.round(clamp(st.top + ddy - b.vtop, 0, CANVAS_H)));
        }
      } else {                                 // 내레이션 — 이 편 공통 design
        if (mode === "move")
          live("tts_y_margin", Math.round(clamp(st.m - dy / fr.height * CANVAS_H, 60, CANVAS_H - 60)));
        else if (mode === "size")
          live("tts_size", Math.round(clamp(st.size + dy / fr.height * CANVAS_H, 20, 300)));
        else if (mode === "w-l" || mode === "w-r"){
          const sign = mode === "w-r" ? 1 : -1;
          live("tts_width", +clamp(st.w + sign * 2 * dx / fr.width, 0.3, 1).toFixed(4));
        } else if (mode === "rot") live("tts_rotate", rotOf(ev));
      }
    };
    const up = () => {
      window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
      if (!moved) return;
      window.__ovDragged = true;               // 곧 올 click 이 재생 토글로 새지 않게
      markDirty();
      if (window.__railOn) renderRailPanel(window.__railOn);
      if (curSel && ((kind === "txt" && curSel.kind === "txt" && curSel.i === curTxtIdx)
          || (kind === "title" && curSel.kind === "title")))
        select(curSel.kind, curSel.i, null, true);   // 인스펙터 숫자 갱신(재탐색 없이)
    };
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  };
  document.addEventListener("mousedown", start, true);
})();

// 파형 PNG 를 세로로 꽉 차게 — 열마다 파형의 위아래 범위를 재고, 전체 최대치로
// 정규화한 뒤 √ 스케일로 다시 그린다(작은 소리도 보이게, 상대 강약은 유지).
// 실패하면(CORS 등) 원본 URL 그대로 — 파형이 작게라도 나온다.
async function normWave(url){
  try {
    const bm = await createImageBitmap(await (await fetch(url)).blob());
    const W = bm.width, H = bm.height, mid = H / 2;
    const c = document.createElement("canvas"); c.width = W; c.height = H;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(bm, 0, 0);
    const d = g.getImageData(0, 0, W, H).data;
    const amp = new Float32Array(W); let max = 0;
    // showwavespic 은 중앙 대칭으로 꽉 채워 그린다 — 위에서 내려오다 처음 만나는
    // 불투명 픽셀이 그 열의 진폭이다. 만나면 즉시 멈춘다(7680×480 이라 전수 주사는
    // 370만 회, 이 방식은 대개 열당 몇 회).
    for (let x = 0; x < W; x++){
      let m = 0;
      for (let y = 0; y < mid; y++)
        if (d[(y * W + x) * 4 + 3] > 10){ m = mid - y; break; }
      amp[x] = m; if (m > max) max = m;
    }
    if (max < 1) return null;              // 통무음
    for (let x = 0; x < W; x++) amp[x] /= max;
    return amp;                            // 0~1 정규화 표본. 그리기는 drawWave 가.
  } catch (e){ return null; }
}
// 표본 → 높이. **최대치 기준 선형**이다.
//  · 정규화 전(선형·원척): 소재 피크가 화면 높이의 8%뿐이라 실선처럼 납작했다.
//  · dB(−45dB 바닥)이나 √: 단계가 전부 위쪽으로 몰려 통짜 덩어리가 됐다(사용자 8/27).
// 원본 PNG 가 120px 높이라 진폭 단계 자체가 4~5개뿐이라서, 정규화만 하면 그 단계가
// 20/40/60/100% 로 고르게 퍼져 높낮이가 가장 잘 읽힌다.
const waveH = a => (a > 0 ? Math.min(1, a) : 0);
// 보이는 구간만 그린다 — 스트립 전체(확대 시 수만 px)를 한 장으로 그릴 수는 없다.
// 표본은 1920개뿐이라 그보다 잘게는 못 나누지만, 늘린 비트맵과 달리 계단이 안 진다.
function drawWave(){
  const cv = document.getElementById("waveCv"), sc = document.getElementById("srcScroll");
  if (!cv || !sc || !cur || !cur.waveAmp || !cur.srcScale) return;
  const left = sc.scrollLeft, vw = Math.max(2, sc.clientWidth);
  cv.style.left = left + "px"; cv.style.width = vw + "px";
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const W = Math.round(vw * dpr), H = Math.round((cv.clientHeight || 56) * dpr);
  if (cv.width !== W) cv.width = W;
  if (cv.height !== H) cv.height = H;
  const g = cv.getContext("2d");
  g.clearRect(0, 0, W, H);
  const amp = cur.waveAmp, n = amp.length;
  // 파형 PNG 는 **원본 전체**를 1920열로 담는다 — 스트립이 '쓰인 범위만'일 때
  // 스트립 폭에 맞춰 늘이면 엉뚱한 시각의 소리가 그려진다(종전 버그).
  const dur = cur.waveDur; if (!(dur > 0)) return;
  const mid = H / 2, cap = mid * 0.92;
  const at = px => {                        // 화면 x → 원본초 → 표본(선형 보간)
    const t = cur.srcMin + (left + px / dpr) / cur.srcScale;
    const f = t / dur * (n - 1);
    if (f < 0 || f > n - 1) return 0;        // 영상 밖 — 그리지 않는다
    const i = Math.floor(f), j = Math.min(n - 1, i + 1), r = f - i;
    return amp[i] * (1 - r) + amp[j] * r;
  };
  g.fillStyle = "#5b8def";
  g.beginPath(); g.moveTo(0, mid);
  for (let x = 0; x < W; x++) g.lineTo(x, mid - waveH(at(x)) * cap);
  for (let x = W - 1; x >= 0; x--) g.lineTo(x, mid + waveH(at(x)) * cap);
  g.closePath(); g.fill();
}
window.drawWave = drawWave;

async function mountVideo(){
  const med = ((cur.row.sprites || {}).assets || {}).media || {};
  const v = $("#vid");
  const vs = $("#vidSrc");
  if (med.scan){
    const { data, error } = await sb.storage.from("ves-outputs").createSignedUrl(med.scan, 1800);
    if (!error && data){ v.src = data.signedUrl; vs.src = data.signedUrl; }
  } else { v.removeAttribute("src"); vs.removeAttribute("src");
    $("#srcTc").textContent = "전체 프리뷰 없음(scan_skip)"; }
  vs.ontimeupdate = () => {
    $("#srcTc").textContent = "원본 " + fmt(vs.currentTime);
    const ph = $("#srcph");
    if (ph && cur.srcScale) ph.style.left = ((vs.currentTime - cur.srcMin) * cur.srcScale) + "px";
  };
  const wave = (cur.row.sprites.assets || {}).wave;
  cur.waveAmp = null;
  if (wave){
    const { data } = await sb.storage.from("ves-outputs").createSignedUrl(wave, 1800);
    if (data) cur.waveAmp = await normWave(data.signedUrl);
    // 파형 PNG 의 시간축(= 원본 전체 길이). 없으면 아는 최댓값으로 하한을 잡는다.
    cur.waveDur = +cur.row.duration_sec
      || Math.max(0, ...(cur.model.clips || []).map(c => c.end),
                     ...(cur.model.tts || []).map(t => t.src + 2));
  }
  // 필름스트립 시트 — 전역 스프라이트(10초 간격). 시트 몇 장이면 전체가 커버되므로
  // 한 번에 서명한다(4시간물도 15장 남짓).
  const sp = cur.row.sprites || {};
  cur.layout = { interval: sp.interval || 10, grid: sp.grid || 10,
                 count: sp.count || 0 };
  cur.sheetUrls = []; cur.edgeSets = [];
  const gkeys = (sp.assets || {}).global || [];
  const edges = (sp.assets || {}).edges || [];
  // 전역 + 경계 밀집 시트를 한 번에 서명한다(요청 1회)
  const ekeys = edges.flatMap(w => w.keys || []);
  if (gkeys.length || ekeys.length){
    const { data } = await sb.storage.from("ves-outputs")
      .createSignedUrls([...gkeys, ...ekeys], 1800);
    const urls = (data || []).map(d => d.signedUrl || null);
    cur.sheetUrls = urls.slice(0, gkeys.length);
    let off = gkeys.length;
    cur.edgeSets = edges.map(w => {
      const u = urls.slice(off, off + (w.keys || []).length);
      off += (w.keys || []).length;
      return { s: +w.start_sec, e: +w.end_sec, interval: +w.interval || 2,
               grid: +w.grid || 10, urls: u };
    });
    if (!cur.layout.count) cur.layout.count = gkeys.length * cur.layout.grid * cur.layout.grid;
  }
  // 오버레이 초기값
  $("#ovWork").textContent = cur.row.run_id.replace(/_[0-9a-f]{6,}$/, "").replace(/_/g, " ");
  layoutShorts(); reCenter();
  v.addEventListener("play", seqTickStart);
  v.addEventListener("pause", () => { if (!holding) seqAudioStop(); });   // 영상이 서면 소리도 선다(어디서 세우든)
  seqWarm();                                   // 열자마자 예열 — 재생 전에 끝나 있게

  v.ontimeupdate = () => {
    const spans = liveSpans();
    // 구간 끝에 닿으면 다음 구간으로 점프 — 가상 미리보기의 심장
    advance();
    const outT = curOut();
    $("#outTc").textContent = outT == null ? "구간 밖" : fmt(outT);
    // 출력 플레이헤드
    const oph = $("#outph");
    if (oph){ if (outT == null) oph.style.left = "-9999px";
      else oph.style.left = (outT * (cur.outPx || 14)) + "px"; }
    // 확대해 둔 채 재생하면 재생 헤드가 화면 끝에 닿을 때 한 화면씩 넘긴다(멈춰 있을 땐 사람이 보는 자리를 건드리지 않는다)
    if (outT != null && cur.outZoom && (!v.paused || (holding && holding.frozen == null))){
      const sc = outScroll(), x = outT * cur.outPx;
      if (x > sc.scrollLeft + sc.clientWidth - 24 || x < sc.scrollLeft) sc.scrollLeft = Math.max(0, x - 24);
    }
    // 활성 내레이션·자막
    $("#pfill").style.width = (outT != null && cur.model.total
      ? Math.min(100, outT / cur.model.total * 100) : 0) + "%";
    paintCues(outT);            // 글자·소리는 아래 한 곳에서 — rAF 도 같은 함수를 부른다
  };
}
// 지금 순간의 내레이션·자막·텍스트를 화면에 얹는다. 값이 안 바뀌면 DOM 을 안 건드리므로
// 60fps 로 불러도 싸다 — 그래서 소리와 **같은 격자**에 놓을 수 있다.
// 내레이션 자막 구절 — 완성본은 합성 음성을 받아써서 짧은 구절로 나눠 하나씩 띄운다(ai-video narration_captions).
// 렌더 그대로인 줄은 그 구절·시각을 그대로, 문구를 고친 줄은 다시 렌더하기 전까지 띄어쓰기 기준 12자 안팎으로 대략 나눈다.
const phraseKey = t => `${t.voice || ""}|${t.speed || "normal"}|${String(t.text || "").trim()}`;
const PHRASE_MAX = 12;
function roughPhrases(text, dur){
  const words = String(text || "").trim().split(/\s+/).filter(Boolean), out = [];
  let line = "";
  for (const w of words){
    if (line && (line + " " + w).length > PHRASE_MAX){ out.push(line); line = w; }
    else line = line ? line + " " + w : w;
  }
  if (line) out.push(line);
  const n = out.reduce((a, x) => a + x.replace(/\s/g, "").length, 0) || 1;
  let t = 0;
  return out.map(x => { const d = dur * x.replace(/\s/g, "").length / n, p = { text: x, start: t, end: t + d }; t += d; return p; });
}
// 문구 칸 줄바꿈 = 자막 구절 경계(엔진 ae8cc2f7). 목소리는 줄을 공백 하나로 이은 한 문장.
const normNarr = v => { const ls = String(v ?? "").split(/\n/).map(l => l.replace(/\s+/g, " ").trim()).filter(Boolean);
  return window.__edPhraseEdit ? ls.join("\n") : ls.join(" "); };
const spokenText = v => String(v ?? "").split(/\n/).map(l => l.trim()).filter(Boolean).join(" ");
function roughLines(lines, dur){          // 줄마다 글자 수 비율로 시간을 나눈다(대략)
  const n = lines.reduce((a, x) => a + x.replace(/\s/g, "").length, 0) || 1;
  let t = 0;
  return lines.map(x => { const d = dur * x.replace(/\s/g, "").length / n, p = { text: x, start: t, end: t + d }; t += d; return p; });
}
// 한 줄의 구절과 그 출처: exact(렌더 그대로·엔진이 잼) · pending(재는 중) · rough(대략)
function phrasesOf(q){
  const lines = String(q.text || "").split("\n").map(l => l.trim()).filter(Boolean);
  const hit = cur.phrases && cur.phrases.get(phraseKey(q));
  if (hit) return { list: hit, state: "exact" };
  const m = window.__edChecks && window.__edChecks.phrasesFor(q, edH());
  if (m && m.list) return { list: m.list, state: "exact", note: m.note };
  const list = lines.length > 1 ? roughLines(lines, q.dur) : roughPhrases(q.text, q.dur);
  return { list, state: m && m.state === "pending" ? "pending" : "rough" };
}
function phraseAt(q, outT){
  const ph = phrasesOf(q).list;
  const rel = outT - q.out, p = ph.find(p => rel >= p.start - 1e-3 && rel < p.end);
  return p ? String(p.text).replace(/(?<!\.)[.,]+$/, "") : "";   // 구절 사이 틈은 완성본처럼 비운다 · 끝 쉼표·마침표는 렌더처럼 뗀다
}
function paintCues(outT){
  if (!cur || !cur.model) return;
  if (window.__edFx) window.__edFx.paint(cur, outT, edH());
  if (window.__edSfx){ const v = $("#vid"); window.__edSfx.paint(cur, outT, !!(v && !v.paused && seqSnd), edH()); }
  if (window.__edFrame) window.__edFrame.paint(cur, outT, edH());   // 구간 줌 미리보기
  const v = $("#vid");
  const q = outT == null ? null
    : (cur.model.cues || []).find(q => !q.dropped && outT >= q.out && outT < q.out + q.dur);
  const ttsEl = $("#ovTts"), ttsTx = q ? phraseAt(q, outT) : "";
  if (ttsEl.dataset.tx !== ttsTx){                     // 바뀔 때만 다시 쓴다(핸들 보존)
    ttsEl.dataset.tx = ttsTx; ttsEl.textContent = ttsTx; ovSyncHandles();
    if (ttsTx){ ttsEl.classList.remove("pop"); void ttsEl.offsetWidth; ttsEl.classList.add("pop"); } }   // 렌더처럼 구절마다 톡
  const live = v && (!v.paused || (holding && holding.frozen == null));
  if (outT != null && live && seqSnd) seqAudioSync(outT);
  // 재생 중이면 지금 울리는 구간 블록을 따라가며 선택한다(사용자 8/27).
  // 사람이 다른 종류(자막·내레이션…)를 골라 뒀거나 ⇧다중 선택 중이면 뺏지 않는다.
  if (live && driving && !multiSel.idx.length
      && (!curSel || curSel.kind === "clip")){
    const f = outT == null ? null : (cur.model.final || [])
      .find(c => !c.dead && outT >= c.out && outT < c.out + clipDur(c));
    if (f && f.i !== followClip){
      followClip = f.i;
      const side = document.getElementById("side");
      if (curSel && side && side.classList.contains("on"))
        select("clip", f.i, null, true);         // 인스펙터가 떠 있으면 내용도 갱신
      else {                                     // 아니면 테두리만 옮긴다(조용히)
        curSel = { kind: "clip", i: f.i };
        document.querySelectorAll("#inner .blk.sel").forEach(b => b.classList.remove("sel"));
        const el = document.querySelector(`#inner .blk.c[data-i="${f.i}"]`);
        if (el) el.classList.add("sel");
      }
    }
  }
  const si = outT == null ? -1
    : (cur.model.subs || []).findIndex(s => !s.del && outT >= s.start && outT < s.end);
  if (si !== curSubIdx){                               // 줄이 바뀔 때만 다시 그린다
    curSubIdx = si;
    $("#ovSub").textContent = si >= 0 ? cur.model.subs[si].text : "";
    styleOvSub(si);
  }
  // 같은 순간에 겹치는 텍스트가 여럿일 수 있다 — find 로 첫 건만 집으면 나머지가
  // 미리보기에서 사라진다(사용자 8/27). 전부 넘긴다.
  const xs = outT == null ? []
    : (cur.model.textCues || [])
        .filter(q => !q.dropped && outT >= q.out && outT < q.out + q.dur).map(q => q.ti);
  if (xs.join(",") !== ovTxtOn.join(",")){
    if (!xs.includes(curTxtIdx)) curTxtIdx = xs.length ? xs[0] : -1;
    styleOvTxt(xs);
  }
}
window.paintCues = paintCues;
function togglePlay(){
  const v = $("#vid"); if (!v.src) return;
  if (holding){                            // 붙잡기 중: 편집본 시계만 세우고 다시 흘린다
    if (holding.frozen == null){ holding.frozen = curOut(); seqAudioStop(); setPlay("▶ 재생"); }
    else { holding.t0 = performance.now() - (holding.frozen - holding.from) * 1000; holding.frozen = null;
      holdTick(); seqTickStart(); setPlay("⏸ 일시정지"); }
    return;
  }
  if (driving && !v.paused){ v.pause(); setPlay("▶ 재생"); return; }
  if (!driving){ seekOut(0); }
  v.play().catch(() => {}); setPlay("⏸ 일시정지");
}
function seekOut(t){                       // 완성본 시각으로 이동(쇼츠 모드)
  const hit = outToSrc(Math.max(0, t)); if (!hit) return;
  const v = $("#vid"); if (!v.src) return;
  driving = true; drvIdx = hit.idx; v.currentTime = hit.src; landAt(hit, Math.max(0, t), false);
  if (holding){ seqTickStart(); setPlay("⏸ 일시정지"); return; }
  v.play().catch(() => {}); setPlay("⏸ 일시정지");
}
function seekSrc(t){                       // 원본 시각으로 이동 — 좌측 원본 화면
  const vs = $("#vidSrc"); if (!vs.src) return;
  vs.currentTime = Math.max(0, t); vs.play().catch(() => {});
}
function seekOutPaused(outT){              // 쇼츠를 그 완성본 시각에 멈춰 세운다
  const hit = outToSrc(Math.max(0, outT)); if (!hit) return;
  const v = $("#vid"); if (!v.src) return;
  driving = true; drvIdx = hit.idx; v.currentTime = hit.src; v.pause(); landAt(hit, Math.max(0, outT), true); setPlay();
}

// ── 그리기 ────────────────────────────────────────────────────────────
let sel = null;
// 겹치는 항목을 여러 줄로 — 시작 시각순으로 훑으며 빈 줄에 놓는다(레인 배치).
// 줄은 **시간이 실제로 겹칠 때만** 나눈다(편집 프로그램처럼 한 트랙은 한 줄). 예전에는 블록 최소 폭(14px)까지
// 겹침으로 쳐서, 맞춤 화면에서 짧은 자막들이 계단처럼 2~3줄로 흩어졌다(2026-09-29). 좁아서 못 잡으면 확대한다.
function laneOf(items, tol = 0.5){
  const order = items.map((it, i) => ({ i, a: +it.a, b: +it.b }))
                     .sort((x, y) => x.a - y.a || x.b - y.b);
  const lastEnd = [], lane = new Array(items.length).fill(0);
  order.forEach(o => {
    let k = lastEnd.findIndex(e => o.a >= e - tol);
    if (k < 0){ k = lastEnd.length; lastEnd.push(0); }
    lastEnd[k] = o.b; lane[o.i] = k;
  });
  return { lane, n: Math.max(1, lastEnd.length) };
}
// 트랙 높이는 타임라인 칸 높이에 맞춰 자동(2026-09-29) — 경계선을 끌어 칸을 키우면 트랙이 그 높이를 채운다.
// 늘어나는 높이는 구간 줄(VZC, 썸네일)이 먼저·가장 많이, 나머지 줄(VZ)은 조금. 둘 다 1배 아래로는 안 줄고(그땐 세로 스크롤) 구간 1.8·나머지 1.4배까지.
let VZ = 1, VZC = 1, lastLanes = null;
const VZC_MAX = 1.8, VZ_MAX = 1.4, CLIP_H0 = 50;
const LANE_H0 = 23, TRACK_PAD = 6;
const laneH = () => Math.round(LANE_H0 * VZ);
const trackStyle = n => `height:${n * laneH() + TRACK_PAD}px`;
const blkTop = k => `top:${k * laneH() + 3}px`;
// 좁은 블록은 글자를 숨긴다(고르면 오른쪽에 전체 문구가 보인다)
const blkW = sec => Math.max(4, sec * cur.outPx - 1);
const tinyCls = sec => (sec * cur.outPx < 26 ? " tiny" : "");

// ── 완성본 타임라인 확대·축소(편집 프로그램처럼) ─────────────────────────
// cur.outZoom = 초당 px(없으면 전체 보기 = 창 폭에 맞춤). 전체 보기보다 작게는 줄이지 않는다.
// 확대하면 가로로 길어져 스크롤하고, 기준점(마우스·재생 헤드·화면 가운데)이 화면의 같은 자리에 남는다.
const OUT_ZMAX = 240;
// 처음 열 때 폭: 초당 30px. 짧은 영상은 전체 보기가 더 넓으니 그대로 한 화면, 긴 영상은 이 폭에서 스크롤해 본다
const OUT_ZSTART = 30;
const outScroll = () => $("#inner").parentElement;
function fitPx(){
  return Math.max(2, ((outScroll().clientWidth || 900) - 30) / Math.max(1, cur.model.total));
}
function outZoomTo(px, anchorT, anchorX){
  if (!cur || !cur.model) return;
  const sc = outScroll(), fit = fitPx(), old = cur.outPx || fit;
  if (anchorT == null){                     // 재생 헤드가 화면 안이면 그 자리, 아니면 화면 가운데
    const ph = curOut(), phx = ph == null ? -1 : ph * old - sc.scrollLeft;
    if (phx >= 0 && phx <= sc.clientWidth){ anchorT = ph; anchorX = phx; }
    else { anchorX = sc.clientWidth / 2; anchorT = (sc.scrollLeft + anchorX) / old; }
  }
  const want = px == null ? null : Math.min(OUT_ZMAX, px);
  cur.outZoom = want == null || want <= fit * 1.01 ? null : want;
  draw();
  sc.scrollLeft = cur.outZoom ? Math.max(0, anchorT * cur.outPx - anchorX) : 0;
}
function syncZoomUi(){
  const r = $("#zoomRange"), f = $("#zoomFit"); if (!r || !cur || !cur.model) return;
  const fit = fitPx(), px = cur.outPx || fit, span = Math.log(OUT_ZMAX / fit);
  r.value = span > 0 ? Math.round(Math.log(px / fit) / span * 100) : 0;
  if (f) f.classList.toggle("on", !cur.outZoom);
}
window.outZoomStep = dir => outZoomTo((cur.outPx || fitPx()) * (dir > 0 ? 1.4 : 1 / 1.4));
window.outZoomFit = () => outZoomTo(null);
window.outZoomSlide = v => { const fit = fitPx(); outZoomTo(fit * Math.pow(OUT_ZMAX / fit, +v / 100)); };

// 칸에 남는 높이를 트랙에 나눠 준다. 1배 기준 높이(레인 수로 계산)와 지금 칸 높이만 보고 정해서, 다시 그려도 값이 흔들리지 않는다
function fitTracks(){
  const sy = document.getElementById("tlScrollY"), ru = document.getElementById("ruler");
  if (!sy || !lastLanes || !cur || !cur.model) return;
  const src = document.getElementById("srcRow");
  const avail = sy.clientHeight - (src ? src.offsetHeight : 0) - (ru ? ru.offsetHeight : 0) - 6;
  const lanes = [1, lastLanes.s, lastLanes.t, lastLanes.x];                 // 제목·자막·내레이션·텍스트
  const other = lanes.reduce((a, n) => a + n * LANE_H0 + TRACK_PAD, 0);
  let extra = avail - CLIP_H0 - other, kc = 1, ko = 1;
  if (extra > 0){
    kc = Math.min(VZC_MAX, 1 + extra * 0.6 / CLIP_H0);                        // 구간 줄이 먼저 60%
    extra -= (kc - 1) * CLIP_H0;
    const laneSum = lanes.reduce((a, n) => a + n * LANE_H0, 0);
    ko = Math.min(VZ_MAX, 1 + extra / laneSum);                               // 나머지 줄에 남은 만큼
    extra -= (ko - 1) * laneSum;
    if (extra > 0) kc = Math.min(VZC_MAX, kc + extra / CLIP_H0);              // 그래도 남으면 다시 구간 줄
  }
  kc = +kc.toFixed(3); ko = +ko.toFixed(3);
  if (Math.abs(kc - VZC) < 0.01 && Math.abs(ko - VZ) < 0.01) return;
  VZC = kc; VZ = ko; draw();
}
window.fitTracks = fitTracks;
function draw(){
  const m = cur.model;
  // 전체 보기: 완성본 전체가 가용 폭을 채운다 — 왼쪽 몰림 방지(사용자 8/24). 확대하면 cur.outZoom.
  // 이 영상을 처음 그릴 때만 시작 폭을 정한다(cur 는 영상마다 새로 만든다 — 이후엔 사람이 고른 확대를 지킨다)
  if (cur.outZoom === undefined) cur.outZoom = fitPx() < OUT_ZSTART ? OUT_ZSTART : null;
  const px = cur.outZoom ? Math.max(cur.outZoom, fitPx()) : fitPx();
  cur.outPx = px;
  const W = Math.ceil(m.total * px) + 30;   // 전체 보기에서는 창 폭과 같다(종전 최소 600px 때문에 좁은 창에서 앞이 잘렸다)

  const fd = m.fromDraft;
  $("#draftchip").innerHTML = (fd.clips || fd.tts || fd.title || fd.texts || fd.sfx)
    ? `<span style="color:var(--accent)">고친 곳: ${["clips","tts","title","subs","texts","sfx"]
        .filter(k => fd[k]).map(k => ({clips:"구간",tts:"내레이션",title:"제목",subs:"자막",texts:"텍스트",sfx:"효과음"}[k])).join("·")}</span>`
    : `<span class="faint">고친 내용 없음</span>`;
  $("#lclips").innerHTML = `구간 <span class="faint">${m.clips.length}</span>`;
  $("#lsubs").innerHTML = `자막 <span class="faint">${m.subs.length}</span>`;
  $("#ltts").innerHTML = `내레이션 <span class="faint">${m.tts.length}</span>`;
  $("#ltxt").innerHTML = `텍스트 <span class="faint">${(m.texts || []).length}</span>`;
  if ($("#lsfx")) $("#lsfx").innerHTML = `효과음 <span class="faint">${window.__edSfx ? window.__edSfx.count(cur) : 0}</span>`;

  let h = `<div class="outph" id="outph" style="left:-9999px"></div>`;
  h += `<div class="ghostph" id="ghostph" style="left:-9999px"><i id="ghosttc"></i><b class="thumb" id="ghostthumb"></b></div>`;
  h += `<div class="ruler" id="ruler" style="width:${W}px">`;
  // 눈금 간격은 확대에 맞춰 — 글자끼리 60px 이상 떨어지는 가장 촘촘한 간격
  const tick = [0.5, 1, 2, 5, 10, 15, 30, 60].find(x => x * px >= 60) || 60;
  for (let s = 0; s <= m.total + 1e-6; s += tick)
    h += `<i style="left:${s * px}px">${fmt(s)}</i>`;
  h += `</div>`;

  // 구간 트랙 — 엔진 적용 후(final) 기준, 블록 안을 썸네일 필름으로 채운다(레퍼런스).
  h += `<div class="track vtrack" data-lab="lclips" style="height:${Math.round(CLIP_H0 * VZC)}px">`;
  // 🛑 제거 예정(dead) 구간의 자리 — 종전엔 **전부 left:0** 이었다. 완성본 시간축에
  //   자리가 없다는 이유였는데, 여러 개면 타임라인 맨 앞에 그대로 포개져 맨 위 한 장만
  //   클릭됐다. 나머지는 보이지도 잡히지도 않아 **삭제 자체가 불가능**했고, 사람은
  //   원본 소재 줄에서만 지울 수 있었다(2026-09-01 실사고 — 16개가 한 점에 묶였다).
  //   이제 '있었을 자리'(직전 살아있는 구간의 끝)에 최소폭으로, 여러 개면 나란히 민다.
  //   시간축상 의미도 맞다: 그 지점에서 빠질 구간이라는 뜻이다.
  let deadAt = 0, deadN = 0;
  m.final.forEach(c => {
    const orig = m.clips[c.i];
    const note = null;
    const cls = "blk c" + (c.dead ? " dead" : "")   // 역할(훅 등)은 보이지 않는다 — 계획 이름표라 순서를 바꾸면 엉뚱한 구간에 남는다
      + (note ? " warned" : "");
    let left, wpx;
    if (c.dead){
      wpx = 14;
      left = deadAt + deadN * (wpx + 2);
      deadN++;
    } else {
      wpx = Math.max(3, clipDur(c) * px - 1);
      left = c.out * px;
      deadAt = left + wpx; deadN = 0;
    }
    let inner = "";
    const TW = Math.round(78 * VZC);   // 썸네일 한 칸 — 구간 블록 높이(44px × VZC)에 16:9 를 유지
    for (let x = 0; x < wpx; x += TW){
      const p2 = thumbAt(Math.min(c.end, c.start + (x + TW / 2) / px * clipSpd(c)));
      if (p2) inner += `<span class="ct" style="left:${x}px;width:${TW}px;${thumbCss(p2)}"></span>`;
    }
    h += `<div class="${cls}${!c.dead && wpx < 18 ? " tiny" : ""}" data-k="clip" data-i="${c.i}"
      style="left:${left}px;width:${wpx}px"
      title="${esc(fmt(orig.start) + "~" + fmt(orig.end) + " (원본)")}">${inner}
      <b class="cl">${c.i + 1}</b>${window.__edChecks ? window.__edChecks.clipBadge(m.checks, c.i) : ""}${window.__edFx ? window.__edFx.clipBadge(m.clips[c.i]) : ""}${window.__edFrame ? window.__edFrame.clipBadge(m.clips[c.i]) : ""}${note ? `<span class="wb">!</span>` : ""}</div>`;
  });
  h += `</div>`;

  // 원음 줄 — 원음이 나오는 곳은 회색, 꺼지는 곳은 노란 점선(렌더와 같은 규칙: apply_edit narration_mute).
  // 일반 구간은 내레이션이 나오는 동안만 끄고, 덮개 구간은 내레이션이 있거나 배속·멈춤이면 통째로 끈다(editor-checks muted)
  {
    const voiced = m.cues.filter(q => !q.dropped).map(q => [q.out, q.out + q.dur]);
    const off = [];
    m.final.forEach(c => {
      if (c.dead) return;
      const a = c.out, b = c.out + clipDur(c);
      if (m.checks && m.checks.muted && m.checks.muted.get(c.i)) { off.push([a, b]); return; }
      voiced.forEach(([x, y]) => { const s0 = Math.max(a, x), e0 = Math.min(b, y); if (e0 - s0 > 1e-3) off.push([s0, e0]); });
    });
    off.sort((u, v) => u[0] - v[0]);
    const merged = [];
    off.forEach(([x, y]) => { const l = merged[merged.length - 1]; if (l && x <= l[1] + 1e-3) l[1] = Math.max(l[1], y); else merged.push([x, y]); });
    h += `<div class="track aud" data-lab="laud" style="height:20px"><i class="aud-on" style="left:0;width:${Math.max(0, m.total * px)}px"></i>`;
    merged.forEach(([x, y]) => { h += `<i class="aud-off" style="left:${x * px}px;width:${Math.max(2, (y - x) * px)}px" title="${esc(fmt(x) + " ~ " + fmt(y))} 원음 꺼짐 · 내레이션이 나오는 동안"></i>`; });
    // 원본 소리가 빈 곳(맥미니가 완성본에서 찾은 것 · 0130) — 렌더 시각 → 원본 → 지금 자리
    (cur.row.audio_gaps || []).forEach(g => {
      const s0 = window.__edSfx ? window.__edSfx.renderToSrc(cur, +g.start) : null, x = s0 != null ? srcToOut(s0) : null;
      if (x == null) return;
      const len = Math.max(0.1, +g.end - +g.start);
      h += `<i class="aud-gap" style="left:${x * px}px;width:${Math.max(3, len * px)}px" title="${esc(fmt(x))}부터 ${len.toFixed(1)}초 원본 소리가 비어 있어요"></i>`;
    });
    h += `</div>`;
  }
  // 효과음 줄(src/editor-sfx.js) — 자동은 회색, 직접 넣은 것은 보라색
  if (window.__edSfx) h += window.__edSfx.laneHtml(cur, px, edH());

  // 제목
  h += `<div class="track" data-lab="lttl" style="${trackStyle(1)}"><div class="blk ttl" data-k="title" data-i="0"
    style="left:0;width:${Math.max(60, m.total * px)}px">${esc(m.title.replace(/\n/g, " ⏎ ")) || "(제목 없음)"}</div></div>`;

  // 자막 (편집본 시간축 그대로)
  // 줄 배치는 초 단위 실제 겹침으로(0.05초 넘게 겹칠 때만 새 줄)
  const pxSpan = (out, dur) => ({ a: out, b: out + Math.max(0, dur) });
  const LANE_TOL = 0.05;
  const subLanes = laneOf(m.subs.map(s =>              // 삭제줄은 줄 배치에서도 제외
    s.del ? { a: -1e9, b: -1e9 } : pxSpan(s.start, s.end - s.start)), LANE_TOL);
  h += `<div class="track" data-lab="lsubs" style="${trackStyle(subLanes.n)}">`;
  m.subs.forEach((s, i) => {
    if (s.del) return;                                  // 숨김 — 되살리기는 [자막] 서랍에서
    h += `<div class="blk s${m.checks && m.checks.subWarn.has(i) ? " ck-bad" : ""}${window.__edFx ? window.__edFx.subClass(s) : ""}${tinyCls(s.end - s.start)}" data-k="sub" data-i="${i}"
      title="${esc(s.text)}" style="left:${s.start * px}px;width:${blkW(s.end - s.start)}px;
        ${blkTop(subLanes.lane[i])}">${esc(s.text)}</div>`;
  });
  h += `</div>`;

  // 내레이션 (엔진 판정 위치)
  const ttsL = laneOf(m.cues.map(q => q.dropped ? { a: -1e9, b: -1e9 } : pxSpan(q.out, q.dur)), LANE_TOL);
  h += `<div class="track" data-lab="ltts" style="${trackStyle(ttsL.n)}">`;
  m.cues.forEach((q, k) => {
    if (q.dropped) return;
    const warn = q.snapped || q.multi;
    // 경계선은 늘 긋고, 칸마다 구절 글자는 블록이 넉넉할 때만(좁으면 문장 한 줄)
    const ph = phrasesOf(q), cells = ph.list.length > 1, wide = blkW(q.dur) > 90;
    // 자리는 정수 px 로 — %·소수 px 면 선이 픽셀 사이에 걸려 어떤 건 1px, 어떤 건 2px 로 보인다
    const bw = blkW(q.dur), at = x => Math.round(Math.max(0, x) / q.dur * bw);
    const inner = !cells ? esc(spokenText(q.text))
      : ph.list.map((p, j) => (j ? `<i class="phd" style="left:${at(p.start)}px"></i>` : "")
          + (wide ? `<span class="phc" style="left:${at(p.start)}px;width:${at(ph.list[j + 1] ? ph.list[j + 1].start : q.dur) - at(p.start)}px">${esc(p.text)}</span>` : "")).join("")
        + (wide ? "" : `<span class="phc" style="left:0;right:0">${esc(spokenText(q.text))}</span>`);
    h += `<div class="blk t${cells ? " phr" : ""}${ph.state !== "exact" ? " phr-rough" : ""}${warn ? " warned" : ""}${q.ckBad ? " ck-bad" : ""}${tinyCls(q.dur)}" data-k="tts" data-i="${q.ti}"
      title="${esc(ph.list.map(p => p.text).join(" / "))}" style="left:${q.out * px}px;width:${blkW(q.dur)}px;${blkTop(ttsL.lane[k])}">${inner}
      ${warn ? `<span class="wb">!</span>` : ""}</div>`;
  });
  h += `</div>`;

  // 텍스트 (자유 텍스트 — 내레이션과 같은 앵커 규칙)
  const txL = laneOf((m.textCues || []).map(q => q.dropped ? { a: -1e9, b: -1e9 } : pxSpan(q.out, q.dur)), LANE_TOL);
  h += `<div class="track" data-lab="ltxt" style="${trackStyle(txL.n)}">`;
  (m.textCues || []).forEach((q, k) => {
    if (q.dropped) return;
    const warn = q.snapped || q.multi;
    h += `<div class="blk x${warn ? " warned" : ""}${q.ckBad ? " ck-bad" : ""}${tinyCls(q.dur)}" data-k="txt" data-i="${q.ti}"
      title="${esc(q.text)}" style="left:${q.out * px}px;width:${blkW(q.dur)}px;${blkTop(txL.lane[k])}">${esc(q.text)}
      ${warn ? `<span class="wb">!</span>` : ""}</div>`;
  });
  h += `</div>`;

  // AI 연출 줄은 없앴다(2026-09-29): AI 의 강조·줌·보조 자막은 묶음에서 바로 읽어 자막·구간·텍스트 줄에 보인다
  // (src/editor-fx.js · labels.json). 예전엔 checkpoint_style.json 을 손으로 열어 이 줄에 띄웠다.

  $("#inner").innerHTML = h;
  $("#inner").style.setProperty("--vz", VZ);        // 블록 높이(CSS calc)가 트랙 배율을 따른다
  $("#inner").style.setProperty("--vzc", VZC);
  lastLanes = { s: subLanes.n, t: ttsL.n, x: txL.n };
  requestAnimationFrame(fitTracks);                  // 레인 수가 바뀌었을 수 있다 — 바뀐 게 없으면 다시 그리지 않는다
  // 내용 칸을 눈금자 폭(완성본 전체)만큼 — 안 하면 트랙이 보이는 폭에서 끝나 그 뒤 빈 곳을 눌러도 재생 위치가 안 옮겨진다
  $("#inner").style.minWidth = W + "px";

  // 이벤트
  document.querySelectorAll("#inner [data-k]").forEach(el =>
    el.addEventListener("click", e => { e.stopPropagation();
      if (el.__moved){ el.__moved = false; return; }        // 드래그 직후 클릭 무시
      if (e.shiftKey && MULTI_KINDS.includes(el.dataset.k)){   // ⇧클릭 = 다중 선택
        multiToggle(el.dataset.k, +el.dataset.i); return; }
      const noSeek = el.__edgeSeek; el.__edgeSeek = false;  // 날개 클릭 = 그 경계에 선다
      select(el.dataset.k, +el.dataset.i, el, noSeek); }));
  paintMulti();                       // 다시 그린 뒤에도 ⇧다중 선택 테두리 유지
  // ── 블록 드래그·리사이즈(편집 모드) ─────────────────────────────────
  // 규약: 가장자리 8px = 늘이기/줄이기, 가운데 = 이동(구간만 예외 — 순서 버튼으로).
  // 드래그 중에는 잡고 있는 가장자리의 시각으로 **영상을 실시간 스크럽**한다 —
  // 눈으로 프레임을 보면서 늘이고 줄일 수 있어야 편집기다.
  let lastScrub = 0;
  const scrubSrc = t => {                     // 드래그 중: **좌측 원본**이 따라간다
    const vs = $("#vidSrc"); if (!vs.src) return;
    if (!vs.paused) vs.pause();
    const now = Date.now(); if (now - lastScrub < 120) return;
    lastScrub = now; vs.currentTime = Math.max(0, t);
  };
  const scrubOut = outT => { const hit = outToSrc(Math.max(0, outT)); if (hit) scrubSrc(hit.src); };
  // 공용 바인더 — live(edge, leftPx, widthPx) 는 매 이동, commit(edge, dSec) 는 놓을 때
  const bindBlk = (el, live, commit, resizable = true, movable = true) => {
    // 길이 조절은 고른 블록의 날개(양끝 12px)에서만 — 안 고른 블록은 어디를 잡아도 고르기·옮기기다
    const WING = 12;
    const wings = () => resizable && el.classList.contains("sel");
    el.addEventListener("mousemove", e => {
      if (el.__moved) return;
      const r = el.getBoundingClientRect();
      const onEdge = wings() && (e.clientX - r.left < WING || r.right - e.clientX < WING);
      el.style.cursor = onEdge ? "col-resize" : (movable ? "grab" : "pointer");
    });
    el.addEventListener("mousedown", e => {
      if (e.shiftKey) return;                 // ⇧클릭 = 범위 선택(click 에서)
      const r = el.getBoundingClientRect();
      // 좁은 블록은 양끝 날개가 겹친다 — 가까운 쪽 끝으로 판정
      const offL = e.clientX - r.left, offR = r.right - e.clientX;
      const edge = wings() && (offL < WING || offR < WING)
        ? (offL < offR ? "start" : "end") : null;
      if (!edge && !movable) return;          // 이동 불가 블록의 가운데 = 클릭 선택
      e.preventDefault(); e.stopPropagation();
      const startX = e.clientX, left0 = parseFloat(el.style.left),
            w0 = parseFloat(el.style.width);
      let dPx = 0;
      const mv = ev => {
        el.__moved = true; dPx = ev.clientX - startX;
        if (edge === "start"){ el.style.left = (left0 + dPx) + "px";
          el.style.width = Math.max(8, w0 - dPx) + "px"; }
        else if (edge === "end") el.style.width = Math.max(8, w0 + dPx) + "px";
        else el.style.left = Math.max(0, left0 + dPx) + "px";
        live(edge, parseFloat(el.style.left), parseFloat(el.style.width));
      };
      const up = () => {
        window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
        if (el.__moved) commit(edge, dPx / px);
        else if (edge){                   // 클릭만 = 그 경계 시각으로 빨간 선을 세운다
          el.__edgeSeek = true;           // 곧 올 click 의 select 가 시작점으로 되돌리지 않게
          seekOutPaused(Math.max(0, (edge === "start" ? left0 : left0 + w0) / px));
        }
      };
      window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
    });
  };
  if (editMode){
    // 내레이션·텍스트 — 앵커(원본초)가 좌표. 이동=앵커, 시작끝=길이
    const anchored = (selector, arr, kindName) =>
      document.querySelectorAll(selector).forEach(el => {
        const i = +el.dataset.i, it = arr[i]; if (!it) return;
        bindBlk(el,
          (edge, left, width) => edge === "end" ? scrubOut((left + width) / px) : scrubOut(left / px),
          (edge, d) => { snap();
            if (edge === "end") it.dur = +Math.max(0.5, it.dur + d).toFixed(3);
            else if (edge === "start"){
              const hit = outToSrc(Math.max(0, parseFloat(el.style.left) / px));
              if (hit){ const grow = it.src - hit.src;
                it.src = +hit.src.toFixed(3); it.dur = +Math.max(0.5, it.dur + grow).toFixed(3); }
            } else {
              const hit = outToSrc(Math.max(0, parseFloat(el.style.left) / px));
              if (hit) it.src = +hit.src.toFixed(3);
            }
            refresh(kindName, i); });
      });
    anchored('#inner .blk.t', cur.model.tts, "tts");
    anchored('#inner .blk.x', cur.model.texts, "txt");
    // 직접 넣은 효과음 — 끌어서 자리만 옮긴다(길이는 오른쪽 칸에서)
    if (window.__edSfx && window.__edSfx.editable())
      document.querySelectorAll('#inner .blk.fx:not(.auto)').forEach(el => {
        const i = +el.dataset.i;
        bindBlk(el, (edge, left) => scrubOut(left / px), () => {
          const hit = outToSrc(Math.max(0, parseFloat(el.style.left) / px));
          if (hit) window.__edSfx.moveTo(i, hit.src); else draw();
        }, false, true);
      });
    // 자막 — 완성본 시각이 좌표. '장면 따라가기'가 켜져 있으면 앵커도 함께 옮긴다.
    document.querySelectorAll('#inner .blk.s').forEach(el => {
      const i = +el.dataset.i, su = cur.model.subs[i]; if (!su) return;
      bindBlk(el,
        (edge, left, width) => edge === "end" ? scrubOut((left + width) / px) : scrubOut(left / px),
        (edge, d) => { snap();
          if (edge === "start") su.start = +Math.max(0, Math.min(su.end - 0.3, su.start + d)).toFixed(3);
          else if (edge === "end") su.end = +Math.max(su.start + 0.3, su.end + d).toFixed(3);
          else { const len = su.end - su.start;
            su.start = +Math.max(0, su.start + d).toFixed(3); su.end = +(su.start + len).toFixed(3);
            if (su.follow){ const hit = outToSrc(su.start); if (hit) su.src = +hit.src.toFixed(3); }
          }
          refresh("sub", i); });
    });
    // 구간 순서 바꾸기 — 블록 가운데를 끌면 삽입 위치가 세로선으로 보이고, 놓으면 그 자리로.
    // 앵커 붙은 자막·내레이션·텍스트는 자기 장면을 따라 함께 움직인다(앵커의 존재 이유).
    document.querySelectorAll('#inner .blk.c').forEach(el => {
      if (el.classList.contains("dead")) return;
      el.addEventListener("mousedown", e => {
        if (e.shiftKey) return;               // ⇧클릭 = 범위 선택(click 에서)
        const r = el.getBoundingClientRect();
        const offL = e.clientX - r.left, offR = r.right - e.clientX;
        // 가장자리는 트림 담당 — 고른 구간은 날개(12px, bindBlk 의 WING)까지. 종전 8px 이라 8~12px 을 잡고 늘이면
        // 늘이기와 순서 바꾸기가 함께 돌아 구간 자리가 바뀌었다(2026-10-02 사용자 '명절에 1억' v6)
        const wing = el.classList.contains("sel") ? 12 : 8;
        if (offL < wing || offR < wing) return;
        e.preventDefault(); e.stopPropagation();
        const from = +el.dataset.i;
        const live = cur.model.final.filter(c => !c.dead);
        // ⇧로 여러 구간을 골라 두고 그중 하나를 끌면 고른 구간을 한 묶음으로 옮긴다(완성본 순서 그대로)
        const group = multiSel.kind === "clip" && multiSel.idx.length > 1 && multiSel.idx.includes(from)
          ? multiSel.idx.slice() : [from];
        const bar = document.createElement("div"); bar.className = "insbar";
        $("#inner").appendChild(bar);
        group.forEach(g => document.querySelector(`#inner .blk.c[data-i="${g}"]`)?.classList.add("dragging"));
        let to = live.findIndex(c => c.i === from);
        const mv = ev => {
          el.__moved = true;
          const ir = $("#inner").getBoundingClientRect();
          const t = (ev.clientX - ir.left) / px;
          let k = live.length;                        // 기본 = 맨 뒤
          for (let n = 0; n < live.length; n++){
            const c = live[n], mid = c.out + clipDur(c) / 2;
            if (t < mid){ k = n; break; }
          }
          to = k;
          const at = k < live.length ? live[k].out : cur.model.total;
          bar.style.left = (at * px) + "px";
        };
        const up = () => {
          window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
          bar.remove(); document.querySelectorAll("#inner .blk.c.dragging").forEach(b => b.classList.remove("dragging"));
          if (!el.__moved) return;
          if (group.length > 1){
            // 놓은 자리 뒤에서 묶음 밖 첫 구간 앞에 넣는다(묶음 안에 놓으면 제자리)
            let k = to; while (k < live.length && group.includes(live[k].i)) k++;
            const target = k < live.length ? cur.model.clips[live[k].i] : null;
            const objs = group.map(g => cur.model.clips[g]);
            const order0 = cur.model.clips.slice();
            snap();
            cur.model.clips = cur.model.clips.filter(c => !objs.includes(c));
            const at = target ? cur.model.clips.indexOf(target) : cur.model.clips.length;
            cur.model.clips.splice(at < 0 ? cur.model.clips.length : at, 0, ...objs);
            if (cur.model.clips.every((c, n) => c === order0[n])){ undoStack.pop(); return; }   // 제자리
            multiSel = { kind: null, idx: [] };
            refresh("clip", cur.model.clips.indexOf(objs[0]));
            return;
          }
          const curPos = live.findIndex(c => c.i === from);
          if (to === curPos || to === curPos + 1) return;      // 제자리
          // 시각 고정(장면 따라가기 끔) 자막이 있으면 알린다 — 그 줄만 제자리에 남는다
          const pinned = cur.model.subs.filter(su => !su.del && !su.follow).length;
          if (pinned) setTimeout(() => undoToast(`구간 순서를 바꿨어요. 장면 따라가기를 끈 자막 ${pinned}줄은 제자리에 있어요`), 0);
          snap();
          // 객체 참조로 옮긴다 — 인덱스는 splice 뒤 밀리므로 믿을 수 없다
          const moved = cur.model.clips[from];
          const targetObj = live[to] ? cur.model.clips[live[to].i] : null;
          cur.model.clips.splice(from, 1);
          const at = targetObj ? cur.model.clips.indexOf(targetObj) : cur.model.clips.length;
          cur.model.clips.splice(at < 0 ? cur.model.clips.length : at, 0, moved);
          refresh("clip", cur.model.clips.indexOf(moved));
        };
        window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
      });
    });
    // 구간 — 원본초 좌표. 가장자리 트림 + 원본 프레임 스크럽
    document.querySelectorAll('#inner .blk.c').forEach(el => {
      const i = +el.dataset.i, c = cur.model.clips[i]; if (!c || el.classList.contains("dead")) return;
      const s0 = c.start, e0 = c.end;
      bindBlk(el,
        (edge, left, width) => scrubSrc(edge === "start" ? s0 + (left - parseFloat(el.dataset.l0 ?? left)) / px
                                        : e0 + (width - parseFloat(el.dataset.w0 ?? width)) / px),
        (edge, d) => { snap();
          if (edge === "start") c.start = +Math.max(0, Math.min(e0 - 0.5, s0 + d)).toFixed(3);
          else c.end = +Math.max(s0 + 0.5, e0 + d).toFixed(3);
          refresh("clip", i); },
        true, false);
      el.dataset.l0 = parseFloat(el.style.left); el.dataset.w0 = parseFloat(el.style.width);
    });
  }
  // 타임스탬프 찍기 모드(사용자 8/25) — 완성본 영역 전체(눈금+트랙 빈 곳)에서
  // 마우스를 따라 고스트 헤드가 움직이고, 클릭하면 그 자리에 재생 헤드가 선다.
  // 블록·재생 헤드 위에서는 각자의 클릭(선택·드래그)이 우선한다(stopPropagation).
  {
    const inner = $("#inner"), g = $("#ghostph"), gt = $("#ghosttc");
    inner.addEventListener("mousemove", e => {
      if (e.buttons){ g.style.left = "-9999px"; return; }   // 드래그 중엔 숨김
      if (e.target.closest(".blk") || e.target.closest(".outph")){
        g.style.left = "-9999px"; return; }
      const r = inner.getBoundingClientRect();
      const x = e.clientX - r.left, t = x / px;
      if (t < 0 || t > cur.model.total){ g.style.left = "-9999px"; return; }
      g.style.left = x + "px"; gt.textContent = fmt(t);
      const gth = $("#ghostthumb"), hit = outToSrc(t);   // 그 지점 장면 미리보기(B)
      const p2 = hit && thumbAt(hit.src);
      if (p2){ gth.style.display = "block"; gth.style.cssText += ";" + thumbCss(p2); }
      else gth.style.display = "none";
    });
    inner.addEventListener("mouseleave", () => { g.style.left = "-9999px"; });
    inner.addEventListener("click", e => {
      if (e.target.closest(".blk") || e.target.closest(".outph")) return;
      const r = inner.getBoundingClientRect();
      const t = (e.clientX - r.left) / px;
      if (t >= 0 && t <= cur.model.total) seekOutPaused(t);   // 찍으면 멈춘 채 선다
    });
  }
  // 재생 헤드 드래그 — 잡는 순간 멈추고 스크럽, 놓으면 (재생 중이었으면) 이어서
  $("#outph").addEventListener("mousedown", e => {
    e.preventDefault(); e.stopPropagation();
    const v = $("#vid"); opWasPlaying = !v.paused;
    v.pause(); seqAudioStop(); setPlay("▶ 재생");
    opDrag = true; opScrub(e);
  });
  // 라벨 칸 높이를 트랙에 맞춘다(레인 수가 다르면 줄이 어긋난다)
  document.querySelectorAll("#inner .track[data-lab]").forEach(tr => {
    const lab = document.getElementById(tr.dataset.lab);
    if (lab) lab.style.height = tr.style.height.replace("height:", "");
  });
  drawSrc();
  drawWarns();
  syncZoomUi();
  // 다시 그려도(확대·축소 등) 고른 블록과 ⇧다중 선택을 그대로 둔다 — 새 블록에 표시만 다시 붙인다
  if (curSel && BLK_CLS[curSel.kind]){
    const el = document.querySelector(`#inner .blk.${BLK_CLS[curSel.kind]}[data-i="${curSel.i}"]`);
    if (el) el.classList.add("sel");
  }
  if (multiSel.kind && BLK_CLS[multiSel.kind]) multiSel.idx.forEach(i => {
    const el = document.querySelector(`#inner .blk.${BLK_CLS[multiSel.kind]}[data-i="${i}"]`);
    if (el) el.classList.add("msel");
  });
}

// 원본 시각 → 스프라이트 썸네일 좌표. 경계 밀집 시트(2초) 우선, 없으면 전역(10초).
function thumbAt(t){
  if (!cur) return null;
  for (const w of cur.edgeSets || []){
    if (t < w.s || t > w.e || !w.urls.length) continue;
    const per = w.grid * w.grid;
    const n = Math.max(0, Math.floor((t - w.s) / w.interval));
    const url = w.urls[Math.floor(n / per)];
    if (!url) continue;
    const idx = n % per;
    return { url, g: w.grid, row: Math.floor(idx / w.grid), col: idx % w.grid };
  }
  if (!(cur.sheetUrls || []).length) return null;
  const L = cur.layout, per = L.grid * L.grid;
  let n = Math.round(t / L.interval);
  n = Math.max(0, Math.min((L.count || 1) - 1, n));
  const url = cur.sheetUrls[Math.floor(n / per)];
  if (!url) return null;
  const idx = n % per;
  return { url, g: L.grid, row: Math.floor(idx / L.grid), col: idx % L.grid };
}
const thumbCss = p2 => { const d = p2.g - 1;
  return `background-image:url('${p2.url}');background-size:${p2.g * 100}% ${p2.g * 100}%;` +
    `background-position:${(p2.col / d * 100).toFixed(3)}% ${(p2.row / d * 100).toFixed(3)}%`; };

// ── 원본 소재 스트립 — 완성본과 독립된 축척(px/원본초). 휠·버튼으로 확대/축소 ──
function drawSrc(){
  if (!cur || !cur.model) return;
  const m = cur.model;
  let srcMin, srcMax;
  if (cur.srcFull){                                   // 전체 원본(토글)
    srcMin = 0;
    srcMax = Math.max(+cur.row.duration_sec || 0,
      ...m.clips.map(c => c.end), ...m.tts.map(t => t.src + 2)) + 2;
  } else {                                            // 쓰인 범위 ±5초(기본)
    srcMin = Math.min(...m.clips.map(c => c.start), ...m.tts.map(t => t.src)) - 5;
    srcMax = Math.max(...m.clips.map(c => c.end), ...m.tts.map(t => t.src + 2)) + 5;
  }
  const cont = $("#srcScroll");
  const fit = Math.max(0.5, (cont.clientWidth - 2) / (srcMax - srcMin));
  const pxs = cur.srcPx || fit;                     // null = 맞춤(전체가 한 화면)
  cur.srcMin = srcMin; cur.srcMaxV = srcMax; cur.srcScale = pxs; cur.srcFit = fit;
  const W = Math.ceil((srcMax - srcMin) * pxs);
  const sx = t => (t - srcMin) * pxs;
  // 파형이 없으면(작업 컴퓨터 영상) 파형 자리를 비워 두지 않는다 — 내레이션 점을 썸네일 바로 아래로
  let h = `<div class="srcarea${cur.waveAmp ? "" : " nowave"}" style="width:${W}px">`;
  const pickThumb = thumbAt;   // 전역 thumbAt (구간 블록 썸네일과 공유)
  {
    const TW = 78;
    for (let x = 0; x < W; x += TW){
      const p = pickThumb(srcMin + (x + TW / 2) / cur.srcScale);
      if (!p) continue;
      const d = p.g - 1;
      h += `<div class="fstile" style="left:${x}px;width:${TW}px;
        background-image:url('${p.url}');background-size:${p.g * 100}% ${p.g * 100}%;
        background-position:${(p.col / d * 100).toFixed(3)}% ${(p.row / d * 100).toFixed(3)}%"></div>`;
    }
  }
  // 안 쓰인 원본을 어둡게 — 쓰인 구간(밝은 창)이 한눈에 갈린다
  {
    const used = m.clips.map(c => [c.start, c.end]).sort((a, b) => a[0] - b[0]);
    const merged = [];
    for (const r of used){
      if (merged.length && r[0] <= merged[merged.length - 1][1])
        merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], r[1]);
      else merged.push([...r]);
    }
    let pos = srcMin;
    for (const [s, e] of merged){
      if (s > pos) h += `<div class="srcdim" style="left:${sx(pos)}px;width:${(s - pos) * cur.srcScale}px"></div>`;
      pos = Math.max(pos, e);
    }
    h += `<div class="srcdim" style="left:${sx(pos)}px;width:${Math.max(0, (srcMax - pos) * cur.srcScale)}px"></div>`;
  }
  h += `${cur.waveAmp ? `<canvas class="wave" id="waveCv"></canvas>` : ""}
    <div class="srcclick" id="srcclick"></div>
    <div class="srcph" id="srcph" style="left:-9999px"></div>`;
  m.clips.forEach((c, i) => {
    h += `<div class="srcuse" data-k="clip" data-i="${i}"
      style="left:${sx(c.start)}px;width:${Math.max(6, (c.end - c.start) * cur.srcScale)}px"
      title="구간 ${i + 1} · 원본 ${fmt(c.start)}~${fmt(c.end)}"><b>${i + 1}</b></div>`;
  });
  m.dups.forEach(d => {
    h += `<div class="srcdup" style="left:${sx(d.s)}px;width:${Math.max(6, (d.e - d.s) * cur.srcScale)}px">
      <em>같은 원본 2회 (${fmt(d.s)}~${fmt(d.e)})</em></div>`;
  });
  m.cues.forEach(q => {
    h += `<div class="srcanchor${q.contained ? "" : " bad"}" data-k="tts" data-i="${q.ti}"
      style="left:${sx(q.src)}px" title="내레이션 원본 시각 ${fmt(q.src)}"></div>`;
  });
  // 찍은 범위(IN/OUT 또는 ⇧드래그) — 노란 점선 상자
  if (srcSel){
    const a = Math.min(srcSel.a, srcSel.b), b = Math.max(srcSel.a, srcSel.b);
    h += `<div class="srcsel" style="left:${sx(a)}px;width:${Math.max(3, (b - a) * pxs)}px"></div>`;
  }
  h += `<div class="srclab" style="left:4px">${fmt(srcMin)}</div>
    <div class="srclab" style="right:4px">${fmt(srcMax)}</div></div>`;

  $("#innerSrc").innerHTML = h;
  drawWave();                               // 보이는 구간 파형(확대·스크롤마다 갱신)
  document.querySelectorAll("#innerSrc [data-k]").forEach(el =>
    el.addEventListener("click", e => { e.stopPropagation();
      if (el.__moved){ el.__moved = false; return; }
      select(el.dataset.k, +el.dataset.i, el); }));
  // 사용창 리사이즈(편집 모드) — 원본 스트립에서 직접 구간 IN/OUT 트림.
  // 좌표가 원본초 그대로라 스크럽이 가장 정확한 곳이다: 잡고 끌면 좌측 원본이 따라온다.
  if (editMode){
    let lastL = 0;
    const scrubL = t => { const vs = $("#vidSrc"); if (!vs.src) return;
      if (!vs.paused) vs.pause();
      const n = Date.now(); if (n - lastL < 120) return; lastL = n;
      vs.currentTime = Math.max(0, t); };
    document.querySelectorAll("#innerSrc .srcuse").forEach(el => {
      const i = +el.dataset.i, c = cur.model.clips[i]; if (!c) return;
      el.addEventListener("mousemove", e => { if (el.__moved) return;
        const r = el.getBoundingClientRect();
        el.style.cursor = (e.clientX - r.left < 8 || r.right - e.clientX < 8)
          ? "col-resize" : "pointer"; });
      el.addEventListener("mousedown", e => {
        const r = el.getBoundingClientRect();
        const offL = e.clientX - r.left, offR = r.right - e.clientX;
        const edge = (offL < 8 || offR < 8) ? (offL < offR ? "start" : "end") : null;
        if (!edge) return;
        e.preventDefault(); e.stopPropagation();
        const startX = e.clientX, left0 = parseFloat(el.style.left), w0 = parseFloat(el.style.width);
        const s0 = c.start, e0 = c.end; let dSec = 0;
        const mv = ev => { el.__moved = true;
          const dpx = ev.clientX - startX; dSec = dpx / pxs;
          if (edge === "start"){ el.style.left = (left0 + dpx) + "px";
            el.style.width = Math.max(6, w0 - dpx) + "px"; scrubL(s0 + dSec); }
          else { el.style.width = Math.max(6, w0 + dpx) + "px"; scrubL(e0 + dSec); } };
        const up = () => {
          window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
          if (!el.__moved) return; snap();
          if (edge === "start") c.start = +Math.max(0, Math.min(e0 - 0.5, s0 + dSec)).toFixed(3);
          else c.end = +Math.max(s0 + 0.5, e0 + dSec).toFixed(3);
          refresh("clip", i); };
        window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
      });
    });
  }
  $("#srcclick").addEventListener("click", e => {
    if (e.shiftKey) return;                        // 범위 선택 중엔 시크하지 않는다
    const r = e.currentTarget.getBoundingClientRect();
    const t = srcMin + (e.clientX - r.left) / pxs;
    const vs = $("#vidSrc");                       // 찍으면 멈춘 채 선다(완성본과 같은 문법)
    if (vs.src){ vs.pause(); vs.currentTime = Math.max(0, t); }
  });
  // 고스트 헤드(A) + 썸네일 툴팁(B) — 훑을 때 마우스 옆에 그 지점 스프라이트 썸네일.
  // 왼쪽 원본 영상은 호버로 건드리지 않는다(재생 중이면 계속 재생) — 이동은 클릭만.
  // 시작(I)만 찍힌 상태면 시작~마우스가 미리 칠해진다.
  {
    const area = $("#srcclick").parentElement;     // .srcarea
    const g = document.createElement("div"); g.className = "srcghost";
    g.innerHTML = '<i></i><b class="thumb"></b>';
    g.style.left = "-9999px"; area.appendChild(g);
    const gi = g.querySelector("i"), gth = g.querySelector(".thumb");
    const pre = document.createElement("div"); pre.className = "srcpre";
    pre.style.left = "-9999px"; area.appendChild(pre);
    $("#srcclick").addEventListener("mousemove", e => {
      if (e.buttons){ g.style.left = "-9999px"; pre.style.left = "-9999px"; return; }
      const r = e.currentTarget.getBoundingClientRect();
      const x = e.clientX - r.left, t = srcMin + x / pxs;
      g.style.left = x + "px";
      gi.textContent = fmt(t);
      const p2 = thumbAt(t);
      if (p2){ gth.style.display = ""; gth.style.cssText += ";" + thumbCss(p2); }
      else gth.style.display = "none";
      // 시작만 찍혀 있으면 시작~마우스 미리 칠하기 — "여기서 끝내면 이만큼"
      if (marks.in != null && marks.out == null && t > marks.in){
        pre.style.left = sx(marks.in) + "px";
        pre.style.width = (t - marks.in) * pxs + "px";
      } else pre.style.left = "-9999px";
    });
    $("#srcclick").addEventListener("mouseleave", () => {
      g.style.left = "-9999px"; pre.style.left = "-9999px"; });
  }
  // ⇧드래그 = 새 구간 범위 선택(편집 모드) — 노란 점선 상자로 표시
  $("#srcclick").addEventListener("mousedown", e => {
    if (!editMode || !e.shiftKey) return;
    e.preventDefault();
    const r = e.currentTarget.getBoundingClientRect();
    const t0 = srcMin + (e.clientX - r.left) / pxs;
    const box = document.createElement("div"); box.className = "srcsel";
    e.currentTarget.parentElement.appendChild(box);
    const mv = ev => {
      const t1 = srcMin + (ev.clientX - r.left) / pxs;
      srcSel = { a: t0, b: t1 };
      box.style.left = sx(Math.min(t0, t1)) + "px";
      box.style.width = Math.abs(t1 - t0) * pxs + "px";
    };
    const up = () => {
      window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up);
      if (srcSel && Math.abs(srcSel.b - srcSel.a) >= 1) $("#addClipBtn").disabled = false;
      else { box.remove(); srcSel = null; }
    };
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  });
}

window.toggleSrcFull = () => {
  cur.srcFull = !cur.srcFull;
  cur.srcPx = null;                                  // 전환하면 맞춤으로 — 축척 혼란 방지
  const b = document.getElementById("srcFullBtn");
  if (b) b.textContent = cur.srcFull ? "전체 보는 중" : "쓰인 범위만";
  drawSrc();
};
function srcZoomBy(f){
  if (!cur || !cur.model) return;
  const cont = $("#srcScroll");
  const center = cont.scrollLeft + cont.clientWidth / 2;
  const t = cur.srcMin + center / cur.srcScale;
  cur.srcPx = Math.min(60, Math.max(cur.srcFit || 1, (cur.srcPx || cur.srcScale) * f));
  drawSrc();
  cont.scrollLeft = Math.max(0, (t - cur.srcMin) * cur.srcScale - cont.clientWidth / 2);
}

function drawWarns(){
  const m = cur.model, out = window.__edChecks ? window.__edChecks.warnHtml(m.checks) : [];
  const cueWarn = (label, list) => (list || []).forEach(q => {
    if (q.multi) out.push(`<div class="alert warn">${label} 「${esc(q.text.slice(0, 18))}」의 원래 장면이 두 구간에 들어 있어서
      앞 구간(${fmt(q.out)})에 붙어요. 뒤 구간에 두려면 원본 시각을 겹치지 않는 곳으로 옮겨 주세요.</div>`);
  });
  cueWarn("내레이션", m.cues);
  cueWarn("텍스트", m.textCues);
  $("#warns").innerHTML = out.length ? out.join("")
    : `<div class="alert ok">확인할 것이 없어요.</div>`;
}

// ── 인스펙터 ──────────────────────────────────────────────────────────
// 인스펙터 패널 상태 — 열 때의 모델을 기억해 [원래대로]가 그 시점으로 되돌린다
let curSel = null, panelOpenState = null;
window.openSide = () => { document.getElementById("side").classList.add("on"); reCenter(); };
window.closeSide = () => {
  document.getElementById("side").classList.remove("on");
  document.querySelectorAll(".blk.sel").forEach(b => b.classList.remove("sel"));
  reCenter();
  curSel = null; panelOpenState = null;
  updTrashBtn();                         // 고른 게 없으면 쓰레기통도 잠근다
};
window.sideRevert = () => {
  if (!panelOpenState || !curSel) return;
  if (modelState() !== panelOpenState){
    undoStack.push(modelState());          // 되돌리기 자체도 ⌘Z 로 취소 가능
    applyState(panelOpenState);
  }
  select(curSel.kind, curSel.i);           // 되돌린 값으로 패널 다시 그림
};
const BLK_CLS = { clip: "c", tts: "t", sub: "s", txt: "x", title: "ttl", sfx: "fx:not(.auto)", sfxa: "fx.auto" };
function select(kind, i, el, noSeek){
  multiSel = { kind: null, idx: [] };    // 보통 선택은 ⇧다중을 푼다
  document.querySelectorAll(".blk.sel, .blk.msel")
    .forEach(b => b.classList.remove("sel", "msel"));
  // 미리보기에서 '지금 고른 요소'를 실선 강조 — 어떤 걸 골랐는지 화면에서 보이게
  document.querySelectorAll(".shorts .pick").forEach(x => x.classList.remove("pick"));
  if (kind === "txt"){
    const e = document.querySelector(`#ovTxt .ovtx[data-i="${i}"]`);
    if (e) e.classList.add("pick");          // 겹친 것 중 **이것**을 골랐다
  } else {
    const pk = { title: "#ovTitle", tts: "#ovTts", sub: "#ovSub" }[kind];
    if (pk && $(pk)) $(pk).classList.add("pick");
  }
  // 서랍 목록에서 눌러도 타임라인 블록에 선택 테두리가 붙게 — el 이 없으면 찾는다
  if (!el && BLK_CLS[kind])
    el = document.querySelector(`#inner .blk.${BLK_CLS[kind]}[data-i="${i}"]`);
  if (el && el.classList.contains("blk")) el.classList.add("sel");
  // 다른 블록으로 갈아타면 '원래대로' 기준점도 그 시점으로 리셋
  if (!curSel || curSel.kind !== kind || curSel.i !== i){
    curSel = { kind, i }; panelOpenState = modelState();
  }
  const m = cur.model; let h = "";
  // 클릭한 요소의 완성본 시점으로 쇼츠를 멈춰 세운다(사용자 8/24) — 드래그 중은 제외
  if (el && !noSeek){
    let outT = null, outEnd = null;
    if (kind === "clip"){ const f = m.final.find(x => x.i === i);
      if (f && !f.dead){ outT = f.out; outEnd = f.out + clipDur(f); } }
    else if (kind === "tts"){ const q = m.cues[i];
      if (q && !q.dropped){ outT = q.out; outEnd = q.out + q.dur; } }
    else if (kind === "txt"){ const q = (m.textCues || [])[i];
      if (q && !q.dropped){ outT = q.out; outEnd = q.out + q.dur; } }
    else if (kind === "sub"){ const su = m.subs[i];
      if (su){ outT = su.start; outEnd = su.end; } }
    else if ((kind === "sfx" || kind === "sfxa") && window.__edSfx){
      const x = window.__edSfx.items(cur, edH()).find(y => y.k === kind && y.i === i);
      if (x){ outT = x.at; outEnd = x.at + x.dur; } }
    if (outT != null){
      // 시작 정각은 시크 왕복 오차로 '블록 밖'이 될 수 있다 — 조금 안쪽에 세운다.
      const inside = outEnd != null
        ? Math.min(outT + 0.06, Math.max(outT, outEnd - 0.02)) : outT;
      seekOutPaused(inside);
    }
  }
  if (kind === "clip"){
    const c = m.clips[i], f = m.final.find(x => x.i === i);
    h = `<div class="khead"><span class="sw" style="background:var(--clip)"></span>
      <span class="ttl">구간 ${i + 1}</span></div>
      ${window.__edChecks ? window.__edChecks.clipPanel(cur, i) : ""}
      ${window.__edFrame ? window.__edFrame.clipPanel(cur, i, editMode) : ""}
      ${window.__edFx ? window.__edFx.clipPanel(cur, i, editMode, edH()) : ""}`;
  } else if (kind === "tts"){
    const q = m.cues[i];
    h = `<div class="khead"><span class="sw" style="background:var(--tts)"></span>
      <span class="ttl">내레이션</span></div>
      ${q.multi ? `<div class="alert warn">같은 장면이 두 구간에 있어서 앞 구간에 붙어요.</div>` : ""}
      ${q.lost || q.dropped ? (window.__edChecks ? window.__edChecks.ttsPanel(cur, i, edH()) : "") : ""}`;
  } else if (kind === "txt"){
    const q = m.textCues[i];
    h = `<div class="khead"><span class="sw" style="background:var(--txt)"></span>
      <span class="ttl">텍스트</span></div>
      ${q.lost || q.dropped ? `<div class="alert warn ck-bad">이 텍스트는 빠져요. 원래 장면이 지금 구간에 없어요.</div>`
        : q.multi ? `<div class="alert warn">같은 장면이 두 구간에 있어서 앞 구간에 붙어요.</div>` : ""}`;
  } else if (kind === "sfx" || kind === "sfxa"){
    h = window.__edSfx ? window.__edSfx.sideHtml(cur, kind, i, editMode, edH()) : "";
  } else if (kind === "sub"){
    const s = m.subs[i];
    h = `<div class="khead"><span class="sw" style="background:var(--sub)"></span>
      <span class="ttl">자막</span>${s.del ? '<span class="small" style="color:var(--danger)">삭제됨</span>' : ""}</div>`;
  } else {
    // 제목은 한 편에 하나뿐. 문구는 여기(오른쪽), 모양은 왼쪽 [제목] 탭이 정본이다.
    // 편집 모드에서만 아래 editFormHtml 이 1줄·2줄 입력칸을 붙이므로, 꺼져 있을 때는
    // 최소한 **읽을 수는 있게** 줄별로 보여준다(칩을 지운 뒤 아예 안 보였다).
    const ls = String(m.title || "").split("\n");
    h = `<div class="khead"><span class="sw" style="background:var(--title)"></span>
      <span class="ttl">제목</span></div>
      ${editMode ? "" : `<div class="kv">
        <span class="k">1줄</span><span class="v" style="font-family:inherit">${esc(ls[0] || "(없음)")}</span>
        <span class="k">2줄</span><span class="v" style="font-family:inherit">${esc(ls.slice(1).join(" ") || "(없음)")}</span>
      </div>
      <div class="small faint">문구를 고치려면 위쪽 편집 잠금을 풀어 주세요.</div>`}
      ${labSegsHtml(editMode)}`;
  }
  // 자막·텍스트·내레이션은 잠겨 있어도 같은 칸을 보여 준다(입력만 막는다) — 문구 → 모양 → 시간 순
  $("#insp").innerHTML = h + (editMode || ["sub", "txt", "tts", "clip"].includes(kind) ? editFormHtml(kind, i) : "");
  updTrashBtn();                         // curSel 이 정해진 뒤에(라벨이 이전 선택을 읽었다)
  openSide();
}

// 편집 폼 — onchange 커밋(입력 중 재그리기로 포커스를 뺏지 않는다)
function editFormHtml(kind, i){
  const m = cur.model, T = v => fmt(v) + "";
  // 시간 칸 — 숫자는 아래에 접어 둔다. 요약(완성본 자리·길이)만 제목줄에 보인다.
  const timeBox = (sum, body) => `<details class="ins-time"><summary>시간 <span>${sum}</span></summary>${body}</details>`;
  const dis = editMode ? "" : " disabled";
  if (kind === "clip"){ const c = m.clips[i]; if (!c) return "";
    const f = m.final.find(x => x.i === i && !x.dead), spd = clipSpd(c) !== 1, hold = +c.hold;
    const x = clipSpd(c).toFixed(2), hs = hold.toFixed(1);
    const way = spd && hold ? `${x}배로 재생하고 끝에서 ${hs}초 멈춰서` : spd ? `${x}배로 재생해서` : `끝에서 ${hs}초 멈춰서`;
    const how = spd || hold ? `<div class="small faint">원본 ${(c.end - c.start).toFixed(1)}초를 ${way} 완성본에서 ${clipDur(c).toFixed(1)}초가 돼요.</div>` : "";
    return `      ${timeBox(f ? `${fmt(f.out)} ~ ${fmt(f.out + clipDur(f))} · ${clipDur(c).toFixed(1)}초` : "빠짐", `
        <div class="erow">
        <label class="small">원본 시작<input class="efld" value="${T(c.start)}"${dis}
          onchange="updClip(${i},'start',this.value)"></label>
        <label class="small">원본 끝<input class="efld" value="${T(c.end)}"${dis}
          onchange="updClip(${i},'end',this.value)"></label></div>
        ${how}
        <button onclick="seekSrc(${c.start})">${EI.play}원본에서 보기</button>`)}
      ${editMode ? `<div class="ebtns eq"><button onclick="moveClip(${i},-1)">${EI.up}앞으로</button>
        <button onclick="moveClip(${i},1)">${EI.down}뒤로</button>
        <button class="danger" onclick="delClip(${i})">구간 삭제</button></div>` : ""}`;
  }
  if (kind === "tts"){ const t = m.tts[i], q = m.cues[i]; if (!t) return "";
    const ph = q && !q.dropped && !q.lost ? phrasesOf(q) : null;
    const phHtml = ph ? `<div class="ph-list">${ph.list.map(p => `<div><span class="tc">${fmt(q.out + Math.max(0, p.start))}</span>${esc(p.text)}</div>`).join("")}
        ${ph.state === "pending" ? `<em>재는 중</em>` : ph.state === "rough" ? `<em>대략</em>` : ""}${ph.note ? `<div class="ph-note">${esc(ph.note)}</div>` : ""}</div>` : "";
    return `<label class="small">문구<textarea class="efld" rows="${Math.max(3, String(t.text || "").split("\n").length + 1)}"${dis}
        onchange="updTts(${i},'text',this.value)">${esc(t.text)}</textarea></label>
      <div class="small faint">${window.__edPhraseEdit ? "줄을 바꾸면 그 자리에서 자막이 나뉘어요. 목소리는 한 문장으로 이어져요." : "이 영상은 아직 자막 나누는 자리를 정할 수 없어요."}</div>
      ${phHtml}
      <label class="small">목소리<span class="vsel">${voiceSelHtml(t.voice,
        `updTts(${i},'voice',this.value)`)}</span></label>
      <div class="erow">
      <label class="small">속도<select class="efld"${dis} onchange="updTts(${i},'speed',this.value)">
        ${TTS_SPEEDS.map(x => `<option ${t.speed === x ? "selected" : ""}>${x}</option>`).join("")}
        </select></label>
      <label class="small">&nbsp;<button class="efld" id="pvIns"
        onclick="ttsPreview('ins${i}','pvIns',${JSON.stringify(t.text)},
          ${JSON.stringify(t.voice)},${JSON.stringify(t.speed || "normal")})"
        ${pvAble(t.voice) ? "" : "disabled"}
        title="${pvAble(t.voice) ? "이 문구를 이 목소리로 들어보기"
          : "기본 목소리는 다시 렌더한 뒤에 들을 수 있어요"}">${EI.play}들어보기</button></label></div>
      ${timeBox(q && !q.dropped && !q.lost ? fmt(q.out) : "빠짐", `
        ${q && !q.lost && !q.dropped && window.__edChecks ? window.__edChecks.ttsPanel(cur, i, edH()) : ""}
        <label class="small">원본 시각<input class="efld" value="${T(t.src)}"${dis}
          onchange="updTts(${i},'src',this.value)"></label>
        <div class="small faint">블록을 좌우로 끌면 시작 자리가 바뀌어요. 길이는 문구를 읽는 길이로 맞춰져요.</div>
        <button onclick="seekSrc(${t.src})">${EI.play}원본에서 보기</button>`)}
      ${editMode ? `<div class="ebtns"><button class="danger" onclick="delTts(${i})">내레이션 삭제</button></div>` : ""}`;
  }
  if (kind === "sub"){ const su = m.subs[i]; if (!su) return "";
    const st = su.style || {};
    return `<label class="small">문구<textarea class="efld" rows="3"${dis}
        onchange="updSub(${i},'text',this.value)">${esc(su.text)}</textarea></label>
      ${window.__edFx ? window.__edFx.subPanel(cur, i, editMode) : ""}
      <label class="dfld"><span>글자 색</span><span class="colrow">
        <input type="color" value="${/^#[0-9a-f]{6}$/i.test(st.color || "") ? st.color : "#ffffff"}"${dis}
          onchange="subStyleSet(${i},'color',this.value)">
        <input class="hex" value="${esc(st.color ?? "")}" placeholder="공통 색"${dis}
          onchange="subStyleSet(${i},'color',this.value)"></span></label>
      ${timeBox(`${fmt(su.start)} ~ ${fmt(su.end)}`, `
        <div class="erow">
        <label class="small">시작<input class="efld" value="${T(su.start)}"${dis}
          onchange="updSub(${i},'start',this.value)"></label>
        <label class="small">끝<input class="efld" value="${T(su.end)}"${dis}
          onchange="updSub(${i},'end',this.value)"></label></div>
        <label class="dfld tog"><span>장면 따라가기</span>
          <span class="togrow"><input type="checkbox" ${su.follow ? "checked" : ""}${dis}
            onchange="subFollowSet(${i},this.checked)">
          <em>${su.follow ? "구간을 옮기면 이 자막도 장면을 따라가요"
                          : "구간을 옮겨도 " + T(su.start) + " 자리에 그대로 있어요"}</em></span></label>
        ${su.src != null ? `<button onclick="seekSrc(${su.src})">${EI.play}원본에서 보기</button>` : ""}`)}
      ${editMode ? `<div class="ebtns"><button class="${su.del ? "" : "danger"}" onclick="delSub(${i})">
        ${su.del ? "삭제 취소" : "자막 삭제"}</button></div>` : ""}`;
  }
  if (kind === "txt"){ const t = m.texts[i], q = (m.textCues || [])[i]; if (!t) return "";
    const r = t._raw || {}, bs = +r.size || 56;
    // 엔진 라벨 색(ai-video stage4 LABEL_PALETTE) — 고르기 쉽게 견본으로. 다른 색도 칸에 직접 넣을 수 있다
    const sw = [["#FFFFFF", "흰색"], ["#FF5540", "빨강"], ["#FFE94A", "노랑"], ["#7ED0FF", "파랑"], ["#FFB637", "주황"]];
    const c = /^#[0-9a-f]{6}$/i.test(r.color || "") ? r.color : "#FFFFFF";
    return `<label class="small">문구<textarea class="efld" rows="3"${dis}
        onchange="updTxt(${i},'text',this.value)">${esc(t.text)}</textarea></label>
      <label class="dfld"><span>글자 색</span><span class="colrow">
        <input type="color" value="${c}"${dis} onchange="updTxtRaw(${i},'color',this.value.toUpperCase())">
        <input class="hex" value="${esc(r.color || "")}" placeholder="#FFFFFF"${dis}
          onchange="updTxtColor(${i},this.value)"></span></label>
      ${editMode ? `<div class="swrow">${sw.map(([h, n]) => `<button type="button" class="sw${String(r.color || "").toUpperCase() === h ? " on" : ""}"
        style="background:${h}" title="${n}" aria-label="${n}" onclick="updTxtRaw(${i},'color','${h}');select('txt',${i},null,true)"></button>`).join("")}</div>` : ""}
      <label class="dfld"><span>크기</span>
        <span class="steprow"><button type="button"${dis} onclick="stepFld(this,-2,${bs})" aria-label="작게">${EI.minus}</button>
        <input value="${r.size ?? ""}" placeholder="56"${dis}
          onchange="updTxtRaw(${i},'size',this.value)">
        <button type="button"${dis} onclick="stepFld(this,2,${bs})" aria-label="크게">${EI.plus}</button></span></label>
      <div class="small faint">크기는 28에서 140 사이예요. 화면의 글자를 끌면 자리, ◢ 는 크기, ↻ 는 회전이 바뀌어요.</div>
      ${timeBox(q && !q.dropped && !q.lost ? `${fmt(q.out)} · ${(+t.dur).toFixed(1)}초` : "빠짐", `
        <div class="erow">
        <label class="small">원본 시각<input class="efld" value="${fmt(t.src)}"${dis}
          onchange="updTxt(${i},'src',this.value)"></label>
        <label class="small">길이(초)<input class="efld" value="${t.dur}"${dis}
          onchange="updTxt(${i},'dur',this.value)"></label></div>
        <button onclick="seekSrc(${t.src})">${EI.play}원본에서 보기</button>`)}
      ${editMode ? `<div class="ebtns"><button class="danger" onclick="delTxt(${i})">텍스트 삭제</button></div>` : ""}`;
  }
  if (kind === "title"){
    const ls = String(m.title || "").split("\n");
    const l2 = ls.slice(1).join(" ");
    return `<label class="tfld"><span>1줄</span><input class="efld" id="ttl1"
        value="${esc(ls[0] || "")}" onchange="updTitleLines()"></label>
      <label class="tfld"><span>2줄 <i class="faint">비우면 한 줄 제목</i></span>
        <input class="efld" id="ttl2" value="${esc(l2)}" onchange="updTitleLines()"></label>
      <div class="small faint">글꼴과 색은 왼쪽 [제목] 탭에서 바꿔요.</div>`;
  }
  return "";
}

// 쇼츠 화면 자체를 눌러도 재생/일시정지 — 유튜브·캡컷과 같은 문법.
// 블록·버튼 클릭과 겹치지 않게 프레임(.shorts) 레벨에서만 받는다.
// 재생 헤드 드래그 상태 — mousedown 은 draw() 가 헤드를 다시 그릴 때마다 붙이고,
// move/up 은 전역에서 한 번만 받는다(드래그 중 헤드 밖으로 나가도 따라온다)
let opDrag = false, opWasPlaying = false;
function opScrub(e){
  if (!cur || !cur.model) return;
  const px = cur.outPx || 14, r = $("#inner").getBoundingClientRect();
  const outT = Math.max(0, Math.min(cur.model.total - 0.05, (e.clientX - r.left) / px));
  const hit = outToSrc(outT); if (!hit) return;
  const v = $("#vid"); if (!v.src) return;
  driving = true; drvIdx = hit.idx; v.currentTime = hit.src; landAt(hit, outT, true);   // seek → timeupdate 가 헤드·오버레이 갱신
}
window.addEventListener("mousemove", e => { if (opDrag) opScrub(e); });
window.addEventListener("mouseup", () => {
  if (!opDrag) return;
  opDrag = false;
  if (opWasPlaying){ if (holding) togglePlay(); else { $("#vid").play().catch(() => {}); setPlay("⏸ 일시정지"); } }
});

// 재생바 — 클릭·드래그로 완성본 시각 이동 (프레임 클릭 토글과 분리)
{
  const pbar = $("#pbar");
  let pbDrag = false;
  const pbSeek = e => {
    if (!cur || !cur.model || !cur.model.total) return;
    const r = pbar.getBoundingClientRect();
    seekOut(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * cur.model.total);
  };
  pbar.addEventListener("click", e => e.stopPropagation());
  pbar.addEventListener("mousedown", e => { e.stopPropagation(); pbDrag = true; pbSeek(e); });
  window.addEventListener("mousemove", e => { if (pbDrag) pbSeek(e); });
  window.addEventListener("mouseup", () => { pbDrag = false; });
}

// 브라우저 기본 '선택된 글자 드래그' 차단 — user-select:none 이전에 생긴 선택이나
// 인스펙터에서 시작된 선택이 타임라인 위로 끌려오는 경우까지 막는다
tlRoot.addEventListener("dragstart", e => {
  if (!e.target.closest("input, textarea")) e.preventDefault();
});
tlRoot.querySelector(".shorts").addEventListener("click", () => {
  if (window.__ovDragged){ window.__ovDragged = false; return; }   // 드래그 끝맺음 클릭
  const v = $("#vid"); if (!v.src) return;
  if (holding){ togglePlay(); return; }         // 붙잡기 중: 편집본 시계만 세우고 다시 흘린다
  if (!v.paused){ v.pause(); seqAudioStop(); }  // 멈춤 — 위치·소리 함께
  else if (driving) v.play().catch(() => {});  // 이어서
  else seekOut(0);                             // 처음부터
});

// 가로 스크롤 — 보이는 구간이 바뀌면 파형을 다시 그린다(프레임당 1회로 묶는다)
{
  let wRaf = 0;
  $("#srcScroll").addEventListener("scroll", () => {
    if (wRaf) return;
    wRaf = requestAnimationFrame(() => { wRaf = 0; drawWave(); });
  }, { passive: true });
  window.addEventListener("resize", () => drawWave());
// 새로고침·창 닫기로도 편집이 날아간다 — 브라우저 기본 확인창을 띄운다
window.addEventListener("beforeunload", e => {
  if (dirty && window.__tlOpen){ e.preventDefault(); e.returnValue = ""; }
});
}
$("#srcScroll").addEventListener("wheel", e => {
  if (!cur || !cur.model) return;
  e.preventDefault();
  const cont = e.currentTarget, rect = cont.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const t = cur.srcMin + (cont.scrollLeft + mx) / cur.srcScale;
  const f = e.deltaY < 0 ? 1.25 : 0.8;
  cur.srcPx = Math.min(60, Math.max(cur.srcFit || 1, (cur.srcPx || cur.srcScale) * f));
  drawSrc();
  cont.scrollLeft = Math.max(0, (t - cur.srcMin) * cur.srcScale - mx);
}, { passive: false });

// 완성본 타임라인 확대·축소: 핀치(ctrl+휠)·⌥/⌘+휠은 마우스 자리 기준. 그냥 휠·가로 쓸기는 그대로 스크롤
outScroll().addEventListener("wheel", e => {
  if (!cur || !cur.model || !(e.ctrlKey || e.altKey || e.metaKey)) return;
  e.preventDefault();
  const sc = e.currentTarget, mx = e.clientX - sc.getBoundingClientRect().left;
  const t = (sc.scrollLeft + mx) / cur.outPx, d = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
  outZoomTo(cur.outPx * Math.exp(-d * (e.ctrlKey ? 0.01 : 0.003)), t, mx);   // 핀치는 작은 값이 잦다
}, { passive: false });
// 단축키: = 확대 · − 축소 · ⇧Z 전체 보기(⌘ 와 함께 눌러도 브라우저 확대 대신 타임라인)
// 단축키는 키 자리(e.code)로 본다 — 한글 입력 중이면 e.key 가 "ㄴ"·"ㅋ"처럼 와서 S·Z 가 먹지 않았다
const keyOf = e => /^Key[A-Z]$/.test(e.code || "") ? e.code.slice(3).toLowerCase() : (e.key || "").toLowerCase();
window.addEventListener("keydown", e => {
  if (!cur || !cur.model || !window.__tlOpen) return;
  const tg = (e.target.tagName || "").toLowerCase();
  if (tg === "input" || tg === "textarea" || tg === "select" || e.target.isContentEditable) return;
  if (e.key === "=" || e.key === "+"){ e.preventDefault(); outZoomStep(1); }
  else if (e.key === "-" || e.key === "_"){ e.preventDefault(); outZoomStep(-1); }
  else if (keyOf(e) === "z" && e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey){ e.preventDefault(); outZoomFit(); }
});

  // ═════════ 편집 모드 (2026-08-24) — 고치기는 자유, 쓰기는 [초안 저장] 하나 ═════════
let editMode = false, dirty = false;
function updSaveBtn(){ const b = $("#saveDraftBtn"); if (b) b.disabled = !dirty; }
// 저장 상태 한 줄 — '초안'이라는 말이 헷갈린다는 지적(8/28)에 따라 '마지막 저장'으로.
let lastSavedAt = null;
const hhmm = d => d.toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" });
function saveMsgText(){
  if (dirty) return lastSavedAt ? "저장 안 됨 · 마지막 저장 " + hhmm(lastSavedAt) : "저장 안 됨";
  return lastSavedAt ? "마지막 저장 · " + hhmm(lastSavedAt) : "";
}
function paintSaveMsg(){ $("#saveMsg").textContent = saveMsgText(); }
window.paintSaveMsg = paintSaveMsg;
function markDirty(){ dirty = true; updSaveBtn(); paintSaveMsg(); }
function toggleEdit(){
  editMode = !editMode;
  document.body.classList.toggle("editing", editMode);
  $("#editToggle").classList.toggle("on", editMode);
  $("#editBtns").style.display = editMode ? "" : "none";
  $("#rochip").textContent = editMode
    ? "편집 중이에요. 30초마다 저장돼요."
    : "보기만 하는 중이에요. 편집 잠금을 풀면 고칠 수 있어요.";
  if (editMode) autoSaveStart(); else autoSaveStop();
  updTrashBtn();
  if (cur && cur.model){ draw(); ovSyncHandles();
    const bx = document.getElementById("ovTxt"); if (bx) bx.dataset.sig = "";
    styleOvTxt(ovTxtOn); styleOvSub(curSubIdx); }
}
const parseT = v => { v = String(v || "").trim(); if (!v) return null;
  if (/^\d+(\.\d+)?$/.test(v)) return parseFloat(v);
  const m = v.match(/^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$/); if (!m) return null;
  return (+(m[1] || 0)) * 3600 + (+m[2]) * 60 + parseFloat(m[3]); };
const refresh = (kind, i) => { markDirty(); runEngineRules(); draw();
  if (kind) select(kind, i);
  if (window.__railOn && window.renderRailPanel) renderRailPanel(window.__railOn); };

// 실행 취소 — 뮤테이터가 바꾸기 **전에** snap() 으로 쌓는다. 60개 상한.
let undoStack = [], redoStack = [];
const modelState = () => JSON.stringify({ c: cur.model.clips, t: cur.model.tts,
  s: cur.model.subs, x: cur.model.texts, ti: cur.model.title, sf: cur.model.sfx });
function snap(){ undoStack.push(modelState());
  if (undoStack.length > 60) undoStack.shift(); redoStack = [];
  // 🛑 30초 자동 저장은 `dirty` 를 보는데(autoSaveStart), 정작 그 값을 세우는 곳이
  //   undo/redo 밖에 없었다 — delClip·moveClip·updTitle·updTts 어느 것도 안 세워서
  //   **자동 저장이 한 번도 돌지 않았다**(화면은 "30초마다 자동 저장됩니다"라고 말하는
  //   중에). 그래서 편집실을 다시 열면 늘 '초안 없음 — 마지막 렌더 상태'였다.
  //   snap() 은 **모든** 편집 뮤테이터가 undo 때문에 반드시 부르는 유일한 지점이라
  //   여기 한 곳에 걸면 새는 함수가 없다. 판정은 변경 **뒤**여야 하므로 다음 tick.
  //   ⚠ 다음 tick 사이에 다른 run 으로 갈아탈 수 있다 — syncDirty 의 try 는 판정만
  //   감싸고 updSaveBtn·paintSaveMsg 는 밖이라, cur 을 여기서 한 번 더 본다.
  setTimeout(() => { if (cur && cur.model) syncDirty(); }, 0); }
function ovRepaint(){                      // 멈춰 있어도 오버레이를 지금 시각으로
  const v = $("#vid");
  if (v && v.src && v.paused){ try { v.currentTime = v.currentTime; } catch (e) {} }
}
function applyState(j){ const st = JSON.parse(j);
  cur.model.clips = st.c; cur.model.tts = st.t; cur.model.subs = st.s;
  cur.model.texts = st.x; cur.model.title = st.ti;
  if (st.sf) cur.model.sfx = st.sf;
  syncDirty();                       // ⌘Z 로 되돌아왔으면 '저장 안 됨'도 풀린다
  runEngineRules(); draw(); layoutShorts(); ovRepaint();
  if (!curSel) closeSide(); }
window.doUndo = () => { if (!undoStack.length){ toast("되돌릴 게 없어요"); return; }
  redoStack.push(modelState()); applyState(undoStack.pop()); };
window.doRedo = () => { if (!redoStack.length) return;
  undoStack.push(modelState()); applyState(redoStack.pop()); };
// 편집 단축키 — I(시작) O(끝) Enter(구간 추가) S(나누기). 본 편집실과 같은 키.
window.addEventListener("keydown", e => {
  if (!editMode || e.metaKey || e.ctrlKey || e.altKey) return;
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select") return;
  const k = keyOf(e);
  if (k === "i"){ e.preventDefault(); markIn(); }
  else if (k === "o"){ e.preventDefault(); markOut(); }
  else if (e.key === "Enter"){ e.preventDefault(); addClipFromMarks(); }
  else if (k === "s"){
    e.preventDefault();
    const sel = document.querySelector("#inner .blk.c.sel");
    if (sel) splitClip(+sel.dataset.i); else toast("나눌 구간을 먼저 골라 주세요");
  }
  else if (k === "delete" || k === "backspace"){ e.preventDefault(); delSelected(); }
  else if (k === "e"){ e.preventDefault(); endHere(); }
  else if (k === "q"){ e.preventDefault(); startHere(); }
});
window.addEventListener("keydown", e => {
  const k = keyOf(e), redoY = k === "y" && e.ctrlKey && !e.metaKey;   // 윈도우의 다시 실행(Ctrl+Y)도 받는다
  if (!editMode || !(e.metaKey || e.ctrlKey) || (k !== "z" && !redoY)) return;
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea") return;   // 입력칸 안은 브라우저 기본 undo
  e.preventDefault(); (e.shiftKey || redoY) ? doRedo() : doUndo();
});

// ── 시간대별 제목(E8) — 실험실은 창을 **읽고 통째로 대체**만 한다 ────────────
// 창의 문구·시각을 하나씩 고치는 화면은 본 편집실이다. 여기서 꼭 알려야 하는 것은 하나:
// 창이 완성본을 다 덮으면 위 1줄·2줄(top_title)은 화면에 한 번도 안 나온다. 종전엔
// "타임드 제목 미사용"이라고 단정해 말해서, 고친 제목이 무시되는 걸 아무도 못 봤다.
function labOutDur(){
  return (cur.model.clips || []).reduce((a, c) => a + Math.max(0, +c.end - +c.start), 0);
}
function labSegsCoverAll(){
  const rows = (cur.model.titleSegs || []).slice().sort((a, b) => a.start - b.start);
  const dur = labOutDur();
  if (!rows.length || dur <= 0) return false;
  let at = 0;
  for (const r of rows){
    if (+r.start > at + 0.05) return false;
    at = Math.max(at, +r.end);
  }
  return at >= dur - 0.05;
}
function labSegsHtml(editMode){
  const rows = cur.model.titleSegs || [];
  if (!rows.length)
    return `<div class="small faint">영상 전체에 같은 제목이 나와요.</div>`;
  const dur = labOutDur();
  // 시간대별 제목(제목 창)은 다시 렌더가 아직 받지 않는다(ai-video apply_edit 거절) — 보여 주기만 한다
  return `<div class="small faint">시간대마다 다른 제목이 ${rows.length}개 있어요:
      ${rows.map(r => `${(+r.start).toFixed(1)}~${(+r.end).toFixed(1)}초`).join(", ")}.
      시간대별 제목은 아직 여기서 고칠 수 없어요.</div>
    ${labSegsCoverAll() ? `<div class="alert warn">시간대별 제목이 영상 전체(0~${dur.toFixed(1)}초)를 덮고 있어서
      위 1줄·2줄을 고쳐도 화면에는 안 나와요.</div>` : ""}`;
}
// 전 구간 창 하나로 못박기 — 창을 **지우는** 것으로는 안 된다(키가 없으면 엔진이
// checkpoint_style 의 AI 창을 다시 얹는다). 본 편집실 edTitleSegAll 과 같은 규약.
window.labTitleAll = () => {
  const t = String(cur.model.title || "").trim();
  if (!t){ toast("제목이 비어 있어요"); return; }
  const dur = labOutDur();
  if (dur <= 0){ toast("구간이 없어서 길이를 알 수 없어요"); return; }
  snap();
  cur.model.titleSegs = [{ text: t, start: 0, end: +dur.toFixed(1) }];
  layoutShorts(); refresh("title", 0); syncDirty();
  toast(`제목을 영상 전체(0~${dur.toFixed(1)}초)에 걸었어요`);
};

// ── 뮤테이터 — inspector 폼과 드래그가 부른다 ──
window.updTitle = v => { snap(); cur.model.title = v; layoutShorts(); refresh("title", 0); };
window.updTitleLines = () => {
  const a = ($("#ttl1").value || "").trim(), b = ($("#ttl2").value || "").trim();
  updTitle(b ? a + "\n" + b : a);          // 뒤에서는 종전대로 줄바꿈 한 덩어리
};
// 크기 칸 +/- 스테퍼 — 칸이 비어 있으면(=기본값 상속) base 에서 출발한다
window.stepFld = (btn, d, base) => {
  const inp = btn.parentElement.querySelector("input");
  const v0 = String(inp.value).trim() === "" ? (+base || 0)
    : (parseFloat(inp.value) || +base || 0);
  inp.value = Math.max(1, Math.round(v0 + d));
  inp.dispatchEvent(new Event("change"));
};
// 디자인 오버라이드 — 이 편에만 적용. 빈 값 = 키 제거(채널 기본으로 되돌림).
// 저장은 saveDraft 의 pendingDesign 경로로 합류한다(템플릿 적용과 같은 자리).
// ⚠ window 에 올리면 안 된다 — 구판 편집실의 전역 edDesign()(7447)을 덮어써서
// 구판 KR 열기(SHOTCONE 일본어 카드의 '원본(한국어) 편집실')가 cur=null 로 즉사한다
// (8/28 실사고: '편집실 여는 중…'에서 영영 안 넘어감. 8/26 병합 e6b27e2 이후 잠복).
// 인라인 핸들러는 dsGet/dsSet 만 부르므로 IIFE 안 이름으로 충분하다.
const edDesign = () => (cur.pendingDesign = cur.pendingDesign
  || { ...((cur.row.draft || {}).design || {}) });
window.dsGet = k => edDesign()[k];
const NUDGE = {                     // 한 번 누를 때 움직임 · 범위 · 출발점(지금 그려진 값)
  title_y:      { step: 10,  min: 0,   max: 1700, base: L => L.titleTop },
  video_y:      { step: 10,  min: 0,   max: 1600, base: L => L.vtop },
  tts_y_margin: { step: -10, min: 60,  max: 1800, base: L => {                // 하단 여백이라 위로 = 커진다
    const e = $("#ovTts"), fr = e && e.closest(".shorts");                          // 글자가 떠 있으면 실제 아랫변에서
    if (e && fr && e.textContent.trim()){ const a = fr.getBoundingClientRect(), b = e.getBoundingClientRect();
      return Math.round((a.bottom - b.bottom) / a.height * 1920); }
    return L.ttsMargin; } },
  tts_width:    { step: .05, min: .3,  max: 1,    base: () => +dsBase("tts_width") || .852, dec: 2 },
  video_width:  { step: 20,  min: 320, max: 1080, base: L => L.vw || 1080 },
};
window.nudgeD = (k, dir) => {
  const n = NUDGE[k]; if (!n) return;
  const cur0 = dsGet(k), v0 = cur0 != null && cur0 !== "" ? +cur0 : +n.base(window.__lay || {});
  if (!isFinite(v0)) return;
  const v = Math.max(n.min, Math.min(n.max, v0 + dir * n.step));
  dsSet(k, n.dec ? v.toFixed(n.dec) : String(Math.round(v)));
};
window.dsBase = k => (cur.chDesign || {})[k];      // 채널 기본값(플레이스홀더용)
window.dsSet = (k, v) => {
  const d = edDesign();
  const t = String(v ?? "").trim();
  // 제목 1줄 크기를 칸에서 바꿀 때 2줄이 따라 커지지 않게(사용자 8/28).
  // 엔진 계약: title_size 는 **두 줄을 비율 유지한 채 함께** 스케일한다(90/70) —
  // 화면에서 제목 블록을 통째로 끄는 동작을 위한 규약이다(ai-video cli.py F-409).
  // 반면 탭의 '1줄 크기' 칸은 그 줄만 바꾸는 뜻으로 읽힌다. 그래서 값을 바꾸기 **전에**
  // 지금 2줄 크기를 그대로 못박아 둔다 — title_size2 가 명시되면 엔진이 스케일을
  // 덮으므로, 2줄은 보이던 크기 그대로 남고 1줄만 바뀐다.
  if (k === "title_size" && t !== ""){
    const cur2 = dsGet("title_size2") ?? dsBase("title_size2");
    if (cur2 == null || cur2 === ""){
      const s1 = +dsGet("title_size") || +dsBase("title_size") || 70;
      d.title_size2 = Math.round(s1 * 90 / 70);
    }
  }
  if (t === "") delete d[k]; else d[k] = /^-?\d+(\.\d+)?$/.test(t) ? +t : t;
  // 제목 세로를 직접 적으면 고정 배치 의도 — 스위치를 함께 보낸다(F-409 규약)
  if (k === "title_y"){ if (t === "") delete d.title_y_fixed; else d.title_y_fixed = true; }
  markDirty();
  layoutShorts();
  if (window.__railOn) renderRailPanel(window.__railOn);
};
window.updClip = (i, f, v) => { snap(); const c = cur.model.clips[i];
  if (f === "role") c.role = v;
  else { const t = parseT(v); if (t == null){ toast("시각은 16:04.1 이나 초로 적어 주세요"); return; } c[f] = t; }
  refresh("clip", i); };
window.delClip = i => {
  snap(); cur.model.clips.splice(i, 1); refresh(); closeSide(); undoToast(`${i + 1}번 구간을 지웠어요`); };
window.moveClip = (i, d) => { const a = cur.model.clips, j = i + d;
  if (j < 0 || j >= a.length) return; snap(); [a[i], a[j]] = [a[j], a[i]]; refresh("clip", j); };
window.updTts = (i, f, v) => { snap(); const t = cur.model.tts[i];
  if (f === "src"){ const x = parseT(v); if (x == null){ toast("시각은 16:04.1 이나 초로 적어 주세요"); return; } t.src = x; }
  else if (f === "dur"){ const x = parseFloat(v); if (!(x > 0)) return; t.dur = x; }
  else t[f] = f === "text" ? normNarr(v) : v;
  // 문구·목소리·속도가 바뀌면 렌더 mp3 는 더 이상 그 줄의 소리가 아니다 →
  // 즉석 합성 쪽으로 보내고(stale), 새 소리를 미리 받아 둔다.
  if (f === "text" || f === "voice" || f === "speed"){
    t.stale = !!t.key; seqCue = -1; cueAudio(t).catch(() => {}); }
  refresh("tts", i); };
window.delTts = i => { snap(); cur.model.tts.splice(i, 1); refresh(); closeSide(); };
window.subFollowSet = (i, on) => {
  snap();
  const su = cur.model.subs[i];
  if (on && su.src == null){                      // 앵커가 없으면 지금 자리의 장면을 앵커로
    const hit = outToSrc(su.start);
    if (!hit){ toast("이 자막 자리가 어느 구간에도 없어서 따라갈 장면을 정할 수 없어요"); return; }
    su.src = +hit.src.toFixed(3);
  }
  su.follow = !!on;
  refresh("sub", i);
  if (window.__railOn === "subs") renderRailPanel("subs");
};

window.updSub = (i, f, v) => { snap(); const su = cur.model.subs[i];
  if (f === "text") su.text = v;
  else { const x = parseT(v); if (x == null){ toast("시각은 0:04.1 이나 초로 적어 주세요"); return; } su[f] = x; }
  refresh("sub", i); };
// 줄별 스타일(F-407/410/412) — 엔진 계약: size·y·color·rotate·width 뿐(폰트 없음).
// 빈 값 = 키 제거 → 이 편 공통값을 따른다.
window.subStyleGet = (i, k) => ((cur.model.subs[i] || {}).style || {})[k];
window.subStyleSet = (i, k, v) => {
  snap();
  const su = cur.model.subs[i]; su.style = { ...(su.style || {}) };
  const t = String(v ?? "").trim();
  if (t === "") delete su.style[k];
  else if (k === "color") su.style[k] = t.toUpperCase();
  else su.style[k] = +t;
  if (!Object.keys(su.style).length) delete su.style;
  layoutShorts(); styleOvSub(i); refresh("sub", i);
};
// 자막 다중 선택 — 목록 체크박스. 카드가 바뀌면 비운다.
window.subCk = new Set();
window.subCkAll = on => { subCk = new Set(on ? cur.model.subs.map((_, i) => i) : []);
  renderRailPanel("subs"); };
window.subCkToggle = (i, on) => { on ? subCk.add(i) : subCk.delete(i);
  renderRailPanel("subs"); };
window.delSubChecked = () => {
  if (!subCk.size){ toast("지울 자막을 먼저 골라 주세요"); return; }
  const n = subCk.size;
  snap(); subCk.forEach(i => { if (cur.model.subs[i]) cur.model.subs[i].del = true; });
  subCk = new Set(); refresh(); renderRailPanel("subs"); undoToast(`자막 ${n}줄을 지웠어요`);
};
window.subsClearAll = () => {
  const live = cur.model.subs.filter(su => !su.del).length;
  if (!live){ toast("이미 모두 지워져 있어요"); return; }
  snap(); cur.model.subs.forEach(su => { su.del = true; });
  subCk = new Set(); refresh(); renderRailPanel("subs"); undoToast(`대사 자막 ${live}줄을 모두 지웠어요`);
};

// 내레이션 다중 선택·일괄 목소리 — 자막과 같은 규약
window.ttsCk = new Set();
window.ttsBulkVoice = "ko_female";
window.ttsCkAll = on => { ttsCk = new Set(on ? cur.model.tts.map((_, i) => i) : []);
  renderRailPanel("tts"); };
window.ttsCkToggle = (i, on) => { on ? ttsCk.add(i) : ttsCk.delete(i); renderRailPanel("tts"); };
window.delTtsChecked = () => {
  if (!ttsCk.size){ toast("지울 내레이션을 먼저 골라 주세요"); return; }
  const n = ttsCk.size;
  snap();
  [...ttsCk].sort((a, b) => b - a).forEach(i => cur.model.tts.splice(i, 1));
  ttsCk = new Set(); refresh(); renderRailPanel("tts"); undoToast(`내레이션 ${n}줄을 지웠어요`);
};
window.applyVoiceAll = () => {
  const idx = ttsCk.size ? [...ttsCk] : cur.model.tts.map((_, i) => i);
  if (!idx.length){ toast("내레이션이 없어요"); return; }
  snap(); idx.forEach(i => { cur.model.tts[i].voice = ttsBulkVoice; });
  refresh(); renderRailPanel("tts"); undoToast(`${idx.length}줄의 목소리를 바꿨어요`);
};
window.previewBulkVoice = () => {
  const t = cur.model.tts.find(x => String(x.text || "").trim());
  ttsPreview("bulk", "pvBulk", t ? t.text : "미리듣기 문구예요", ttsBulkVoice, "normal");
};

window.delSub = i => { snap(); cur.model.subs[i].del = !cur.model.subs[i].del; refresh("sub", i); };
window.updTxt = (i, f, v) => { snap(); const t = cur.model.texts[i];
  if (f === "src"){ const x = parseT(v); if (x == null){ toast("시각은 16:04.1 이나 초로 적어 주세요"); return; } t.src = x; }
  else if (f === "dur"){ const x = parseFloat(v); if (!(x > 0)) return; t.dur = x; }
  else t[f] = v;
  refresh("txt", i); };
window.updTxtRaw = (i, k, v) => { snap(); const t = cur.model.texts[i]; if (!t) return;
  t._raw = { ...(t._raw || {}) };
  const n = parseFloat(v);
  if (k === "size"){ if (!(n > 0)) delete t._raw.size;      // 비우면 기본(56)
    else t._raw.size = Math.round(clamp(n, 28, 140)); }      // 엔진 허용 28~140(밖이면 적용을 거절한다)
  else t._raw[k] = v;
  markDirty(); styleOvTxt(ovTxtOn); };
// 텍스트 색 칸(글자로 입력) — #RRGGBB 만 받는다(엔진이 그대로 ASS 색으로 쓴다)
window.updTxtColor = (i, v) => {
  const x = String(v || "").trim();
  if (!/^#[0-9a-f]{6}$/i.test(x)){ toast("색은 #FF5540 처럼 적어 주세요"); return; }
  updTxtRaw(i, "color", x.toUpperCase()); select("txt", i, null, true);
};
window.delTxt = i => { snap(); cur.model.texts.splice(i, 1); refresh(); closeSide();
  curTxtIdx = -1; ovTxtOn = []; ovRepaint(); };
window.addTxtAt = () => { snap();
  const v = $("#vid"), src = +(v.currentTime || 0).toFixed(3);
  // 기본 배치는 본 편집실 '＋ 텍스트'와 같은 값(0071) — 위치·크기 조정은 본 편집실에서
  cur.model.texts.push({ src, dur: 1.5, text: "(텍스트)",
    _raw: { x: 0.5, y: 0.35, size: 72, color: "#FFFFFF" } });
  refresh("txt", cur.model.texts.length - 1); };

// ── 추가 — 재생 지점·⇧드래그 범위 기준 ──
window.addTtsAt = () => { snap();
  const v = $("#vid"), src = +(v.currentTime || 0).toFixed(3);
  cur.model.tts.push({ src, dur: 3, text: "(내레이션 문구)", voice:
    (cur.model.tts[0] || {}).voice || "ko_female", speed: (cur.model.tts[0] || {}).speed || "normal" });
  cur.model.tts.sort((a, b) => a.src - b.src);
  refresh("tts", cur.model.tts.findIndex(t => t.src === src));
};
window.addSubAt = () => { snap();
  const v = $("#vid"), outT = curOut();
  if (outT == null){ toast("재생 헤드가 구간 밖에 있어요. 구간 안에 두고 눌러 주세요"); return; }
  cur.model.subs.push({ start: +outT.toFixed(3), end: +(outT + 2).toFixed(3),
    src: +(v.currentTime).toFixed(3), text: "(자막 문구)", del: false });
  refresh("sub", cur.model.subs.length - 1);
};
let srcSel = null;   // ⇧드래그 범위 {a,b} (원본 절대초)
// ── IN/OUT 마킹(본 편집실 edMarkIn/Out·edAddClip 계약 그대로) ──
window.marks = { in: null, out: null };
function markInfo(){
  const { in: a, out: b } = marks;
  // 스트립 표시·재그리기는 원본 탭이 닫혀 있어도 한다 — I/O 단축키는 어디서든 쓰인다
  srcSel = (a != null && b != null && b > a) ? { a, b }
    : (a == null && b == null ? null : srcSel);
  if (cur && cur.model) drawSrc();
  const el = document.getElementById("markInfo"); if (!el) return;
  el.innerHTML = (a == null && b == null)
    ? '<span class="faint">아직 찍은 범위가 없어요</span>'
    : `시작 <span class="tc">${a == null ? "-" : fmt(a)}</span> · 끝 <span class="tc">${b == null ? "-" : fmt(b)}</span>` +
      (a != null && b != null && b > a ? ` · <b>${(b - a).toFixed(2)}s</b>` : "") +
      ` <button class="lnk" onclick="clearMarks()">지우기</button>`;
}
window.markIn = () => { const v = $("#vidSrc"); if (!v.src) return;
  marks.in = +v.currentTime.toFixed(3);
  if (marks.out != null && marks.out <= marks.in) marks.out = null;
  markInfo(); };
window.markOut = () => { const v = $("#vidSrc"); if (!v.src) return;
  marks.out = +v.currentTime.toFixed(3);
  if (marks.in != null && marks.in >= marks.out) marks.in = null;
  markInfo(); };
window.clearMarks = () => { marks.in = marks.out = null; srcSel = null; markInfo(); };
window.addClipFromMarks = () => {
  const { in: a, out: b } = marks;
  if (a == null || b == null || b <= a){ toast("시작과 끝을 먼저 찍어 주세요"); return; }
  snap();
  // 소스 시각순 정렬은 목록이 아직 그 순서일 때만 — 사람이 만든 완성본 순서를
  // 새 구간 추가가 리셋하면 안 된다(본 편집실 edAddClip 과 같은 규약).
  const cl = cur.model.clips;
  const wasSorted = cl.every((c, k, arr) => !k || arr[k - 1].start <= c.start);
  cl.push({ start: +a.toFixed(3), end: +b.toFixed(3), role: cl.length ? "build" : "hook" });
  if (wasSorted) cl.sort((x, y) => x.start - y.start);
  marks.in = marks.out = null; srcSel = null;
  refresh("clip", cl.findIndex(c => c.start === +a.toFixed(3)));
  markInfo();
};

// ── 구간 나누기 ✂ — 재생 헤드에서 둘로. 분할 직후 완성본은 분할 전과 동일하다
// (본 편집실 edSplitClip 의 안전 계약: [start,t]+[t,end] 가 목록에서 연속 위치).
const SPLIT_MIN = 0.5;
window.splitAt = i => {
  const c = cur && cur.model.clips[i]; if (!c) return null;
  const f = cur.model.final.find(x => x.i === i);
  if (!f || f.dead || f.out == null) return null;
  const v = $("#vid");                       // 쇼츠(완성본) 재생 헤드가 기준
  const outT = curOut();
  if (outT == null) return null;
  const t = clipSrcAt(c, f.out, outT);         // 완성본 위치 → 이 구간의 원본 시각
  if (t < c.start + SPLIT_MIN || t > c.end - SPLIT_MIN) return null;
  return +t.toFixed(3);
};
// '여기까지'(사용자 8/25) — 선택한 블록의 끝을 재생 헤드 위치로 마무리.
// 자막은 완성본 끝 시각을, 내레이션·텍스트는 길이를, 구간은 원본 OUT 을 조정한다.
window.endHere = () => {
  if (multiSel.idx.length){ multiTrim("end"); return; }
  const sel = document.querySelector("#inner .blk.sel");
  if (!sel){ toast("블록을 먼저 골라 주세요"); return; }
  const v = $("#vid"), outT = curOut();
  if (outT == null){ toast("재생 헤드를 먼저 세워 주세요"); return; }
  const kind = sel.dataset.k, i = +sel.dataset.i, m = cur.model;
  if (kind === "sub"){
    const su = m.subs[i];
    if (outT <= su.start + 0.3){ toast("끝은 블록 시작보다 0.3초 이상 뒤여야 해요"); return; }
    snap(); su.end = +outT.toFixed(3); refresh("sub", i);
  } else if (kind === "tts" || kind === "txt"){
    const q = (kind === "tts" ? m.cues : m.textCues)[i];
    if (!q || q.dropped){ toast("이 블록은 완성본에 없어요"); return; }
    const d = outT - q.out;
    if (d < 0.3){ toast("재생 헤드가 블록 시작보다 0.3초 이상 뒤에 있어야 해요"); return; }
    snap(); (kind === "tts" ? m.tts : m.texts)[i].dur = +d.toFixed(3); refresh(kind, i);
  } else if (kind === "clip"){
    const c = m.clips[i], f = m.final.find(x => x.i === i);
    if (!f || f.dead){ toast("이 구간은 완성본에 없어요"); return; }
    const srcT = clipSrcAt(c, f.out, outT);
    if (srcT < c.start + 0.5){ toast("재생 헤드가 구간 시작보다 0.5초 이상 뒤에 있어야 해요"); return; }
    snap(); c.end = +srcT.toFixed(3); refresh("clip", i);
  } else toast("자막, 내레이션, 텍스트, 구간 블록에서 쓸 수 있어요");
};

window.startHere = () => {
  if (multiSel.idx.length){ multiTrim("start"); return; }
  const sel = document.querySelector("#inner .blk.sel");
  if (!sel){ toast("블록을 먼저 골라 주세요"); return; }
  const v = $("#vid"), outT = curOut();
  if (outT == null){ toast("재생 헤드를 먼저 세워 주세요"); return; }
  const kind = sel.dataset.k, i = +sel.dataset.i, m = cur.model;
  if (kind === "sub"){
    const su = m.subs[i];
    if (outT >= su.end - 0.3){ toast("시작은 블록 끝보다 0.3초 이상 앞이어야 해요"); return; }
    snap(); su.start = +outT.toFixed(3);
    if (su.follow){ const hit = outToSrc(su.start); if (hit) su.src = +hit.src.toFixed(3); }
    refresh("sub", i);
  } else if (kind === "tts" || kind === "txt"){
    const q = (kind === "tts" ? m.cues : m.textCues)[i];
    if (!q || q.dropped){ toast("이 블록은 완성본에 없어요"); return; }
    const endOut = q.out + q.dur;
    if (outT >= endOut - 0.3){ toast("시작은 블록 끝보다 0.3초 이상 앞이어야 해요"); return; }
    const hit = outToSrc(outT);
    if (!hit){ toast("재생 헤드가 구간 밖에 있어요"); return; }
    snap();
    const it = (kind === "tts" ? m.tts : m.texts)[i];
    it.src = +hit.src.toFixed(3);                  // 앵커를 헤드 지점으로
    it.dur = +(endOut - outT).toFixed(3);          // 끝은 그대로
    refresh(kind, i);
  } else if (kind === "clip"){
    const c = m.clips[i], f = m.final.find(x => x.i === i);
    if (!f || f.dead){ toast("이 구간은 완성본에 없어요"); return; }
    const srcT = clipSrcAt(c, f.out, outT);
    if (srcT > c.end - 0.5){ toast("시작은 구간 끝보다 0.5초 이상 앞이어야 해요"); return; }
    if (srcT < 0){ toast("원본 0초보다 앞으로는 갈 수 없어요"); return; }
    snap(); c.start = +srcT.toFixed(3); refresh("clip", i);
  } else toast("자막, 내레이션, 텍스트, 구간 블록에서 쓸 수 있어요");
};

// ⇧클릭 다중 선택(사용자 8/27) — 누른 블록을 하나씩 담고, 다시 누르면 뺀다.
// 구간·자막·내레이션·텍스트 모두. 이미 보통 클릭으로 골라둔 같은 종류가 있으면
// 그것부터 담고 시작한다. 이후 여기부터(Q)·여기까지(E)·삭제가 담긴 것들에 걸린다.
const MULTI_KINDS = ["clip", "sub", "tts", "txt"];
const MULTI_LABEL = { clip: "구간", sub: "자막", tts: "내레이션", txt: "텍스트" };
// 화면 순서 — 구간은 완성본 배열 순, 나머지는 인덱스 순(정렬은 표시·다듬기 순서용)
function multiOrder(kind){
  if (kind !== "clip") return null;
  return cur.model.final.filter(c => !c.dead).map(c => c.i);
}
function paintMulti(){
  document.querySelectorAll("#inner .blk.msel").forEach(b => b.classList.remove("msel"));
  if (!multiSel.kind) return;
  const cls = BLK_CLS[multiSel.kind];
  multiSel.idx.forEach(k => {
    const el = document.querySelector(`#inner .blk.${cls}[data-i="${k}"]`);
    if (el) el.classList.add("msel");
  });
}
window.paintMulti = paintMulti;
function multiToggle(kind, i){
  if (multiSel.kind !== kind) multiSel = { kind, idx: [] };   // 종류를 바꾸면 새로 시작
  const order = multiOrder(kind);
  if (order && order.indexOf(i) < 0) return;                  // 완성본에 없는 구간
  if (!multiSel.idx.length && curSel && curSel.kind === kind && curSel.i !== i
      && (!order || order.includes(curSel.i)))
    multiSel.idx = [curSel.i];
  const at = multiSel.idx.indexOf(i);
  if (at >= 0) multiSel.idx.splice(at, 1); else multiSel.idx.push(i);
  multiSel.idx.sort((a, b) => order ? order.indexOf(a) - order.indexOf(b) : a - b);
  if (!multiSel.idx.length) multiSel.kind = null;
  else curSel = { kind, i };
  document.querySelectorAll("#inner .blk.sel").forEach(b => b.classList.remove("sel"));
  paintMulti(); updTrashBtn();
  toast(multiSel.idx.length
    ? `${MULTI_LABEL[kind]} ${multiSel.idx.length}개를 골랐어요. ⇧클릭으로 더하거나 뺄 수 있어요`
    : "여러 개 고르기를 풀었어요");
}
window.multiToggle = multiToggle;

// 다중 다듬기 — 재생 헤드 기준으로 담긴 블록들을 한꺼번에.
// **구간**: 재생 길이를 맞추는 도구다 — 헤드 밖으로 완전히 나간 조각은 삭제,
//   헤드를 품은 조각은 트림, 나머지는 유지(범위 다듬기).
// **자막·내레이션·텍스트**: 끝(또는 시작)을 헤드에 **딱 맞추는** 도구다(사용자
//   8/27 — "특정 구간 끝까지 띄우다가 딱 맞게 끝내고 싶다"). 선택한 전부의
//   끝/시작을 헤드로 옮긴다 — 늘어나든 줄어들든. 헤드가 시작보다 앞이라 끝을
//   못 맞추는 줄만 건너뛰고 알린다. 삭제는 없다(삭제는 쓰레기통이 한다).
// 판정은 완성본 시각, 저장은 각 종류의 좌표계로 되돌려 쓴다.
function multiTrim(edge){
  const v = $("#vid"), outT = curOut();
  if (outT == null){ toast("재생 헤드를 먼저 세워 주세요"); return true; }
  const m = cur.model, kind = multiSel.kind;
  // 각 항목의 완성본 [시작, 끝] — 종류마다 출처가 다르다
  const spans = multiSel.idx.map(i => {
    if (kind === "clip"){ const f = m.final.find(x => x.i === i && !x.dead);
      return f && { i, a: f.out, b: f.out + clipDur(f), f }; }
    if (kind === "sub"){ const su = m.subs[i];
      return su && !su.del && { i, a: su.start, b: su.end }; }
    const q = (kind === "tts" ? m.cues : m.textCues)[i];
    return q && !q.dropped && { i, a: q.out, b: q.out + q.dur };
  }).filter(Boolean).sort((p, q) => p.a - q.a);
  if (!spans.length){ multiSel = { kind: null, idx: [] }; updTrashBtn(); return false; }
  const MIN = kind === "clip" ? 0.5 : 0.3;

  if (kind === "clip"){                       // ── 구간: 범위 다듬기(삭제+트림) ──
    if (outT <= spans[0].a + 0.01 || outT >= spans[spans.length - 1].b - 0.01){
      toast("재생 헤드를 고른 구간들 안쪽에 두어 주세요"); return true; }
    const del = [], trim = [];
    for (const sp of spans){
      if (edge === "start"){ if (sp.b <= outT + 0.001) del.push(sp);
        else if (sp.a < outT) trim.push(sp); }
      else { if (sp.a >= outT - 0.001) del.push(sp);
        else if (sp.b > outT) trim.push(sp); }
    }
    snap();
    if (del.length) setTimeout(() => undoToast(`구간 ${del.length}개를 지우고 ${trim.length}개를 잘랐어요`), 0);
    for (const sp of trim){
      const c = m.clips[sp.i], srcT = clipSrcAt(sp.f, sp.f.out, outT);
      if (edge === "start") c.start = +Math.max(0, Math.min(c.end - MIN, srcT)).toFixed(3);
      else c.end = +Math.max(c.start + MIN, srcT).toFixed(3);
    }
    multiDelete(del.map(sp => sp.i), kind, true);   // 인덱스 밀림은 저쪽이 처리
    multiSel = { kind: null, idx: [] }; curSel = null;
    refresh(); closeSide(); updTrashBtn();
    toast(`다듬었어요. ${del.length}개 지우고 ${trim.length}개 잘랐어요`);
    return true;
  }

  // ── 자막·내레이션·텍스트: 전부의 끝/시작을 헤드에 맞춘다 ──
  const can = sp => edge === "end" ? outT > sp.a + MIN : outT < sp.b - MIN;
  const fit = spans.filter(can), skip = spans.length - fit.length;
  if (!fit.length){
    toast(edge === "end" ? "재생 헤드가 고른 블록들보다 앞에 있어서 끝을 맞출 수 없어요"
                         : "재생 헤드가 고른 블록들보다 뒤에 있어서 시작을 맞출 수 없어요");
    return true;
  }
  snap();
  for (const sp of fit){
    if (kind === "sub"){
      const su = m.subs[sp.i];
      if (edge === "end") su.end = +outT.toFixed(3);
      else { su.start = +outT.toFixed(3);
        if (su.follow){ const hit = outToSrc(su.start); if (hit) su.src = +hit.src.toFixed(3); } }
    } else {                                  // 내레이션·텍스트 — 앵커(원본초)+길이
      const it = (kind === "tts" ? m.tts : m.texts)[sp.i];
      if (edge === "end") it.dur = +(outT - sp.a).toFixed(3);
      else { const hit = outToSrc(outT);
        if (hit){ it.src = +hit.src.toFixed(3); it.dur = +(sp.b - outT).toFixed(3); } }
    }
  }
  multiSel = { kind: null, idx: [] }; curSel = null;
  refresh(); closeSide(); updTrashBtn();
  toast(`${MULTI_LABEL[kind]} ${fit.length}개의 ${edge === "end" ? "끝" : "시작"}을 ` +
    `${fmt(outT)}에 맞췄어요` + (skip ? `. ${skip}개는 맞출 수 없어서 건너뛰었어요` : ""));
  return true;
}
// 여러 개 삭제 — 인덱스가 splice 로 밀리므로 **객체 참조**로 지운다.
// 자막만 예외: 소프트 삭제(del 표시)라 되살리기가 가능하다(전량 교체 규약).
function multiDelete(idx, kind, quiet){
  const m = cur.model;
  if (!idx.length) return 0;
  if (!quiet) snap();
  if (kind === "sub"){ idx.forEach(i => { if (m.subs[i]) m.subs[i].del = true; }); return idx.length; }
  const arr = kind === "clip" ? m.clips : kind === "tts" ? m.tts : m.texts;
  const gone = new Set(idx.map(i => arr[i]).filter(Boolean));
  const kept = arr.filter(x => !gone.has(x));
  if (kind === "clip") m.clips = kept; else if (kind === "tts") m.tts = kept; else m.texts = kept;
  return gone.size;
}

// 쓰레기통 — 지금 고른 것(⇧다중이면 전부)을 지운다. 자막은 소프트 삭제라 다시 살릴
// 수 있고(전량 교체 규약), 나머지는 목록에서 빠진다. 전부 ⌘Z 로 되돌아간다.
function updTrashBtn(){
  const b = document.getElementById("trashBtn"); if (!b) return;
  const n = multiSel.idx.length;
  const one = !n && curSel && MULTI_KINDS.includes(curSel.kind);
  b.disabled = !(n || one);
  b.title = n ? `${MULTI_LABEL[multiSel.kind]} ${n}개 삭제 (Delete)`
    : one ? `${MULTI_LABEL[curSel.kind]} 삭제 (Delete)`
          : "지울 블록을 먼저 골라 주세요";
}
window.updTrashBtn = updTrashBtn;
window.delSelected = () => {
  if (!editMode){ toast("편집 잠금을 먼저 풀어 주세요"); return; }
  if (!multiSel.idx.length && curSel && curSel.kind === "sfx" && window.__edSfx){
    window.__edSfx.del(curSel.i); curSel = null; return; }
  const kind = multiSel.idx.length ? multiSel.kind
    : (curSel && MULTI_KINDS.includes(curSel.kind) ? curSel.kind : null);
  if (!kind){ toast("지울 블록을 먼저 골라 주세요"); return; }
  const idx = multiSel.idx.length ? [...multiSel.idx] : [curSel.i];
  snap();
  const n = multiDelete(idx, kind, true);
  multiSel = { kind: null, idx: [] }; curSel = null;
  refresh(); closeSide(); updTrashBtn();
  undoToast(`${MULTI_LABEL[kind]} ${n}개를 지웠어요`);
};

window.splitSelClip = () => {
  const sel = document.querySelector("#inner .blk.c.sel");
  if (!sel){ toast("나눌 구간을 먼저 골라 주세요"); return; }
  splitClip(+sel.dataset.i);
};
window.splitClip = i => {
  const t = splitAt(i);
  if (t == null){ toast("재생 헤드를 구간 안쪽에 두고 나눠 주세요. 양끝에서 0.5초 이상 떨어져야 해요"); return; }
  snap();
  const cl = cur.model.clips, c = cl[i];
  cl.splice(i + 1, 0, { ...c, start: t, zoom: null });   // 줌은 앞 조각에만
  c.end = t; c.hold = 0;                      // 붙잡기는 끝 조각에만
  refresh("clip", i + 1);                     // 포커스는 뒤 조각
};

// 덮개 구간 1배속으로: 1배속·멈춤 없음이고 내레이션이 없으면 엔진이 원음을 다시 켠다(apply_edit narration_mute)
window.coverNormalSpeed = i => {
  const c = cur.model.clips[i]; if (!c) return;
  snap(); c.speed = 1; c.hold = 0; refresh("clip", i);
};
window.__edSelect = (k, i) => { if (cur && cur.model) select(k, i); };
window.__edCur = () => cur;
// 화면 위치 끌기(src/editor-frame.js) — 끌기 한 번 = ⌘Z 한 번: 시작에 snap, 끝에 refresh
window.__edOutNow = () => curOut();
window.__edSnap = () => snap();
window.__edRefresh = (kind, i, keep) => {      // keep: 재생 위치를 그대로 두고 다시 고른다(화면 위치는 보던 샷에서 바꾼다)
  if (!keep) return refresh(kind, i);
  markDirty(); runEngineRules(); draw(); if (kind) select(kind, i, null, true);
  if (window.__railOn && window.renderRailPanel) renderRailPanel(window.__railOn); };
window.__edTime = { curOut, srcToOut, outToSrc };   // src/editor-sfx.js — 재생 헤드 자리에 효과음 넣기
window.__edEditing = () => editMode;   // 진단용 — 검사 결과(cur.model.checks)를 밖에서 확인할 때만
window.__edToast = msg => toast(msg);
// 강조·줌 바꾸기 — 실행 취소에 쌓고 다시 그린다(미리보기 자막 모양도 바로)
window.__edMut = (fn, kind, i) => {
  if (!cur || !cur.model) return;
  snap(); fn(cur.model); refresh(kind, i); styleOvSub(curSubIdx); ovRepaint();
};
// 내레이션 길이를 잰 뒤 다시 그린다(편집 기록·실행 취소에는 넣지 않는다 — 사람이 고친 것이 아니다)
window.__edRedraw = () => {
  if (!cur || !cur.model) return;
  runEngineRules(); draw(); syncDirty();
  if (curSel) select(curSel.kind, curSel.i, null, true);
  if (window.__railOn && window.renderRailPanel) renderRailPanel(window.__railOn);
};
window.addClipFromSel = () => {
  if (!srcSel){ toast("원본 줄에서 ⇧를 누른 채 끌어서 범위를 먼저 골라 주세요"); return; }
  const [a, b] = [Math.min(srcSel.a, srcSel.b), Math.max(srcSel.a, srcSel.b)];
  if (b - a < 1){ toast("1초 이상 골라 주세요"); return; }
  snap(); cur.model.clips.push({ start: +a.toFixed(3), end: +b.toFixed(3), role: "build" });
  srcSel = null; $("#addClipBtn").disabled = true;
  refresh("clip", cur.model.clips.length - 1);
};
// 되돌리기 알림 — 지우기·한꺼번에 바꾸기는 묻지 않고 바로 하고, 화면 아래에 [되돌리기] 를 8초 띄운다(2026-09-29 사용자).
// 브라우저 확인창은 편집 흐름을 끊는다. 되돌리기는 ⌘Z 와 같다(바꾸기 전에 snap 해 둔 상태로).
function undoToast(msg){
  let el = document.getElementById("undoToast");
  if (!el){ el = document.createElement("div"); el.id = "undoToast"; el.setAttribute("role", "status"); document.body.append(el); }
  const hide = () => el.classList.remove("on");
  el.innerHTML = `<span>${esc(msg)}</span><button type="button">되돌리기</button>`;
  el.querySelector("button").onclick = () => { hide(); doUndo(); };
  // 8초 뒤 사라진다 — 마우스를 올려 두는 동안은 기다린다
  const arm = () => { clearTimeout(el._t); el._t = setTimeout(hide, 8000); };
  el.onmouseenter = () => clearTimeout(el._t); el.onmouseleave = arm;
  el.classList.add("on"); arm();
}
window.undoToast = undoToast;
// 알림 — 화면 아래 가운데 알약(되돌리기 알림과 같은 모양). 예전에는 저장 상태 한 줄 글자만 3.5초 바꿔서
// 제출이 거절돼도('같은 수정을 이미 제출했어요' 등) 못 보고 지나갔다(2026-09-30)
function toast(msg){
  let el = document.getElementById("edToast");
  if (!el){ el = document.createElement("div"); el.id = "edToast"; el.setAttribute("role", "status"); el.setAttribute("aria-live", "polite"); document.body.append(el); }
  el.textContent = msg; el.classList.add("on");
  clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("on"), 5000);
}

// ── 초안 저장 — 바뀐 섹션만, 기존 초안(디자인·이미지 등) 위에 얹어서 ──
// 바뀐 섹션만 모은다 — 안 보낸 키는 서버가 이전 라운드를 승계한다(0053).
// forDraft: 화면 상태(i0·del) 보존 / 제출: 삭제분은 목록에서 뺀다(전량 교체 규약).
function collectOv(forDraft){
  const m = cur.model, d = {};
  let n = 0;
  if (JSON.stringify(m.clips, edNoFx) !== cur.orig.clips){
    d.clips = m.clips.map(c => ({ role: c.role,
      start_sec: +c.start.toFixed(3), end_sec: +c.end.toFixed(3),
      ...(clipSpd(c) !== 1 ? { playback_speed: clipSpd(c) } : {}), ...(+c.hold ? { hold_sec: +c.hold } : {}),
        ...(c.frame_x != null ? { frame_x: +(+c.frame_x).toFixed(4) } : {}) })); n++; }
  // 렌더 값으로 되돌아왔으면 초안의 구간을 비운다 — 초안은 이전 초안 위에 덮어 저장해서, 안 비우면 옛 구간
  // (예: 되돌리기 전에 저장된 화면 위치)이 남아 다음에 열 때 되살아난다
  else if (forDraft && (cur.row.draft || {}).clips) d.clips = null;
  if (JSON.stringify(m.tts) !== cur.orig.tts){
    d.tts = m.tts.filter(t => String(t.text).trim()).map(t => ({
      text: String(t.text).trim(), source_time_sec: +t.src.toFixed(3),
      duration_sec: +t.dur.toFixed(3), voice: t.voice, speed: t.speed || "normal" })); n++; }
  else if (forDraft && (cur.row.draft || {}).tts) d.tts = null;
  // 제목 — 창(E8)이 있으면 top_title 과 **한 몸**으로 나간다. 승계가 title 키를 통째로
  // 교체하므로 창을 빼고 보내면 엔진이 checkpoint_style 의 AI 창을 다시 얹어, 고친 제목이
  // 조용히 무시된다(본 편집실 edCollect 와 같은 규약 · 2026-09-01 실사고).
  const segsNow = JSON.stringify(m.titleSegs || []);
  if (m.title !== cur.orig.title || segsNow !== (cur.orig.titleSegs || "[]")){
    d.title = { top_title: m.title };
    if ((m.titleSegs || []).length)
      d.title.segments = m.titleSegs.map(x => ({ text: x.text,
        start_sec: +(+x.start).toFixed(3), end_sec: +(+x.end).toFixed(3) }));
    n++; }
  else if (forDraft && (cur.row.draft || {}).title) d.title = null;
  if (cur.pendingDesign && Object.keys(cur.pendingDesign).length){
    d.design = { ...cur.pendingDesign }; n++; }
  if (JSON.stringify(m.subs, edNoFx) !== cur.orig.subs){
    d.subtitles = m.subs
      .filter(su => forDraft || !su.del)          // 제출: 뺀 줄 = 삭제(전량 교체)
      .map(su => { const o = { start_sec: +su.start.toFixed(3),
        end_sec: +su.end.toFixed(3), text: su.text };
      if (forDraft && su.i0 != null) o.i0 = su.i0;
      if (forDraft && su.del) o.del = true;
      // 장면 따라가기 켬 = 앵커 동봉(엔진이 최종 타임라인으로 재배치).
      // 끔 = 앵커 없이 → start_sec 그대로 박힌다(V3-b 계약).
      // 같은 장면이 여러 구간에 있는 줄(_amb)은 제출 때 원본 시각을 빼고 편집실이 고른 자리를 그대로 보낸다 — 엔진은 첫 구간에 붙인다.
      // 초안에는 남긴다(다시 열 때 '장면 따라가기'가 켜진 채로)
      if (su.src != null && su.follow && (forDraft || !su._amb)) o.source_time_sec = +(+su.src).toFixed(3);
      if (su.style && Object.keys(su.style).length) o.style = { ...su.style };
      return o; }); n++; }
  else if (forDraft && (cur.row.draft || {}).subtitles) d.subtitles = null;
  if (JSON.stringify(m.texts) !== cur.orig.texts){
    d.texts = m.texts.filter(t => String(t.text).trim()).map(t => ({
      ...(t._raw || {}), text: String(t.text).trim(),
      source_time_sec: +t.src.toFixed(3), duration_sec: +t.dur.toFixed(3) })); n++; }
  else if (forDraft && (cur.row.draft || {}).texts) d.texts = null;
  if (window.__edFx){ const fx = window.__edFx.collect(cur, forDraft); Object.assign(d, fx); n += Object.keys(fx).length; }
  if (window.__edSfx){ const sf = window.__edSfx.collect(cur, forDraft, edH(), !!d.clips);
    Object.assign(d, sf); if (sf.sfx) n++; }
  return { d, n };
}

window.__collectOv = collectOv;   // 진단용 — 무엇이 제출되는지 밖에서 확인할 때만
// 키 순서에 흔들리지 않는 비교 — 저장 여부 판정에만 쓴다
function canon(v){
  if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
  if (v && typeof v === "object")
    return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canon(v[k])).join(",") + "}";
  return JSON.stringify(v);
}
// '지금 [저장]을 누르면 초안이 달라지는가' = 저장 안 된 편집이 있는가.
function syncDirty(){
  try {
    const { d } = collectOv(true);
    const cu = cur.row.draft || {};
    dirty = canon({ ...cu, ...d }) !== canon(cu);
  } catch (e) { /* 판정 실패 시엔 보수적으로 그대로 둔다 */ }
  updSaveBtn(); paintSaveMsg();
}
window.syncDirty = syncDirty;

// 조용한 저장 — 확인창 없이. 자동 저장과 렌더 제출 직전이 함께 쓴다.
async function saveDraftQuiet(){
  if (!cur || !cur.model) return false;
  const { d: dNew } = collectOv(true);
  const merged = { ...(cur.row.draft || {}), ...dNew };
  if (canon(merged) === canon(cur.row.draft || {})) return false;   // 바뀐 게 없다
  const { error } = await sb.rpc("save_editor_draft",
    { p_run_id: cur.row.run_id, p_draft: merged });
  if (error){ $("#saveMsg").textContent = "저장하지 못했어요. " + error.message; return false; }
  cur.row.draft = merged; lastSavedAt = new Date(); dirty = false;
  updSaveBtn(); paintSaveMsg();
  return true;
}
window.saveDraftQuiet = saveDraftQuiet;

// 30초 주기. 저장이 겹치지 않게 진행 중이면 건너뛴다.
let autoTimer = 0, autoBusy = false;
function autoSaveStart(){
  if (autoTimer) return;
  autoTimer = setInterval(async () => {
    if (autoBusy || !dirty || !editMode || !cur || !cur.model || cur.sent) return;
    autoBusy = true;
    try { await saveDraftQuiet(); } catch (e) {} finally { autoBusy = false; }
  }, 30000);
}
function autoSaveStop(){ if (autoTimer){ clearInterval(autoTimer); autoTimer = 0; } }
window.autoSaveStart = autoSaveStart; window.autoSaveStop = autoSaveStop;

window.saveDraft = async () => {
  const { d: dNew, n } = collectOv(true);
  const d = { ...(cur.row.draft || {}), ...dNew };
  if (!n){ toast("바뀐 게 없어요"); return; }
  if (!confirm("지금 고친 내용을 저장할까요? 전에 저장한 내용은 이걸로 바뀌어요.")) return;
  const { error } = await sb.rpc("save_editor_draft",
    { p_run_id: cur.row.run_id, p_draft: d });
  if (error){ $("#saveMsg").textContent = "저장하지 못했어요. " + error.message; return; }
  cur.row.draft = d; dirty = false; lastSavedAt = new Date(); updSaveBtn(); paintSaveMsg();
};

// ── 제출 — 검사하고 확인 창을 띄운 뒤 작업 컴퓨터로 보낸다. 끝나면 온 곳으로 돌아간다.
window.submitRender = async () => {
  try {
    const check = await window.__workspaceEditorCheck();
    if (!check.canOpen) { toast(check.label); return; }
  } catch (e) { toast("영상 상태를 확인하지 못했어요. 다시 해 주세요."); return; }

  if (cur.sent){ toast("이미 제출했어요"); return; }
  const m = cur.model;
  // 구간 전량 삭제는 조용히 무시되는 함정 — 본 편집실과 같은 차단
  if (!m.clips.length){ toast("구간이 하나도 없어서 제출할 수 없어요"); return; }
  const { d: ov, n } = collectOv(false);
  if (!n){ toast("고친 내용이 없어요"); return; }
  // 작업 컴퓨터 영상: 수정 기록을 남기고 ai-video 가 다시 렌더한다(src/local-editor-client.js)
  if (window.__workspaceLocal){
    const names = Object.keys(ov).map(k => ({clips:"구간",tts:"내레이션",title:"제목",subtitles:"자막",texts:"텍스트·보조 자막",design:"디자인"}[k] || k)).join(" · ");
    const unsupported = [ov.images && "이미지", ov.title && (ov.title.segments || []).length && "제목 창"].filter(Boolean);
    if (unsupported.length){ toast(`${unsupported.join("·")} 수정은 아직 다시 렌더에 반영할 수 없어요. 되돌린 뒤 제출해 주세요`); return; }
    const pre = window.__edChecks ? await window.__edChecks.beforeSubmit(cur, edH(), ov) : null;
    if (pre){ runEngineRules(); draw(); }
    const ask = await window.__workspaceConfirmSubmit(Object.keys(ov), pre || {});   // src/editor-submit-dialog.js — 항목·결과·메모를 한 창에
    if (!ask) return;
    const note = ask.note;
    try { await saveDraftQuiet(); } catch (e) {}
    const r = await window.__workspaceLocal.submit(ov, note);
    if (r.error){ toast("제출하지 못했어요. " + r.error); return; }
    cur.sent = true; dirty = false; updSaveBtn();
    const btn = $("#renderBtn"); if (btn) btn.querySelector("span").textContent = "제출함";
    $("#saveMsg").textContent = "제출했어요. 목록으로 돌아가요";
    autoSaveStop();
    setTimeout(() => { location.href = window.__workspaceBack || "index.html#editor"; }, 600);   // 온 곳으로 돌아간다 — 작업 화면·편집실 목록 둘 다 렌더 진행을 보여 준다
    return;
  }
  toast("이 영상은 여기서 제출할 수 없어요");
};

  // ── 앱 레이아웃 셋업 — DOM 을 100vh 격자로 재배치(1회) ──
// 내레이션 목소리 — 본 편집실 ED_VOICES/ED_EL_VOICES_DEFAULT 와 같은 정본.
// ⚠ 목록을 두 곳에 두면 어긋난다 — 본 편집실이 바뀌면 여기도 바꿔야 한다.
const EL_PREFIX = "elevenlabs:";
const TTS_BASIC = [["ko_female","기본 여성"],["ko_female_high","밝은 여성"],
                   ["ko_male","기본 남성"],["ko_male_low","낮은 남성"]];
const TTS_EL_DEFAULT = [
  ["elevenlabs:JBFqnCBsd6RMkjVDRZzb", "내레이션 · 남 · 따뜻함 (George, 영국)"],
  ["elevenlabs:pFZP5JQG7iQjIQuC4Bku", "내레이션 · 여 · 따뜻함 (Lily, 영국)"],
  ["elevenlabs:XrExE9yKIg1WjnnlVkGX", "내레이션 · 여 · 친근함 (Matilda, 미국)"],
  ["elevenlabs:nPczCjzI2devNBz1zQrb", "내레이션 · 남 · 낮고 굵음 (Brian, 미국)"],
  ["elevenlabs:TX3LPaxmHKxFdv7VOQHJ", "내레이션 · 남 · 또렷함·젊음 (Liam, 미국)"],
  ["elevenlabs:pqHfZKP75CvOlQylNhV4", "내레이션 · 남 · 중후함 (Bill, 미국)"],
  ["elevenlabs:EXAVITQu4vr4xnSDxMaL", "뉴스 · 여 · 부드러움 (Sarah, 미국)"],
  ["elevenlabs:Xb7hH8MSUJpSbSDYk0k2", "뉴스 · 여 · 단단함 (Alice, 영국)"],
  ["elevenlabs:onwK4e9ZLuTAKqWW03F9", "뉴스 · 남 · 권위 (Daniel, 영국)"],
  ["elevenlabs:cgSgspJ2msm6clMCkdW9", "대화체 · 여 · 표현 풍부 (Jessica, 미국)"],
  ["elevenlabs:cjVigY5qzO86Huf0OWal", "대화체 · 남 · 친근함 (Eric, 미국)"],
  ["elevenlabs:iP95p4xoKVk53GoZ742B", "대화체 · 남 · 편안함 (Chris, 미국)"],
  ["elevenlabs:IKne3meq5aSn9XLyUdCD", "대화체 · 남 · 자연스러움 (Charlie, 호주)"],
  ["elevenlabs:9BWtsMINqrJLrRacOk9x", "쇼츠 · 여 · 표현 풍부 (Aria, 미국)"],
  ["elevenlabs:FGY2WhTYpPnrIDTdsKH5", "쇼츠 · 여 · 밝고 빠름 (Laura, 미국)"],
  ["elevenlabs:CwhRBWXzGAHq8TQ4Fs17", "쇼츠 · 남 · 자신감 (Roger, 미국)"],
  ["elevenlabs:bIHbv24MWmeRgasZH58o", "쇼츠 · 남 · 친근함·젊음 (Will, 미국)"],
  ["elevenlabs:SAz9YHcvj6GT2YYXdXww", "쇼츠 · 중성 · 담백함 (River, 미국)"],
  ["elevenlabs:N2lVS1w4EtoT3dr4eOWO", "캐릭터 · 남 · 강렬함 (Callum)"],
  ["elevenlabs:XB0fDUnXU5powFXDhCwa", "캐릭터 · 여 · 나른함 (Charlotte, 스웨덴)"],
];
// 예상 발화 길이(본 편집실 ED_TTS_CHARS_PER_SEC·SPEED_FACTOR 와 같은 값).
// 창보다 길면 엔진이 뜻을 지키며 줄여 재합성한다 — 그 예고를 보여준다.
const TTS_CHARS_PER_SEC = 5.5;
const SPEED_FACTOR = { very_slow: 0.75, slow: 0.9, normal: 1, fast: 1.1, very_fast: 1.25 };
const EL_SPEED_FACTOR = { very_slow: 0.7, slow: 0.85, normal: 1, fast: 1.1, very_fast: 1.2 };
const speedFactor = t =>
  (pvAble(t.voice) ? EL_SPEED_FACTOR : SPEED_FACTOR)[t.speed || "normal"] || 1;
const ttsEst = t => String(t.text || "").replace(/\s/g, "").length
  / TTS_CHARS_PER_SEC / speedFactor(t);
const TTS_SPEEDS = ["very_slow","slow","normal","fast","very_fast"];
let opsCfg = {};                       // ops_config 캐시(목록·게이트)
function elVoices(){                   // 운영자 목록이 있으면 그것이 이긴다
  try {
    const rows = JSON.parse(opsCfg.editor_tts_voices || "null");
    if (Array.isArray(rows) && rows.length){
      const ok = rows.filter(r => r && /^[A-Za-z0-9]{16,32}$/.test(String(r.id || "")))
                     .map(r => [EL_PREFIX + r.id, String(r.label || r.id)]);
      if (ok.length) return ok;
    }
  } catch (e) { /* 기본 목록으로 */ }
  return TTS_EL_DEFAULT;
}
const elVoicesOn = () => opsCfg.editor_tts_elevenlabs === "on";
const pvAble = v => String(v || "").startsWith(EL_PREFIX);   // 미리듣기는 EL 만
// 낯선 프리셋(chat_* 등 엔진 어휘)은 현재값을 그룹 밖 맨 위에 보존한다 —
// 편집실을 거쳤다고 사람이 안 고른 목소리로 바뀌면 안 된다.
function voiceSelHtml(curV, onchange){
  const groups = [["기본 목소리", TTS_BASIC]];
  if (elVoicesOn() || pvAble(curV)) groups.push(["일레븐랩스", elVoices()]);
  const known = groups.some(([, arr]) => arr.some(([v]) => v === curV));
  return `<select onchange="${onchange}">` +
    (known || !curV ? "" : `<option value="${esc(curV)}" selected>${esc(curV)} (현재값)</option>`) +
    groups.map(([g, arr]) => `<optgroup label="${esc(g)}">` + arr.map(([v, t]) =>
      `<option value="${esc(v)}" ${v === curV ? "selected" : ""}>${esc(t)}</option>`).join("") +
      `</optgroup>`).join("") + `</select>`;
}

// ── 미리듣기 — 본 편집실과 같은 엣지 함수(tts-preview). 한 번에 하나만 운다 ──
let pvAudio = null, pvGen = 0;
const pvCache = new Map();
// 미리보기 재생 중 내레이션 소리(2026-08-26) — 본 편집실 edSeqAudioSync 와 같은 규약:
// 하늘색 자막이 뜨는 그 순간 그 줄이 울린다. 줄 중간부터 들어왔으면 그만큼 건너뛴다.
let seqSnd = true, seqAudio = null, seqCue = -1, seqGen = 0;
window.seqSndToggle = () => {
  seqSnd = !seqSnd;
  if (!seqSnd) seqAudioStop(); else { seqWarm(); seqTickStart(); }
  const b = document.getElementById("sndBtn"); if (b) b.classList.toggle("on", seqSnd);
};
function seqAudioStop(){ ++seqGen; seqCue = -1;
  const vv = document.getElementById("vid"); if (vv && vv._narrMute){ vv._narrMute = false; vv.muted = false; }
  if (seqAudio){ seqAudio.pause(); seqAudio = null; } }
window.seqAudioStop = seqAudioStop;
// 그 줄의 소리 — 렌더가 만든 mp3(tts[].key)가 정본, 없고 EL 목소리면 미리듣기로 합성
const cueUrlCache = new Map();      // 키 → Promise<url> (동시 요청 합치기)
const cueAudCache = new Map();      // 키 → 미리 디코딩해 둔 Audio
const cueKey = t => `${t.stale ? "" : (t.key || "")}|${t.voice}|${t.speed || "normal"}|${t.text}`;
function cueUrl(t){
  const k = cueKey(t);
  if (cueUrlCache.has(k)) return cueUrlCache.get(k);
  const p = (async () => {
    let url = null;
    // 문구·목소리가 그대로면 렌더가 만든 mp3 가 정본이자 **가장 빠른 길**이다.
    if (t.key && !t.stale){
      const { data } = await sb.storage.from("ves-outputs").createSignedUrl(t.key, 1800);
      url = data && data.signedUrl;
    }
    if (!url && pvAble(t.voice) && String(t.text || "").trim()){
      const { data, error } = await sb.functions.invoke("tts-preview",
        { body: { text: spokenText(t.text), voice: t.voice, speed: t.speed || "normal" } });
      if (!error && data && data.audio){
        const bin = atob(data.audio), buf = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
        url = URL.createObjectURL(new Blob([buf], { type: data.mime || "audio/mpeg" }));
      }
    }
    return url;
  })();
  cueUrlCache.set(k, p);
  return p;
}
// 소리를 **미리 받아 디코딩까지** 해 둔다. 이게 없으면 그 줄에 닿는 순간
// 서명 URL 요청 → 다운로드 → 디코딩이 줄줄이 붙어 첫 마디가 잘린다.
async function cueAudio(t){
  const k = cueKey(t);
  if (cueAudCache.has(k)) return cueAudCache.get(k);
  const url = await cueUrl(t);
  if (!url) return null;
  const a = new Audio(); a.preload = "auto"; a.src = url;
  try { a.load(); } catch (e) {}
  cueAudCache.set(k, a);
  return a;
}
// 예열 — 타임라인 순서로 하나씩(동시에 쏘면 요금·레이트리밋만 튄다).
// 저장된 mp3 는 서명만 하면 되니 빠르고, 즉석 합성만 1~2초 걸린다.
let warmGen = 0, warmWarned = false;
async function seqWarm(){
  if (!seqSnd || !cur || !cur.model) return;
  const gen = ++warmGen;
  for (const q of (cur.model.cues || [])){
    if (gen !== warmGen || !seqSnd) return;
    const t = cur.model.tts[q.ti];
    if (q.dropped || !t) continue;
    try { await cueAudio(t); }
    catch (e){ if (!warmWarned){ warmWarned = true;
      toast("내레이션 소리를 불러오지 못했어요. " + (e.message || e), true); } }
  }
}
window.seqWarm = seqWarm;
window.__cueAudio = cueAudio;      // 진단용 — 예열 상태를 밖에서 확인할 때만 쓴다
window.__cueKey = cueKey;
window.__seqPeek = () => seqAudio;
function seqAudioSync(outT){
  if (!seqSnd || !cur || !cur.model) return;
  let idx = -1, pos = 0;
  (cur.model.cues || []).forEach((q, i) => {
    if (idx >= 0 || q.dropped) return;
    if (outT >= q.out && outT < q.out + q.dur){ idx = i; pos = outT - q.out; }
  });
  // 렌더와 같은 규칙 — 내레이션이 나오는 동안 원본 소리를 끈다(apply_edit narration_mute)
  const vv = document.getElementById("vid");
  if (vv){ const want = idx >= 0; if (want !== !!vv._narrMute){ vv._narrMute = want; vv.muted = want; } }
  if (idx === seqCue) return;
  seqCue = idx;
  if (seqAudio){ seqAudio.pause(); seqAudio = null; }
  const gen = ++seqGen;
  if (idx < 0) return;
  const t = cur.model.tts[cur.model.cues[idx].ti];
  const start = a => {
    if (!a || gen !== seqGen || !seqSnd) return;
    seqAudio = a;
    const go = () => { if (gen !== seqGen) return;
      // 줄 중간부터 들어왔으면(클릭 점프) 그만큼 건너뛴다 — 처음부터 틀면 자막과 어긋난다
      a.currentTime = pos > 0.2 && isFinite(a.duration)
        ? Math.min(pos, Math.max(0, a.duration - 0.05)) : 0;
      a.play().catch(() => {}); };
    if (a.readyState > 0) go(); else a.addEventListener("loadedmetadata", go, { once: true });
  };
  // 예열이 끝난 줄은 **기다리지 않고 그 자리에서** 운다 — 이게 지연의 핵심이었다.
  const k = cueKey(t);
  if (cueAudCache.has(k)) start(cueAudCache.get(k));
  else cueAudio(t).then(start).catch(() => {});
}

// 프레임 단위 소리 동기 — timeupdate(≈250ms)보다 15배 촘촘하다. 재생 중에만 돈다.
let seqRaf = 0;
function seqTick(){
  seqRaf = 0;
  const v = document.getElementById("vid");
  if (!v || !v.src || (v.paused && !(holding && holding.frozen == null))) return;   // 멈추면 루프도 멈춘다
  if (cur && cur.model){
    advance();
    if (holding && v.ontimeupdate) v.ontimeupdate();    // 붙잡기 중엔 timeupdate 가 없다 — 헤드를 직접 옮긴다
    const outT = curOut();
    if (outT != null) paintCues(outT);      // 소리와 글자를 한 프레임에 함께
  }
  seqRaf = requestAnimationFrame(seqTick);
}
function seqTickStart(){ if (!seqRaf) seqRaf = requestAnimationFrame(seqTick); }
window.seqTickStart = seqTickStart;

window.ttsStop = () => { pvGen++; if (pvAudio){ pvAudio.pause(); pvAudio = null; } };
window.ttsPreview = async (slot, btnId, text, voice, speed) => {
  if (pvAudio && pvAudio._slot === slot && !pvAudio.paused){ ttsStop(); return; }
  ttsStop();
  const txt = String(text || "").trim();
  if (!txt){ toast("문구가 비어 있어요"); return; }
  if (!pvAble(voice)){ toast("미리듣기는 일레븐랩스 목소리만 돼요. 기본 목소리는 다시 렌더한 뒤에 들을 수 있어요"); return; }
  const gen = ++pvGen, btn = btnId && document.getElementById(btnId);
  const label = btn && btn.textContent;
  if (btn) btn.textContent = "만드는 중…";
  try {
    const k = `${voice}|${speed || "normal"}|${txt}`;
    let url = pvCache.get(k);
    if (!url){
      const { data, error } = await sb.functions.invoke("tts-preview",
        { body: { text: spokenText(txt), voice, speed: speed || "normal" } });
      if (error){                       // 함수는 한국어로 이유를 말한다 — 본문을 꺼내 쓴다
        let msg = error.message || String(error);
        try { const j = await error.context.json(); if (j && j.error) msg = j.error; } catch (e) {}
        throw new Error(msg);
      }
      if (!data || !data.audio) throw new Error("소리를 만들지 못했어요");
      const bin = atob(data.audio), buf = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
      url = URL.createObjectURL(new Blob([buf], { type: data.mime || "audio/mpeg" }));
      if (data.truncated) toast(`문구가 길어서 앞 ${data.chars}자만 들려 드려요`);
      pvCache.set(k, url);
    }
    if (gen !== pvGen) return;
    $("#vid").pause(); seqAudioStop();  // 미리듣기와 영상·시퀀스 소리가 겹치면 안 된다
    pvAudio = new Audio(url); pvAudio._slot = slot;
    pvAudio.play().catch(() => toast("미리듣기를 재생할 수 없어요"));
  } catch (e){
    if (gen === pvGen) toast("미리듣기를 하지 못했어요. " + (e.message || e));
  } finally { if (btn) btn.textContent = label; }
};

// 아이콘 — 인라인 SVG(외부 의존 없음, currentColor 로 테마 따라감)
const I = {
  undo:'<svg viewBox="0 0 24 24"><path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-4"/></svg>',
  redo:'<svg viewBox="0 0 24 24"><path d="m15 14 5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h4"/></svg>',
  lock:'<svg viewBox="0 0 24 24"><path d="m14.5 3.5 6 6L9 21H3v-6z"/><path d="m12 6 6 6"/></svg>',
  bolt:'<svg viewBox="0 0 24 24"><path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12z"/></svg>',
  save:'<svg viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><path d="M17 21v-8H7v8M7 3v5h8"/></svg>',
  spark:'<svg viewBox="0 0 24 24"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/><circle cx="12" cy="12" r="2.5"/></svg>',
  cut:'<svg viewBox="0 0 24 24"><circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><path d="M8.2 7.6 20 19M8.2 16.4 20 5"/></svg>',
  starth:'<svg viewBox="0 0 24 24"><path d="M21 12H11M15 6l-6 6 6 6M4 4v16"/></svg>',
  endh:'<svg viewBox="0 0 24 24"><path d="M3 12h10M9 6l6 6-6 6M20 4v16"/></svg>',
  trash:'<svg viewBox="0 0 24 24"><path d="M4 7h16M10 4h4M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>',
  misc:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 8.9 19a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 5 8.9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9.6a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  snd:'<svg viewBox="0 0 24 24"><path d="M4 9v6h4l5 4V5L8 9z"/><path d="M17 8.5a5 5 0 0 1 0 7"/></svg>',
  zoom:'<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M8 11h6"/></svg>',
  // 해·달은 Workspace 사이드바(index.html theme-toggle)와 같은 그림
  sun:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></svg>',
  moon:'<svg viewBox="0 0 24 24"><path d="M20.5 14A9 9 0 0 1 10 3.5 9 9 0 1 0 20.5 14Z"/></svg>',
};
// 글자 기호(⬅︎ ⛶ ＋ − ▶ ⚠ ✂ ✕ ▸) 대신 쓰는 작은 선 아이콘 — 글자 옆에 붙는다(2026-09-29 Studio 디자인)
const EI = {
  back:'<svg class="ei" viewBox="0 0 24 24"><path d="M15 6l-6 6 6 6"/></svg>',
  max:'<svg class="ei" viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
  plus:'<svg class="ei" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  minus:'<svg class="ei" viewBox="0 0 24 24"><path d="M5 12h14"/></svg>',
  play:'<svg class="ei" viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z"/></svg>',
  alert:'<svg class="ei" viewBox="0 0 24 24"><path d="M12 4 2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2v.3"/></svg>',
  cut:'<svg class="ei" viewBox="0 0 24 24"><circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><path d="M8.2 7.6 20 19M8.2 16.4 20 5"/></svg>',
  x:'<svg class="ei" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  right:'<svg class="ei" viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>',
  down:'<svg class="ei" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
  up:'<svg class="ei" viewBox="0 0 24 24"><path d="M6 15l6-6 6 6"/></svg>',
};
window.EI = EI;
document.querySelectorAll("[data-ico]").forEach(el => { el.outerHTML = I[el.dataset.ico] || ""; });

// 테마 — Studio 는 다크 고정(2026-09-29, 영상 편집 프로그램처럼). Workspace 의 테마 저장값은 읽지도 쓰지도 않는다.
document.documentElement.dataset.theme = "dark";

(function setupLayout(){
  const header = tlRoot.querySelector("header");
  // ← 목록 — 대시보드에서 열려온 탭이면 그 탭을 앞으로 올리고 닫는다.
  // 직접 연 탭이면 대시보드로 이동(같은 오리진에 index.html 이 함께 배포된다).
  const back = document.createElement("button");
  back.id = "backBtn"; back.innerHTML = EI.back + "<span>목록</span>";
  back.title = "목록으로 돌아가기";
  back.onclick = () => window.tlClose();
  header.insertBefore(back, header.firstChild.nextSibling);   // 제목 바로 뒤
  const fs = document.createElement("button");
  fs.id = "fsBtn"; fs.innerHTML = EI.max; fs.title = "전체화면 (F)";
  fs.onclick = () => toggleFs();
  header.insertBefore(fs, $("#logout"));
  const top = tlRoot.querySelector(".top");
  // ── 좌측 레일(2026-08-24 v2) — 원본영상·제목·대사자막·텍스트·내레이션·로고.
  // 아이콘은 인라인 SVG(글자·이모지는 환경 따라 깨진다). 패널은 서랍처럼 열린다(width 트랜지션).
  const rail = document.createElement("div"); rail.id = "rail";
  const railPanel = document.createElement("div"); railPanel.id = "railPanel";
  top.insertBefore(railPanel, top.firstChild);
  top.insertBefore(rail, top.firstChild);
  const stash = document.createElement("div"); stash.style.display = "none";
  document.body.appendChild(stash);
  // 서랍 오른쪽 경계 — 잡아당겨 폭 조절(240~560px). 드래그 중엔 트랜지션을 끈다.
  const ddiv = document.createElement("div"); ddiv.id = "ddiv";
  top.insertBefore(ddiv, railPanel.nextSibling);
  ddiv.addEventListener("mousedown", e => {
    e.preventDefault();
    railPanel.classList.add("noanim");
    const panelL = railPanel.getBoundingClientRect().left;   // 패널 왼쪽 기준 — 레일 위치 가정 없음
    const mv = ev => { document.body.style.setProperty("--drawerw",
      Math.max(240, Math.min(560, ev.clientX - panelL)) + "px"); centerShorts(); };
    const up = () => { window.removeEventListener("mousemove", mv);
      window.removeEventListener("mouseup", up);
      railPanel.classList.remove("noanim");
      if (cur && cur.model) drawSrc(); };
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  });
  const ICONS = {
    src: `<svg viewBox="0 0 24 24"><rect x="3" y="6" width="18" height="13" rx="2"/>
      <path d="M3 10h18M7 6l2.2 4M12 6l2.2 4M17 6l2.2 4"/></svg>`,
    title: `<svg viewBox="0 0 24 24"><path d="M5 6h14M12 6v13M8.5 19h7"/></svg>`,
    subs: `<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/>
      <path d="M6.5 13h6M6.5 16h11M15.5 13h2"/></svg>`,
    txt: `<svg viewBox="0 0 24 24"><path d="M4 8V5h16v3M9 5v14M15 12v7M12 19h6M6 19h6"/></svg>`,
    sfx: `<svg viewBox="0 0 24 24"><path d="M4 10v4h3l5 4V6L7 10z"/><path d="M16 9.5a3.5 3.5 0 0 1 0 5M18.5 7a7 7 0 0 1 0 10"/></svg>`,
    tts: `<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/>
      <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/></svg>`,
    misc: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/>
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M18.7 5.3l-2.1 2.1M7.4 16.6l-2.1 2.1"/></svg>`,
    logo: `<svg viewBox="0 0 24 24"><circle cx="12" cy="10" r="6"/>
      <path d="M8.8 15.2 7 21l5-2.6L17 21l-1.8-5.8M12 7.5l.9 1.8 2 .3-1.45 1.4.35 2-1.8-.95-1.8.95.35-2L9.1 9.6l2-.3z"/></svg>`,
  };
  const railTabs = [["src", "원본"], ["title", "제목"], ["subs", "자막"],
                    ["txt", "텍스트"], ["tts", "내레이션"], ["sfx", "효과음"], ["logo", "로고"], ["misc", "기타"]];
  window.__railOn = null;
  railTabs.forEach(([k, label]) => {
    const b = document.createElement("button");
    b.innerHTML = ICONS[k] + "<span>" + label + "</span>"; b.dataset.k = k;
    b.onclick = () => {
      window.__railOn = window.__railOn === k ? null : k;
      rail.querySelectorAll("button").forEach(x =>
        x.classList.toggle("on", x.dataset.k === window.__railOn));
      railPanel.classList.toggle("on", !!window.__railOn);
      renderRailPanel(window.__railOn);
      toggleSrcStrip(window.__railOn === "src");   // 원본 탭 = 스트립 펼침, 그 외 접힘
      centerShorts();                              // 서랍이 떠 있으므로 바로 자리를 잡는다(트랜지션을 기다리지 않는다)
      setTimeout(() => { if (cur && cur.model) drawSrc(); centerShorts(); }, 240);
    };
    rail.appendChild(b);
  });
  // 원본 플레이어는 서랍 밖에서는 숨김 보관 — "항상 띄우지 않는다"(사용자 8/24)
  const stashSrc = () => { const sp = $("#srcPane"); if (sp && sp.parentElement !== stash) stash.appendChild(sp); };
  // ── 디자인 입력 위젯 (본 편집실 ED_STYLE_FIELDS 와 같은 키·같은 계약) ──
  const FONTS = [["", "채널 기본"],
    ["여기어때 잘난체 2 TTF", "여기어때 잘난체"],
    ["여기어때 잘난체 고딕 TTF", "여기어때 잘난체 고딕"],
    ["물마루", "물마루"], ["그리운 경찰공평체", "그리운 경찰공평체"]];
  const ph = k => { const b = dsBase(k); return b != null && b !== "" ? "지금: " + b : ""; };
  const dnum = (k, label, hint) => `<label class="dfld"><span>${label}</span>
    <input value="${esc(dsGet(k) ?? "")}" placeholder="${esc(ph(k) || hint || "")}"
      onchange="dsSet('${k}',this.value)"></label>`;
  // 크기 칸 — 직접 입력 + −/＋ 클릭(빈 칸이면 base 에서 출발)
  // 위치·폭은 숫자를 적지 않고 버튼으로 — 누를 때마다 미리보기에서 바로 보인다(2026-09-29 사용자). 지금 자리에서 출발한다.
  const own = k => { const v = dsGet(k); return v != null && v !== ""; };
  const dmove = (k, label) => `<label class="dfld"><span>${label}</span><span class="steprow mv">
    <button type="button" onclick="nudgeD('${k}',-1)" aria-label="위로" title="위로">${EI.up}</button>
    <button type="button" onclick="nudgeD('${k}',1)" aria-label="아래로" title="아래로">${EI.down}</button>
    <em class="mvv">${own(k) ? "직접 정함" : "자동"}</em>
    ${own(k) ? `<button type="button" class="lnk" onclick="dsSet('${k}','')">자동으로</button>` : ""}</span></label>`;
  const dwide = (k, label, show) => `<label class="dfld"><span>${label}</span><span class="steprow mv">
    <button type="button" onclick="nudgeD('${k}',-1)" aria-label="좁게">${EI.minus}</button>
    <em class="mvv">${show}</em>
    <button type="button" onclick="nudgeD('${k}',1)" aria-label="넓게">${EI.plus}</button>
    ${own(k) ? `<button type="button" class="lnk" onclick="dsSet('${k}','')">기본으로</button>` : ""}</span></label>`;
  const dstep = (k, label, hint, base) => `<label class="dfld"><span>${label}</span>
    <span class="steprow"><button type="button" onclick="stepFld(this,-2,${base})" aria-label="작게">${EI.minus}</button>
    <input value="${esc(dsGet(k) ?? "")}" placeholder="${esc(ph(k) || hint || "")}"
      onchange="dsSet('${k}',this.value)">
    <button type="button" onclick="stepFld(this,2,${base})" aria-label="크게">${EI.plus}</button></span></label>`;
  const dsel = (k, label, opts) => `<label class="dfld"><span>${label}</span>
    <select onchange="dsSet('${k}',this.value)">${opts.map(([v, t]) =>
      `<option value="${v}" ${String(dsGet(k) ?? "") === v ? "selected" : ""}>${esc(t)}</option>`).join("")}
    </select></label>`;
  const dcol = (k, label) => { const v = dsGet(k) ?? "";
    // 미지정 자막 색은 흰색이 아니라 **엔진 프리셋 색**이다 — 견본도 안내도 그렇게
    // 보여야 한다(8/27 락커룸: 화면 흰색·렌더 노랑).
    const fallback = "#ffffff";
    return `<label class="dfld"><span>${label}</span><span class="colrow">
      <input type="color" value="${/^#[0-9a-f]{6}$/i.test(v) ? v : (/^#[0-9a-f]{6}$/i.test(dsBase(k) || "") ? dsBase(k) : fallback)}"
        onchange="dsSet('${k}',this.value)">
      <input class="hex" value="${esc(v)}" placeholder="${esc(ph(k) || fallback)}"
        onchange="dsSet('${k}',this.value)"></span></label>`; };

  // 제목 배경 — 네모 버튼을 누를 때마다 없음 → 둥근네모 → 각진네모 → 없음. 바로 옆에서 색을 고른다.
  const BOX_NEXT = { "": "round", none: "round", round: "rect", rect: "none" };
  const BOX_NAME = { "": "없음", none: "없음", round: "둥근네모", rect: "각진네모" };
  const dbox = (k, ck) => { const v = String(dsGet(k) ?? dsBase(k) ?? ""), kind = BOX_NAME[v] ? v : "";
    const col = String(dsGet(ck) ?? dsBase(ck) ?? "") || "#000000";
    return `<label class="dfld"><span>배경</span><span class="boxrow">
      <button type="button" class="boxcyc ${kind === "round" || kind === "rect" ? kind : "none"}" onclick="dsSet('${k}','${BOX_NEXT[kind]}')"
        title="${BOX_NAME[kind]} (누르면 ${BOX_NAME[BOX_NEXT[kind]]})" aria-label="제목 배경 ${BOX_NAME[kind]}"><i style="--boxc:${esc(col)}"></i></button>
      <input type="color" value="${/^#[0-9a-f]{6}$/i.test(col) ? col : "#000000"}" onchange="dsSet('${ck}',this.value)"
        title="배경색" aria-label="제목 배경색"></span></label>`; };
  // 구역 제목 옆에 그 줄의 문구를 옅게 — 어느 줄을 고치는지 바로 보이게
  const tline = (m, i) => { const t = String((m && m.title) || "").split("\n")[i]; return t ? ` <em>${esc(t)}</em>` : ""; };
  window.titleTabHtml = m => `
    <div class="dgrp"><b>공통</b>
      ${dsel("title_font", "폰트", FONTS)}
      ${dmove("title_y", "세로 위치")}
    </div>
    <div class="dgrp"><b>1줄${tline(m, 0)}</b>
      ${dstep("title_size", "크기", "예: 70", +dsBase("title_size") || 70)}
      ${dcol("title_color", "색")}
      ${dbox("title_box", "title_box_color")}
    </div>
    <div class="dgrp"><b>2줄${tline(m, 1)}</b>
      ${dstep("title_size2", "크기", "비우면 1줄 × 90/70", Math.round(+dsBase("title_size2") || (+dsGet("title_size") || +dsBase("title_size") || 70) * 90 / 70))}
      ${dcol("title_color2", "색")}
      ${dbox("title_box2", "title_box_color2")}
    </div>
    <div class="small faint">비운 칸은 지금 값 그대로예요. 이 영상에만 적용돼요.</div>`;

  window.openRail = k => {
    if (window.__railOn !== k){
      const b = rail.querySelector(`button[data-k="${k}"]`);
      if (b) b.click();
    }
  };
  window.renderRailPanel = k => {
    stashSrc();   // innerHTML 재구성 전에 항상 대피 — 안 하면 플레이어가 파괴된다
    if (!k){ railPanel.innerHTML = ""; return; }
    const m = cur && cur.model;
    const need = !m ? '<span class="small faint">영상을 먼저 열어 주세요.</span>' : "";
    const list = (arr, kind, rowFn, addBtn) => `<div class="drawList">` +
      (arr.length ? arr.map(rowFn).join("") : '<span class="small faint">아직 없어요.</span>') +
      `</div>` + (addBtn || "") +
      `<div class="small faint">항목을 누르면 타임라인에서 골라지고 미리보기가 그 자리로 가요.
       고치거나 지우는 건 오른쪽 칸에서 해요. 편집 잠금을 풀어야 해요.</div>`;
    if (k === "src"){
      railPanel.innerHTML = `<h3>원본 영상</h3><div id="srcSlot"></div>
        <div class="markrow">
          <button onclick="markIn()" title="지금 위치를 시작으로 (I)">[ 시작</button>
          <button onclick="markOut()" title="지금 위치를 끝으로 (O)">끝 ]</button>
          <button class="mkadd" onclick="addClipFromMarks()"
            title="찍은 범위를 새 구간으로 (Enter)">${EI.plus}구간 추가</button>
        </div>
        <div class="small" id="markInfo"></div>
        <div class="small faint">원본 영상을 원하는 곳에 세우고 [ 시작과 끝 ] 으로 범위를 찍은 뒤
          구간 추가를 눌러요. 아래 원본 줄에서 ⇧를 누른 채 끌어서 골라도 돼요.</div>`;
      const sp = $("#srcPane");
      document.getElementById("srcSlot").appendChild(sp);
      markInfo();
    } else if (k === "title"){
      railPanel.innerHTML = `<h3>제목</h3>` + (need || titleTabHtml(m));
    } else if (k === "subs"){
      if (!m){ railPanel.innerHTML = `<h3>대사 자막</h3>` + need; return; }
      const live = m.subs.filter(su => !su.del).length;
      const nCk = subCk.size, allCk = nCk && nCk === m.subs.length;
      railPanel.innerHTML = `<h3>대사 자막 <span class="faint">${live}/${m.subs.length}</span></h3>
        <div class="dgrp"><b>공통 스타일</b>
          ${dsel("subtitle_font", "폰트", [["", "기본 (Noto Sans CJK KR Black)"], ...FONTS.slice(1)])}
          ${dstep("subtitle_size", "기본 크기", "예: 62", +dsBase("subtitle_size") || 62)}
          ${dcol("subtitle_color", "기본 색")}
          ${dsGet("subtitle_font") || dsBase("subtitle_font")
            ? `<div class="small faint">기본이 아닌 폰트는 같은 크기 숫자에서 글자가 더 작게 나와요.</div>` : ""}
        </div>
        <div class="listhead">
          <label class="ckall"><input type="checkbox" ${allCk ? "checked" : ""}
            onchange="subCkAll(this.checked)"> 전체</label>
          <span class="grow"></span>
          ${nCk ? `<button class="lnk danger" onclick="delSubChecked()">선택 ${nCk}줄 삭제</button>` : ""}
        </div>
        <div class="drawList">${m.subs.length ? m.subs.map((su, i) => [su, i])
          .sort((a, b) => a[0].start - b[0].start || a[1] - b[1])   // 목록은 완성본 시각 순 — 옮긴 줄이 제자리에 보이게(번호 i 는 그대로)
          .map(([su, i]) => {
          const st = su.style || {};
          const badge = st.color ? "색" : "";
          const pinB = su.follow ? "" : '<em class="stbadge pinb" title="구간을 옮겨도 이 자리에 그대로 있어요">📌</em>';
          return `<div class="tplItem${su.del ? " dead" : ""}${subCk.has(i) ? " ck" : ""}">
            <input type="checkbox" ${subCk.has(i) ? "checked" : ""}
              onclick="event.stopPropagation()" onchange="subCkToggle(${i},this.checked)">
            <span class="tc" onclick="select('sub',${i})">${fmt(su.start)}</span>
            <span class="tx" onclick="select('sub',${i})">${esc(su.text)}</span>
            ${pinB}${badge ? `<em class="stbadge" title="이 줄만 색을 바꿨어요">${esc(badge)}</em>` : ""}
          </div>`; }).join("") : '<span class="small faint">아직 없어요.</span>'}</div>
        <button onclick="addSubAt()">${EI.plus}자막 추가 (재생 헤드 자리)</button>
        <button class="lnk danger" style="text-align:left" onclick="subsClearAll()">
          자막 없이 내보내기 (모두 지우기)</button>
        <div class="small faint">항목을 누르면 타임라인에서 골라지고 미리보기가 그 자리로 가요.</div>`;
    } else if (k === "txt"){
      railPanel.innerHTML = `<h3>텍스트 <span class="faint">${m ? m.texts.length : 0}</span></h3>`
        + (need || list(m.texts, "txt", (t, i) =>
            `<div class="tplItem" onclick="select('txt',${i})">
             <span class="tc">${fmt(t.src)}</span><span class="tx">${esc(t.text)}</span></div>`,
          `<button onclick="addTxtAt()">${EI.plus}텍스트 추가 (원본 재생 자리)</button>`));
    } else if (k === "tts"){
      if (!m){ railPanel.innerHTML = `<h3>내레이션</h3>` + need; return; }
      // '이 편 공통' 목소리는 이 영상의 내레이션 목소리로 시작한다(편을 열 때 한 번) — 기본 여성으로 보이면 다른 목소리로 만든 것처럼 오해한다
      if (window.ttsBulkRun !== cur.row.run_id){ window.ttsBulkRun = cur.row.run_id;
        ttsBulkVoice = (m.tts.find(t => t.voice) || {}).voice || "ko_female"; }
      const nCk = ttsCk.size, allCk = nCk && nCk === m.tts.length;
      railPanel.innerHTML = `<h3>내레이션 <span class="faint">${m.tts.length}</span></h3>
        <div class="dgrp"><b>모든 줄 공통</b>
          <label class="dfld"><span>기본 목소리</span>
            ${voiceSelHtml(ttsBulkVoice, "ttsBulkVoice=this.value")}</label>
          <div class="ebtns">
            <button onclick="applyVoiceAll()">${nCk ? `선택 ${nCk}줄` : "전체"}에 적용</button>
            <button id="pvBulk" onclick="previewBulkVoice()">${EI.play}이 목소리 들어보기</button>
          </div>
          ${dstep("tts_size", "자막 크기", "예: 70", +dsBase("tts_size") || 70)}
          ${dcol("tts_color", "자막 색")}
          ${dmove("tts_y_margin", "세로 위치")}
          ${dwide("tts_width", "글자 폭", Math.round((+dsGet("tts_width") || +dsBase("tts_width") || 0.852) * 100) + "%")}
        </div>
        <div class="listhead">
          <label class="ckall"><input type="checkbox" ${allCk ? "checked" : ""}
            onchange="ttsCkAll(this.checked)"> 전체</label>
          <span class="grow"></span>
          ${nCk ? `<button class="lnk danger" onclick="delTtsChecked()">선택 ${nCk}줄 삭제</button>` : ""}
        </div>
        <div class="drawList">${m.tts.length ? m.tts.map((t, i) => {
          const q = (m.cues || [])[i];
          const warn = q && (q.snapped || q.multi);
          return `<div class="tplItem${ttsCk.has(i) ? " ck" : ""}">
            <input type="checkbox" ${ttsCk.has(i) ? "checked" : ""}
              onclick="event.stopPropagation()" onchange="ttsCkToggle(${i},this.checked)">
            <span class="tc" onclick="select('tts',${i})">${fmt(t.src)}</span>
            <span class="tx" onclick="select('tts',${i})">${esc(t.text)}</span>
            ${warn ? '<em class="stbadge warnb" title="자리 확인이 필요해요">${EI.alert}</em>' : ""}
            ${pvAble(t.voice) ? `<button class="pvb" id="pvrow${i}"
              title="들어보기" onclick="event.stopPropagation();ttsPreview('row${i}','pvrow${i}',
                ${JSON.stringify(t.text)},${JSON.stringify(t.voice)},${JSON.stringify(t.speed || "normal")})" aria-label="들어보기">${EI.play}</button>` : ""}
          </div>`; }).join("") : '<span class="small faint">아직 없어요.</span>'}</div>
        <button onclick="addTtsAt()">${EI.plus}내레이션 추가 (원본 재생 자리)</button>
        <div class="small faint">미리듣기는 일레븐랩스 목소리만 돼요. 기본 목소리는 다시 렌더한 뒤에 들을 수 있어요.
          ${elVoicesOn() ? "" : "일레븐랩스가 꺼져 있어서 새로 고를 수 없어요. 지금 목소리는 그대로 둬요."}</div>`;
    } else if (k === "sfx"){
      railPanel.innerHTML = need ? `<h3>효과음</h3>` + need : (window.__edSfx ? window.__edSfx.railHtml(cur, editMode) : "");
    } else if (k === "misc"){
      if (!m){ railPanel.innerHTML = `<h3>기타</h3>` + need; return; }
      const chd = cur.chDesign || {};
      railPanel.innerHTML = `<h3>기타</h3>
        <div class="dgrp"><b>영상 자리</b>
          ${dnum("aspect_ratio", "화면비", "비우면 1:1, 예: 16:9")}
          ${dmove("video_y", "영상 세로 위치")}
          ${dwide("video_width", "영상 가로", Math.round((+dsGet("video_width") || (window.__lay || {}).vw || 1080) / 1080 * 100) + "%")}
          ${dnum("video_speed", "영상 배속", "0.8~2.0, 예: 1.25")}
          ${dsel("face_tracking", "얼굴 추종", [["", "채널 기본"],
            ["true", "켬 (인물 확대)"], ["false", "끔 (화면 전체)"]])}
          ${dsel("subtitles", "대사 자막", [["", "채널 기본"],
            ["false", "끔 (이 영상은 자막 없이)"]])}
        </div>
        <div class="small faint">이 영상에만 적용돼요.</div>`;
    } else if (k === "logo"){
      railPanel.innerHTML = `<h3>로고</h3>` + (need || logoTabHtml());
    }
  };
  // ── 로고 탭 — 작품 관리에 올린 이 작품의 로고를 그림으로 보고 고른다. 자리·크기는 미리보기에서 끌어서 ──
  const effD = () => ({ ...(cur.chDesign || {}), ...((cur.row.draft || {}).design || {}), ...(cur.pendingDesign || {}) });
  const LOGO_BOX = { work_logo: [620, 300], platform_logo: [180, 80] };
  window.__logoUp = null;
  const logoTile = (l, on, pick) => `<button type="button" class="lgTile${on ? " on" : ""}" onclick="${pick}" title="${esc(l.filename || l.label)}">
      <span class="lgImg">${l.url ? `<img alt="" src="${esc(l.url)}">` : `<i>${esc(l.ph || "")}</i>`}</span>
      <span class="lgName">${esc(l.label)}${l.is_default && l.label !== "기본" ? ' <em>기본</em>' : ""}</span></button>`;
  const upForm = role => { const u = window.__logoUp;
    if (!u || u.role !== role) return "";
    return `<div class="lgUp"><span class="small">${esc(u.file.name)}</span>
      <label class="dfld"><span>로고 이름</span><input id="lgUpName" value="${esc(u.label)}" maxlength="30"
        oninput="__logoUp.label=this.value" placeholder="예: 노랑 가로"></label>
      <div class="ebtns"><button onclick="logoUploadGo()" ${u.busy ? "disabled" : ""}>${u.busy ? "올리는 중…" : "올리기"}</button>
        <button class="lnk" onclick="__logoUp=null;renderRailPanel('logo')">취소</button></div></div>`; };
  const upBtn = (r, role) => r.can_upload && r.work ? `<button class="lnk" onclick="logoUploadPick('${role}')">${EI.plus}새 로고 올리기</button>` : "";
  // 접고 펴는 구역 — 탭을 다시 그려도(로고를 고를 때마다) 접은 상태를 기억한다
  window.__lgOpen = { work: true, cap: true, plat: true };
  const lgSec = (k, title, body) => `<details class="dgrp lgSec" ${window.__lgOpen[k] ? "open" : ""}
      ontoggle="__lgOpen['${k}']=this.open"><summary>${title}</summary>${body}</details>`;
  window.logoTabHtml = () => {
    const r = window.__edLogoList, d = effD(), logos = window.__edLogos || {};
    if (!r) return `<div class="small faint">로고를 불러오는 중이에요.</div>`;
    if (r.error) return `<div class="small faint">로고를 불러오지 못했어요. ${esc(r.error)}</div>
      <button class="lnk" onclick="__edLogoList=null;renderRailPanel('logo');__edLoadLogos()">다시 불러오기</button>`;
    // 맥미니 영상도 된다 — 로고는 id 로 보내고 맥미니 엔진이 작품 관리에서 받는다(mm-01~06 d6490e3 이후 확인, 2026-09-29)
    const isImg = d.work_type === "image";
    const wl = r.work_logos || [], pl = r.platform_logos || [];
    // 고른 로고 = 같은 파일이거나, 렌더 값 그대로인데 그 로고와 같은 그림(서버 same_as_render — 해상도만 다른 같은 로고)
    const base = cur.chDesign || {};
    const isSel = (l, k) => l.path === d[k] || (d[k] === base[k] && l.same_as_render);
    const wKnown = wl.some(l => isSel(l, "work_value"));
    let work = logoTile({ label: "글자", ph: window.__edWorkName || "작품명" }, !isImg, "pickWorkLogo(-1)")
      + wl.map((l, i) => logoTile(l, isImg && isSel(l, "work_value"), `pickWorkLogo(${i})`)).join("");
    if (isImg && !wKnown) work = logoTile({ label: "지금 로고", url: logos.work, ph: "그림 없음" }, true, "") + work;
    const pKnown = pl.some(l => isSel(l, "platform_image"));
    let plat = pl.map((l, i) => logoTile(l, !!d.platform_image && isSel(l, "platform_image"), `pickPlatLogo(${i})`)).join("");
    if (d.platform_image && !pKnown) plat = logoTile({ label: "지금 로고", url: logos.platform, ph: "그림 없음" }, true, "") + plat;
    const right = (d.platform_align || "left") === "right";
    return lgSec("work", "작품 로고", `
        ${r.work ? "" : `<div class="small faint">「${esc(r.work_title || "")}」 작품을 작품 관리에서 찾지 못했어요.</div>`}
        <div class="lgGrid">${work}</div>${upBtn(r, "work_logo")}${upForm("work_logo")}
        ${isImg ? "" : `${dnum("work_value", "문구", window.__edWorkName || "작품명")}${dcol("work_color", "글자 색")}`}`)
      + lgSec("cap", "하단 문구", `
        ${dnum("work_caption", "문구", "비우면 없음")}
        ${d.work_caption ? dcol("work_caption_color", "글자 색") : ""}`)
      + lgSec("plat", "플랫폼 로고", `
        <div class="lgGrid">${plat || '<span class="small faint">올린 로고가 없어요.</span>'}</div>${upBtn(r, "platform_logo")}${upForm("platform_logo")}
        ${d.platform_image ? `<label class="dfld"><span>자리</span><span class="seg">
          <button type="button" class="${right ? "" : "on"}" onclick="dsSet('platform_align','left')">왼쪽 위</button>
          <button type="button" class="${right ? "on" : ""}" onclick="dsSet('platform_align','right')">오른쪽 위</button></span></label>` : ""}`)
      + `
      <div class="small faint">자리와 크기는 가운데 화면에서 로고를 끌어서 바꿔요. 모서리 점을 끌면 크기가 바뀌어요.
        로고는 작품 관리에 올린 것이고, 고른 로고는 이 영상에만 들어가요.</div>`;
  };
  const setMany = obj => { const dd = edDesign();
    Object.entries(obj).forEach(([k, v]) => { if (v === null) delete dd[k]; else dd[k] = v; });
    markDirty(); layoutShorts(); renderRailPanel("logo"); };
  // 렌더에는 에셋 id(work_asset_id·platform_asset_id = work_asset_versions.id)를 보낸다 — 엔진이 작품 관리에서 받아
  // 해시를 확인하고 경로를 채운다(ai-video d6490e36, 작업 컴퓨터·맥미니 공통, id 가 경로보다 우선).
  // 경로(work_value·platform_image)는 미리보기 그림을 찾는 데만 쓴다.
  window.pickWorkLogo = i => {
    if (i < 0){ setMany({ work_type: "text", work_asset_id: null,
      work_value: effD().work_type === "text" ? effD().work_value || window.__edWorkName : window.__edWorkName }); return; }
    const l = window.__edLogoList.work_logos[i]; if (!l) return;
    setMany({ work_type: "image", work_asset_id: l.id, work_value: l.path, work_image_width: l.box[0], work_image_height: l.box[1] });
  };
  window.pickPlatLogo = i => {
    const l = window.__edLogoList.platform_logos[i]; if (!l) return;
    setMany({ platform_asset_id: l.id, platform_image: l.path, platform_image_width: l.box[0], platform_image_height: l.box[1] });
  };
  window.logoUploadPick = role => {
    const f = document.createElement("input"); f.type = "file"; f.accept = "image/png,image/jpeg,image/webp";
    f.onchange = () => { const file = f.files[0]; if (!file) return;
      window.__logoUp = { role, file, label: file.name.replace(/\.[^.]+$/, "").slice(0, 30) };
      renderRailPanel("logo"); const n = document.getElementById("lgUpName"); if (n) n.select(); };
    f.click();
  };
  window.logoUploadGo = async () => {
    const u = window.__logoUp, r = window.__edLogoList; if (!u || u.busy) return;
    const label = String(u.label || "").trim(); if (!label){ toast("로고 이름을 적어 주세요"); return; }
    u.busy = true; renderRailPanel("logo");
    try {
      await window.__workspaceLocal.uploadLogo(r.work.id, u.role, u.file, label, LOGO_BOX[u.role]);
      window.__logoUp = null; toast("로고를 올렸어요");
      await window.__edLoadLogos();
    } catch (e){ u.busy = false; toast(e.message); renderRailPanel("logo"); }
  };
  window.loadTemplates = async () => {
    const box = document.getElementById("tplList"); if (!box) return;
    const [tpl, chd] = await Promise.all([
      sb.from("editor_templates").select("name,design,updated_at").order("updated_at", { ascending: false }),
      cur && cur.channel ? sb.from("channel_design_overrides").select("design").eq("token_slug", cur.channel).maybeSingle()
        : Promise.resolve({ data: null }),
    ]);
    const sum = d => Object.keys(d || {}).filter(k => k !== "_note").slice(0, 6).join(" · ") || "(빈 디자인)";
    let hh = "";
    if (chd && chd.data) hh += `<div class="tplItem" onclick="applyTpl('채널 기본', null)">
      <b>지금 디자인</b>${cur.channel && cur.channel !== "local-render" ? ` <span class="small">(${esc(cur.channel)})</span>` : ""}
      <div class="small">${esc(sum(chd.data.design))}</div>
      <div class="small faint">이 영상은 이미 이 디자인으로 만들어졌어요.</div></div>`;
    const rows = (tpl.data || []);
    if (!rows.length) hh += `<div class="small faint">저장된 템플릿이 없어요. 채널 템플릿 화면에서 만들면 여기 보여요.</div>`;
    rows.forEach((t, i) => { hh += `<div class="tplItem" data-i="${i}">
      <b>${esc(t.name)}</b><div class="small">${esc(sum(t.design))}</div></div>`; });
    box.classList.remove("faint"); box.innerHTML = hh;
    rows.forEach((t, i) => {
      const el = box.querySelector(`[data-i="${i}"]`);
      if (el) el.onclick = () => applyTpl(t.name, t.design);
    });
  };
  window.applyTpl = (name, design) => {
    if (!design){ toast("이미 이 디자인이에요"); return; }
    if (!editMode){ toast("편집 잠금을 먼저 풀어 주세요"); return; }
    if (!confirm(`템플릿 「${name}」의 디자인을 이 영상에 적용할까요?\n제목 글꼴, 색, 자막 모양 같은 것이 바뀌어요.`)) return;
    cur.pendingDesign = design; markDirty();
    toast(`템플릿 「${name}」을 적용했어요`);
  };
  // ⚠ 레일 패치가 삼켰던 원래 코드 복구 — 인스펙터 열·경계선은 레일 오른쪽에 이어진다
  const vdiv = document.createElement("div"); vdiv.id = "vdiv";
  const side = document.createElement("div"); side.id = "side";
  top.appendChild(vdiv); top.appendChild(side);
  side.appendChild($("#insp")); side.appendChild($("#warns"));
  const sgrip = document.createElement("div");
  sgrip.id = "sideGrip"; sgrip.title = "끌어서 폭 조절";
  sgrip.addEventListener("mousedown", e => {
    e.preventDefault();
    side.classList.add("noanim");
    const rightEdge = side.getBoundingClientRect().right;
    const mv = ev => document.body.style.setProperty("--sidew",
      Math.max(260, Math.min(640, rightEdge - ev.clientX)) + "px");
    const up = () => { window.removeEventListener("mousemove", mv);
      window.removeEventListener("mouseup", up); side.classList.remove("noanim"); };
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  });
  side.appendChild(sgrip);
  const sx2 = document.createElement("button");
  sx2.id = "sideClose"; sx2.innerHTML = EI.x; sx2.title = "닫기 (ESC)";
  sx2.onclick = () => closeSide();
  const sacts = document.createElement("div"); sacts.id = "sideActs";
  sacts.innerHTML = `
    <button onclick="sideRevert()" title="이 창을 연 시점의 상태로 되돌립니다">원래대로</button>
    <button class="primary" onclick="closeSide()"
      title="고친 내용을 두고 닫아요">저장</button>`;
  side.appendChild(sacts); side.appendChild(sx2);   // 인스펙터+경고 → 우측 열
  const stage = $("#stage"), tl = tlRoot.querySelector(".tlwrap");
  const hdiv = document.createElement("div"); hdiv.id = "hdiv";
  hdiv.title = "끌어서 타임라인 높이 조절";
  stage.insertBefore(hdiv, tl);
  // 원본 소재 줄 — 기본 접힘(사용자 8/24). 라벨 클릭 토글 + [원본] 탭과 연동
  const srcRow = tl.querySelector(".tlbody"); srcRow.id = "srcRow";
  srcRow.classList.add("collapsed");
  const srcLab = srcRow.querySelector(".srcl");
  srcLab.innerHTML = '<div><span class="caret">' + EI.right + '</span>원본 소재</div>';
  srcLab.style.flexDirection = "column"; srcLab.style.alignItems = "flex-start";
  const srcFullChip = document.createElement("button");
  srcFullChip.id = "srcFullBtn"; srcFullChip.className = "srcfloat";
  srcFullChip.title = "쓴 부분만 보기와 원본 전체 보기를 바꿔요";
  srcFullChip.textContent = "쓰인 범위만";
  srcFullChip.onclick = e => { e.stopPropagation(); toggleSrcFull(); };
  srcRow.style.position = "relative";
  srcRow.appendChild(srcFullChip);
  window.toggleSrcStrip = open => {
    const to = open === undefined ? srcRow.classList.contains("collapsed") : open;
    srcRow.classList.toggle("collapsed", !to);
    srcLab.innerHTML = (to
      ? '<div><span class="caret">' + EI.down + '</span>원본 소재' +
        '<div class="srcz"><button onclick="event.stopPropagation();srcZoomBy(0.72)" title="축소" aria-label="축소">' + EI.minus + '</button>' +
        '<button onclick="event.stopPropagation();srcZoomBy(1.4)" title="확대" aria-label="확대">' + EI.plus + '</button>' +
        '<button onclick="event.stopPropagation();cur.srcPx=null;drawSrc()" title="전체 맞춤" style="width:auto;padding:0 6px">맞춤</button>' +
        '</div></div>'
      : '<div><span class="caret">' + EI.right + '</span>원본 소재</div>');
    if (to && cur && cur.model) drawSrc();
    requestAnimationFrame(fitTracks);            // 원본 소재 줄 높이만큼 트랙 자리가 바뀐다
  };
  srcLab.addEventListener("click", () => toggleSrcStrip());
  const sy = document.createElement("div"); sy.id = "tlScrollY";  // 트랙 세로 스크롤
  tl.querySelectorAll(":scope > .tlbody").forEach(b => sy.appendChild(b));
  tl.appendChild(sy);
  // 트랙 높이 자동 맞춤 — 타임라인 칸 높이가 바뀌면(경계선 끌기·창 크기) 다시 계산한다
  new ResizeObserver(() => fitTracks()).observe(sy);
  const dragDiv = (el, horiz) => el.addEventListener("mousedown", e => {
    e.preventDefault();
    const mv = ev => {
      if (horiz) document.body.style.setProperty("--tlh",
        Math.max(140, Math.min(window.innerHeight - 180, window.innerHeight - ev.clientY)) + "px");
      else document.body.style.setProperty("--sidew",
        Math.max(230, Math.min(560, window.innerWidth - ev.clientX)) + "px");
    };
    const up = () => { window.removeEventListener("mousemove", mv);
      window.removeEventListener("mouseup", up);
      if (cur && cur.model) drawSrc(); centerShorts(); };
    window.addEventListener("mousemove", mv); window.addEventListener("mouseup", up);
  });
  dragDiv(hdiv, true); dragDiv(vdiv, false);
  stashSrc();   // 원본 플레이어는 시작부터 숨김 — [원본] 서랍에서만 보인다
  // 미리보기 미니 창 — 쇼츠 프레임을 통째로 모달로 옮긴다(영상·오버레이 그대로 산다)
  const modal = document.createElement("div"); modal.id = "pvModal";
  document.body.appendChild(modal);
  let pvHome = null;
  window.openPv = () => { const f = tlRoot.querySelector(".shorts");
    pvHome = f.parentElement; modal.appendChild(f); modal.classList.add("on"); };
  window.closePv = () => { const f = modal.querySelector(".shorts");
    if (f && pvHome) pvHome.appendChild(f); modal.classList.remove("on"); };
  modal.addEventListener("click", e => { if (e.target === modal) closePv(); });
  window.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    if (modal.classList.contains("on")) closePv();
    else if (document.getElementById("side").classList.contains("on")) closeSide();
  });
  const pv = document.createElement("button");
  pv.id = "pvBtn"; pv.textContent = "미리보기"; pv.title = "크게 보기 (ESC로 닫기)";
  pv.onclick = () => openPv();
  header.insertBefore(pv, $("#fsBtn"));
})();
window.toggleFs = () => document.fullscreenElement
  ? document.exitFullscreen() : document.documentElement.requestFullscreen();
window.addEventListener("keydown", e => {
  if (keyOf(e) !== "f" || e.metaKey || e.ctrlKey || e.altKey) return;
  const t = (e.target.tagName || "").toLowerCase();
  if (t === "input" || t === "textarea" || t === "select") return;
  e.preventDefault(); toggleFs();
});
window.addEventListener("resize", () => { centerShorts();
  if (!cur || !cur.model) return;
  if (!cur.outZoom) draw(); else { drawSrc(); syncZoomUi(); } });

// 병합(2026-08-26): 대시보드에 내장 — 처음 진입할 때만 부팅한다
let tlInited = false;
window.__tlEnter = async opts => {
  // 편집실이 열려 있다는 표시 — 떠날 때 저장 안 된 편집 확인창과 타임라인 단축키가 이걸 본다(종전엔 아무도 켜지 않아 둘 다 꺼져 있었다)
  window.__tlOpen = true;
  document.body.classList.add("applayout");
  if (tlInited) document.body.classList.toggle("editing", editMode);
  if (!tlInited){
    tlInited = true;
    await boot();
    sb.auth.onAuthStateChange((_ev, session) => {
      if (session && document.getElementById("tlRoot").style.display !== "none") boot(); });
    toggleEdit();                      // 편집 모드 기본
  }
  reCenter();
  if (opts && opts.run) openRun(opts.run);
};

// 인라인 on* 핸들러는 전역에서 실행된다 — IIFE 안 함수 중 그 경로로 불리는 것 노출
Object.assign(window, { draw, drawSrc, srcZoomBy, doLogin, toggleEdit, select, seekSrc });
window.tlCur = () => cur;   // 디버깅용 상태 접근
})();
