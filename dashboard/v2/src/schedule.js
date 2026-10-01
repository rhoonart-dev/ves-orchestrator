import {icon} from './icons.js';
import {loadCatalog} from './work-catalog.js?v=hide-1';
import {askConfirm} from './confirm-dialog.js';
import {esc} from './review-details.js?v=web-1';
import {assetRequest} from './work-assets.js?v=web-1';
import {STATUS,PLATFORMS,EDITORS,KINDS,SOURCE_LOCATIONS,kindOf,kstISO,kstParts,shownStatus,episodeNo,weeklyRows,listRange,insertRows,updateRow,updateSeriesTime,removeRows,listPublished,youtubeUrl,youtubeThumb,listSourceChannels,addSourceChannel,removeSourceChannel,workCard,listWorkCards,linkWorkSource,updateFollowing} from './release-schedule.js?v=rev-1';
// 발행 일정: calendar (left / top) + list of the selected day (right / below).
// Two kinds, never mixed: 작품 공개(원작, round dots, editable) and 우리 영상(채널에 공개된 쇼츠, square marks, read-only).
// Cells stay quiet (marks only); details live in the list.
const WEEKDAYS=['일','월','화','수','목','금','토'];
const pad=n=>String(n).padStart(2,'0');
const iso=d=>`${d.y}-${pad(d.m+1)}-${pad(d.d)}`;
const fromUTC=t=>({y:t.getUTCFullYear(),m:t.getUTCMonth(),d:t.getUTCDate(),dow:t.getUTCDay()});
const addDays=(d,n)=>fromUTC(new Date(Date.UTC(d.y,d.m,d.d+n)));
const sameDay=(a,b)=>a.y===b.y&&a.m===b.m&&a.d===b.d;
const parseDay=s=>{const [y,m,d]=s.split('-').map(Number);return fromUTC(new Date(Date.UTC(y,m-1,d)));};
function seoulToday(){
 const p=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(x=>[x.type,x.value]));
 return fromUTC(new Date(Date.UTC(+p.year,+p.month-1,+p.day)));
}
// ?date=YYYY-MM-DD wins; ?month=YYYY-MM (older links) selects the 1st, or today in the current month.
export function initialSelection(params,today){
 const d=/^(\d{4})-(\d{2})-(\d{2})$/.exec(params.get('date')||'');
 if(d){const t=fromUTC(new Date(Date.UTC(+d[1],+d[2]-1,+d[3])));if(iso(t)===d[0])return t;}
 const m=/^(\d{4})-(\d{2})$/.exec(params.get('month')||'');
 if(m&&+m[2]>=1&&+m[2]<=12)return +m[1]===today.y&&+m[2]-1===today.m?today:fromUTC(new Date(Date.UTC(+m[1],+m[2]-1,1)));
 return today;
}
// 6 weeks from the Sunday on/before the 1st — the grid height never jumps between months.
export function monthCells(y,m){
 const first=new Date(Date.UTC(y,m,1));
 return Array.from({length:42},(_,i)=>{const c=fromUTC(new Date(Date.UTC(y,m,1-first.getUTCDay()+i)));return {...c,inMonth:c.m===m};});
}
const statusBadge=r=>`<span class="rs-status" data-status="${shownStatus(r)}">${STATUS[shownStatus(r)]}</span>`;
const SRC_ICONS={drive:'folder',youtube:'video',other:'file'};
const kindTag=r=>{const k=kindOf(r);return `<span class="rs-kind${k==='main'?' is-main':''}">${KINDS[k]}</span>`;};
const chanAvatar=c=>c?.avatar_url?`<img class="rs-chan-av" src="${esc(c.avatar_url)}" alt="" referrerpolicy="no-referrer">`:`<span class="rs-chan-av">${esc((c?.name||'?').slice(0,1))}</span>`;
const dayLabel=s=>{const d=parseDay(s);return `${d.m+1}/${d.d}(${WEEKDAYS[d.dow]})`;};

