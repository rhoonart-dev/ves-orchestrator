import {listRange,listPublished,kstParts,kstISO,KINDS,kindOf} from './release-schedule.js';
// 홈 '이번 주 발행' — 오늘부터 7일 띠(작품 공개 ● · 우리 영상 ■), 오늘 목록, 다가오는 작품 공개.
// 데이터는 발행 일정 탭과 같다(work_release_schedule · perf_video_map). 예약 발행 기록이 생기면 '오늘 발행' 칸에 예약 수를 더한다.
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DOW=['일','월','화','수','목','금','토'];
const addDays=(ymd,n)=>{const d=new Date(ymd+'T12:00:00+09:00');d.setUTCDate(d.getUTCDate()+n);return kstParts(d.toISOString()).date;};
const dowOf=ymd=>new Date(ymd+'T12:00:00+09:00').getUTCDay();
// '7-8화 본편'·'7-8화 선공개'처럼 공개 종류를 늘 붙인다
const workName=r=>[r.work_title,r.episode_label||(r.episode_no?r.episode_no+'화':''),KINDS[kindOf(r)]].filter(Boolean).join(' ');

export async function loadWeek(client,now=new Date()){
 const today=kstParts(now.toISOString()).date,end=addDays(today,7);
 const [works,upcoming,videos]=await Promise.all([
  listRange(client,kstISO(today),kstISO(end)),
  listRange(client,now.toISOString(),kstISO(addDays(today,45))),
  listPublished(client,kstISO(today),kstISO(end)),
 ]);
 return {today,days:Array.from({length:7},(_,i)=>addDays(today,i)),works:works.filter(r=>r.status!=='cancelled'),
  upcoming:upcoming.filter(r=>r.status==='scheduled').slice(0,3),videos};
}

// '오늘 발행' 숫자 칸 — 지금은 올라간 영상만(예약 데이터는 발행 기능이 붙으면 더한다)
export function todayMetric(week){
 if(!week)return {value:null,unit:'발행 일정 연결 중'};
 const vids=week.videos.filter(v=>kstParts(v.published_at).date===week.today);
 return {value:vids.length,unit:'올라간 우리 영상'};
}

export function weekHtml(week){
 const dayWorks=d=>week.works.filter(r=>kstParts(r.release_at).date===d);
 const dayVids=d=>week.videos.filter(v=>kstParts(v.published_at).date===d);
 const strip=week.days.map((d,i)=>{
  const w=dayWorks(d),v=dayVids(d),dow=dowOf(d);
  // 작품 하나 = 두 줄: 작품 이름(길면 …) / 회차·공개 종류(안 잘림). 최대 2개, 나머지는 +N — 날짜 칸 높이가 가지런하다
  const ep=r=>r.episode_label||(r.episode_no?r.episode_no+'화':'');
  const marks=[...w.slice(0,2).map(r=>`<span class="hw-mk" title="${esc(workName(r))}"><i class="lg-work"></i><span class="hw-mt"><span class="hw-mn">${esc(r.work_title)}</span><span class="hw-me">${esc(ep(r))}<em>${esc(KINDS[kindOf(r)])}</em></span></span></span>`),
   w.length>2?`<span class="more">작품 +${w.length-2}</span>`:'',
   v.length?`<span class="hw-mk"><i class="lg-video"></i><span class="hw-mt"><span class="hw-mn">우리 영상</span><span class="hw-me">${v.length}편</span></span></span>`:''].join('');
  return `<a class="hw-day${i===0?' today':''}${dow===0?' sun':dow===6?' sat':''}" href="#schedule?date=${d}"><span class="hw-dow">${DOW[dow]}${i===0?' · 오늘':''}</span><span class="hw-date">${+d.slice(8)}</span><span class="hw-marks">${marks}</span></a>`;
 }).join('');
 const todayItems=[...dayWorks(week.today).map(r=>({at:r.release_at,kind:'work',html:`<span class="hw-kind"><i class="lg-work"></i>작품 공개${r.platform?' · '+esc(r.platform):''}</span><strong>${esc(workName(r))}</strong>`})),
  ...dayVids(week.today).map(v=>({at:v.published_at,kind:'video',html:`<span class="hw-kind"><i class="lg-video"></i>우리 영상${v.channel_name?' · '+esc(v.channel_name):''}</span><strong>${esc(v.title)}</strong>${v.work_title?`<small>${esc(v.work_title)}</small>`:''}`}))]
  .sort((a,b)=>String(a.at).localeCompare(String(b.at)));
 const dday=r=>{const n=Math.round((Date.parse(kstParts(r.release_at).date+'T00:00:00+09:00')-Date.parse(week.today+'T00:00:00+09:00'))/864e5);return n?`D-${n}`:'오늘';};
 const when=r=>{const p=kstParts(r.release_at);return `${+p.date.slice(5,7)}월 ${+p.date.slice(8)}일(${DOW[dowOf(p.date)]}) ${p.time}`;};
 return `<div class="hw-strip">${strip}</div><div class="hw-cols">
  <div><h3>오늘</h3>${todayItems.map(it=>`<div class="hw-item"><time>${kstParts(it.at).time}</time><div>${it.html}</div></div>`).join('')||'<p class="home-empty">오늘 공개되는 작품도, 올라간 영상도 아직 없어요.</p>'}</div>
  <div><h3>다가오는 작품 공개</h3>${week.upcoming.map(r=>`<a class="hw-soon" href="#schedule?date=${kstParts(r.release_at).date}"><span><strong>${esc(workName(r))}</strong><small>${when(r)}${r.platform?' · '+esc(r.platform):''}</small></span><b>${dday(r)}</b></a>`).join('')||'<p class="home-empty">등록된 작품 공개 일정이 없어요.</p>'}</div>
 </div>`;
}
