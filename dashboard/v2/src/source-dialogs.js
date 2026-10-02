import {buildRoom,defaultItems,itemsSeconds,compileName,nextNo,epText,shortTitle} from './source-room-model.js';
import {chanChip,when} from './source-room.js';
import {showToast} from './toast.js';
import {askConfirm} from './confirm-dialog.js';
import {esc} from './review-details.js?v=web-1';
// 소스 창고 창 세 개(0121) — 유튜브 원천 설정 · 합본 만들기 · 작업하기. 쓰기는 모두 RPC(운영자부터).

const mmss=s=>{s=Math.max(0,Math.round(Number(s)||0));return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;};
const av=(src,name)=>src?`<img class="sr-av" src="${esc(src)}" alt="" referrerpolicy="no-referrer">`:`<span class="sr-av">${esc((name||'?').slice(0,1))}</span>`;
const sw=(name,on)=>`<button type="button" class="sr-sw${on?' on':''}" role="switch" aria-checked="${!!on}" data-sw="${name}"></button>`;
const seg=(name,opts,val)=>`<span class="sr-seg" data-seg="${name}">${opts.map(([v,t])=>`<button type="button" data-v="${esc(v)}" class="${String(v)===String(val)?'on':''}">${esc(t)}</button>`).join('')}</span>`;
const row=(label,sub,ctrl)=>`<div class="sr-row"><span class="sr-lb">${label}${sub?`<small>${sub}</small>`:''}</span>${ctrl}</div>`;

function shell(title,sub=''){
 const d=document.createElement('dialog');d.className='sr-dlg';d.tabIndex=-1;
 d.innerHTML=`<header><div><h3></h3>${sub?'<p class="sr-sm"></p>':''}</div><button type="button" class="sr-x" aria-label="닫기">×</button></header><div class="sr-body"></div><p class="sr-err" role="alert"></p><footer class="sr-act"></footer>`;
 d.querySelector('h3').textContent=title;if(sub)d.querySelector('.sr-sm').textContent=sub;
 const close=()=>{d.close();d.remove();};
 d.querySelector('.sr-x').onclick=close;d.addEventListener('close',()=>d.remove());
 d.addEventListener('click',e=>{if(e.target===d)close();});
 document.body.append(d);
 const show=d.showModal.bind(d);d.showModal=()=>{show();d.focus();};   // 열 때 닫기 버튼이 아니라 창에 초점(× 에 초점 테두리가 뜨지 않게)
 const wire=()=>{
  d.querySelectorAll('[data-sw]').forEach(b=>b.onclick=()=>{const on=!b.classList.contains('on');b.classList.toggle('on',on);b.setAttribute('aria-checked',on);b.dispatchEvent(new Event('change',{bubbles:true}));});
  d.querySelectorAll('[data-seg]').forEach(s=>s.querySelectorAll('button').forEach(b=>b.onclick=()=>{s.querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));s.dispatchEvent(new Event('change',{bubbles:true}));}));
 };
 const val={sw:n=>d.querySelector(`[data-sw="${n}"]`)?.classList.contains('on'),seg:n=>d.querySelector(`[data-seg="${n}"] .on`)?.dataset.v};
 const err=t=>{d.querySelector('.sr-err').textContent=t||'';};
 return {d,body:d.querySelector('.sr-body'),act:d.querySelector('.sr-act'),close,wire,val,err};
}

