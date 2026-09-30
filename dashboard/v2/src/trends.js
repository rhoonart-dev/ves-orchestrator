import {askConfirm} from "./confirm-dialog.js";
// 트렌드 — 예전 VES 대시보드 트렌드 탭(ves-orchestrator/dashboard/index.html renderTrends, 에디토리얼판 8/27)을 옮겼다.
// 숫자는 전부 get_trend_report RPC 의 facts(SQL 집계) — 이 화면은 표시만 한다. 해설(narrative)은 Gemini 산출이라 없을 수 있다.
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
// 트렌드 로봇 — 안경 왼쪽 옆 십자 반짝이(.trx-spark, 팟칭!) + 흑백 인베이더(몸은 회색 명도만) + 코발트 테·하얀 알 안경. 색은 trends.css 의 .b1·.b2·.b3·.bg·.bw(토큰)
const trendBotIcon = `<svg class="trx-bot" viewBox="-3.5 -.5 20 14" aria-hidden="true" shape-rendering="crispEdges" style="stroke:none"><g class="trx-spark"><rect class="sp-c" x="-2" y="5" width="1" height="1"/><rect class="sp-a" x="-2" y="4" width="1" height="1"/><rect class="sp-a" x="-3" y="5" width="1" height="1"/><rect class="sp-a" x="-1" y="5" width="1" height="1"/><rect class="sp-a" x="-2" y="6" width="1" height="1"/></g><rect class="b3" x="4" y="0" width="1" height="1"/><rect class="b3" x="11" y="0" width="1" height="1"/><rect class="b3" x="5" y="1" width="1" height="1"/><rect class="b3" x="10" y="1" width="1" height="1"/><rect class="b1" x="3" y="2" width="1" height="1"/><rect class="b1" x="4" y="2" width="1" height="1"/><rect class="b1" x="5" y="2" width="1" height="1"/><rect class="b1" x="6" y="2" width="1" height="1"/><rect class="b1" x="7" y="2" width="1" height="1"/><rect class="b1" x="8" y="2" width="1" height="1"/><rect class="b1" x="9" y="2" width="1" height="1"/><rect class="b1" x="10" y="2" width="1" height="1"/><rect class="b1" x="11" y="2" width="1" height="1"/><rect class="b1" x="12" y="2" width="1" height="1"/><rect class="b1" x="2" y="3" width="1" height="1"/><rect class="b1" x="3" y="3" width="1" height="1"/><rect class="b1" x="4" y="3" width="1" height="1"/><rect class="b1" x="5" y="3" width="1" height="1"/><rect class="b1" x="6" y="3" width="1" height="1"/><rect class="b1" x="7" y="3" width="1" height="1"/><rect class="b1" x="8" y="3" width="1" height="1"/><rect class="b1" x="9" y="3" width="1" height="1"/><rect class="b1" x="10" y="3" width="1" height="1"/><rect class="b1" x="11" y="3" width="1" height="1"/><rect class="b1" x="12" y="3" width="1" height="1"/><rect class="b1" x="13" y="3" width="1" height="1"/><rect class="b1" x="1" y="4" width="1" height="1"/><rect class="bg" x="2" y="4" width="1" height="1"/><rect class="bg" x="3" y="4" width="1" height="1"/><rect class="bg" x="4" y="4" width="1" height="1"/><rect class="bg" x="5" y="4" width="1" height="1"/><rect class="bg" x="6" y="4" width="1" height="1"/><rect class="b1" x="7" y="4" width="1" height="1"/><rect class="b1" x="8" y="4" width="1" height="1"/><rect class="bg" x="9" y="4" width="1" height="1"/><rect class="bg" x="10" y="4" width="1" height="1"/><rect class="bg" x="11" y="4" width="1" height="1"/><rect class="bg" x="12" y="4" width="1" height="1"/><rect class="bg" x="13" y="4" width="1" height="1"/><rect class="b1" x="14" y="4" width="1" height="1"/><rect class="b1" x="1" y="5" width="1" height="1"/><rect class="bg" x="2" y="5" width="1" height="1"/><rect class="bw" x="3" y="5" width="1" height="1"/><rect class="bw" x="4" y="5" width="1" height="1"/><rect class="bw" x="5" y="5" width="1" height="1"/><rect class="bg" x="6" y="5" width="1" height="1"/><rect class="bg" x="7" y="5" width="1" height="1"/><rect class="bg" x="8" y="5" width="1" height="1"/><rect class="bg" x="9" y="5" width="1" height="1"/><rect class="bw" x="10" y="5" width="1" height="1"/><rect class="bw" x="11" y="5" width="1" height="1"/><rect class="bw" x="12" y="5" width="1" height="1"/><rect class="bg" x="13" y="5" width="1" height="1"/><rect class="b1" x="14" y="5" width="1" height="1"/><rect class="b1" x="1" y="6" width="1" height="1"/><rect class="bg" x="2" y="6" width="1" height="1"/><rect class="bw" x="3" y="6" width="1" height="1"/><rect class="bw" x="4" y="6" width="1" height="1"/><rect class="bw" x="5" y="6" width="1" height="1"/><rect class="bg" x="6" y="6" width="1" height="1"/><rect class="b1" x="7" y="6" width="1" height="1"/><rect class="b1" x="8" y="6" width="1" height="1"/><rect class="bg" x="9" y="6" width="1" height="1"/><rect class="bw" x="10" y="6" width="1" height="1"/><rect class="bw" x="11" y="6" width="1" height="1"/><rect class="bw" x="12" y="6" width="1" height="1"/><rect class="bg" x="13" y="6" width="1" height="1"/><rect class="b1" x="14" y="6" width="1" height="1"/><rect class="b1" x="1" y="7" width="1" height="1"/><rect class="b1" x="2" y="7" width="1" height="1"/><rect class="bg" x="3" y="7" width="1" height="1"/><rect class="bg" x="4" y="7" width="1" height="1"/><rect class="bg" x="5" y="7" width="1" height="1"/><rect class="b1" x="6" y="7" width="1" height="1"/><rect class="b1" x="7" y="7" width="1" height="1"/><rect class="b1" x="8" y="7" width="1" height="1"/><rect class="b1" x="9" y="7" width="1" height="1"/><rect class="bg" x="10" y="7" width="1" height="1"/><rect class="bg" x="11" y="7" width="1" height="1"/><rect class="bg" x="12" y="7" width="1" height="1"/><rect class="b1" x="13" y="7" width="1" height="1"/><rect class="b1" x="14" y="7" width="1" height="1"/><rect class="b1" x="2" y="8" width="1" height="1"/><rect class="b1" x="3" y="8" width="1" height="1"/><rect class="b1" x="4" y="8" width="1" height="1"/><rect class="b2" x="5" y="8" width="1" height="1"/><rect class="b2" x="6" y="8" width="1" height="1"/><rect class="b2" x="7" y="8" width="1" height="1"/><rect class="b2" x="8" y="8" width="1" height="1"/><rect class="b2" x="9" y="8" width="1" height="1"/><rect class="b2" x="10" y="8" width="1" height="1"/><rect class="b1" x="11" y="8" width="1" height="1"/><rect class="b1" x="12" y="8" width="1" height="1"/><rect class="b1" x="3" y="9" width="1" height="1"/><rect class="b1" x="4" y="9" width="1" height="1"/><rect class="b1" x="5" y="9" width="1" height="1"/><rect class="b1" x="6" y="9" width="1" height="1"/><rect class="b1" x="7" y="9" width="1" height="1"/><rect class="b1" x="8" y="9" width="1" height="1"/><rect class="b1" x="9" y="9" width="1" height="1"/><rect class="b1" x="10" y="9" width="1" height="1"/><rect class="b1" x="11" y="9" width="1" height="1"/><rect class="b1" x="12" y="9" width="1" height="1"/><rect class="b2" x="2" y="10" width="1" height="1"/><rect class="b1" x="4" y="10" width="1" height="1"/><rect class="b1" x="7" y="10" width="1" height="1"/><rect class="b1" x="8" y="10" width="1" height="1"/><rect class="b1" x="11" y="10" width="1" height="1"/><rect class="b2" x="13" y="10" width="1" height="1"/><rect class="b2" x="1" y="11" width="1" height="1"/><rect class="b1" x="4" y="11" width="1" height="1"/><rect class="b1" x="7" y="11" width="1" height="1"/><rect class="b1" x="8" y="11" width="1" height="1"/><rect class="b1" x="11" y="11" width="1" height="1"/><rect class="b2" x="14" y="11" width="1" height="1"/><rect class="b3" x="4" y="12" width="1" height="1"/><rect class="b3" x="5" y="12" width="1" height="1"/><rect class="b3" x="10" y="12" width="1" height="1"/><rect class="b3" x="11" y="12" width="1" height="1"/></svg>`;
export function mountTrends(root, {client = null, role = null} = {}){
if (!client){ root.innerHTML = '<p class="home-empty">로그인하면 트렌드 리포트를 볼 수 있어요.</p>'; return () => {}; }
let dead = false;
const T = window.__trends = {};
root.classList.add("trends-page");   // 스타일은 src/trends.css (.trx-*)
function render(){ if (!dead){ renderTrends(); nameChannels(root); } }
let trends = null, trendsSeq = 0, trendsDate = null;
// 리포트 facts·해설에는 채널이 슬러그(JAEMISHOTS)로 적혀 있다 — 화면에서는 채널 이름(재미쇼츠)으로 바꿔 보인다(글자만, 속성은 그대로)
let chNames = null;
function nameChannels(el){
  if (!chNames || !chNames.size) return;
  const re = new RegExp(`\\b(${[...chNames.keys()].map(k => k.replace(/[^A-Z0-9_]/g, "")).filter(Boolean).join("|")})\\b`, "g");
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode())
    if (re.test(n.nodeValue)){ re.lastIndex = 0; n.nodeValue = n.nodeValue.replace(re, k => chNames.get(k) || k); }
}
async function loadTrends(){
  // 재진입 가드 대신 순번 토큰 — 진행 중 날짜 변경 시 낡은 응답을 버린다(리뷰 반영)
  const seq = ++trendsSeq;
  try {
    const [{ data, error }, ch] = await Promise.all([client.rpc("get_trend_report",
      trendsDate ? { p_date: trendsDate } : {}),
      chNames ? null : client.from("channels_mirror").select("token_slug,name").then(r => r, () => ({ data: [] }))]);
    if (ch) chNames = new Map((ch.data || []).map(c => [c.token_slug, c.name]));
    if (seq !== trendsSeq) return;
    trends = error ? { error: error.message } : (data && data.report ? data : { empty: true, dates: (data||{}).dates||[], notice: (data||{}).notice });
  } catch (e) { if (seq === trendsSeq) trends = { error: String(e) }; }
  finally { if (seq === trendsSeq) render(); }
}
T.trendsPick = d => { trendsDate = d || null; trends = null; render(); };
T.trendsDismissNotice = async () => {
  if (!await askConfirm({title:"이 공지를 내릴까요?", body:"모든 사람 화면에서 사라져요.", ok:"내리기"})) return;
  const { error } = await client.rpc("dismiss_trend_notice");
  if (error){ alert(`공지를 내리지 못했어요: ${error.message}`); return; }
  trends = null; render();
};
T.trendsReload = () => { trends = null; render(); };
const tvN = v => v == null ? "—" : Number(v).toLocaleString();
const tvSect = (eyebrow, title, narr, inner) => `
  <section class="trx-sec">
    <div class="trx-eyebrow">${esc(eyebrow)}</div>
    <h2 class="trx-h2">${esc(title)}</h2>
    ${narr ? `<p class="trx-prose">${esc(String(narr))}</p>` : ""}
    ${inner}</section>`;
