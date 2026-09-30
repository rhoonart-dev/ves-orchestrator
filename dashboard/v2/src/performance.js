import {hiddenChannels} from './channel-visibility.js';
import {pagerHtml} from "./pager.js";
// 성과 — 예전 VES 대시보드 성과 탭(ves-orchestrator/dashboard/index.html renderPerf, v3.3)을 옮겼다.
// 계산(스냅샷 보간 → 일별 증가 · 수집률 · 전기 대비)과 인라인 SVG 차트는 원본 그대로, 화면 모양만 워크스페이스에 맞췄다.
// 데이터: perf_video_snapshot · perf_video_map · perf_channel_snapshot(perf_sync 가 매시간 레이블리에서 복사) — 읽기만.
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const kstDay = ts => new Date(ts || Date.now()).toLocaleDateString("sv", {timeZone:"Asia/Seoul"});
// PostgREST 는 한 번에 최대 1,000행만 준다(원본 대시보드의 .limit(60000) 은 조용히 잘렸다 — 30일 스냅샷 ≈1.2만 행).
// 첫 쪽에서 전체 개수를 받고 나머지 쪽은 6개씩 동시에 받는다. 결과는 {data, error} 모양 그대로.
async function pageAll(make, cap){
  const SIZE = 1000;
  const first = await make().range(0, SIZE - 1);
  if (first.error) return first;
  const total = Math.min(cap, first.count ?? (first.data || []).length), rows = [...(first.data || [])];
  const starts = []; for (let at = SIZE; at < total; at += SIZE) starts.push(at);
  for (let i = 0; i < starts.length; i += 6){
    const pages = await Promise.all(starts.slice(i, i + 6).map(at => make().range(at, Math.min(at + SIZE, total) - 1)));
    const bad = pages.find(r => r.error); if (bad) return bad;
    pages.forEach(r => rows.push(...(r.data || [])));
  }
  return { data: rows, error: null };
}
export function mountPerformance(root, {client = null} = {}){
if (!client){ root.innerHTML = '<p class="home-empty">로그인하면 성과를 볼 수 있어요.</p>'; return () => {}; }
let dead = false, chans = [], backfill = null, hiddenIds = new Set();   // hiddenIds: 숨긴 채널 channel_id
const P = window.__perf = {};
P.toggleFilter = () => { perfFilterOpen = !perfFilterOpen; render(); };
P.allCh = () => { perfChSet = null; perfPage = 0; render(); };
P.noCh = () => { perfChSet = new Set(); perfPage = 0; render(); };
root.classList.add("perf-page");   // 스타일은 src/performance.css — 원본 클래스 이름(.card·.pill·.pf-*)을 이 안에서만 쓴다
function render(){ if (!dead) renderPerf(); }
let perf = null, perfLoading = false, perfSort = { col: "dper", dir: -1 };
// 지표 셋을 한 페이지에 나란히 그린다. 영상 스냅샷에서 오는 것(views·likes)과 채널
// 스냅샷에서 오는 것(subs)이 섞여 있어 시리즈 키를 따로 든다 — subs 는 "누적"이 아니라
// 그 시점의 구독자 수라 누적 차트의 제목·해석이 다르다(absolute).
const PERF_METRICS = {
  views: { key: "cum", label: "조회수", daily: "일별 조회 증가", total: "누적 조회수",
           unit: "회", color: "var(--accent)" },
  likes: { key: "lik", label: "좋아요", daily: "일별 좋아요 증가", total: "누적 좋아요",
           unit: "개", color: "var(--accent)" },
  subs:  { key: "subs", label: "구독자", daily: "일별 구독자 증가", total: "구독자 수",
           unit: "명", color: "var(--accent)", absolute: true },
};
const PERF_COV_LOW = 0.7;   // 이 아래면 "그날 대부분이 보간 추정" — 차트에 음영으로 표시한다
// perf_sync 가 ops_config.perf_backfill_status 에 남기는 보완 상태.
// perf_sync.backfill_missing: 레이블리에 오늘치가 아직 없는 우리 영상을 유튜브 공개 API 로 직접 받아 채운다.
// ops_config.perf_backfill_status = {reason, pending, filled, at, date, channels:{channel_id: 그날 채운 편수}}.
// 채운 게 있으면 회색 안내로 채널별 편수를, 보완이 멈췄으면(api_key_missing·api_error) 빨간 안내를 띄운다.
function perfBackfillNote(){
  const row = backfill;
  if (!row || !row.value) return "";
  let d; try { d = JSON.parse(row.value); } catch(e){ return ""; }
  const crit = ["api_key_missing", "api_error"].includes(d.reason) && d.pending;
  const day = d.date || (d.at ? kstDay(d.at) : "");
  const dayLabel = day ? `${+day.slice(5, 7)}월 ${+day.slice(8)}일` : "";
  const name = id => (chans.find(c => c.channel_id === id) || {}).name || "채널";
  // 채널 필터를 걸었으면 그 채널 줄만(필터는 채널 이름으로 고른다 — 차트·표와 같은 기준)
  const counts = (d.channels ? Object.entries(d.channels).filter(([, n]) => n > 0) : (d.filled ? [[null, d.filled]] : []))
    .filter(([id]) => !id || !hiddenIds.has(id))
    .filter(([id]) => !perfChSet || !id || perfChSet.has(chNameById(id)));
  if (!crit && !counts.length) return "";
  const lines = counts.map(([id, n]) => `<p><b>${esc(dayLabel)}</b> ${id ? `<em>${esc(name(id))}</em> 채널의 ` : ""}영상 <em>${fmtN(n)}</em>편의 성과를 유튜브에서 직접 가져왔어요</p>`).join("");
  const stop = crit ? `<p class="pf-stop">${d.reason === "api_key_missing"
    ? `맥미니에 유튜브 API 키(YOUTUBE_API_KEY)가 없어서 영상 <em>${fmtN(d.pending)}</em>편을 채우지 못하고 있어요`
    : `유튜브 API 호출이 실패해서 영상 <em>${fmtN(d.pending)}</em>편을 채우지 못했어요. 키가 만료됐거나 하루 사용량을 넘겼을 수 있어요`}</p>` : "";
  return `<section class="pf-notice${crit ? " crit" : ""}"><p>성과 데이터는 <b>레이블리</b>에서 매시간 가져와요</p>
    <p>레이블리에 아직 없는 기록은 <b>VES</b>가 유튜브에서 직접 받아 채워요</p>
    ${lines || stop ? `<blockquote>${lines}${stop}</blockquote>` : ""}</section>`;
}
let perfFrom = null, perfTo = null;   // 직접 지정 구간(YYYY-MM-DD). 있으면 프리셋보다 우선
let perfVid = null;                   // 상세를 펼친 영상(content_id)
let perfPage = 0; const PERF_PAGE = 10;   // 영상 표 — 10편씩 넘겨 본다
// 채널 멀티 필터 — null=전체, Set=선택된 채널들(빈 Set=전부 해제). 차트·표 전부에 걸린다.
let perfChSet = null, perfFilterOpen = false;
let perfDays = 28;   // 기간 프리셋(일) — 0 이면 보유 전체
let perfLoadedDays = 0;      // 지금 perf 에 담긴 스냅샷 창(일). 더 긴 기간을 고르면 다시 받는다
const PERF_RANGES = [[7, "7일"], [14, "14일"], [28, "28일"], [90, "90일"], [0, "전체"]];
const PERF_MAX_DAYS = 120;   // perf_sync KEEP_DAYS 와 짝 — 미러가 보관하는 상한
// 구간 첫날의 증가분을 내려면 하루 전 값이 있어야 한다 → 고른 기간 + 이틀
const perfWant = d => d > 0 ? Math.min(d + 2, PERF_MAX_DAYS) : PERF_MAX_DAYS;
// 지금 화면이 요구하는 로드 창(일). 직접 지정 구간은 그 시작일까지 거슬러 필요하다.
function perfNeedDays(){
  if (!perfFrom) return perfWant(perfDays);
  const back = Math.round((Date.parse(kstDay() + "T00:00:00Z") - Date.parse(perfFrom + "T00:00:00Z")) / DAY_MS);
  return Math.min(PERF_MAX_DAYS, Math.max(3, back + 2));
}
const fmtN = v => v == null ? "—" : Number(v).toLocaleString("ko-KR");
const fmtD = v => v == null ? "—" : (v > 0 ? "+" : "") + Number(v).toLocaleString("ko-KR");
// 축·타일용 축약 — 12,345 → 1.2만
const fmtK = v => { const n = Math.abs(Number(v) || 0);
  return n >= 10000 ? (v / 10000).toFixed(n >= 100000 ? 0 : 1) + "만"
       : n >= 1000 ? (v / 1000).toFixed(1) + "천" : String(Math.round(v)); };
const chNameById = id => { const c = chans.find(x => x.channel_id === id);
  return (c && c.name) || (id || "").slice(0,10); };
const DAY_MS = 86400000;
const dayAdd = (ds, n) => new Date(Date.parse(ds + "T00:00:00Z") + n * DAY_MS).toISOString().slice(0,10);
const mmdd = ds => ds.slice(5).replace("-", "/");

async function loadPerf(days){
  if (perfLoading) return; perfLoading = true;
  const want = perfWant(days);
  const from = dayAdd(kstDay(), -want);
  try {
    const [vs, vm, cs, ch, bf] = await Promise.all([
      // 고른 기간만큼만 받는다 — 실측 2026-08 은 영상 291 × 40일 ≈ 4.9천 행이지만
      // 영상이 늘면 (영상 수 × 일수)로 커진다. 한도에 닿으면 서버 집계 RPC 로 옮길 것.
      pageAll(() => client.from("perf_video_snapshot").select("content_id,snapshot_date,view_count,like_count", {count: "exact"})
        .gte("snapshot_date", from).order("snapshot_date").order("content_id"), 60000),
      pageAll(() => client.from("perf_video_map").select("*", {count: "exact"}).order("content_id"), 3000),
      pageAll(() => client.from("perf_channel_snapshot").select("*", {count: "exact"}).gte("snapshot_date", from)
        .order("snapshot_date").order("channel_id"), 20000),
      client.from("channels_mirror").select("channel_id,name,token_slug"),
      client.from("ops_config").select("value").eq("key", "perf_backfill_status").maybeSingle(),
    ]);
    // 숨긴 채널(ops_config.workspace_hidden_channels)은 성과 전부에서 뺀다 — 영상·스냅샷·채널 요약·안내 줄
    const hidden = await hiddenChannels(client);
    const gone = new Set((ch.data || []).filter(c => hidden.has(c.token_slug)).map(c => c.channel_id));
    chans = (ch.data || []).filter(c => !gone.has(c.channel_id)); backfill = bf.data || null;
    if (vs.error || vm.error || cs.error) throw new Error((vs.error||vm.error||cs.error).message);
    const vmap = (vm.data||[]).filter(m => !gone.has(m.channel_id)), keep = new Set(vmap.map(m => m.content_id));
    const vsnap = (vs.data||[]).filter(s => keep.has(s.content_id));
    perf = vsnap.length ? { vs: vsnap, vm: vmap, cs: (cs.data||[]).filter(s => !gone.has(s.channel_id)) } : { empty: true };
    hiddenIds = gone;
    perfLoadedDays = want;
  } catch(e){ perf = { error: String(e.message || e) }; }
  finally { perfLoading = false; render(); }
}

// 영상 하나의 관측점(o) 을 매일 값으로 편다. ix 는 관측 항목(1=조회, 2=좋아요).
// 보유 구간 안에서 발행된 영상은 발행일 0 에서 출발한다 — 첫 스냅샷까지의 조회가 발행
// 이후 날들로 분배된다. 구간 밖 발행분은 첫 관측값이 기준선일 뿐(증가로 세지 않음).
function perfInterp(o, ix, N, pubI){
  const arr = new Array(N).fill(null);
  let pi, pv;
  if (pubI != null && pubI < o[0][0]) { pi = pubI; pv = 0; }
  else { pi = o[0][0]; pv = o[0][ix]; }
  arr[pi] = pv;
  o.forEach(pt => { const i = pt[0], v = pt[ix];
    if (i <= pi) { arr[i] = v; return; }
    const span = i - pi, dv = v - pv;
    for (let k = 1; k <= span; k++) arr[pi + k] = Math.round(pv + dv * k / span);
    pi = i; pv = v;
  });
  for (let k = pi + 1; k < N; k++) arr[k] = pv;   // 마지막 관측 이후는 값 유지(증가 0)
  return arr;
}

// 원본 → 파생. 영상별 일별 시리즈(보간)와 채널별 합계를 만든다 — perf 를 새로 받을 때 한 번만.
function perfBuild(){
  if (perf.built) return perf.built;
  let min = null, max = null;
  perf.vs.forEach(s => { const d = s.snapshot_date;
    if (!min || d < min) min = d; if (!max || d > max) max = d; });
  const dates = []; for (let d = min; d <= max; d = dayAdd(d, 1)) dates.push(d);
  const N = dates.length, at = new Map(dates.map((d, i) => [d, i]));

  const obs = new Map();   // content_id → [[날짜인덱스, 조회, 좋아요], ...]
  perf.vs.forEach(s => { const i = at.get(s.snapshot_date); if (i === undefined) return;
    let a = obs.get(s.content_id); if (!a) obs.set(s.content_id, a = []);
    a.push([i, Number(s.view_count)||0, Number(s.like_count)||0]); });

  const vids = [];
  perf.vm.forEach(m => {
    const o = (obs.get(m.content_id) || []).sort((x, y) => x[0] - y[0]);
    if (!o.length) return;                       // 스냅샷이 아직 없는 영상 — 표·차트에서 제외
    const pub = m.published_at ? kstDay(m.published_at) : null;
    const pubI = pub && at.has(pub) ? at.get(pub) : null;
    const last = o[o.length - 1];
    vids.push({ cid: m.content_id, chId: m.channel_id, ch: chNameById(m.channel_id),
      title: m.title || m.content_id, work: m.work_title || "", dead: !!m.dead_at,
      pub: pub || "", cum: perfInterp(o, 1, N, pubI), lik: perfInterp(o, 2, N, pubI),
      obs: new Set(o.map(x => x[0])), views: last[1], likes: last[2] });
  });

  const chans = new Map();
  const ensure = (chId) => { const ch = chNameById(chId); let g = chans.get(ch);
    if (!g) chans.set(ch, g = { ch, chId, cum: new Array(N).fill(0), lik: new Array(N).fill(0),
      ups: new Array(N).fill(0), subs: new Array(N).fill(null),
      chViews: new Array(N).fill(null), vids: 0,
      seen: new Array(N).fill(0), live: new Array(N).fill(0) });
    return g; };
  vids.forEach(v => { const g = ensure(v.chId); g.vids++;
    for (let i = 0; i < N; i++){
      if (v.cum[i] != null) g.cum[i] += v.cum[i];
      if (v.lik[i] != null) g.lik[i] += v.lik[i];
    } });
  // 업로드 수는 vm 전체에서 센다 — 방금 발행돼 아직 스냅샷이 없는 영상도 올라간 건 올라간 것.
  perf.vm.forEach(m => { if (!m.published_at) return;
    const i = at.get(kstDay(m.published_at)); if (i === undefined) return;
    ensure(m.channel_id).ups[i]++; });
  // 일별 수집률 = 그날 스냅샷이 찍힌 영상 ÷ 그날 살아 있던 영상.
  // 원천 수집이 성겼던 구간(2026-06~07 실측 27~32%)의 증가값은 관측이 아니라 보간 추정이다.
  const chOf = new Map(perf.vm.map(m => [m.content_id, m.channel_id]));
  perf.vm.forEach(m => {
    if (!m.published_at) return;
    const pd = kstDay(m.published_at);
    const from = at.has(pd) ? at.get(pd) : (pd < dates[0] ? 0 : -1);
    if (from < 0) return;                         // 보유 구간 뒤에 올라온 영상
    let to = N - 1;
    if (m.dead_at){ const dd = kstDay(m.dead_at);
      if (at.has(dd)) to = at.get(dd); else if (dd < dates[0]) return; }
    const g = ensure(m.channel_id);
    for (let i = from; i <= to; i++) g.live[i]++;
  });
  perf.vs.forEach(s => { const i = at.get(s.snapshot_date); if (i === undefined) return;
    const cid = chOf.get(s.content_id); if (cid === undefined) return;
    ensure(cid).seen[i]++; });
  // 채널 스냅샷(구독자·채널 누적 조회) — 결측일은 직전 값을 끌고 간다
  const csAt = new Map();
  perf.cs.forEach(s => { const i = at.get(s.snapshot_date); if (i === undefined) return;
    const g = ensure(s.channel_id); let arr = csAt.get(g.ch);
    if (!arr) csAt.set(g.ch, arr = new Array(N).fill(null));
    arr[i] = s; });
  chans.forEach(g => { const arr = csAt.get(g.ch); if (!arr) return;
    let ls = null, lv = null;
    for (let i = 0; i < N; i++){ const s = arr[i];
      if (s){ ls = Number(s.subscriber_count); lv = Number(s.view_count); }
      g.subs[i] = ls; g.chViews[i] = lv; } });

  perf.built = { dates, N, vids, chans: [...chans.values()], maxDate: max, minDate: min };
  return perf.built;
}

// 기간·채널 필터를 적용한 뷰 — 타일·차트·표가 전부 이걸 본다.
function perfView(){
  const B = perfBuild(), N = B.N;
  // 표시 구간 [a..b] — 직접 지정한 날짜는 보유 범위 밖이면 가까운 쪽으로 붙인다
  let a, b;
  if (perfFrom || perfTo){
    const i0 = perfFrom ? B.dates.findIndex(d => d >= perfFrom) : 0;
    a = i0 < 0 ? N - 1 : i0;
    b = N - 1;
    if (perfTo){ let k = -1; B.dates.forEach((d, i) => { if (d <= perfTo) k = i; }); b = k < 0 ? a : k; }
    if (b < a) b = a;
  } else {
    a = N - (perfDays > 0 ? Math.min(perfDays, N) : N); b = N - 1;
  }
  const span = b - a + 1;
  const sel = B.chans.filter(g => !perfChSet || perfChSet.has(g.ch));
  const dates = B.dates.slice(a, b + 1);
  const at = (key, i) => sel.reduce((t, g) => t + (g[key][i] || 0), 0);
  const seriesOf = key => dates.map((_, i) => at(key, a + i));
  const before = key => a > 0 ? at(key, a - 1) : null;   // 구간 첫날의 증가분을 낼 기준점
  const dailyOf = (arr, prev) => arr.map((v, i) => i ? v - arr[i-1] : (prev == null ? 0 : v - prev));

  // 지표 셋을 한꺼번에 만든다 — 화면이 셋을 나란히 그린다
  const metrics = {};
  Object.keys(PERF_METRICS).forEach(k => { const M = PERF_METRICS[k];
    const total = seriesOf(M.key), daily = dailyOf(total, before(M.key));
    metrics[k] = { M, total, daily, end: total[total.length-1],
                   gain: daily.reduce((t, v) => t + v, 0) }; });
  const ups = seriesOf("ups"), upTotal = ups.reduce((t, v) => t + v, 0);
  // 수집률(0~1) — 낮은 날은 차트에 음영으로 표시하고 툴팁에도 적는다
  const cov = dates.map((_, i) => { const live = at("live", a + i);
    return live ? Math.min(1, at("seen", a + i) / live) : null; });
  const covOk = cov.filter(v => v != null);
  const covAvg = covOk.length ? covOk.reduce((t, v) => t + v, 0) / covOk.length : null;
  const covLow = cov.filter(v => v != null && v < PERF_COV_LOW).length;
  const cum = metrics.views.total, gain = metrics.views.gain;
  // 전기(같은 길이의 직전 구간) 조회 증가 — 비교할 데이터가 있을 때만
  const prevGain = (a - span - 1 >= 0) ? at("cum", a - 1) - at("cum", a - span - 1) : null;

  // 채널별 요약(같은 구간) — 표·막대·스파크라인이 같은 행을 쓴다
  const rowsCh = sel.map(g => {
    const take = key => { const arr = g[key].slice(a, b + 1);
      const prev = a > 0 ? g[key][a-1] : arr[0];
      return { arr, end: arr[arr.length-1], gain: (arr[arr.length-1] || 0) - (prev || 0) }; };
    const v = take("cum"), l = take("lik");
    return { ch: g.ch, chId: g.chId, vids: g.vids,
      upsArr: g.ups.slice(a, b + 1), ups: g.ups.slice(a, b + 1).reduce((t, x) => t + x, 0),
      gain: v.gain, cum: v.end, likes: l.end, likeGain: l.gain,
      subs: g.subs[b], dsubs: (g.subs[b] != null && g.subs[a] != null) ? g.subs[b] - g.subs[a] : null,
      chViews: g.chViews[b],
      series: v.arr.map((x, i) => i ? x - v.arr[i-1] : 0) };
  }).sort((x, y) => (y.gain||0) - (x.gain||0));

  // 영상별 행 — "기간 조회수"는 구간 시작 직전 값 대비, 즉 그 기간에 벌어들인 조회수다
  const rowsVid = B.vids.filter(v => !perfChSet || perfChSet.has(v.ch)).map(v => {
    const span2 = arr => { const cb = arr[b], prev = a > 0 ? arr[a-1] : arr[a];
      return cb == null ? null : cb - (prev == null ? 0 : prev); };
    return { title: v.title, work: v.work, ch: v.ch, cid: v.cid, dead: v.dead, pub: v.pub,
      views: v.cum[b] == null ? v.views : v.cum[b],
      dper: span2(v.cum), likes: v.lik[b] == null ? v.likes : v.lik[b], dlike: span2(v.lik),
      isNew: !!(v.pub && v.pub >= dates[0]) };
  });
  const fresh = rowsVid.filter(r => r.isNew);
  return { B, a, b, span, dates, metrics, cum, ups, cov, covAvg, covLow,
    daily: metrics.views.daily, gain, prevGain,
    likeNow: metrics.likes.end, likeGain: metrics.likes.gain,
    subsNow: at("subs", b), dsubs: at("subs", b) - at("subs", a), chViewNow: at("chViews", b),
    upTotal, rowsCh, rowsVid, freshCount: fresh.length,
    freshAvg: fresh.length ? Math.round(fresh.reduce((t, r) => t + (r.views||0), 0) / fresh.length) : null };
}

// ── 인라인 SVG 차트 (대시보드는 단일 파일 자급자족 — 차트 라이브러리를 두지 않는다) ──
// 원천 수집이 성겼던 날은 값이 관측이 아니라 보간 추정이다 — 그 구간에 음영을 깔아
// "여기는 덜 믿을 값"이라고 화면이 먼저 말하게 한다(연속 구간은 하나로 묶어 그린다).
function pfCovBand(cov, X, n, pw, T, ph){
  if (!cov.length) return "";
  const w = pw / Math.max(1, n), out = [];
  let from = -1;
  const flush = to => { if (from < 0) return;
    const x0 = X(from) - w / 2, x1 = X(to) + w / 2;
    out.push(`<rect x="${x0.toFixed(1)}" y="${T}" width="${(x1 - x0).toFixed(1)}" height="${ph}"
      fill="var(--muted)" opacity=".13"/>`); from = -1; };
  cov.forEach((v, i) => { const low = v != null && v < PERF_COV_LOW;
    if (low && from < 0) from = i;
    if (!low) flush(i - 1); });
  flush(n - 1);
  return out.join("");
}
const pfCovTip = v => v == null ? "" :
  ` · 수집 ${Math.round(v * 100)}%${v < PERF_COV_LOW ? " (추정치)" : ""}`;
// 선택 지표의 일별 증가(라인/영역) + 업로드 수(막대) 콤보. 날짜마다 투명 rect 를 깔아 툴팁.
function pfCombo(dates, daily, ups, M, W, H, cov){
  W = W || 560; H = H || 240; cov = cov || [];
  const hasUp = ups.some(u => u), L = 52, R = hasUp ? 40 : 12, T = 14, BM = 28;
  const pw = W - L - R, ph = H - T - BM, n = dates.length;
  const hi = Math.max(1, ...daily), lo = Math.min(0, ...daily);
  const maxU = Math.max(1, ...ups);
  const X = i => n === 1 ? L + pw / 2 : L + pw * i / (n - 1);
  const Y = v => T + ph - ph * (v - lo) / (hi - lo);
  const uh = ph * 0.4, bw = Math.max(3, Math.min(20, (pw / Math.max(1, n)) * 0.55));
  const pts = daily.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const step = Math.max(1, Math.ceil(n / 8));
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="일별 조회 증가와 업로드 수">
    ${[hi, (hi + lo) / 2, lo].map(v => `<line class="gl" x1="${L}" x2="${L + pw}"
      y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke-dasharray="${v === 0 ? "" : "3 4"}"/>
      <text class="ax" x="${L - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${fmtK(v)}</text>`).join("")}
    ${pfCovBand(cov, X, n, pw, T, ph)}
    ${!hasUp ? "" : ups.map((u, i) => u ? `<rect x="${(X(i) - bw / 2).toFixed(1)}"
      y="${(T + ph - uh * u / maxU).toFixed(1)}" width="${bw.toFixed(1)}"
      height="${(uh * u / maxU).toFixed(1)}" rx="2" fill="var(--info)" opacity=".5"/>` : "").join("")}
    <polygon points="${X(0).toFixed(1)},${Y(lo).toFixed(1)} ${pts} ${X(n-1).toFixed(1)},${Y(lo).toFixed(1)}"
      fill="${M.color}" opacity=".09"/>
    <polyline points="${pts}" fill="none" stroke="${M.color}" stroke-width="2.2"
      stroke-linejoin="round" stroke-linecap="round"/>
    ${n <= 45 ? daily.map((v, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(v).toFixed(1)}" r="2.6"
      fill="${M.color}"/>`).join("") : ""}
    ${hasUp ? `<text class="ax" x="${L + pw + 8}" y="${(T + ph - uh).toFixed(1)}"
      fill="var(--info)">${maxU}편</text>` : ""}
    ${dates.map((d, i) => i % step === 0 || i === n - 1
      ? `<text class="ax" x="${X(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${mmdd(d)}</text>` : "").join("")}
    ${dates.map((d, i) => `<rect class="hit" x="${(X(i) - pw / Math.max(1, n) / 2).toFixed(1)}" y="${T}"
      width="${(pw / Math.max(1, n)).toFixed(1)}" height="${ph}" fill="transparent"
      ><title>${esc(d)} · ${M.label} ${fmtD(daily[i])}${M.unit}${
        hasUp ? ` · 업로드 ${ups[i]}편` : ""}${pfCovTip(cov[i])}</title></rect>`).join("")}
  </svg>`;
}

// 선택 지표의 누적(구독자는 그 시점 값) — 세로축을 0 부터 잡으면 변화가 안 보여
// 데이터 범위에 맞춘다(캡션에 명시).
function pfArea(dates, cum, M, W, H, cov){
  W = W || 560; H = H || 240; cov = cov || [];
  const L = 52, R = 12, T = 14, BM = 28;
  const pw = W - L - R, ph = H - T - BM, n = dates.length;
  const hi = Math.max(...cum), lo = Math.min(...cum);
  const pad = (hi - lo) * 0.15 || Math.max(1, hi * 0.02);
  const y0 = Math.max(0, lo - pad), y1 = hi + pad;
  const X = i => n === 1 ? L + pw / 2 : L + pw * i / (n - 1);
  const Y = v => T + ph - ph * (v - y0) / (y1 - y0 || 1);
  const pts = cum.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  const step = Math.max(1, Math.ceil(n / 8));
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="누적 조회수 추이">
    ${[y1, (y0 + y1) / 2, y0].map(v => `<line class="gl" x1="${L}" x2="${L + pw}"
      y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke-dasharray="3 4"/>
      <text class="ax" x="${L - 8}" y="${(Y(v) + 4).toFixed(1)}" text-anchor="end">${fmtK(v)}</text>`).join("")}
    ${pfCovBand(cov, X, n, pw, T, ph)}
    <polygon points="${X(0).toFixed(1)},${(T + ph).toFixed(1)} ${pts} ${X(n-1).toFixed(1)},${(T + ph).toFixed(1)}"
      fill="${M.color}" opacity=".14"/>
    <polyline points="${pts}" fill="none" stroke="${M.color}" stroke-width="2.2"
      stroke-linejoin="round"/>
    ${dates.map((d, i) => i % step === 0 || i === n - 1
      ? `<text class="ax" x="${X(i).toFixed(1)}" y="${H - 8}" text-anchor="middle">${mmdd(d)}</text>` : "").join("")}
    ${dates.map((d, i) => `<rect class="hit" x="${(X(i) - pw / Math.max(1, n) / 2).toFixed(1)}" y="${T}"
      width="${(pw / Math.max(1, n)).toFixed(1)}" height="${ph}" fill="transparent"
      ><title>${esc(d)} · ${esc(M.total)} ${fmtN(cum[i])}${M.unit}${pfCovTip(cov[i])}</title></rect>`).join("")}
  </svg>`;
}

// 채널 표에 들어가는 미니 추이선(선택 지표의 일별 증가)
// 채널 표 '최근 흐름' — 작은 일별 막대(마지막 k일은 진하게) + 최근 k일 합계와 직전 k일 대비 변화.
// 선 한 줄(스파크라인)은 행마다 눈금이 달라 크기를 읽을 수 없었다 — 숫자와 방향을 같이 보여 준다.
function pfTrend(vals, dates){
  const n = vals.length; if (!n) return "";
  const k = Math.max(1, Math.min(7, Math.floor(n / 2)));
  const sum = arr => arr.reduce((t, v) => t + Math.max(0, v || 0), 0);
  const recent = sum(vals.slice(n - k)), prev = n >= 2 * k ? sum(vals.slice(n - 2 * k, n - k)) : null;
  const pct = prev ? Math.round((recent - prev) / prev * 100) : null;
  const hi = Math.max(1, ...vals.map(v => Math.max(0, v || 0)));
  const W = 120, H = 30, gap = 1, bw = Math.max(1, (W - gap * (n - 1)) / n);
  let peak = 0; vals.forEach((v, i) => { if ((v || 0) > (vals[peak] || 0)) peak = i; });
  const bars = vals.map((v, i) => { const h = Math.max(1, (H - 2) * Math.max(0, v || 0) / hi);
    return `<rect x="${(i * (bw + gap)).toFixed(1)}" y="${(H - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="1"
      fill="var(--accent)" opacity="${i >= n - k ? 1 : .28}"/>`; }).join("");
  const tip = `최근 ${k}일 ${fmtN(recent)}회${prev != null ? ` · 직전 ${k}일 ${fmtN(prev)}회` : ""}${dates && dates[peak] ? ` · 최고 ${mmdd(dates[peak])} ${fmtN(vals[peak])}회` : ""}`;
  return `<div class="pf-trend" title="${esc(tip)}"><svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">${bars}</svg>
    <span><b>${fmtK(recent)}</b><small>최근 ${k}일</small></span>
    <em class="${pct == null ? "" : pct >= 0 ? "up" : "dn"}">${pct == null ? "—" : `${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct)}%`}</em></div>`;
}
function pfSpark(vals, w, h, color){
  const n = vals.length; if (!n) return "";
  const hi = Math.max(1, ...vals), lo = Math.min(0, ...vals);
  const X = i => n === 1 ? w / 2 : w * i / (n - 1);
  const Y = v => h - 1 - (h - 2) * (v - lo) / (hi - lo || 1);
  return `<svg class="pf-spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"
    preserveAspectRatio="none" aria-hidden="true"><polyline fill="none" stroke="${color}"
    stroke-width="1.6" points="${vals.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ")}"/></svg>`;
}

// 채널별 영상 개수 — 기간 안에 올린 분(밝은 파랑)과 그 전부터 있던 분을 이어 붙인 가로 막대.
function pfChBars(V){
  const rows = V.rowsCh.slice().sort((x, y) => y.vids - x.vids);
  const max = Math.max(1, ...rows.map(r => r.vids));
  return `<div class="pf-cb">${rows.map(r => { const old = Math.max(0, r.vids - r.ups);
    return `<div class="nm ${perfChSet && perfChSet.has(r.ch) ? "sel" : ""}"
        title="누르면 이 채널만 봐요" onclick="__perf.perfChOnly('${esc(r.ch)}')">${esc(r.ch)}</div>
      <div class="bar" title="${esc(r.ch)} · 추적 영상 ${r.vids}편 (최근 ${V.span}일 업로드 ${r.ups}편)">
        <i style="width:${(old / max * 100).toFixed(1)}%"></i>
        <b style="width:${(Math.min(r.ups, r.vids) / max * 100).toFixed(1)}%"></b></div>
      <div class="n">${fmtN(r.vids)}<span>${r.ups ? " +" + r.ups : ""}</span></div>`; }).join("")
    || '<div class="empty">채널 없음</div>'}</div>`;
}

// 업로드 히트맵 — "어느 채널이 며칠에 몇 편 올렸나" 를 한 판에. 진할수록 그날 편수가 많다.
function pfHeat(V){
  const dates = V.dates, n = dates.length, today = kstDay();
  const rows = V.rowsCh.slice().sort((a, b) => (b.ups||0) - (a.ups||0));
  const maxU = Math.max(1, ...rows.flatMap(r => r.upsArr));
  const step = Math.max(1, Math.ceil(n / 10));
  const cols = `grid-template-columns:repeat(${n},minmax(0,1fr))`;
  return `<div class="pf-heat">
    <div></div><div class="row" style="${cols}">${dates.map((d, i) =>
      `<div class="hd">${i % step === 0 || i === n - 1 ? mmdd(d) : ""}</div>`).join("")}</div>
    ${rows.map(r => `<div class="nm ${perfChSet && perfChSet.has(r.ch) ? "sel" : ""}"
        title="누르면 이 채널만 봐요" onclick="__perf.perfChOnly('${esc(r.ch)}')">${esc(r.ch)}</div>
      <div class="row" style="${cols}">${r.upsArr.map((u, i) => `<div
        class="c ${u ? "up" : ""} ${dates[i] === today ? "today" : ""}"
        ${u ? `style="opacity:${(0.3 + 0.7 * u / maxU).toFixed(2)}"` : ""}
        title="${esc(r.ch)} · ${esc(dates[i])} · ${u ? u + "편 업로드" : "업로드 없음"}"></div>`).join("")}</div>`).join("")
    || '<div class="empty">채널 없음</div>'}
  </div>`;
}

// 영상 하나의 상세 — 표에서 행을 누르면 그 아래로 펼친다(대시보드 관행: bdetail).
// 차트는 표시 구간이 아니라 그 영상이 살아온 전 구간을 그린다 — 발행 직후 급상승이
// 구간 밖으로 잘려 나가면 영상을 판단할 수 없다.
function pfVidDetail(V, cid){
  const v = V.B.vids.find(x => x.cid === cid);
  if (!v) return '<div class="empty">이 영상은 아직 데이터가 없어요</div>';
  let s0 = v.cum.findIndex(x => x != null); if (s0 < 0) s0 = 0;
  const ds = V.B.dates.slice(s0), cum = v.cum.slice(s0), lik = v.lik.slice(s0);
  const dOf = arr => arr.map((x, i) => i ? (x||0) - (arr[i-1]||0) : 0);
  // 이 영상이 실제로 찍힌 날 = 1, 아니면 0 — 차트가 추정 구간에 음영을 깐다
  const cov = ds.map((_, i) => v.obs.has(s0 + i) ? 1 : 0);
  const miss = cov.filter(x => !x).length;
  const views = cum[cum.length-1] || 0, likes = lik[lik.length-1] || 0;
  const prevC = V.a > 0 ? v.cum[V.a-1] : v.cum[V.a];
  const gain = (v.cum[V.b] || 0) - (prevC || 0);
  const pubI = v.pub ? V.B.dates.indexOf(v.pub) : -1;
  const age = v.pub ? Math.round((Date.parse(V.B.maxDate + "T00:00:00Z")
                                - Date.parse(v.pub + "T00:00:00Z")) / DAY_MS) + 1 : null;
  // 첫날·첫 7일은 그 시기 스냅샷이 있어야 낼 수 있다 — 보유 구간 밖 발행분은 알 수 없다
  const at = k => pubI >= 0 ? (v.cum[Math.min(pubI + k, V.B.N - 1)] || 0) - (v.cum[pubI] || 0) : null;
  const d1 = at(1), d7 = at(7);
  const box = (val, k, tip) => `<span title="${esc(tip||"")}"><b>${val}</b>${k}</span>`;
  return `<div class="pf-vd">
    <img class="th" src="https://i.ytimg.com/vi/${esc(cid)}/mqdefault.jpg" alt=""
      loading="lazy" onerror="this.remove()">
    <div class="meta">
      <div class="t">${v.dead ? '<span class="sub" title="내려간 영상">†</span> ' : ""}${esc(v.title)}</div>
      <div class="m">${esc(v.ch)}${v.work ? " · " + esc(v.work) : ""}${
        v.pub ? " · " + esc(v.pub) + " 게시" : ""}${age ? ` · ${age}일째` : ""}
        · <a href="https://youtu.be/${esc(cid)}" target="_blank" rel="noopener">유튜브에서 열기 ↗</a></div>
      <div class="kpis">
        ${box(fmtN(views), "누적 조회")}
        ${box(fmtD(gain), `최근 ${V.span}일 조회`)}
        ${box(fmtN(likes), "좋아요")}
        ${box(views ? (likes / views * 100).toFixed(2) + "%" : "—", "좋아요율", "좋아요 ÷ 누적 조회")}
        ${box(age ? fmtN(Math.round(views / age)) : "—", "하루 평균", "누적 조회 ÷ 게시 후 일수")}
        ${box(d1 == null ? "—" : fmtN(d1), "첫날",
          d1 == null ? "모아 둔 기간보다 먼저 올린 영상이라 알 수 없어요" : "올린 다음 날까지 조회수")}
        ${box(d7 == null ? "—" : fmtN(d7), "첫 7일",
          d7 == null ? "모아 둔 기간보다 먼저 올린 영상이라 알 수 없어요" : "올린 뒤 7일까지 조회수")}
      </div>
    </div>
  </div>
  <p class="pf-idx">올린 날부터 지금까지 전체 (위 기간과 무관)${miss ? ` · 회색 = 데이터 없는 날 ${miss}일` : ""}</p>
  <div class="pf-duo two">
    <div><div class="pf-cap">일별 조회 증가</div>
      ${pfCombo(ds, dOf(cum), [], PERF_METRICS.views, 520, 200, cov)}</div>
    <div><div class="pf-cap">누적 조회수</div>
      ${pfArea(ds, cum, PERF_METRICS.views, 520, 200, cov)}</div>
    <div><div class="pf-cap">일별 좋아요 증가</div>
      ${pfCombo(ds, dOf(lik), [], PERF_METRICS.likes, 520, 200, cov)}</div>
    <div><div class="pf-cap">누적 좋아요</div>
      ${pfArea(ds, lik, PERF_METRICS.likes, 520, 200, cov)}</div>
  </div>
`;
}

// 지표 한 덩어리(일별 증가 + 누적) — 조회수·좋아요·구독자를 같은 판형으로 나란히 놓는다
function pfMetricCard(V, k, withUps){
  const m = V.metrics[k], M = m.M;
  const head = M.absolute
    ? `지금 ${fmtN(m.end)}${M.unit} · ${V.span}일 ${fmtD(m.gain)}`
    : `${V.span}일 ${fmtD(m.gain)}${M.unit} · 누적 ${fmtN(m.end)}`;
  const idx = [M.absolute ? "채널 전체 기준" : "", V.covLow ? `회색 = 데이터 부족 ${V.covLow}일` : ""].filter(Boolean).join(" · ");
  return `<section class="card pf-chart"><h2>${esc(M.label)}${idx ? ` <small class="pf-idx">${esc(idx)}</small>` : ""}
      <span class="pf-sum" style="color:${M.color}">${head}</span></h2>
    <div class="pf-duo">
      <div><div class="pf-cap">${esc(M.daily)}${withUps
        ? ' <i class="lg" style="background:var(--info)"></i>그날 올린 영상 수 (오른쪽 눈금)' : ""}</div>
        ${pfCombo(V.dates, m.daily, withUps ? V.ups : [], M, 0, 0, V.cov)}</div>
      <div><div class="pf-cap">${esc(M.total)}</div>${pfArea(V.dates, m.total, M, 0, 0, V.cov)}</div>
    </div>
  </section>`;
}

function renderPerf(){
  if (!perf){ loadPerf(perfFrom ? perfNeedDays() - 2 : perfDays);
    root.innerHTML = '<section class="card"><div class="empty">성과 불러오는 중…</div></section>'; return; }
  if (perf.error){
    root.innerHTML = `<section class="card"><h2>성과</h2><div class="empty">성과를 불러오지 못했어요: ${esc(perf.error)}
      <button class="mini" onclick="__perf.perfReload()">다시 시도</button></div></section>`; return; }
  if (perf.empty){
    root.innerHTML = `<section class="card"><h2>성과</h2><div class="empty">아직 모인 성과 데이터가 없어요. 1시간마다 채워져요.</div></section>`; return; }

  const V = perfView(), B = V.B;
  const chipChs = B.chans.map(g => g.ch).sort((x, y) => x.localeCompare(y, "ko"));
  const pct = (V.prevGain != null && V.prevGain > 0)
    ? Math.round((V.gain - V.prevGain) / V.prevGain * 100) : null;
  const perDay = V.span ? (V.upTotal / V.span) : 0;
  const custom = !!(perfFrom || perfTo);

  // 영상 표 — 정렬 후 상위 200
  const COLS = [["title","영상 제목"],["work","작품"],["ch","채널"],
    ["dper",`${V.span}일 조회`],["views","전체 누적"],["likes","좋아요"],["pub","게시일"]];
  const c = perfSort.col, dir = perfSort.dir;
  const vrows = V.rowsVid.slice().sort((x, y) => { const p = x[c], q = y[c];
    const cmp = (typeof p === "number" || typeof q === "number")
      ? (Number(p)||0) - (Number(q)||0) : String(p??"").localeCompare(String(q??""), "ko");
    return dir * cmp; });

  const pages = Math.max(1, Math.ceil(vrows.length / PERF_PAGE));
  if (perfPage >= pages) perfPage = pages - 1;
  const pageAt = perfPage * PERF_PAGE;
  const pager = pagerHtml({cur: perfPage, pages, label: "영상 표 페이지", prev: 'onclick="__perf.perfPageBy(-1)"', next: 'onclick="__perf.perfPageBy(1)"'});
  root.innerHTML = `
    <div class="pf-ctl">
      <span class="pf-seg">${PERF_RANGES.map(([d, l]) =>
        `<button class="${!custom && perfDays === d ? "on" : ""}" onclick="__perf.perfRange(${d})">${l}</button>`).join("")}</span>
      <span class="pf-dates ${custom ? "on" : ""}" title="기간을 직접 고를 수 있어요">
        <input type="date" value="${esc(perfFrom || V.dates[0])}" min="${esc(B.dates[0])}"
          max="${esc(B.maxDate)}" onchange="perfSetRange('from', this.value)">
        <span>~</span>
        <input type="date" value="${esc(perfTo || B.maxDate)}" min="${esc(B.dates[0])}"
          max="${esc(B.maxDate)}" onchange="perfSetRange('to', this.value)">
        ${custom ? '<button class="mini" onclick="__perf.perfSetRange(\'clear\')" title="기본 기간으로">✕</button>' : ""}
      </span>
      <span class="pill" title="모아 둔 기간이에요. 1시간마다 갱신돼요">보유 ${esc(B.dates[0])} ~ ${esc(B.maxDate)}</span>
      ${V.covAvg == null ? "" : `<span class="pill ${V.covAvg < PERF_COV_LOW ? "bad" : ""}"
        title="날마다 데이터가 모인 영상 비율의 평균이에요. 낮은 날은 앞뒤 값으로 채운 추정치예요">수집률 ${
        Math.round(V.covAvg * 100)}%${V.covLow ? ` · ${V.covLow}일 부족` : ""}</span>`}
      ${perfChSet ? `<span class="pill" style="color:var(--accent)">채널 ${perfChSet.size}개만</span>` : ""}
      <span class="sp"></span>
      <button class="mini ${perfChSet ? "on" : ""}"
        onclick="__perf.toggleFilter()">⏷ 채널 필터${perfChSet ? " 적용 중" : ""}</button>
      <button class="mini" onclick="__perf.perfReload()">새로고침</button>
    </div>
    ${perfFilterOpen ? `<div class="filters">
      <button class="mini" onclick="__perf.allCh()">✓ 전체 선택</button>
      <button class="mini" onclick="__perf.noCh()">✕ 전체 해제</button>
      <span style="border-left:1px solid var(--line);margin:0 2px"></span>
      ${chipChs.map(ch => { const g = B.chans.find(x => x.ch === ch);
        return `<button class="mini ${!perfChSet || perfChSet.has(ch) ? "on" : ""}"
        ${g.vids ? "" : 'style="opacity:.45" title="아직 모인 데이터가 없어요"'}
        onclick="__perf.perfChToggle('${esc(ch)}')">${esc(ch)} <span style="opacity:.6">${g.vids}</span></button>`; }).join("")}
    </div>` : ""}

    ${perfBackfillNote()}
    ${V.covLow >= Math.max(3, V.span * 0.25) ? `<section class="pf-notice"><p><b>이 기간 중 ${V.covLow}일은 조회수가 ${Math.round(PERF_COV_LOW*100)}%도 안 모였어요</b></p>
      <p>그날그날 숫자보다 기간 합계를 보세요 · 차트의 회색 부분</p></section>` : ""}
    <div class="pf-kpi">
      <div class="tile"><div class="v">${fmtN(V.gain)}</div><div class="k">${V.span}일 조회수</div>
        <div class="d ${pct == null ? "" : pct >= 0 ? "up" : "dn"}">${
          pct == null ? "비교할 이전 기간 없음" : `${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct)}% · 직전 ${V.span}일 ${fmtN(V.prevGain)}`}</div></div>
      <div class="tile"><div class="v">${fmtN(V.cum[V.cum.length-1])}</div><div class="k">누적 조회수 (관리 영상)</div>
        <div class="d" title="우리가 만들지 않은 영상까지 합친 채널 전체 조회수예요">채널 전체 ${fmtN(V.chViewNow)}</div></div>
      <div class="tile"><div class="v">${fmtN(V.upTotal)}<span style="font-size:15px">편</span></div>
        <div class="k">${V.span}일 업로드</div>
        <div class="d">하루 평균 ${perDay.toFixed(1)}편 · 채널 ${V.rowsCh.length}개</div></div>
      <div class="tile"><div class="v">${fmtN(V.subsNow)}</div><div class="k">구독자 합계</div>
        <div class="d ${V.dsubs > 0 ? "up" : V.dsubs < 0 ? "dn" : ""}">${V.span}일 ${fmtD(V.dsubs)}</div></div>
      <div class="tile"><div class="v">${fmtN(V.likeNow)}</div><div class="k">누적 좋아요</div>
        <div class="d ${V.likeGain > 0 ? "up" : ""}">${V.span}일 ${fmtD(V.likeGain)}</div></div>
      <div class="tile"><div class="v">${V.freshAvg == null ? "—" : fmtN(V.freshAvg)}</div>
        <div class="k">신규 영상 평균 조회</div>
        <div class="d">이 기간 발행 ${V.freshCount}편 기준</div></div>
    </div>

    ${pfMetricCard(V, "views", true)}
    ${pfMetricCard(V, "likes", false)}
    ${pfMetricCard(V, "subs", false)}

    <section class="card"><div class="pf-cardhead"><h2>채널별 영상 개수 <small class="pf-idx">최근 ${V.span}일 기준</small></h2><span class="pf-legend"><span><i class="old"></i>이전부터 있던 영상</span><span><i class="new"></i>이 기간에 올린 영상</span></span></div>
      ${pfChBars(V)}
    </section>

    <section class="card"><h2>채널별 업로드 <small class="pf-idx">진할수록 많이 올린 날 · 채널 이름을 누르면 그 채널만</small></h2>
      ${pfHeat(V)}
    </section>

    <section class="card"><h2>채널 요약 <small class="pf-idx">최근 ${V.span}일 기준</small></h2>
    <div class="tblwrap pf-sticky"><table><tr><th>채널</th><th class="num">영상</th><th class="num">업로드</th>
      <th class="num">${V.span}일 조회</th><th class="num">누적 조회</th><th class="num">좋아요</th><th class="num">구독자</th>
      <th class="num">구독 ${V.span}일</th><th>최근 흐름 <small>일별 조회 · 직전 대비</small></th></tr>${
    V.rowsCh.map(r => `<tr class="${perfChSet && perfChSet.has(r.ch) ? "selrow" : ""}" style="cursor:pointer"
        title="누르면 이 채널만 봐요" onclick="__perf.perfChOnly('${esc(r.ch)}')">
      <td class="nowrap">${esc(r.ch)}</td><td class="num">${fmtN(r.vids)}</td><td class="num">${fmtN(r.ups)}</td>
      <td class="num">${fmtN(r.gain)}</td><td class="num">${fmtN(r.cum)}</td>
      <td class="num">${fmtN(r.likes)}</td><td class="num">${fmtN(r.subs)}</td>
      <td class="num">${fmtD(r.dsubs)}</td>
      <td>${pfTrend(r.series, V.dates)}</td></tr>`).join("")
    || '<tr><td colspan="9" class="empty">채널 없음</td></tr>'}</table></div></section>

    <section class="card"><div class="pf-vhead"><h2>영상별 성과 <small class="pf-idx">행을 누르면 상세</small></h2></div>
    <div class="tblwrap"><table class="pf-vtable"><colgroup><col><col class="c-work"><col class="c-ch"><col class="c-n"><col class="c-n"><col class="c-n"><col class="c-pub"></colgroup><tr>${COLS.map(([k, l], i) =>
      `<th class="sortable${i >= 3 ? " num" : ""}" onclick="__perf.perfSortBy('${k}')">${l}${perfSort.col === k ? (dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr>${
    vrows.slice(pageAt, pageAt + PERF_PAGE).map(r => `<tr class="${perfVid === r.cid ? "selrow" : ""}" style="cursor:pointer"
      title="누르면 자세히 봐요" onclick="__perf.perfOpenVid('${esc(r.cid)}')">
      <td>${r.dead ? '<span class="sub" title="내려간 영상">†</span> ' : ""}${esc(r.title)}</td>
      <td>${esc(r.work)}</td><td class="nowrap">${esc(r.ch)}</td>
      <td class="num">${fmtN(r.dper)}</td><td class="num">${fmtN(r.views)}</td>
      <td class="num">${fmtN(r.likes)}</td>
      <td class="num pf-pub"><span class="pf-new${r.isNew ? "" : " off"}" title="이 기간에 올린 영상">신규</span>${esc(r.pub)}</td></tr>${
      perfVid === r.cid ? `<tr><td colspan="7" class="vdcell">${pfVidDetail(V, r.cid)}</td></tr>` : ""}`).join("")
    || `<tr><td colspan="7" class="empty">${perfChSet && perfChSet.size === 0
        ? "고른 채널이 없어요. 채널 필터에서 켜 주세요" : "영상 데이터가 없어요"}</td></tr>`}</table></div>
    <div class="pf-vcards">
      <div class="pf-vsort"><select aria-label="정렬" onchange="__perf.perfSortPick(this.value)">${COLS.slice(3).map(([k, l]) =>
        `<option value="${k}" ${perfSort.col === k ? "selected" : ""}>${l}순</option>`).join("")}</select></div>
      ${vrows.slice(pageAt, pageAt + PERF_PAGE).map(r => `<div class="pf-vcard${perfVid === r.cid ? " sel" : ""}" onclick="__perf.perfOpenVid('${esc(r.cid)}')" title="누르면 자세히 봐요">
        <div class="pf-vc-t">${r.dead ? '<span class="sub" title="내려간 영상">†</span> ' : ""}${esc(r.title)}</div>
        <div class="pf-vc-m">${esc([r.work, r.ch].filter(Boolean).join(" · "))}</div>
        <div class="pf-vc-n"><span><small>${V.span}일</small>${fmtN(r.dper)}</span><span><small>누적</small>${fmtN(r.views)}</span><span><small>좋아요</small>${fmtN(r.likes)}</span>${r.isNew ? '<span class="pf-vc-new">신규</span>' : `<span class="pf-vc-d">${esc(r.pub)}</span>`}</div>
      </div>${perfVid === r.cid ? `<div class="pf-vc-detail">${pfVidDetail(V, r.cid)}</div>` : ""}`).join("")
      || `<p class="empty">${perfChSet && perfChSet.size === 0 ? "고른 채널이 없어요. 채널 필터에서 켜 주세요" : "영상 데이터가 없어요"}</p>`}
    </div>${pager ? `<div class="pf-vfoot">${pager}</div>` : ""}</section>`;
}
// 영상 상세 토글 — 같은 행을 다시 누르면 접힌다
P.perfOpenVid = cid => { perfVid = perfVid === cid ? null : cid; render(); };
// 직접 구간 지정 — 로드해 둔 창보다 더 거슬러야 하면 다시 받는다
P.perfSetRange = (which, val) => { perfPage = 0;
  if (which === "clear"){ perfFrom = perfTo = null; render(); return; }
  if (which === "from") perfFrom = val || null; else perfTo = val || null;
  if (perfFrom && perfTo && perfFrom > perfTo){ const t = perfFrom; perfFrom = perfTo; perfTo = t; }
  if (perfNeedDays() > perfLoadedDays) perf = null;
  render();
};


P.perfRange = d => { perfPage = 0; perfDays = d; perfFrom = perfTo = null;   // 프리셋이 직접 지정을 대체한다
  if (perfWant(d) > perfLoadedDays) perf = null;   // 더 긴 창이 필요 — 다시 받는다
  render(); };
// 칩 토글 — 전체(null)에서 하나 끄면 "그 채널만 제외" 상태가 된다
P.perfChToggle = ch => { perfPage = 0;
  const all = perfBuild().chans.map(g => g.ch);
  if (!perfChSet) perfChSet = new Set(all);
  perfChSet.has(ch) ? perfChSet.delete(ch) : perfChSet.add(ch);
  if (perfChSet.size === all.length) perfChSet = null;   // 전부 켜지면 전체 상태로 정규화
  render();
};
// 요약 행·히트맵 행 클릭 — 이 채널만 보기 (재클릭 시 전체)
P.perfChOnly = ch => { perfPage = 0;
  perfChSet = (perfChSet && perfChSet.size === 1 && perfChSet.has(ch)) ? null : new Set([ch]);
  render();
};
P.perfPageBy = d => { perfPage += d; perfVid = null; render(); };
P.perfReload = () => { perf = null; perfLoadedDays = 0; render(); };
// 좁은 화면의 정렬 고르기 — 고르면 늘 큰 값(최근)부터
P.perfSortPick = c => { perfPage = 0; perfSort = { col: c, dir: -1 }; render(); };
P.perfSortBy = c => { perfPage = 0;
  perfSort = perfSort.col === c ? { col: c, dir: -perfSort.dir } : { col: c, dir: -1 };
  render();
};
render();
return () => { dead = true; root.classList.remove("perf-page"); if (window.__perf === P) delete window.__perf; };
}
