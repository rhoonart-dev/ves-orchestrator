import {askConfirm} from "./confirm-dialog.js";
// 소재 아카이브 — 예전 VES '소재 아카이브'(renderArchive, L-P3b)를 옮겼다. 잔망루피 원 채널 전량(약 1,100편)에서 오늘 올릴 편을 고르는 선반.
// 매일 03:00 원 채널 지표를 다시 세고 04:00 선별기(ops_config.loopy_picker)가 점수를 매긴다. 규칙은 RPC 에 있고 화면은 보여 주고 부르기만 한다.
//   list_external_shorts(채널, 쇼츠/롱폼, 거르기, 정렬, 개수, 건너뛰기) · set_external_short_allow(되살리기/빼기) · select_external_short(작업 걸기)
// 이미 올린 편·내용이 겹치는 편은 어디서도 후보가 되지 않는다(되살리기로도 못 뒤집는다 — 내용 중복 오탐만 풀 수 있다). 발행은 늘 사람이 검수함에서.
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const FILTERS = [["recommended","오늘의 추천"],["available","고를 수 있는"],["blocked","제외됨"],["published","이미 올림"],["all","전체"]];
const SORTS = [["score","점수순"],["views","조회수순"],["oldest","오래된 것부터"],["newest","최신순"]];
const KINDS = [["short","쇼츠"],["longform","롱폼"]];
const SIG = {views:"조회수",like_ratio:"좋아요율",jp_comments:"일본 반응",llm_jp_fit:"일본 적합",timing:"시의성",diversity:"다양성",kpi_feedback:"성과 학습"};
// 쇼츠는 남의 완성본에 일본어를 입힌다 — 화면 한글을 어떻게 다룰지가 route
const ROUTES = [["B","화면 한글 지우고 일본어 넣기","기본"],["BJ","한글 두고 일본어 같이 넣기","더 빨라요"],["A","자막 파일만 붙이기",""],["C","B에 일본어 더빙까지",""],["BC","한글만 지우고 더빙",""]];
const PAGE = 60;
const dur = s => { const n = Math.round(Number(s) || 0); return `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`; };
const num = n => Number(n || 0).toLocaleString("ko-KR");
const day = t => t ? String(t).slice(0, 10) : "—";