function renderTrends(){
  if (!trends){ loadTrends();
    root.innerHTML = '<div class="trx"><div class="trx-empty">리포트 불러오는 중…</div></div>'; return; }
  if (trends.error){
    root.innerHTML = `<div class="trx"><div class="trx-empty">리포트 조회 실패 — ${esc(trends.error)}
      <button class="mini" onclick="__trends.trendsReload()">다시 시도</button></div></div>`; return; }
  const canOp = ["operator","admin"].includes(role);
  const noticeHtml = trends.notice ? `
    <div class="trx-corr"><div class="trx-corr-t"><span class="trx-notice-tag">공지</span><span class="trx-notice-title">${esc(trends.notice.title||"공지")}</span>${
      canOp ? ` <button class="mini" onclick="__trends.trendsDismissNotice(this)">공지 내리기</button>` : ""}</div>${
      String(trends.notice.body||"").split("\n").map(l => `<p>${esc(l)}</p>`).join("")}</div>` : "";
  const dates = trends.dates || [];
  const dateSel = dates.length > 1 ? `<select class="trx-datesel" onchange="__trends.trendsPick(this.value)">${
    dates.map(d => `<option value="${d}" ${d===(trends.report||{}).report_date?"selected":""}>${d}</option>`).join("")}</select>` : "";
  if (trends.empty){
    root.innerHTML = `<div class="trx"><header class="trx-mast">
      <div class="trx-kicker"><span>일일 트렌드 리포트</span></div>
      <h1 class="trx-h1">아직 리포트가 없다</h1>
      <p class="trx-stand">매일 05:00 KST 에 만들어진다 — ops_config.trend_report 가 스위치다.</p>
      </header>${noticeHtml}</div>`; return; }

  const r = trends.report, f = r.facts || {}, nr = r.narrative || {};
  const cur = trends.constants || {}, prop = trends.constants_proposed;
  const d = f.diagnosis || {counts:{},videos:[]}, cnt = d.counts || {};
  const works = ((f.inside||{}).works)||[];
  const out = f.outside || {regions:{}}, ov = out.overlaps || [];
  const sc = f.success || {}, zan = f.zanmang;
  const rd = String(r.report_date||"");
  const lagBad = f.data_lag_days != null && f.data_lag_days > 2;

  // 밖 — 지역 3열
  const regionCols = Object.entries(out.regions||{}).map(([rg, items]) => `
    <div class="trx-panel"><div class="trx-clab">${esc(rg)}</div>
      <div class="trx-ledger">${items.map(t => `
        <div class="trx-lrow"><span class="trx-rank">${t.rank}</span>
          <span class="trx-lname">${esc(t.title||"")}</span>
          <span class="trx-lsrc">${t.source==="youtube_chart"?"차트":"검색"}</span></div>`).join("")
        || '<div class="trx-empty">수집 없음</div>'}</div></div>`).join("");

  // 안 — 작품 원장
  const workRows = works.map(w => {
    const bad = ["n_blocked","n_noclick","n_exit","n_hold"], badLab = ["배포✕","클릭✕","이탈","보류"],
          badCls = ["crit","warn","warn","mut"];
    const chips = bad.map((k2,i)=>w[k2]?`<span class="trx-v ${badCls[i]}">${badLab[i]} ${w[k2]}</span>`:"")
                     .filter(Boolean).join(" ") || '<span class="trx-v ok">전부 정상</span>';
    return `<tr><td class="trx-tname">${esc(w.work||"")}<div class="trx-tsub">${(w.channels||[]).map(esc).join(" · ")}</div></td>
      <td class="num">${tvN(w.n_videos)}</td><td class="num">${tvN(w.impressions)}</td>
      <td class="num">${w.ctr==null?"—":w.ctr}</td><td class="num">${w.view_pct==null?"—":w.view_pct}</td>
      <td class="num strong">${tvN(w.views)}</td><td>${chips}</td></tr>`;
  }).join("") || '<tr><td colspan="7" class="trx-empty">데이터 없음</td></tr>';

  // 진단 — 정상 아닌 영상
  const vcls = {"정상":"ok","이탈":"warn","안 눌림":"warn","배포 안 됨":"crit","판정 보류":"mut"};
  // 운영자 지시(8/27): '배포 안 됨' 개별 나열 제외 — 집계(타일)로만. 구 리포트 호환 필터.
  const diagRows = (d.videos||[]).filter(v => v.verdict !== "배포 안 됨").map(v => `
    <tr><td><span class="trx-v ${vcls[v.verdict]||"mut"}">${esc(v.verdict)}</span></td>
      <td class="trx-tname">${esc((v.title||"").slice(0,42))}<div class="trx-tsub">${esc(v.work||"")} · ${esc(v.channel||"")}</div></td>
      <td class="num">${tvN(v.impr)}</td><td class="num">${v.ctr==null?"—":v.ctr}</td>
      <td class="num">${v.view_pct==null?"—":v.view_pct}</td><td class="num">${v.len==null?"—":v.len}</td>
      <td class="trx-hint">${esc(v.hint||"")}</td></tr>`).join("")
    || '<tr><td colspan="7" class="trx-empty">전부 정상</td></tr>';

  // 성공 — 축 대조 막대쌍
  const axLab = {len:"길이(초)", publish_hour:"게시 시각(시)", shares_per_1k:"공유/1k뷰", title_len:"제목 길이(자)"};
  const axesHtml = sc.axes ? Object.entries(sc.axes).map(([k2,a]) => {
    const mx = Math.max(a.top||0, a.rest||0) || 1;
    const bar = (v,c) => `<div class="trx-bar"><div class="trx-fill ${c}" style="width:${Math.max(2,(v||0)/mx*100)}%"></div><span>${v==null?"—":v}</span></div>`;
    return `<div class="trx-pair"><div class="trx-clab">${axLab[k2]||esc(k2)}</div>${bar(a.top,"ours")}${bar(a.rest,"mkt")}</div>`;
  }).join("") : "";
  const topVids = (sc.top_videos||[]).map(v =>
    `<span class="trx-v ok">${esc((v.title||"").slice(0,28))} · ${tvN(v.views)}회</span>`).join(" ");

  const badge = prop && prop.differs ? `
    <div class="trx-note">⚠ 알고리즘 상수 제안이 현행과 다르다(조사 ${esc(String(prop.checked_at||"").slice(0,10))} · ${esc(prop.confidence||"")}).
    반영은 사람이 ops_config.algo_constants 를 고친다.</div>` : "";

  root.innerHTML = `<div class="trx">
    <header class="trx-mast">
      <div class="trx-kicker"><span>일일 트렌드 리포트</span><span class="dot"></span>${dateSel||`<span>${esc(rd)}</span>`}${r.status && r.status!=="ok"?`<span class="dot"></span><span class="crit">오늘은 요약 글을 만들지 못했어요. 숫자는 그대로예요.</span>`:""}
        ${lagBad?`<span class="dot"></span><span class="crit">데이터 ${esc(String(f.ref_date||""))} · 지연 ${f.data_lag_days}일</span>`:""}
        <button class="mini" onclick="__trends.trendsReload()">새로고침</button></div>
      <h1 class="trx-h1">${trendBotIcon}깔때기는 어디서 끊겼나</h1>
      ${nr.summary ? `<blockquote class="trx-stand">${esc(nr.summary)}</blockquote>` : ""}
    </header>
    ${noticeHtml}
    <div class="trx-tiles">
      <div class="trx-tile good"><div class="lab">정상</div><div class="num">${tvN(cnt["정상"])}</div><div class="sub">깔때기 전 구간 통과</div></div>
      <div class="trx-tile alarm"><div class="lab">배포 안 됨</div><div class="num">${tvN(cnt["배포 안 됨"])}</div><div class="sub">노출 &lt; ${cur.impression_floor??100} — 콘텐츠 수정 금지</div></div>
      <div class="trx-tile alarm"><div class="lab">이탈</div><div class="num">${tvN(cnt["이탈"])}</div><div class="sub">완주율 미달 — 훅 3초</div></div>
      <div class="trx-tile"><div class="lab">안 눌림</div><div class="num">${tvN(cnt["안 눌림"])}</div><div class="sub">CTR &lt; ${cur.ctr_floor??2}% — 제목·썸네일</div></div>
      <div class="trx-tile"><div class="lab">판정 보류</div><div class="num">${tvN(cnt["판정 보류"])}</div><div class="sub">표본 부족</div></div>
    </div>
    ${(f.actions||[]).length ? tvSect("actions", "오늘 할 것", nr.actions && !Array.isArray(nr.actions) ? nr.actions : null, `
      <div class="trx-ledger">${(f.actions||[]).map(a => `
        <div class="trx-lrow act"><span class="trx-v ${a.pri===1?"crit":"warn"}">P${a.pri}</span>
          <span class="trx-lname">${esc(a.text)}</span></div>`).join("")}</div>`) : ""}
    ${((f.momentum||[]).length) ? tvSect("turning point", "전환점 — 급증·급락", nr.momentum, `
      <div class="trx-cols">${(f.momentum||[]).map(m => `
        <div class="trx-panel"><div class="trx-clab"><span class="trx-v ${m.dir==="surge"?"ok":"crit"}">${m.dir==="surge"?"급증":"급락"}</span>
          ${esc(m.channel)} <span class="trx-mkmed">최근 7일 ${tvN(m.recent)} · 이전 7일 ${tvN(m.prev)}</span></div>
          <div class="trx-ledger">${(m.drivers||[]).map(dv => `
            <div class="trx-lrow"><span class="trx-lname">${esc((dv.title||"").slice(0,34))}
              <div class="trx-tsub">${esc(dv.published||"")}${(dv.matches||[]).length ? " · 외부 겹침: " + esc(dv.matches.map(x=>(x.tokens||[]).join("·")).join(" / ")) : ""}</div></span>
              <span class="trx-mknum">${tvN(dv.views)}</span></div>`).join("")
            || '<div class="trx-empty">주도 영상 없음</div>'}</div></div>`).join("")}</div>
      <div class="trx-figsub">기준: 최근 7일 vs 이전 7일 (급증 ≥3배·급락 ≤0.4배) · '외부 겹침'은 그 무렵 트렌드·시장 제목과 겹친 고유명사 — 인과가 아니라 검증할 단서다</div>`) : ""}
    ${ov.length ? tvSect("crossover", "밖 ↔ 안 — 트렌드에 등장한 작품", null,
      `<div class="trx-xover">${ov.map(h => `<span class="trx-v ok">「${esc(h.work)}」 ← ${esc(h.region||"")} "${esc(h.trend)}"</span>`).join("")}</div>`) : ""}
    ${tvSect("market", "밖 — 우리 작품의 시장", nr.outside, `
      ${(out.market||[]).length ? `<div class="trx-cols">${(out.market||[]).map(m => `
        <div class="trx-panel"><div class="trx-clab">${esc(m.work)} <span class="trx-mkmed">외부 중앙 ${tvN(m.market_median)}회</span></div>
          <div class="trx-ledger">${(m.videos||[]).map(v => `
            <div class="trx-lrow"><span class="trx-lname">${esc((v.title||"").slice(0,34))}
              <div class="trx-tsub">${esc(v.channel||"")}</div></span>
              <span class="trx-mknum">${tvN(v.views)}</span></div>`).join("")}</div></div>`).join("")}</div>
        <div class="trx-figsub">최근 7일 · 같은 작품을 다루는 외부 상위 영상(순위 상위 편향 — 중앙값은 실제보다 높게 잡힌다) · 방영 중(prefer_latest) 작품만</div>`
      : '<div class="trx-empty">시장 스냅샷 없음 — 다음 03:00 수집부터(방영 중 작품 대상)</div>'}
      <details class="trx-details"><summary>검색·차트 트렌드 (참고)</summary>
        <div class="trx-cols">${regionCols || '<div class="trx-empty">오늘 수집 없음</div>'}</div></details>
      <div class="trx-figsub">수집 ${esc(String(out.collected_date||""))}</div>`)}
    ${tvSect("inside", "안 — 작품별 깔때기", nr.inside, `
      <div class="trx-tablewrap"><table class="trx-table">
      <tr><th>작품 · 채널</th><th class="num">편수</th><th class="num">노출</th><th class="num">CTR%</th>
          <th class="num">완주%</th><th class="num">조회</th><th>판정 분포</th></tr>${workRows}</table></div>`)}
    ${tvSect("diagnosis", "진단 — 콘텐츠로 고칠 수 있는 영상", nr.diagnosis, `
      <div class="trx-tablewrap"><table class="trx-table">
      <tr><th>판정</th><th>영상</th><th class="num">노출</th><th class="num">CTR%</th>
          <th class="num">완주%</th><th class="num">길이s</th><th>처방</th></tr>${diagRows}</table></div>
      <div class="trx-figsub">이탈·안 눌림만 — '배포 안 됨' ${tvN(cnt["배포 안 됨"])}건은 집계로만 본다(처방은 회차·태그, 상단 공지)</div>`)}
    ${sc.axes ? tvSect("success", `왜 되나 — 상위 ${sc.top_n}편(조회 ${tvN(sc.top_views_min)}+) vs 나머지`, nr.success, `
      <div class="trx-pairs">${axesHtml}</div>
      <div class="trx-legend"><span class="sw ours"></span>상위 10% 중앙값 <span class="sw mkt"></span>나머지 중앙값</div>
      ${topVids ? `<div class="trx-topvids">${topVids}</div>` : ""}`) : ""}
    ${zan ? tvSect("잔망루피 · 일본", "잔망루피 — 별도 원장", null, `
      <div class="trx-tablewrap"><table class="trx-table">
      <tr><th>제목</th><th class="num">조회</th><th>발행</th></tr>${
      (zan.recent||[]).map(v => `<tr><td class="trx-tname">${esc((v.title||"").slice(0,40))}</td>
        <td class="num">${tvN(v.view_count)}</td><td>${esc(String(v.publish_at||"").slice(0,10))}</td></tr>`).join("")
      || '<tr><td colspan="3" class="trx-empty">발행 없음</td></tr>'}</table></div>
      <div class="trx-figsub">발행 ${tvN(zan.published)} / 전체 ${tvN(zan.total)} — ${esc(zan.source||"")} (laeebly 밖)</div>`) : ""}
    ${badge}
    <div class="trx-figsub trx-foot">생성 ${esc(String(r.generated_at||"").slice(0,16))} · ${esc(r.model||"facts only")} ·
      임계값 노출≥${cur.impression_floor??"?"} · CTR≥${cur.ctr_floor??"?"}% · 완주 &lt;30s ${(cur.retention_min||{}).lt30??"?"}% / ≥30s ${(cur.retention_min||{})["30to60"]??"?"}%</div>
  </div>`;
}
render();
return () => { dead = true; root.classList.remove("trends-page"); if (window.__trends === T) delete window.__trends; };
}