export function mountSchedule(root,{params=new URLSearchParams(),client=null,role=null}={}){
 const today=seoulToday(),canEdit=!!client&&EDITORS.includes(role);
 let selected=initialSelection(params,today),channels=[],rows=[],videos=[],videoError='',loadState='idle',loadError='',loadTicket=0,works=null,dead=false;
 root.innerHTML=`<section class="schedule" aria-label="발행 일정"><div class="schedule-main"><header class="schedule-toolbar"><div class="schedule-heading"><h2 class="schedule-title" aria-live="polite"></h2><div class="schedule-legend" aria-label="표시"><span><i class="lg-work"></i>작품 공개</span><span><i class="lg-video"></i>우리 영상</span></div></div><div class="schedule-nav">${canEdit?`<button type="button" class="schedule-add">${icon('pencil')}<span>작품 일정 추가</span></button>`:''}<button type="button" class="schedule-today">오늘</button><button type="button" class="schedule-step" data-step="-1" aria-label="이전 달">${icon('chevron')}</button><button type="button" class="schedule-step" data-step="1" aria-label="다음 달">${icon('chevron')}</button></div></header><div class="schedule-calendar" role="grid" aria-label="달력. 날짜를 고르면 목록이 바뀌어요"><div class="schedule-weekdays" role="row">${WEEKDAYS.map((w,i)=>`<span role="columnheader" data-dow="${i}">${w}</span>`).join('')}</div><div class="schedule-days"></div></div></div><aside class="schedule-panel" aria-label="선택한 날짜의 작품 공개와 우리 영상"><header class="schedule-panel-head"><p class="schedule-panel-kicker"></p><h2 class="schedule-panel-title"></h2></header><div class="schedule-list" role="list"></div></aside></section><dialog class="schedule-dialog" aria-labelledby="rs-title"><form method="dialog" class="rs-form"></form></dialog><dialog class="rs-chan-dialog" aria-labelledby="rs-chan-title"><div class="rs-chan-body"></div></dialog>`;
 const $=s=>root.querySelector(s);
 const group=(list,at)=>{const map=new Map();for(const r of list){const k=kstParts(r[at]).date;(map.get(k)||map.set(k,[]).get(k)).push(r);}return map;};
 const byDate=()=>group(rows,'release_at'),videosByDate=()=>group(videos,'published_at');
 function renderCalendar(){
  const y=selected.y,m=selected.m,map=byDate(),vmap=videosByDate();
  $('.schedule-title').textContent=`${y}년 ${m+1}월`;
  $('.schedule-today').disabled=sameDay(selected,today);
  const cells=monthCells(y,m);
  $('.schedule-days').innerHTML=Array.from({length:6},(_,w)=>`<div class="schedule-week" role="row">${cells.slice(w*7,w*7+7).map(c=>{
   const isToday=sameDay(c,today),isSel=sameDay(c,selected),items=map.get(iso(c))||[],vids=vmap.get(iso(c))||[];
   const label=`${c.y}년 ${c.m+1}월 ${c.d}일 ${WEEKDAYS[c.dow]}요일${isToday?' · 오늘':''}${items.length?` · 작품 공개 ${items.length}건`:''}${vids.length?` · 우리 영상 ${vids.length}개`:''}`;
   // one mark per kind + count; the work dot takes the most urgent status of the day
   const ws=items.map(r=>shownStatus(r)),urgent=['delayed','scheduled','cancelled','released'].find(k=>ws.includes(k));
   const dots=(items.length?`<span class="mk-work"><i data-status="${urgent}"></i><small>${items.length}</small></span>`:'')
    +(vids.length?`<span class="mk-video"><b></b><small>${vids.length}</small></span>`:'');
   return `<div class="schedule-day${c.inMonth?'':' is-outside'}${isToday?' is-today':''}${isSel?' is-selected':''}" role="gridcell" tabindex="${isSel?0:-1}" aria-selected="${isSel}" data-dow="${c.dow}" data-date="${iso(c)}" aria-label="${label}"${isToday?' aria-current="date"':''}><span class="schedule-date">${c.d===1&&!c.inMonth?`<small class="schedule-month">${c.m+1}월 </small>`:''}${c.d}</span><div class="schedule-marks" aria-hidden="true">${dots}</div></div>`;
  }).join('')}</div>`).join('');
 }
 function renderList(){
  $('.schedule-panel-kicker').textContent=sameDay(selected,today)?'오늘':`${selected.y}년`;
  $('.schedule-panel-title').textContent=`${selected.m+1}월 ${selected.d}일 ${WEEKDAYS[selected.dow]}요일`;
  const list=$('.schedule-list');
  if(!client){list.innerHTML=empty('로그인하면 일정을 볼 수 있어요.');return;}
  if(loadState==='loading'&&!rows.length&&!videos.length){list.innerHTML=empty('불러오는 중…');return;}
  const items=(byDate().get(iso(selected))||[]).slice().sort((a,b)=>a.release_at.localeCompare(b.release_at));
  const vids=(videosByDate().get(iso(selected))||[]).slice().sort((a,b)=>a.published_at.localeCompare(b.published_at));
  const works=loadState==='error'?`<p class="rs-section-note">작품 공개 일정을 불러오지 못했어요. ${esc(loadError)}</p>`
   :items.length?items.map(r=>`<article class="rs-item" role="listitem"><button type="button" class="rs-open" data-id="${esc(r.id)}" ${canEdit?'':'disabled'}><span class="rs-time">${kstParts(r.release_at).time}</span><span class="rs-copy"><strong>${esc(r.work_title)}${r.episode_label?` <em>${esc(r.episode_label)}</em>`:''}${kindTag(r)}</strong><small>${[esc(r.platform||''),srcText(r),esc(r.note||'')].filter(Boolean).join(' · ')}</small></span>${statusBadge(r)}</button></article>`).join('')
   :`<p class="rs-section-note">이날 공개되는 작품이 없어요.${canEdit?' 위의 작품 일정 추가로 넣을 수 있어요.':''}</p>`;
  const ours=videoError?`<p class="rs-section-note">채널 영상을 불러오지 못했어요. ${esc(videoError)}</p>`
   :vids.length?vids.map(v=>`<article class="rs-item rs-video" role="listitem"><a class="rs-video-link" href="${esc(youtubeUrl(v.content_id))}" target="_blank" rel="noopener noreferrer"><span class="rs-time">${kstParts(v.published_at).time}</span><img class="rs-thumb" src="${esc(v.thumb_url||youtubeThumb(v.content_id))}" alt="" loading="lazy"><span class="rs-copy">${v.channel_name?`<span class="rs-channel">${esc(v.channel_name)}</span>`:''}<strong>${esc(v.title||v.content_id)}</strong>${v.work_title?`<small>${esc(v.work_title)}</small>`:''}</span></a></article>`).join('')
   :'<p class="rs-section-note">이날 채널에 공개된 영상이 없어요.</p>';
  list.innerHTML=`<section class="rs-section" data-kind="work"><h3><i class="lg-work"></i>작품 공개<small>${items.length||''}</small></h3>${works}</section><section class="rs-section" data-kind="video"><h3><i class="lg-video"></i>우리 영상<small>${vids.length||''}</small></h3>${ours}<p class="rs-sync-note">방금 올린 영상은 조금 있다가 떠요.</p></section>`;
 }
 function srcText(r){
  if(!r.source_location)return '';
  const names=r.source_location==='youtube'?(r.source_channel_ids||[]).map(id=>channels.find(x=>x.id===id)?.name).filter(Boolean):[];
  return `<span class="rs-src" title="원본을 받는 곳">${icon(SRC_ICONS[r.source_location])}${esc(names.length?names.join(', '):SOURCE_LOCATIONS[r.source_location])}</span>`;
 }
 const empty=(t,s='')=>`<div class="schedule-empty">${icon('grid')}<p>${esc(t)}</p>${s?`<small>${esc(s)}</small>`:''}</div>`;
 async function load(){
  if(!client){renderList();return;}
  const ticket=++loadTicket,cells=monthCells(selected.y,selected.m);
  const from=kstISO(iso(cells[0])),to=kstISO(iso(addDays(cells[41],1)));
  loadState='loading';renderList();
  const [works,ours,chs]=await Promise.allSettled([listRange(client,from,to),listPublished(client,from,to),listSourceChannels(client)]);
  if(chs.status==='fulfilled')channels=chs.value;
  if(dead||ticket!==loadTicket)return;
  if(works.status==='fulfilled'){rows=works.value;loadState='ready';}else{rows=[];loadState='error';loadError=works.reason?.message||'';}
  if(ours.status==='fulfilled'){videos=ours.value;videoError='';}else{videos=[];videoError=ours.reason?.message||'';}
  renderCalendar();renderList();
 }
 function select(day,{focus=false}={}){
  const monthChanged=day.y!==selected.y||day.m!==selected.m;
  selected=day;
  history.replaceState(null,'',`#schedule?date=${iso(day)}`);   // no route remount
  if(monthChanged){renderCalendar();load();}
  else{
   root.querySelectorAll('.schedule-day.is-selected').forEach(el=>{el.classList.remove('is-selected');el.setAttribute('aria-selected','false');el.tabIndex=-1;});
   const el=$(`.schedule-day[data-date="${iso(day)}"]`);
   if(el){el.classList.add('is-selected');el.setAttribute('aria-selected','true');el.tabIndex=0;}
   $('.schedule-today').disabled=sameDay(selected,today);
  }
  renderList();
  if(focus)$(`.schedule-day[data-date="${iso(day)}"]`)?.focus();
 }
 const stepMonth=n=>{const t=fromUTC(new Date(Date.UTC(selected.y,selected.m+n,1)));select(t.y===today.y&&t.m===today.m?today:t);};
 root.querySelectorAll('.schedule-step').forEach(b=>b.onclick=()=>stepMonth(+b.dataset.step));
 $('.schedule-today').onclick=()=>select(today);
 $('.schedule-days').addEventListener('click',e=>{const cell=e.target.closest('.schedule-day');if(cell)select(parseDay(cell.dataset.date));});
 // Arrows move the selected day (grid convention); PageUp/PageDown change the month; Home = today.
 $('.schedule-calendar').addEventListener('keydown',e=>{
  const moves={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7};
  if(e.key in moves){e.preventDefault();select(addDays(selected,moves[e.key]),{focus:true});}
  else if(e.key==='PageUp'||e.key==='PageDown'){e.preventDefault();stepMonth(e.key==='PageUp'?-1:1);$(`.schedule-day[data-date="${iso(selected)}"]`)?.focus();}
  else if(e.key==='Home'){e.preventDefault();select(today,{focus:true});}
 });

 // ── 추가·수정 창 ──
 const dialog=$('.schedule-dialog'),form=$('.rs-form');
 let editing=null,picked=null,mode='single',kind='main',srcLoc=null,srcChans=[],card=null,cardTicket=0;
 async function loadWorks(){
  if(works)return works;
  const body=await loadCatalog(client);   // 레이블리 작품 정보 사본(웹에서도 된다)
  works=(body.works||[]).map(w=>({id:String(w.id),title:w.title,type:w.video_type||'',holder:w.copyrights_holder_name||''}));
  return works;
 }
 // 작품 검색 = 자동완성: 결과는 입력칸 아래에 겹쳐 뜨고(레이아웃이 움직이지 않는다) ↑/↓·Enter·Esc 로 고른다.
 let hits=[],active=-1;
 function workResults(q){
  const box=form.querySelector('.rs-work-results'),input=form.querySelector('.rs-work-search');if(!box)return;
  const t=q.trim().toLocaleLowerCase('ko');
  if(!t){hits=[];box.hidden=true;input?.setAttribute('aria-expanded','false');return;}
  if(!works){box.innerHTML='<p class="rs-hint">작품 목록을 불러오는 중…</p>';box.hidden=false;return;}
  hits=works.filter(w=>w.title.toLocaleLowerCase('ko').includes(t)).slice(0,8);active=hits.length?0:-1;
  const dup=new Set(works.filter((w,i)=>works.findIndex(x=>x.title===w.title)!==i).map(w=>w.title));
  box.innerHTML=hits.map((w,i)=>`<button type="button" class="rs-work" role="option" id="rs-work-${i}" data-i="${i}" tabindex="-1"><strong>${esc(w.title)}</strong><small>${esc([w.type,w.holder,dup.has(w.title)?'ID '+w.id.slice(-6):''].filter(Boolean).join(' · '))}</small></button>`).join('')||'<p class="rs-hint">일치하는 작품이 없어요.</p>';
  box.hidden=false;input?.setAttribute('aria-expanded','true');markActive();
 }
 function markActive(){
  const input=form.querySelector('.rs-work-search');
  form.querySelectorAll('.rs-work').forEach(b=>{const on=+b.dataset.i===active;b.classList.toggle('is-active',on);b.setAttribute('aria-selected',String(on));if(on)b.scrollIntoView({block:'nearest'});});
  if(input){if(active>=0)input.setAttribute('aria-activedescendant','rs-work-'+active);else input.removeAttribute('aria-activedescendant');}
 }
 const pick=i=>{if(hits[i]){picked=hits[i];drawPicked();}};
 function drawPicked(){
  card=null;if(form.querySelector('.rs-src-yt'))drawSource();
  const slot=form.querySelector('.rs-work-slot');
  slot.innerHTML=picked?`<div class="rs-picked"><span><strong>${esc(picked.title)}</strong><small>${esc([picked.type,picked.holder].filter(Boolean).join(' · '))}</small></span>${editing?'':'<button type="button" class="rs-unpick">바꾸기</button>'}</div>`
   :`<input type="search" class="rs-work-search" placeholder="작품 이름으로 검색" autocomplete="off" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="rs-work-results" aria-label="작품 검색"><div class="rs-work-results" id="rs-work-results" role="listbox" hidden></div>`;
  const input=slot.querySelector('.rs-work-search'),box=slot.querySelector('.rs-work-results');
  if(input){
   input.oninput=()=>workResults(input.value);
   input.onkeydown=e=>{
    if(box.hidden)return;
    if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();if(hits.length){active=(active+(e.key==='ArrowDown'?1:-1)+hits.length)%hits.length;markActive();}}
    else if(e.key==='Enter'){e.preventDefault();pick(active);}
    else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();box.hidden=true;input.setAttribute('aria-expanded','false');}   // close the list, not the dialog
   };
   input.onfocus=()=>{if(input.value.trim())workResults(input.value);};
   input.onblur=()=>setTimeout(()=>{if(box.isConnected&&!box.contains(document.activeElement)){box.hidden=true;input.setAttribute('aria-expanded','false');}},120);
   box.onmousedown=e=>e.preventDefault();   // keep focus in the input while clicking a result
   box.onclick=e=>{const b=e.target.closest('.rs-work');if(b)pick(+b.dataset.i);};
   input.focus();
  }
  const un=slot.querySelector('.rs-unpick');if(un)un.onclick=()=>{picked=null;drawPicked();};
 }
 // ── 반복 묶음: 다음 회차들에도 옮길 수 있는 것(시간·플랫폼·공개 종류·소스 위치·원본 채널)을 바꿨을 때만 묻는다 ──
 // 날짜·회차·상태·메모는 그 회차 것이라 옮기지 않는다.
 function seriesChanges(){
  if(!editing?.series_id)return null;
  const f=form.elements,out={labels:[],fields:{},time:null};
  const t0=kstParts(editing.release_at).time,t1=f.time1?.value;
  if(t1&&t1!==t0){out.time=t1;out.labels.push(`시간 ${t1}`);}
  const p0=editing.platform||'',p1=f.platform.value.trim();
  if(p1!==p0){out.fields.platform=p1||null;out.labels.push(p1?`플랫폼 ${p1}`:'플랫폼 비움');}
  const k0=kindOf(editing);
  if(kind!==k0){out.fields.release_kind=kind;out.labels.push(KINDS[kind]);}
  const s0=editing.source_location||null,c0=[...(editing.source_channel_ids||[])].sort().join(),c1=srcLoc==='youtube'?[...srcChans].sort().join():'';
  if(srcLoc!==s0||c1!==c0){out.fields.source_location=srcLoc;out.fields.source_channel_ids=srcLoc==='youtube'?srcChans:[];const names=srcLoc==='youtube'?srcChans.map(id=>channels.find(c=>c.id===id)?.name).filter(Boolean):[];out.labels.push(srcLoc?`원본 ${names.length?names.join(', '):SOURCE_LOCATIONS[srcLoc]}`:'소스 위치 비움');}
  return out.labels.length?out:null;
 }
 function drawSeries(){
  const box=form.querySelector('.rs-series');if(!box)return;
  const ch=seriesChanges(),was=!!form.elements.series_apply?.checked;
  box.hidden=!ch;
  box.innerHTML=ch?`<label class="rs-check"><input type="checkbox" name="series_apply" ${was?'checked':''}><span>뒤 회차에도 똑같이 바꾸기<span class="rs-series-tags">${ch.labels.map(l=>`<em>${esc(l)}</em>`).join('')}</span></span></label>`:'';
 }
 // ── 소스 위치: 유튜브면 원본 채널 목록 + 원본 링크 + '이 작품의 원본 채널로도 저장' ──
 async function drawSource(){
  const box=form.querySelector('.rs-src-yt');if(!box)return;
  box.hidden=srcLoc!=='youtube';if(box.hidden)return;
  if(!channels.length){try{channels=await listSourceChannels(client);}catch(e){box.innerHTML=`<p class="rs-hint">${esc(e.message)}</p>`;return;}}
  srcChans=srcChans.filter(id=>channels.some(c=>c.id===id));   // 목록에서 빠진 채널은 버린다
  const chosen=srcChans.map(id=>channels.find(c=>c.id===id)),ch=chosen[0];
  box.innerHTML=`<div class="rs-chans">${channels.map(c=>`<button type="button" class="rs-chan" data-id="${esc(c.id)}" aria-pressed="${srcChans.includes(c.id)}">${chanAvatar(c)}<span><strong>${esc(c.name)}</strong><small>${esc(c.handle||c.url.replace('https://www.youtube.com/',''))}</small></span>${srcChans.includes(c.id)?icon('check'):''}</button>`).join('')}
   <button type="button" class="rs-chan rs-chan-add">${icon('plus')}원본 채널 추가</button></div>
   ${ch?`<div class="rs-link-work"></div>`:'<p class="rs-hint">원본을 받는 채널을 골라 주세요. 여러 개 골라도 돼요.</p>'}`;
  box.querySelectorAll('.rs-chan[data-id]').forEach(b=>b.onclick=()=>{const id=b.dataset.id;srcChans=srcChans.includes(id)?srcChans.filter(x=>x!==id):[...srcChans,id];drawSource();drawSeries();});
  box.querySelector('.rs-chan-add').onclick=()=>openChannels();
  if(ch&&picked)drawLink(ch,chosen.length);
 }
 // 작품 카드의 지금 원본 링크와 비교해 체크 상자를 고른다 — 없으면 저장(기본 켬), 같은 채널이면 안내만, 다르면 바꾸기(기본 끔)
 async function drawLink(ch,many=1){
  const slot=form.querySelector('.rs-link-work');if(!slot)return;
  const t=++cardTicket;
  try{if(!card||card.work_title!==picked.title)card=(await workCard(client,picked.title))||{work_title:picked.title};}catch{card={work_title:picked.title};}
  if(t!==cardTicket||!slot.isConnected)return;
  const cur=card.playlist_url||'';
  let same=cur.startsWith(ch.url);
  if(cur&&!same){try{const r=await assetRequest(client,'/api/youtube/owners?url='+encodeURIComponent(cur));same=(r.owners?.[cur]||'').toLowerCase()===ch.url.toLowerCase();}catch{}}
  if(t!==cardTicket||!slot.isConnected)return;
  slot.innerHTML=same?`<p class="rs-hint">${many>1?`'${esc(ch.name)}'은 `:''}이 작품의 원본 채널로 이미 저장돼 있어요.</p>`
   :`<label class="rs-check"><input type="checkbox" name="link_work" ${cur?'':'checked'}><span>${many>1?`'${esc(ch.name)}'을 `:''}${cur?'이 작품의 원본 링크를 이 채널로 바꾸기':'이 작품의 원본 채널로도 저장'}<small>${many>1?'소스 창고 자동 등록은 채널 하나만 연결돼요. 처음 고른 채널이에요. ':''}${cur?`지금 연결: ${esc(cur.replace('https://',''))}`:`맥미니가 이 채널에서 제목에 '${esc(picked.title)}'가 들어간 영상을 찾아 소스 창고에 담아요`}</small></span></label>`;
 }
 // ── 원본 채널 관리: 목록 · 쓰는 작품 · 추가 · 빼기 ──
 const chanDlg=$('.rs-chan-dialog');
 async function openChannels(){
  const body=chanDlg.querySelector('.rs-chan-body');
  let preview=null;
  const usedBy=new Map();
  async function usage(){
   try{
    const cards=await listWorkCards(client);
    const urls=cards.map(c=>c.playlist_url).filter(u=>!/youtube\.com\/@/.test(u));
    const own=urls.length?(await assetRequest(client,'/api/youtube/owners?'+urls.map(u=>'url='+encodeURIComponent(u)).join('&'))).owners||{}:{};
    for(const c of cards){const u=c.playlist_url,o=(/youtube\.com\/(@[^/?#]+)/.exec(u)?'https://www.youtube.com/'+/youtube\.com\/(@[^/?#]+)/.exec(u)[1]:own[u])||'';
     const ch=channels.find(x=>x.url.toLowerCase()===o.toLowerCase());if(ch)(usedBy.get(ch.id)||usedBy.set(ch.id,[]).get(ch.id)).push(c.work_title);}
   }catch{}
  }
  function draw(msg=''){
   body.innerHTML=`<header class="rs-head"><h2 id="rs-chan-title">원본 채널</h2><button type="button" class="rs-close" aria-label="닫기">×</button></header>
    <p class="rs-hint">작품 원본을 받는 유튜브 채널이에요. 발행 일정의 소스 위치에서 골라요.</p>
    <div class="rs-chan-list">${channels.map(c=>`<div class="rs-chan-row">${chanAvatar(c)}<span class="rs-chan-copy"><strong>${esc(c.name)}</strong><small>${esc(c.handle||c.url.replace('https://www.youtube.com/',''))}</small>${(usedBy.get(c.id)||[]).length?`<span class="rs-chan-works">${usedBy.get(c.id).map(w=>`<em>${esc(w)}</em>`).join('')}</span>`:'<span class="rs-chan-works"><small>쓰는 작품 없음</small></span>'}</span><button type="button" class="rs-chan-del" data-id="${esc(c.id)}">빼기</button></div>`).join('')||'<p class="rs-hint">아직 등록된 채널이 없어요.</p>'}</div>
    <div class="rs-chan-new"><label class="rs-field"><span>채널 추가</span><span class="rs-chan-input"><input name="chan_url" placeholder="채널 주소 또는 @핸들" autocomplete="off"><button type="button" class="rs-chan-find">불러오기</button></span></label>
     ${preview?`<div class="rs-chan-row is-preview">${chanAvatar(preview)}<span class="rs-chan-copy"><strong>${esc(preview.name)}</strong><small>${esc(preview.handle||preview.url)}</small></span><button type="button" class="primary rs-chan-save">추가</button></div>`:''}
     <p class="rs-error" role="alert">${esc(msg)}</p></div>`;
   body.querySelector('.rs-close').onclick=()=>chanDlg.close();
   const input=body.querySelector('[name=chan_url]');
   const find=async()=>{const b=body.querySelector('.rs-chan-find');b.disabled=true;
    try{preview=await assetRequest(client,'/api/youtube/channel?url='+encodeURIComponent(input.value.trim()));draw();}
    catch(e){preview=null;draw(e.message);body.querySelector('[name=chan_url]').value=input.value;}};
   body.querySelector('.rs-chan-find').onclick=find;
   input.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();find();}};
   const save=body.querySelector('.rs-chan-save');
   if(save)save.onclick=async()=>{save.disabled=true;try{const c=await addSourceChannel(client,preview);channels=[...channels,c];if(!srcChans.includes(c.id))srcChans=[...srcChans,c.id];preview=null;draw();drawSource();}catch(e){draw(e.message);}};
   body.querySelectorAll('.rs-chan-del').forEach(b=>b.onclick=async()=>{
    const c=channels.find(x=>x.id===b.dataset.id),n=(usedBy.get(c.id)||[]).length;
    if(!await askConfirm({title:`'${c.name}'을 목록에서 뺄까요?`,body:`${n?`이 채널을 원본으로 쓰는 작품 ${n}개의 작품 설정은 그대로 남아요. `:''}이 채널을 고른 일정은 '유튜브'만 남아요.`,ok:'빼기'}))return;
    try{await removeSourceChannel(client,c.id);channels=channels.filter(x=>x.id!==c.id);srcChans=srcChans.filter(x=>x!==c.id);draw();drawSource();}catch(e){draw(e.message);}});
  }
  draw();chanDlg.showModal();body.querySelector('[name=chan_url]').focus();
  await usage();if(chanDlg.open)draw();
 }
 function preview(){
  if(mode!=='weekly')return;
  const f=form.elements,wd=[...form.querySelectorAll('[name=wd]:checked')].map(i=>+i.value);
  const list=weeklyRows({start:f.start.value,weekdays:wd,time:f.time.value,from:+f.from.value,to:+f.to.value,fmt:f.fmt.value,per:+f.per.value});
  form.querySelector('.rs-preview').textContent=list.length?`${list.length}번 공개 · ${list[0].episode_label} ${dayLabel(list[0].date)} ~ ${list[list.length-1].episode_label} ${dayLabel(list[list.length-1].date)} ${f.time.value}`:'요일과 회차 범위를 고르면 만들어질 회차가 보여요.';
 }
 function openDialog(row=null){
  editing=row;mode='single';picked=row?{id:row.work_id,title:row.work_title,type:'',holder:''}:null;
  kind=kindOf(row);srcLoc=row?.source_location||null;srcChans=[...(row?.source_channel_ids||[])];card=null;
  const at=row?kstParts(row.release_at):{date:iso(selected),time:'20:00'};
  form.innerHTML=`<header class="rs-head"><h2 id="rs-title">${row?'작품 일정 고치기':'작품 일정 추가'}</h2><button type="button" class="rs-close" aria-label="닫기">×</button></header>
<div class="rs-field"><span>작품</span><div class="rs-work-slot"></div></div>
<div class="rs-field"><span>공개 종류</span><div class="rs-chips" data-group="kind" role="radiogroup" aria-label="공개 종류">${Object.entries(KINDS).map(([k,v])=>`<button type="button" class="rs-chip" role="radio" data-v="${k}" aria-checked="${k===kind}">${v}</button>`).join('')}</div></div>
${row?'':`<div class="rs-modes" role="radiogroup" aria-label="입력 방식"><button type="button" role="radio" data-mode="single" aria-checked="true">한 회차</button><button type="button" role="radio" data-mode="weekly" aria-checked="false">매주 반복</button></div>`}
<div class="rs-single"><div class="rs-row"><label class="rs-field"><span>날짜</span><input type="date" name="date" value="${at.date}" required></label><label class="rs-field"><span>시간</span><input type="time" name="time1" value="${at.time}" required></label></div>
<div class="rs-row"><label class="rs-field"><span>회차</span><input name="episode" value="${esc(row?.episode_label||'')}" placeholder="예: 5화, 5-6화" maxlength="40"></label><label class="rs-field"><span>상태</span><select name="status">${Object.entries(STATUS).map(([k,v])=>`<option value="${k}" ${(row?shownStatus(row):'scheduled')===k?'selected':''}>${v}</option>`).join('')}</select></label></div></div>
<div class="rs-weekly" hidden><div class="rs-row"><label class="rs-field"><span>시작 날짜</span><input type="date" name="start" value="${at.date}"></label><label class="rs-field"><span>시간</span><input type="time" name="time" value="${at.time}"></label></div>
<fieldset class="rs-field rs-days"><legend>공개 요일</legend>${WEEKDAYS.map((w,i)=>`<label><input type="checkbox" name="wd" value="${i}"><span>${w}</span></label>`).join('')}</fieldset>
<div class="rs-row rs-row-4"><label class="rs-field"><span>첫 회차</span><input type="number" name="from" value="1" min="0" max="10000"></label><label class="rs-field"><span>마지막 회차</span><input type="number" name="to" value="12" min="0" max="10000"></label><label class="rs-field"><span>한 번에 공개</span><select name="per">${[1,2,3,4].map(n=>`<option value="${n}">${n}화씩</option>`).join('')}</select></label><label class="rs-field"><span>표기</span><input name="fmt" value="{n}화" maxlength="30" title="{n} 자리에 회차 번호가 들어가요. 두 화씩이면 1-2처럼 들어가요"></label></div>
<p class="rs-preview" role="status"></p></div>
<div class="rs-row"><label class="rs-field"><span>플랫폼</span><input name="platform" list="rs-platforms" value="${esc(row?.platform||'')}" maxlength="60" placeholder="예: 티빙"></label></div><datalist id="rs-platforms">${PLATFORMS.map(p=>`<option value="${esc(p)}">`).join('')}</datalist>
<div class="rs-field"><span>소스 위치 <small>우리 쇼츠 원본을 받는 곳 · 플랫폼과 따로</small></span><div class="rs-chips" data-group="src" role="radiogroup" aria-label="소스 위치">${Object.entries(SOURCE_LOCATIONS).map(([k,v])=>`<button type="button" class="rs-chip" role="radio" data-v="${k}" aria-checked="${k===srcLoc}">${icon(SRC_ICONS[k])}${v}</button>`).join('')}</div><div class="rs-src-yt" hidden></div></div>
<label class="rs-field"><span>메모</span><textarea name="note" rows="2" maxlength="1000" placeholder="선택">${esc(row?.note||'')}</textarea></label>
${row?.series_id?'<div class="rs-series" hidden></div>':''}
<p class="rs-error" role="alert"></p>
<footer class="rs-actions">${row?`<button type="button" class="rs-delete">이 회차 삭제</button>${row.series_id?'<button type="button" class="rs-delete-following">이후 회차 모두 삭제</button>':''}`:''}<span></span><button type="button" class="rs-cancel">취소</button><button type="submit" class="rs-save primary">저장</button></footer>`;
  drawPicked();drawSource();
  form.querySelectorAll('[data-group]').forEach(g=>g.onclick=e=>{const b=e.target.closest('.rs-chip');if(!b)return;
   const v=b.dataset.v;
   if(g.dataset.group==='kind')kind=v;else srcLoc=srcLoc===v?null:v;   // 소스 위치는 다시 누르면 비운다(선택 안 함)
   g.querySelectorAll('.rs-chip').forEach(x=>x.setAttribute('aria-checked',String(g.dataset.group==='kind'?x===b:x.dataset.v===srcLoc)));
   if(g.dataset.group==='src')drawSource();drawSeries();});
  form.oninput=form.onchange=e=>{if(e.target.name!=='series_apply')drawSeries();};
  form.querySelector('.rs-close').onclick=form.querySelector('.rs-cancel').onclick=()=>dialog.close();
  form.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;form.querySelectorAll('[data-mode]').forEach(x=>x.setAttribute('aria-checked',String(x===b)));
   form.querySelector('.rs-single').hidden=mode!=='single';form.querySelector('.rs-weekly').hidden=mode!=='weekly';
   form.elements.date.required=form.elements.time1.required=mode==='single';preview();});
  form.querySelector('.rs-weekly').addEventListener('input',preview);
  if(!row){const wd=form.querySelector(`[name=wd][value="${selected.dow}"]`);if(wd)wd.checked=true;}
  const del=(following)=>async()=>{
   const n=following?'이 회차와 이후 회차를 모두':'이 회차를';
   if(!await askConfirm({title:`${n} 삭제할까요?`,body:'되돌릴 수 없어요.',ok:'삭제',danger:true}))return;
   await run(()=>removeRows(client,row,{following}));
  };
  const d1=form.querySelector('.rs-delete');if(d1)d1.onclick=del(false);
  const d2=form.querySelector('.rs-delete-following');if(d2)d2.onclick=del(true);
  form.querySelector('.rs-error').textContent='';
  dialog.showModal();
  (form.querySelector('.rs-work-search')||form.elements.date).focus();   // not the × button
  if(!row)loadWorks().then(()=>workResults(form.querySelector('.rs-work-search')?.value||'')).catch(e=>{const b=form.querySelector('.rs-work-results');if(b){b.innerHTML=`<p class="rs-hint">${esc(e.message)}</p>`;b.hidden=false;}});
 }
 async function run(task){
  const buttons=form.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);form.querySelector('.rs-error').textContent='';
  try{await task();dialog.close();await load();}
  catch(e){form.querySelector('.rs-error').textContent=e.message;}
  finally{buttons.forEach(b=>b.disabled=false);}
 }
 form.addEventListener('submit',e=>{
  e.preventDefault();
  if(!picked){form.querySelector('.rs-error').textContent='작품을 골라 주세요.';return;}
  const f=form.elements,base={work_id:picked.id,work_title:picked.title,platform:f.platform.value.trim(),note:f.note.value.trim(),release_kind:kind,source_location:srcLoc,source_channel_ids:srcLoc==='youtube'?srcChans:[]};
  const ch=srcLoc==='youtube'&&channels.find(c=>c.id===srcChans[0]),link=ch&&f.link_work?.checked?()=>linkWorkSource(client,picked.title,ch,card):async()=>{};
  if(editing){
   const patch={release_at:kstISO(f.date.value,f.time1.value),episode_label:f.episode.value.trim()||null,episode_no:episodeNo(f.episode.value),status:f.status.value,platform:base.platform||null,note:base.note||null,release_kind:base.release_kind,source_location:base.source_location,source_channel_ids:base.source_channel_ids};
   const follow=f.series_apply?.checked?seriesChanges():null;
   run(async()=>{await updateRow(client,editing.id,patch);if(follow)await updateFollowing(client,editing,{time:follow.time,fields:follow.fields});await link();});
   return;
  }
  if(mode==='weekly'){
   const wd=[...form.querySelectorAll('[name=wd]:checked')].map(i=>+i.value);
   const list=weeklyRows({start:f.start.value,weekdays:wd,time:f.time.value,from:+f.from.value,to:+f.to.value,fmt:f.fmt.value,per:+f.per.value});
   if(!list.length){form.querySelector('.rs-error').textContent='요일과 회차 범위를 확인해 주세요.';return;}
   const series_id=crypto.randomUUID();
   run(async()=>{await insertRows(client,list.map(r=>({...base,series_id,release_at:kstISO(r.date,r.time),episode_label:r.episode_label,episode_no:r.episode_no})));await link();});
   return;
  }
  run(async()=>{await insertRows(client,[{...base,release_at:kstISO(f.date.value,f.time1.value),episode_label:f.episode.value.trim(),status:f.status.value}]);await link();});
 });
 const add=$('.schedule-add');if(add)add.onclick=()=>openDialog();
 $('.schedule-list').addEventListener('click',e=>{
  const open=e.target.closest('.rs-open');
  if(open&&canEdit){const r=rows.find(x=>x.id===open.dataset.id);if(r)openDialog(r);}
 });
 renderCalendar();renderList();load();
 return()=>{dead=true;if(dialog.open)dialog.close();if(chanDlg.open)chanDlg.close();};
}