// 채널 고르기 — 아이콘 + 이름. multi 면 체크 칸, 아니면 하나.
function picker(host,{options,selected=[],multi=false,onChange}){
 let sel=new Set(selected);
 const draw=()=>{
  const chosen=options.filter(o=>sel.has(o.id));
  const cap=chosen.length?`<span class="sr-stk">${chosen.slice(0,3).map(o=>av(o.avatar,o.name)).join('')}</span>${esc(chosen[0].name)}${chosen.length>1?` 외 ${chosen.length-1}`:''}`:'<span class="sr-ph">고르기</span>';
  host.innerHTML=`<button type="button" class="sr-pick" aria-haspopup="listbox" aria-expanded="false">${cap}<em>⌄</em></button><div class="sr-pick-menu" role="listbox" hidden>${options.map(o=>`<button type="button" role="option" aria-selected="${sel.has(o.id)}" data-id="${esc(o.id)}">${multi?`<b class="sr-ck${sel.has(o.id)?' on':''}"></b>`:''}${av(o.avatar,o.name)}<span>${esc(o.name)}</span>${!multi&&sel.has(o.id)?'<small>✓</small>':''}</button>`).join('')}</div>`;
  const btn=host.querySelector('.sr-pick'),menu=host.querySelector('.sr-pick-menu');
  btn.onclick=e=>{e.stopPropagation();menu.hidden=!menu.hidden;btn.setAttribute('aria-expanded',!menu.hidden);};
  menu.querySelectorAll('[data-id]').forEach(b=>b.onclick=e=>{e.stopPropagation();const id=b.dataset.id;
   if(multi){sel.has(id)?sel.delete(id):sel.add(id);}else sel=new Set([id]);
   draw();if(multi)host.querySelector('.sr-pick-menu').hidden=false;onChange?.([...sel]);});
 };
 const shut=e=>{if(!host.contains(e.target)){const m=host.querySelector('.sr-pick-menu');if(m)m.hidden=true;}};
 document.addEventListener('click',shut);
 draw();
 return {get:()=>[...sel],release:()=>document.removeEventListener('click',shut)};
}