export function mountArchive(root, {client = null, role = null} = {}){
  if (!client){ root.innerHTML = '<p class="arc-note">로그인하면 소재 아카이브를 볼 수 있어요.</p>'; return () => {}; }
  const canReview = ["reviewer","operator","admin"].includes(role), canRun = ["operator","admin"].includes(role);
  const saved = () => { try { return localStorage.getItem("arc-channel"); } catch { return null; } };
  const st = {channel:saved(), kind:"short", filter:"recommended", sort:"score", page:0};
  let rows = [], total = 0, state = "idle", err = "", picker = null, msg = "", dead = false;
  // 채널 목록 — 아카이브에 영상이 있는 채널만. 채널이 늘면 여기에 저절로 붙는다(channel_slug 를 하나씩 건너뛰며 읽어 전체를 훑지 않는다)
  let chans = null;
  async function loadChannels(){
    const slugs = []; let last = "";
    for (let i = 0; i < 50; i++){
      const r = await client.from("external_shorts").select("channel_slug").gt("channel_slug", last).order("channel_slug").limit(1);
      if (r.error || !r.data?.length) break;
      last = r.data[0].channel_slug; slugs.push(last);
    }
    if (!slugs.length) slugs.push("LOOPY");
    const [m, ...counts] = await Promise.all([
      client.from("channels_mirror").select("token_slug,name,channel_id,avatar_url").in("token_slug", slugs),
      ...slugs.map(c => client.from("external_shorts").select("video_id", {count:"exact", head:true}).eq("channel_slug", c)),
    ]);
    const by = new Map((m.data || []).map(c => [c.token_slug, c]));
    chans = slugs.map((c, i) => ({slug:c, name:c, ...(by.get(c) || {}), count:counts[i].count ?? null}));
    // 원본 채널 — 수집기 설정(ops_config *_scout 의 handle)으로 찾고, 이름·아이콘은 원본 채널 목록(source_channels)에서
    const [scouts, srcs] = await Promise.all([
      client.from("ops_config").select("value").like("key", "%_scout"),
      client.from("source_channels").select("name,url,handle,avatar_url"),
    ]);
    const handleOf = new Map();
    for (const r of scouts.data || []){ try { const v = JSON.parse(r.value); if (v.handle && v.channel_slug) handleOf.set(v.channel_slug, v.handle); } catch {} }
    const srcBy = new Map((srcs.data || []).map(x => [String(x.handle || "").toLowerCase(), x]));
    for (const c of chans){
      const h = handleOf.get(c.slug);
      if (h) c.source = srcBy.get(h.toLowerCase()) || {name:h, url:`https://www.youtube.com/${h}`, avatar_url:null};
    }
    if (!chans.some(c => c.slug === st.channel)) st.channel = chans[0].slug;
  }
  async function load(){
    state = "loading"; draw();
    if (!chans) await loadChannels();
    const [list, conf] = await Promise.all([
      client.rpc("list_external_shorts", {p_channel:st.channel, p_kind:st.kind, p_filter:st.filter, p_sort:st.sort, p_limit:PAGE, p_offset:st.page * PAGE}),
      picker ? Promise.resolve(null) : client.from("ops_config").select("value").eq("key","loopy_picker").maybeSingle(),
    ]);
    if (dead) return;
    if (conf){ try { picker = JSON.parse(conf.data?.value || "{}"); } catch { picker = {}; } }
    if (list.error){ rows = []; total = 0; err = list.error.message; state = "error"; }
    else { rows = list.data || []; total = rows.length ? Number(rows[0].total) : 0; state = "ok"; }
    draw();
  }
  const set = (k, v) => { if (k === "channel"){ try { localStorage.setItem("arc-channel", v); } catch {} } if (k === "page") st.page = Math.max(0, v); else { if (st[k] === v) return; st[k] = v; st.page = 0; } msg = ""; load(); };

  function signals(scores){
    const xs = Object.entries(scores || {}).filter(([, v]) => typeof v === "number");
    return xs.length ? `<div class="arc-sigs">${xs.map(([k, v]) => `<div class="arc-sig"><span>${esc(SIG[k] || k)}</span><span class="arc-bar"><i style="width:${Math.round(Math.max(0, Math.min(1, v)) * 100)}%"></i></span><span>${v.toFixed(2)}</span></div>`).join("")}</div>` : "";
  }
  function card(r){
    const done = r.youtube_id || r.state === "uploaded", blocked = r.block_reason && !r.allowed_by;
    const tag = done ? '<span class="arc-tag pub">이미 올림</span>'
      : r.dup_of ? '<span class="arc-tag no">내용 중복</span>'
      : blocked ? '<span class="arc-tag no">제외됨</span>'
      : r.allowed_by ? '<span class="arc-tag wait">사람이 되살림</span>'
      : ["selected","processing","pending_approval","approved"].includes(r.state) ? '<span class="arc-tag wait">작업 걸림</span>'
      : r.score != null ? `<span class="arc-score">${Number(r.score).toFixed(3)}</span>` : "";
    // 작업 걸기는 아직 안 건 후보에만(두 번 걸면 같은 영상이 두 번 올라간다). 되살리기는 제외 사유만 — 발행 이력은 못 뒤집는다
    const runnable = canRun && !done && !blocked && ["discovered","scored"].includes(r.state);
    const acts = !canReview || done ? "" : `<div class="arc-acts">
      ${runnable ? `<button type="button" class="primary" data-run="${esc(r.video_id)}">${st.kind === "longform" ? "쇼츠 만들기" : "작업 걸기"}</button>` : ""}
      ${blocked ? `<button type="button" data-allow="${esc(r.video_id)}" data-dup="${r.dup_of ? 1 : 0}">${r.dup_of ? "중복 아님 · 되살리기" : "되살리기"}</button>`
        : `<button type="button" data-deny="${esc(r.video_id)}">후보에서 빼기</button>`}</div>`;
    return `<article class="arc-card${blocked || done ? " dim" : ""}">
      <a class="arc-th" ${r.thumbnail_url ? `style="background-image:url('${esc(r.thumbnail_url)}')"` : ""} href="${esc(r.url || "https://youtu.be/" + r.video_id)}" target="_blank" rel="noopener" title="원본 열기">${r.duration_sec ? `<span class="arc-dur">${dur(r.duration_sec)}</span>` : ""}</a>
      <div class="arc-bd">
        <div class="arc-t" title="${esc(r.title || "")}">${esc(r.title || r.video_id)}</div>
        <div class="arc-m">${tag}<span>조회 ${num(r.view_count)}</span><span>${day(r.published_at)}</span></div>
        ${r.block_reason ? `<div class="arc-why">${r.allowed_by ? "되살림 · " : ""}${esc(r.block_reason)}${r.allowed_by ? ` (${esc(r.allowed_by)})` : ""}</div>` : ""}
        ${st.filter === "recommended" ? signals(r.scores) : ""}
        ${acts}</div></article>`;
  }
  // 틀은 한 번만 — 검색 칸이 다시 그려지며 입력이 끊기지 않게. 왼쪽은 채널 관리 탭과 같은 긴 채널 칸
  let main = null, side = null, search = null;
  function shell(){
    root.innerHTML = `<div class="template-layout arc-page"><aside class="template-sidebar"><label>채널 검색<input type="search" placeholder="채널 검색" aria-label="채널 검색"></label><div class="template-channels"></div></aside>
      <div class="arc-main"></div><dialog class="arc-dialog" aria-labelledby="arc-dlg-title"></dialog></div>`;
    main = root.querySelector(".arc-main"); side = root.querySelector(".template-channels"); search = root.querySelector("input[type=search]");
    search.oninput = drawSide;
  }
  function drawSide(){
    if (!chans){ side.innerHTML = '<p class="arc-note">불러오는 중…</p>'; return; }
    const q = search.value.trim().toLowerCase();
    const xs = chans.filter(c => !q || String(c.name).toLowerCase().includes(q) || c.slug.toLowerCase().includes(q));
    side.innerHTML = xs.map(c => `<button type="button" data-v="${esc(c.slug)}" class="has-av${c.slug === st.channel ? " active" : ""}"><span class="tc-av">${c.avatar_url ? `<img src="${esc(c.avatar_url)}" alt="" referrerpolicy="no-referrer">` : esc(String(c.name || "?").slice(0, 1))}</span><span class="tc-txt">${esc(c.name)}<small>${c.count != null ? `영상 ${num(c.count)}편` : ""}</small></span></button>`).join("")
      || '<p class="arc-note">맞는 채널이 없어요.</p>';
    side.querySelectorAll("button").forEach(b => b.onclick = () => set("channel", b.dataset.v));
  }
  function draw(){
    if (dead) return;
    const on = picker?.enabled === true, pages = Math.ceil(total / PAGE) || 1;
    const body = state === "loading" ? '<p class="arc-note">불러오는 중…</p>'
      : state === "error" ? `<p class="arc-note arc-err">목록을 불러오지 못했어요. ${esc(err)}</p>`
      : !rows.length ? `<p class="arc-note">${st.filter === "recommended" ? (on ? "아직 추천이 없어요. 새벽 4시에 새로 나와요." : "자동 추천이 꺼져 있어요.") : "영상이 없어요."}</p>`
      : `<div class="arc-grid">${rows.map(card).join("")}</div>
        ${pages > 1 ? `<div class="arc-pager"><button type="button" data-page="${st.page - 1}" ${st.page ? "" : "disabled"}>‹ 이전</button><span>${st.page + 1} / ${pages} · 총 ${num(total)}편</span><button type="button" data-page="${st.page + 1}" ${st.page + 1 < pages ? "" : "disabled"}>다음 ›</button></div>` : ""}`;
    const chan = chans?.find(c => c.slug === st.channel), src = chan?.source;
    if (!root.querySelector(".arc-page")) shell();
    drawSide();
    main.innerHTML = `<section class="arc-panel">
      <header class="arc-head"><div><h2 class="arc-chan">${src ? `<a href="${esc(src.url)}" target="_blank" rel="noopener" title="원본 채널 열기">${src.avatar_url ? `<img src="${esc(src.avatar_url)}" alt="" referrerpolicy="no-referrer">` : ""}<span>${esc(src.name)}</span></a>` : chan ? esc(chan.name) : "&nbsp;"}</h2>
        <p>새벽 3시에 조회수를 다시 모으고 4시에 점수를 매겨요. 이미 올렸거나 내용이 겹치는 영상은 빠져요.</p></div>
        <button type="button" class="arc-reload">다시 읽기</button></header>
      ${on ? "" : '<p class="arc-off">자동 추천이 꺼져 있어서 새 추천은 안 나와요. 목록은 그대로 볼 수 있어요.</p>'}
      <div class="arc-bars">
        <div class="arc-seg">${KINDS.map(([k, l]) => `<button type="button" data-k="kind" data-v="${k}" aria-pressed="${st.kind === k}">${l}</button>`).join("")}</div>
        <div class="arc-seg">${FILTERS.map(([k, l]) => `<button type="button" data-k="filter" data-v="${k}" aria-pressed="${st.filter === k}">${l}</button>`).join("")}</div>
        <div class="arc-seg">${SORTS.map(([k, l]) => `<button type="button" data-k="sort" data-v="${k}" aria-pressed="${st.sort === k}">${l}</button>`).join("")}</div>
        <span class="arc-count">${state === "ok" ? `${num(total)}편` : ""}</span></div>
      <p class="arc-msg" role="status">${esc(msg)}</p>
      ${body}
      <p class="arc-foot">${st.kind === "longform" ? "롱폼은 쇼츠로 새로 만든 뒤 일본어로 바꿔요. 시간이 좀 걸려요." : "쇼츠는 영상은 그대로 두고 화면 글자만 일본어로 바꿔요."} 여기서는 고르기만 하고, 올리는 건 검수 후에 사람이 해요.</p>
    </section>`;
    main.querySelector(".arc-reload").onclick = () => load();
    main.querySelectorAll("[data-k]").forEach(b => b.onclick = () => set(b.dataset.k, b.dataset.v));
    main.querySelectorAll("[data-page]").forEach(b => b.onclick = () => set("page", +b.dataset.page));
    main.querySelectorAll("[data-allow]").forEach(b => b.onclick = () => allow(b, b.dataset.allow, true, b.dataset.dup === "1"));
    main.querySelectorAll("[data-deny]").forEach(b => b.onclick = () => allow(b, b.dataset.deny, false, false));
    main.querySelectorAll("[data-run]").forEach(b => b.onclick = () => run(b.dataset.run));
  }
  async function allow(btn, vid, yes, clearDup){
    if (!await askConfirm(yes ? {title:"이 영상을 다시 후보에 넣을까요?", ok:"넣기"} : {title:"이 영상을 후보에서 뺄까요?", ok:"빼기"})) return;
    btn.disabled = true;
    const {error} = await client.rpc("set_external_short_allow", {p_video_id:vid, p_allow:yes, p_note:null, p_clear_dup:!!clearDup});
    msg = error ? `안 됐어요. ${error.message}` : yes ? "다시 후보에 넣었어요." : "후보에서 뺐어요.";
    load();
  }
  // 작업 걸기 — 드라이브발은 파일이 route 를 안다, 쇼츠는 route 를 고르고, 롱폼은 확인만. 자동이 아니다(선별기는 점수만)
  function run(vid){
    const r = rows.find(x => x.video_id === vid) || {}, drive = !!r.flags?.drive;
    const dlg = root.querySelector(".arc-dialog");
    const pickRoute = !drive && st.kind === "short";
    dlg.innerHTML = `<form method="dialog" class="arc-dlg"><h2 id="arc-dlg-title">${st.kind === "longform" ? "쇼츠 만들기" : "작업 걸기"}</h2>
      <p class="arc-dlg-t">${esc(r.title || vid)}</p>
      ${pickRoute ? `<div class="arc-routes">${ROUTES.map(([k, l, s], i) => `<label><input type="radio" name="route" value="${k}" ${i ? "" : "checked"}><span><b>${k}</b> ${esc(l)}${s ? `<small>${esc(s)}</small>` : ""}</span></label>`).join("")}</div>`
        : drive ? `<p class="arc-note">드라이브에서 받은 원본이라 ${esc(r.flags?.route || "B")} 방식으로 진행해요.${(r.flags?.route || "B") === "A" ? " 화면에 글자가 없어서 지우는 단계는 건너뛰어요." : ""}</p>`
        : `<p class="arc-note">이 영상으로 쇼츠를 만들고 일본어로 바꿔요. 시간이 좀 걸려요.</p>`}
      <p class="arc-err" role="alert"></p>
      <footer><button type="button" value="cancel">취소</button><button type="submit" class="primary">${st.kind === "longform" ? "만들기" : "작업 걸기"}</button></footer></form>`;
    const f = dlg.querySelector("form");
    f.querySelector("[value=cancel]").onclick = () => dlg.close();
    f.onsubmit = async e => {
      e.preventDefault();
      const route = pickRoute ? f.route.value : null;
      f.querySelectorAll("button").forEach(b => b.disabled = true);
      const {data, error} = await client.rpc("select_external_short", {p_video_id:vid, p_route:route, p_note:null});
      if (error){ f.querySelector(".arc-err").textContent = `안 됐어요. ${error.message}`; f.querySelectorAll("button").forEach(b => b.disabled = false); return; }
      dlg.close();
      msg = `작업을 걸었어요.${data?.route ? ` ${data.route} 방식이에요.` : ""}`;
      load();
    };
    dlg.showModal();
  }
  load();
  return () => { dead = true; };
}