// ── 유튜브 원천 설정 ──────────────────────────────────────────────
const EP_FORMATS=[['','자동(5화 · EP.5)'],['EP[.\\s]?(\\d{1,4})','EP.410 모양만'],['custom','직접 적기']];
export function openSourceSettings({client,data,youtube=false,onSaved}){
 const card=data.card||{};
 const rows=(data.yt||[]).map(s=>({channel_id:s.channel_id||'',url:s.channel_id?'':s.url,label:s.label||'',title_filter:s.title_filter||'',episode_regex:s.episode_regex||'',last:s.last_checked_at,found:s.last_found,error:s.last_error}));
 const chOpts=[...data.channels.map(c=>({id:c.id,name:c.name.replace(/\s*:.*$/,''),avatar:c.avatar_url})),{id:'url',name:'재생목록 주소 직접 적기',avatar:''}];
 let showYt=youtube||rows.length>0;   // 파일 원본 작품(가왕쇼 등)은 유튜브 칸 없이 기본값만
 const ui=shell('작품 설정',data.work);
 const pickers=[];
 function draw(){
  pickers.splice(0).forEach(p=>p.release());
  const fmt=r=>EP_FORMATS.some(([v])=>v===r.episode_regex)?r.episode_regex:'custom';
  const ytHtml=!showYt?'':`<h4>유튜브 원천</h4><p class="sr-hint">여기 적은 채널에서 이 작품 클립을 모아요. 위에 있는 채널이 먼저예요. 아래 채널 클립은 위 채널과 같은 장면을 잘라내고 남은 부분만 합본에 들어가요. 남는 부분이 20초보다 짧으면 통째로 빼요.</p>
   <div class="sr-srcs">${rows.map((r,i)=>`<div class="sr-srcrow" data-i="${i}">
    <span class="sr-rank">${i+1}</span>
    <div class="sr-srcbody"><div class="sr-srcline"><span class="sr-pickhost"></span>${i===0?'<span class="sr-first">먼저 씀</span>':''}
     <span class="sr-grow"></span>${i>0?`<button type="button" class="sr-ic" data-up="${i}" aria-label="위로">↑</button>`:''}${i<rows.length-1?`<button type="button" class="sr-ic" data-down="${i}" aria-label="아래로">↓</button>`:''}<button type="button" class="sr-ic" data-del="${i}" aria-label="빼기">×</button></div>
     ${r.channel_id?'':`<input class="sr-in" data-f="url" placeholder="https://www.youtube.com/playlist?list=…" value="${esc(r.url)}">`}
     <div class="sr-srcline"><label class="sr-mini">제목에<input class="sr-in" data-f="title_filter" placeholder="${esc(data.work)}" value="${esc(r.title_filter)}"></label>
      <label class="sr-mini">회차 읽기<select class="sr-in" data-f="fmt">${EP_FORMATS.map(([v,t])=>`<option value="${esc(v)}" ${fmt(r)===v?'selected':''}>${esc(t)}</option>`).join('')}</select></label></div>
     ${fmt(r)==='custom'?`<input class="sr-in" data-f="episode_regex" placeholder="회차 숫자를 ( ) 로 묶은 정규식" value="${esc(r.episode_regex)}">`:''}
     ${r.last?`<small class="sr-muted">${r.error?'마지막 확인 실패':`클립 ${r.found??0}개`} · ${esc(when(r.last))} 확인</small>`:'<small class="sr-muted">아직 확인 전이에요</small>'}
    </div></div>`).join('')}</div>
   <div class="sr-foot"><small class="sr-muted">하루 한 번 아침 7시에 새 클립을 확인해요.</small><button type="button" class="sr-btn" data-add>채널 추가</button></div>`;
  ui.body.innerHTML=ytHtml+`<div class="${showYt?'sr-sect':''}"><h4>기본값</h4><p class="sr-hint">창이 처음 열릴 때 이렇게 골라져 있어요. 창에서 그때그때 바꿀 수 있어요.</p>
    ${row('회차 부르는 말','소스 창고와 작업 이름에 써요 · 예: 5화 · 410회 · 1회차',seg('unit',[['화','화'],['회','회'],['회차','회차']],ui.val.seg('unit')||card.episode_unit||'화'))}
    ${showYt?row('한 합본에 넣을 회차','합본 만들 때 · 티빙에서 두 편씩 나오는 드라마는 2회씩',seg('group',[['1','1회씩'],['2','2회씩']],ui.val.seg('group')||card.compile_group||1)):''}
    ${showYt?row('앞 회차 몰아보기 넣기','합본 만들 때 · 지난 이야기를 말할 때 밑 화면으로만 써요',sw('recap',ui.val.sw('recap')??card.compile_recap)):''}
    ${row('앞 회차 내용 참고하기','작업할 때 · 앞 회차 작업의 대본 요약을 같이 넘겨요',sw('prev',ui.val.sw('prev')??card.task_prev_ref))}</div>
   ${showYt?'':'<p class="sr-sm"><button type="button" class="sr-link" data-yt>유튜브에서 클립을 받는 작품이면 원천 채널 추가 ›</button></p>'}`;
  ui.body.querySelectorAll('.sr-srcrow').forEach(el=>{
   const i=+el.dataset.i,r=rows[i];
   pickers.push(picker(el.querySelector('.sr-pickhost'),{options:chOpts,selected:[r.channel_id||'url'],onChange:([id])=>{r.channel_id=id==='url'?'':id;draw();}}));
   el.querySelectorAll('[data-f]').forEach(inp=>inp.oninput=inp.onchange=()=>{const f=inp.dataset.f;if(f==='fmt'){r.episode_regex=inp.value==='custom'?(r.episode_regex&&!EP_FORMATS.some(([v])=>v===r.episode_regex)?r.episode_regex:'(\\d{1,4})화'):inp.value;draw();}else r[f]=inp.value;});
  });
  ui.body.querySelectorAll('[data-up]').forEach(b=>b.onclick=()=>{const i=+b.dataset.up;[rows[i-1],rows[i]]=[rows[i],rows[i-1]];draw();});
  ui.body.querySelectorAll('[data-down]').forEach(b=>b.onclick=()=>{const i=+b.dataset.down;[rows[i+1],rows[i]]=[rows[i],rows[i+1]];draw();});
  ui.body.querySelectorAll('[data-del]').forEach(b=>b.onclick=()=>{rows.splice(+b.dataset.del,1);draw();});
  const add=()=>{rows.push({channel_id:data.channels[0]?.id||'',url:'',title_filter:data.work,episode_regex:''});showYt=true;draw();};
  ui.body.querySelector('[data-add]')?.addEventListener('click',add);
  ui.body.querySelector('[data-yt]')?.addEventListener('click',add);
  ui.wire();
 }
 draw();
 ui.act.innerHTML='<button type="button" class="sr-btn ghost" data-cancel>취소</button><button type="button" class="sr-btn solid" data-save>저장</button>';
 ui.act.querySelector('[data-cancel]').onclick=ui.close;
 ui.act.querySelector('[data-save]').onclick=async e=>{
  const b=e.currentTarget;b.disabled=true;ui.err('');
  const items=rows.map(r=>({channel_id:r.channel_id||null,url:r.channel_id?'':r.url.trim(),title_filter:r.title_filter.trim(),episode_regex:r.episode_regex||''}));
  const bad=items.find(x=>!x.channel_id&&!/^https:\/\/(www\.)?youtube\.com\//.test(x.url));
  if(bad){ui.err('재생목록 주소는 https://www.youtube.com/ 으로 시작해야 해요.');b.disabled=false;return;}
  const r1=showYt?await client.rpc('set_work_youtube_sources',{p_work:data.work,p_items:items}):{};
  const r2=r1.error?null:await client.rpc('set_work_compile_defaults',{p_work:data.work,p_unit:ui.val.seg('unit'),
   p_group:showYt?+ui.val.seg('group'):null,p_recap:showYt?ui.val.sw('recap'):null,p_prev_ref:ui.val.sw('prev')});
  const er=r1.error||r2?.error;
  if(er){ui.err('저장하지 못했어요. '+er.message);b.disabled=false;return;}
  const r3=showYt&&items.length?await client.rpc('request_youtube_check',{p_work:data.work}):null;
  pickers.forEach(p=>p.release());ui.close();
  showToast(document.body,r3&&!r3.error?'저장했어요. 새 클립을 지금 확인하고 있어요.':'저장했어요.');onSaved?.();
 };
 ui.d.addEventListener('close',()=>pickers.forEach(p=>p.release()));
 ui.d.showModal();
}

// ── 합본 만들기 · 구성 보기 ─────────────────────────────────────────
export function openCompile({client,data,room,group,comp,readOnly=false,onDone}){
 if(readOnly&&comp){
  const items=comp.recipe?.items||[],man=comp.recipe?.manifest?.clips||[];
  const ui=shell(`${epText(comp.episode_key,room.unit)} ${comp.name}`,`${when(comp.done_at||comp.created_at)}에 만든 합본이에요.`);
  ui.body.innerHTML=`<ol class="sr-order">${items.map((it,i)=>{const m=man[i]||{};const span=m.concat_start_sec!=null?`${mmss(m.concat_start_sec)}~${mmss(m.concat_end_sec)}`:'';
   return `<li><span class="sr-otitle">${esc(shortTitle(it.title,comp.work_title))}<small>${esc(kindText(it,room.unit))}${it.start!=null||it.end!=null?` · 원본 ${mmss(it.start||0)}~${it.end!=null?mmss(it.end):'끝'}만`:''}</small></span><small>${esc(span)}</small></li>`;}).join('')}</ol>
   ${comp.notes?`<details class="sr-notes"><summary>대본 쓸 때 같이 넘기는 구성 메모</summary><pre>${esc(comp.notes)}</pre></details>`:''}`;
  ui.act.innerHTML='<button type="button" class="sr-btn" data-close>닫기</button>';ui.act.querySelector('[data-close]').onclick=ui.close;
  ui.d.showModal();return;
 }
 const card=data.card||{};
 let size=room.group,recap=!!card.compile_recap,state=null;
 const ui=shell('','');
 const regroup=()=>{
  const r=size===room.group?room:buildRoom({...data,card:{...card,compile_group:size}});
  const a=parseInt(String(group.key).split('-')[0],10);
  return r.groups.find(g=>String(g.key).split('-').map(Number).includes(a))||group;
 };
 function compute(){const g=regroup();const {items,skipped}=defaultItems(g,{recap});state={g,items,skipped};}
 function draw(){
  const {g,items,skipped}=state,name=compileName(items,size);
  ui.d.querySelector('h3').textContent=`${g.label} ${name} 만들기`;
  const low=g.clips.filter(c=>c.rank>1&&c.overlap);
  ui.body.innerHTML=`<p class="sr-sm">아래 순서로 이어 붙여요. 끌어서 순서를 바꾸거나 ×로 뺄 수 있어요. 클립 앞뒤의 채널 화면은 잘라요.</p>
   <ol class="sr-order" data-list>${items.map((it,i)=>`<li draggable="true" data-i="${i}"><span class="sr-otitle">${esc(shortTitle(it.title,data.work))}<small>${esc(kindText(it,room.unit))}${it.start!=null?` · ${mmss(it.start)}~${it.end!=null?mmss(it.end):'끝'}만`:''}</small></span>${chanChip(it.channel,it.avatar)}<small class="sr-cd">${mmss(it.use)}</small><span class="sr-gr" aria-hidden="true">⋮⋮</span><button type="button" class="sr-ic" data-rm="${i}" aria-label="빼기">×</button></li>`).join('')||'<li class="sr-none">넣을 클립이 없어요</li>'}</ol>
   <p class="sr-warn">같은 회차 안에서는 올라온 순서로 놓았어요. 원래 방송 순서와 다를 수 있어요. 합치면 ${mmss(itemsSeconds(items))}이에요.</p>
   <div class="sr-sect">${row('한 합본에 넣을 회차','',seg('size',[['1','1회씩'],['2','2회씩']],size))}${row('앞 회차 몰아보기 넣기','지난 이야기를 말할 때 밑 화면으로만 써요',sw('recap',recap))}</div>
   ${skipped.length||low.length?`<p class="sr-sm">${overlapSentence(g,skipped)}</p>`:''}`;
  ui.wire();
  ui.body.querySelector('[data-seg="size"]').addEventListener('change',()=>{size=+ui.val.seg('size');compute();draw();});
  ui.body.querySelector('[data-sw="recap"]').addEventListener('change',()=>{recap=ui.val.sw('recap');compute();draw();});
  ui.body.querySelectorAll('[data-rm]').forEach(b=>b.onclick=()=>{state.items.splice(+b.dataset.rm,1);draw();});
  let from=null;
  ui.body.querySelectorAll('[data-list] li[draggable]').forEach(li=>{
   li.ondragstart=e=>{from=+li.dataset.i;e.dataTransfer.effectAllowed='move';li.classList.add('drag');};
   li.ondragend=()=>li.classList.remove('drag');
   li.ondragover=e=>{e.preventDefault();};
   li.ondrop=e=>{e.preventDefault();const to=+li.dataset.i;if(from==null||from===to)return;const [x]=state.items.splice(from,1);state.items.splice(to,0,x);from=null;draw();};
  });
  ui.act.querySelector('[data-go]').disabled=!items.length;
 }
 ui.act.innerHTML='<button type="button" class="sr-btn ghost" data-cancel>취소</button><button type="button" class="sr-btn solid" data-go>합본 만들기</button>';
 ui.act.querySelector('[data-cancel]').onclick=ui.close;
 ui.act.querySelector('[data-go]').onclick=async e=>{
  const b=e.currentTarget;b.disabled=true;ui.err('');
  const {g,items}=state;
  const {error}=await client.rpc('request_source_compilation',{p_work:data.work,p_episode_key:g.key,p_name:compileName(items,size),
   p_items:items.map(i=>({source_id:i.source_id,start:i.start,end:i.end})),p_options:{group:size,recap}});
  if(error){ui.err('합본을 걸지 못했어요. '+error.message);b.disabled=false;return;}
  ui.close();showToast(document.body,'합본을 만들기 시작했어요. 다 되면 회차에 나타나요.');onDone?.();
 };
 compute();draw();ui.d.showModal();
}
function kindText(it,unit){
 return it.kind==='recap'?`${it.label?epText(it.label,unit)+' ':''}몰아보기`:it.kind==='prerelease'?`${it.label?epText(it.label,unit)+' ':''}선공개`:it.episode!=null?epText(it.episode,unit):'클립';
}
function overlapSentence(g,skipped){
 const byCh=new Map();
 for(const c of g.clips.filter(c=>c.rank>1&&c.overlap&&(c.overlap.covered||[]).length))byCh.set(c.channel,(byCh.get(c.channel)||0)+1);
 const top=g.clips.find(c=>c.rank<=1);
 const names=[...byCh.keys()].map(n=>chanChip(n,g.clips.find(c=>c.channel===n)?.avatar)).join(' ');
 if(!names)return '';
 return `${names} 클립은 ${top?chanChip(top.channel,top.avatar):'위 채널'}과 겹친 부분을 잘라내고 넣어요.${skipped.length?` 다 겹치거나 남는 부분이 20초보다 짧은 ${skipped.length}개는 빼요.`:''}`;
}

// ── 작업하기 ─────────────────────────────────────────────────────
export function openTask({client,data,room,group,sourceId,task=null,workChannels=[],onDone,readOnly=false}){
 const card=data.card||{},comp=data.comps.find(c=>c.source_id===sourceId),file=data.sources.find(s=>s.id===sourceId);
 const name=comp?`${group.label} ${comp.name}`:`${group.label} 원본`;
 const opts=task?.options||{};
 const a=parseInt(String(group.key).split('-')[0],10);
 const prev=room.groups.filter(g=>g.key!==''&&parseInt(String(g.key).split('-')[0],10)<a).map(g=>({g,t:g.tasks.filter(t=>t.status==='queued').sort((x,y)=>y.work_no-x.work_no)[0]})).find(x=>x.t);
 const chans=workChannels.map(c=>({id:c.token_slug,name:c.name,avatar:c.avatar_url}));
 let chosen=task?[task.channel_slug]:chans.length===1?[chans[0].id]:[];
 const others=group.tasks.filter(t=>t.source_id===sourceId&&t.status!=='deleted'&&t.id!==task?.id);
 const ui=shell(task?`${name} · #${task.work_no}`:`${name}으로 작업하기`,'');
 const sub=comp?`${Math.round((Number(comp.duration_sec)||0)/60)}분 · 클립 ${comp.clip_count||0}개 · ${when(comp.done_at||comp.created_at)}에 만든 합본이에요.`
  :`${file?.duration_sec?Math.round(file.duration_sec/60)+'분 · ':''}${file?.title||'원본 파일'}`;
 let pick;
 ui.body.innerHTML=`<p class="sr-sm">${esc(sub)}</p><div class="sr-sect">
  ${row('앞 회차 내용 참고하기',prev?`${esc(prev.g.label)} #${prev.t.work_no} 작업의 대본 요약을 같이 넘겨요`:'앞 회차 작업이 아직 없어요',sw('prev',opts.prev_ref??card.task_prev_ref))}
  <div class="sr-row top"><span class="sr-lb">만들 채널${task?'':'<small>여러 개 고르면 채널마다 작업이 따로 생겨요</small>'}</span><span class="sr-pickhost"></span></div>
  ${row('만들 편수','',`<input class="sr-in sr-num" type="number" min="1" max="14" value="${Number(opts.count)||10}" data-count>`)}
  ${row('다른 채널이 쓴 장면 피하기','켜면 한 채널씩 차례로 만들어요. 먼저 만든 채널이 고른 장면은 다음 채널이 쓰지 않아요.',sw('avoid',opts.avoid_other??true))}
  <div class="sr-row col"><span class="sr-lb">대본 쓸 때 참고할 메모</span><textarea class="sr-memo" maxlength="2000" placeholder="예: 실장 정체는 6화 엔딩 전까지 말하지 않기">${esc(opts.memo||'')}</textarea></div>
 </div><p class="sr-warn" data-plan hidden></p>${others.length&&!task?`<p class="sr-sm">이 원본으로 한 작업: ${others.map(t=>'#'+t.work_no).join(' · ')}</p>`:''}`;
 ui.wire();
 // 채널마다 만들어질 영상 모양(0134) — 채널 템플릿의 '이 채널에서만' → '모든 채널 기본' → 엔진 기본. 바꾸는 곳은 채널 템플릿
 let tpl=null;
 const tplName=id=>!tpl?'':tpl.chan.has(id)?'<b>이 채널 값</b>':tpl.work?'모든 채널 기본':'엔진 기본';
 const plan=()=>{const el=ui.body.querySelector('[data-plan]'),list=pick.get();el.hidden=!list.length;
  if(!list.length)return;const n=nextNo(group);
  el.innerHTML=(task?'':'채널마다 작업이 따로 생겨요.')+'<span class="sr-tpl-lines">'+list.map((id,i)=>{const c=chans.find(x=>x.id===id);return `<span>${chanChip(c?.name||id,c?.avatar,task?'':`#${n+i}`)}${tpl?` 모양 ${tplName(id)}`:''}</span>`;}).join('')+'</span>'+(tpl?'<small>영상 모양은 채널 템플릿에서 작품마다 정해요.</small>':'');};
 Promise.all([client.from('channel_work_designs').select('token_slug').eq('work_title',data.work),
  client.from('work_cards').select('render_design').eq('work_title',data.work).maybeSingle()]).then(([c,w])=>{
   tpl={chan:new Set((c.data||[]).map(x=>x.token_slug)),work:!!(w.data?.render_design&&Object.keys(w.data.render_design).length)};plan();}).catch(()=>{});
 pick=picker(ui.body.querySelector('.sr-pickhost'),{options:chans,selected:chosen,multi:!task,onChange:()=>plan()});
 plan();
 const options=()=>({count:+ui.body.querySelector('[data-count]').value||10,prev_ref:ui.val.sw('prev'),avoid_other:ui.val.sw('avoid'),memo:ui.body.querySelector('.sr-memo').value.trim()||null,...(opts.args?{args:opts.args}:{})});
 ui.act.innerHTML=readOnly?'<button type="button" class="sr-btn" data-close>닫기</button>':`${task?'<button type="button" class="sr-btn ghost danger" data-del>지우기</button><span class="sr-grow"></span>':'<button type="button" class="sr-btn ghost" data-close>취소</button>'}<button type="button" class="sr-btn" data-save>저장</button><button type="button" class="sr-btn solid" data-start>작업 시작</button>`;
 ui.act.querySelector('[data-close]')?.addEventListener('click',ui.close);
 if(!readOnly)ui.act.insertAdjacentHTML('afterend','<p class="sr-sm sr-right">저장하면 시작 전 작업으로 남아요. 나중에 회차 화면에서 이 작업을 눌러 시작할 수 있어요.</p>');
 const go=async(start,b)=>{
  ui.err('');const list=pick.get();
  if(!list.length){ui.err('만들 채널을 골라 주세요.');return;}
  b.disabled=true;let r;
  if(task){
   r=await client.rpc('update_tikitaka_task',{p_task:task.id,p_channel:list[0],p_options:options()});
   if(!r.error&&start)r=await client.rpc('start_tikitaka_tasks',{p_tasks:[task.id]});
  }else r=await client.rpc('save_tikitaka_tasks',{p_source:sourceId,p_channels:list,p_options:options(),p_start:start});
  if(r.error){ui.err((start?'시작하지 못했어요. ':'저장하지 못했어요. ')+r.error.message);b.disabled=false;return;}
  const made=task?[{work_no:task.work_no}]:(r.data||[]);
  pick.release();ui.close();
  showToast(document.body,`${made.map(m=>'#'+m.work_no).join(' · ')} ${start?'작업을 시작했어요.':'시작 전 작업으로 저장했어요.'}`);onDone?.();
 };
 ui.act.querySelector('[data-save]')?.addEventListener('click',e=>go(false,e.currentTarget));
 ui.act.querySelector('[data-start]')?.addEventListener('click',e=>go(true,e.currentTarget));
 ui.act.querySelector('[data-del]')?.addEventListener('click',async e=>{
  if(!await askConfirm({title:`#${task.work_no} 작업을 지울까요?`,body:'아직 아무것도 만들지 않았어요. 지운 번호는 다시 쓰지 않아요.',ok:'지우기',danger:true}))return;
  const {error}=await client.rpc('delete_tikitaka_task',{p_task:task.id});
  if(error){ui.err('지우지 못했어요. '+error.message);return;}
  pick.release();ui.close();showToast(document.body,`#${task.work_no} 작업을 지웠어요.`);onDone?.();
 });
 ui.d.addEventListener('close',()=>pick.release());
 ui.d.showModal();
}
