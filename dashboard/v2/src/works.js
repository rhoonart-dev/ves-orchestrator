import {mountWorkAssets,assetRequest} from './work-assets.js?v=web-2';
import {loadCatalog,loadGuide} from './work-catalog.js';
import {loadSources,workSummary,videoRows,epUsable,epUsed,epTries,epLeft,epRemain,setLimit,setUsed} from './sources.js';
import {workPosters} from './work-posters.js';
import {icon} from './icons.js';
import {enhanceDropdowns} from './dropdowns.js';
import {guideFragment} from './workbench.js?v=pr-6';
import {GuideDetails} from './guide-details.js';
import {esc} from './review-details.js';
const sampleWorks=[['lotto','로또 1등도 출근합니다','드라마'],['jigeum','지금 불륜이 문제가 아닙니다(c)','드라마'],['gawang','가왕쇼','예능'],['sinbyeong','신병','드라마'],['jjijji','종합광고대행사 찌찌: 광고의 온도편','드라마'],['karlovy','카를로비바리','영화']].map(([id,name,type])=>({id,name,type}));
const state={work:'all',kind:'전체',workQuery:''};
const EDIT_ROLES=['operator','admin'];
const norm=t=>String(t||'').replace(/\s/g,'');
const mmss=d=>d==null?'–':Math.floor(d/60)+':'+String(Math.round(d%60)).padStart(2,'0');
const date=value=>new Date(value).toLocaleDateString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',timeZone:'Asia/Seoul'});
export function mountWorks(root,{client,role}={}){
 let works=sampleWorks.map(w=>({...w})),releaseAssets=()=>{},liveGuides={};
 root.parentElement.classList.add('works-page');
 let catalogByTitle=new Map(),disposed=false,src=null,srcError='',openVideos=new Set(),guideData=null,guideError=false,releaseDropdown=()=>{},copyNoticeTimer;
 root.innerHTML=`<div class="works-layout"><aside class="works-sidebar" aria-label="작품 목록"><label class="works-search">${icon('search')}<input type="search" placeholder="작품 검색" aria-label="작품 검색" value="${esc(state.workQuery)}"></label><div class="works-options"></div></aside><section class="works-main"><div class="works-heading"></div><div class="works-toolbar"><div class="works-kinds" aria-label="작품 유형"></div></div><div class="works-results" aria-live="polite"></div></section></div><dialog class="works-guide" aria-labelledby="works-guide-title"><header><div><p class="works-guide-kicker"></p><h2 id="works-guide-title"></h2><p class="works-guide-meta"></p></div><button type="button" class="works-close" aria-label="안내 닫기">×</button></header><div class="works-guide-body"></div><footer></footer><div role="status" aria-live="polite" aria-atomic="true" class="works-copy-status"></div></dialog>`;
 const $=s=>root.querySelector(s),guideDialog=$('.works-guide'),canEdit=EDIT_ROLES.includes(role);
 function hideCopyNotice(){clearTimeout(copyNoticeTimer);$('.works-copy-status')?.classList.remove('visible');}   // 화면을 떠나며 창을 닫을 때는 이미 없다
 function showCopyNotice(message,duration=1800){
  const notice=$('.works-copy-status');clearTimeout(copyNoticeTimer);
  notice.textContent=message;notice.classList.add('visible');
  copyNoticeTimer=setTimeout(()=>notice.classList.remove('visible'),duration);
 }
 guideDialog.addEventListener('close',hideCopyNotice);
 const closeDialog=dialog=>{dialog.querySelector('.works-close').onclick=()=>dialog.close();dialog.addEventListener('click',e=>{if(e.target!==dialog)return;const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();});};
 closeDialog(guideDialog);
 // 작품 목록 = 작품 카탈로그 + 소스가 등록된 작품(소스 창고에만 있는 작품도 고를 수 있게)
 const srcTitle=w=>src&&Object.keys(src.eps).find(t=>norm(t)===norm(w.name)||norm(t)===norm(liveGuides[w.id]?.title));
 function allWorks(){
  if(!src)return works;
  const have=new Set(works.map(srcTitle).filter(Boolean));
  return [...works,...Object.keys(src.eps).filter(t=>!have.has(t)).sort((a,b)=>a.localeCompare(b,'ko')).map(t=>{const id='src-'+t,rec=catalogByTitle.get(norm(t));if(rec)liveGuides[id]=rec;return {id,name:t,type:rec?.video_type||'작품'};})];
 }
 const epCount=w=>{const t=srcTitle(w);return t?Object.keys(src.eps[t]).length:0;};
 // 포스터 — 레이블리 작품 DB(licensed_video.thumbnail)의 것, 없으면 로컬에 적어 둔 것
 const poster=w=>liveGuides[w.id]?.thumbnail||catalogByTitle.get(norm(w.name))?.thumbnail||workPosters[w.id]?.url||Object.values(workPosters).find(p=>norm(p.title)===norm(w.name))?.url||'';
 function chooseWork(id){state.work=id;state.kind='전체';render();$('.works-main').scrollTop=0;}
 // 좁은 화면의 가로 포스터 줄 — 오른쪽에 더 있으면 끝을 흐리게(끝까지 넘기면 흐림을 없앤다)
 function fadeEdge(){const o=$('.works-options');o.classList.toggle('more-right',o.scrollLeft+o.clientWidth<o.scrollWidth-4);}
 function renderSidebar(){
  const list=allWorks();
  $('.works-options').innerHTML=`<button type="button" class="works-option works-all ${state.work==='all'?'active':''}" data-work="all" aria-pressed="${state.work==='all'}">${icon('library')}<span>전체 작품</span><small>${list.length}</small></button>`+list.filter(w=>w.name.toLowerCase().includes(state.workQuery.trim().toLowerCase())).map(w=>`<button type="button" class="works-option ${state.work===w.id?'active':''}" data-work="${esc(w.id)}" aria-pressed="${state.work===w.id}">${poster(w)?`<img src="${esc(poster(w))}" alt="" referrerpolicy="no-referrer">`:`<span class="work-no-poster">${icon('library')}</span>`}<span><strong>${esc(w.name)}</strong><em>${esc(w.type)}</em></span><small title="소스 회차">${src?epCount(w)||'':''}</small></button>`).join('');
  $('.works-options').querySelectorAll('[data-work]').forEach(b=>b.onclick=()=>chooseWork(b.dataset.work));
  fadeEdge();
 }
 const chip=(sum)=>{
  const d=sum.days===Infinity?'':` · ${Math.floor(sum.days)}일치`;
  return {none:'<span class="src-chip">소스 없음</span>',empty:'<span class="src-chip crit">전 회차 소진</span>',
   low:`<span class="src-chip warn">${sum.rem}편 남음${d}</span>`,ok:`<span class="src-chip ok">${sum.rem}편 남음${d}</span>`}[sum.state];
 };
 const avatar=c=>c.avatar_url?`<img class="src-avatar" src="${esc(c.avatar_url)}" alt="" referrerpolicy="no-referrer">`:`<span class="src-avatar">${esc((c.name||'?').slice(0,1))}</span>`;
 function render(){
  renderSidebar();
  const list=allWorks(),work=list.find(w=>w.id===state.work);
  $('.works-heading').innerHTML=`<div><h2>${esc(work?.name||'소스 창고')}</h2><p>${esc(work?work.type:'작품별 원본 소스와 채널별 남은 편수')}</p></div>${work&&(!work.id.startsWith('src-')||liveGuides[work.id])?`<div class="works-heading-actions"><button type="button" class="works-button" data-guide="assets">에셋</button><button type="button" class="works-button" data-guide="guide">${icon('file')}권리사 가이드</button><button type="button" class="works-button solid" data-guide="required">${icon('pencil')}필수 기입 정보</button></div>`:''}`;
  $('.works-heading').querySelectorAll('[data-guide]').forEach(b=>b.onclick=()=>showGuide(b.dataset.guide));
  const out=$('.works-results');
  if(!src){$('.works-toolbar').hidden=true;out.innerHTML=`<p class="works-empty">${srcError?'소스 목록을 불러오지 못했어요. '+esc(srcError):client?'소스 목록을 불러오는 중…':'로그인하면 소스 창고를 볼 수 있어요.'}</p>`;return;}
  if(work){$('.works-toolbar').hidden=true;renderWork(work);return;}
  // 전체 — 소스가 있는 작품을 급한 순(며칠치가 적은 순)으로
  const kinds=['전체','드라마','예능','영화','웹콘텐츠','다큐멘터리'];
  const rows=list.map(w=>({w,t:srcTitle(w)})).filter(r=>r.t).map(r=>({...r,sum:workSummary(src,r.t)}))
   .sort((a,b)=>(a.sum.days-b.sum.days)||a.w.name.localeCompare(b.w.name,'ko'));
  const shown=rows.filter(r=>state.kind==='전체'||r.w.type===state.kind);
  $('.works-toolbar').hidden=false;
  $('.works-kinds').innerHTML=kinds.filter(k=>k==='전체'||rows.some(r=>r.w.type===k)).map(k=>`<button type="button" data-kind="${k}" class="${state.kind===k?'active':''}" aria-pressed="${state.kind===k}">${k}<small>${k==='전체'?rows.length:rows.filter(r=>r.w.type===k).length}</small></button>`).join('');
  $('.works-kinds').querySelectorAll('button').forEach(b=>b.onclick=()=>{state.kind=b.dataset.kind;render();});
  out.innerHTML=`${src.byChannelMissing?'<p class="src-warn">채널별 소진 기록을 읽지 못했어요 — 채널 숫자가 0으로 보일 수 있어요.</p>':''}
   <div class="src-works">${shown.map(({w,sum})=>`<button type="button" class="src-work" data-work="${esc(w.id)}">
    ${poster(w)?`<img class="src-poster" src="${esc(poster(w))}" alt="" referrerpolicy="no-referrer">`:`<span class="src-poster">${icon('library')}</span>`}
    <span class="src-work-copy"><strong>${esc(w.name)}</strong><small>${sum.eps.length}회차 · ${sum.chs.length?esc(sum.chs.map(c=>c.name).join(', ')):'배정 채널 없음'}</small></span>
    <span class="src-work-next">${sum.next.map(n=>`<span>${avatar(n.channel)}${n.ep?`다음 ${esc(n.ep)}`:'남은 회차 없음'}</span>`).join('')}</span>
    ${chip(sum)}</button>`).join('')||'<p class="works-empty">이 유형의 소스가 없어요.</p>'}</div>`;
  out.querySelectorAll('[data-work]').forEach(b=>b.onclick=()=>chooseWork(b.dataset.work));
 }
 function renderWork(work){
  const out=$('.works-results'),t=srcTitle(work);
  if(!t){out.innerHTML='<div class="src-none"><h3>아직 등록된 원본이 없어요</h3><p>소스 창고에는 VES가 쇼츠를 만들 때 쓰는 원본 영상(회차)이 모여요.</p><ul><li><b>유튜브에 있는 원본</b>은 VES가 알아서 등록해요.</li><li><b>드라이브 같은 파일 원본</b>은 관리자가 한 번 등록해 줘야 해요. <small>(<code>deploy/register_source.py</code>)</small></li></ul><p class="src-muted">작업 컴퓨터에서 바로 만든 작품은 원본 파일을 그 컴퓨터에 두고 쓰기 때문에 여기에는 안 보여요.</p></div>';return;}
  const sum=workSummary(src,t);
  out.innerHTML=`<div class="src-summary">${chip(sum)}<span>${sum.eps.length}회차</span>${sum.chs.length?sum.chs.map(c=>`<span class="src-ch-tag">${avatar(c)}${esc(c.name)}</span>`).join(''):'<span class="src-muted">배정된 채널이 없어 소진되지 않아요 — 채널 목록에서 작품을 배정하세요</span>'}</div>
   <p class="src-help"><b>한도</b>는 그 회차로 만들 수 있는 편수예요(길이로 자동: 10분 미만 1 · 10~30분 2 · 30분 이상 3). 채널마다 따로 세고, <b>발행된 편수</b>만 한도를 깎아요. 반려·취소된 시도는 <b>시도</b>로만 잡혀요.${canEdit?' 숫자를 고치면 바로 저장돼요.':''}</p>
   <p class="src-msg" role="status"></p>
   <div class="src-eps">${sum.eps.map(e=>epBlock(e,sum)).join('')}</div>`;
  out.querySelectorAll('[data-vids]').forEach(b=>b.onclick=()=>{const k=b.dataset.vids;openVideos.has(k)?openVideos.delete(k):openVideos.add(k);renderWork(work);});
  const msg=text=>{const m=out.querySelector('.src-msg');if(m)m.textContent=text;};
  const reload=async note=>{try{src=await loadSources(client);}catch{}if(!disposed){renderWork(work);msg(note);}};
  out.querySelectorAll('[data-limit]').forEach(el=>el.onchange=async()=>{const v=parseInt(el.value,10);
   if(!Number.isInteger(v)||v<0||v>20){msg('한도는 0~20 사이로 적어 주세요.');return reload('');}
   const sids=el.dataset.limit.split(',');try{await setLimit(client,sids,v);reload(sids.length>1?`영상 ${sids.length}개 한도를 ${v}편으로 저장했어요.`:`한도를 ${v}편으로 저장했어요.`);}catch(e){reload('저장하지 못했어요: '+e.message);}});
  out.querySelectorAll('[data-used]').forEach(el=>el.onchange=async()=>{const v=parseInt(el.value,10);
   if(!Number.isInteger(v)||v<0){msg('쓴 수는 0 이상으로 적어 주세요.');return reload('');}
   try{await setUsed(client,el.dataset.used,el.dataset.ch,v);reload(`쓴 수를 ${v}로 저장했어요.`);}catch(e){reload('저장하지 못했어요: '+e.message);}});
 }
 function epBlock(e,sum){
  const key=e.work+'|'+(e.ep??'-'),open=openVideos.has(key);
  const each=e.limits.length?Math.max(...e.limits):0,mixed=new Set(e.limits).size>1;
  const facts=[e.dur?Math.floor(e.dur/60)+'분':'',e.files>1?`영상 ${e.files}개${e.usable<e.files?` · 쓸 수 있는 것 ${e.usable}개`:''}`:'',!epUsable(e)?(!e.active?'비활성':'3분 이하 — 안 써요'):''].filter(Boolean).join(' · ');
  const lim=canEdit?`<label class="src-num" title="${e.files>1?'영상마다 같은 한도가 걸려요':'이 영상으로 만들 편수 상한'}">${e.files>1?'영상당 한도':'한도'}<input type="number" min="0" max="20" value="${each}" data-limit="${esc(e.ids.join(','))}"></label>${e.files>1?`<small class="src-muted">합계 ${e.limit}${mixed?' · 영상별로 다름':''}</small>`:''}`
   :`<small class="src-muted">한도 ${e.limit}${e.files>1?` (영상 ${e.files}개 합)`:''}</small>`;
  const rows=sum.chs.map(c=>{const s=c.token_slug,u=e.ch[s]||{},used=epUsed(e,s),remain=epRemain(e,s),tries=epTries(e,s),left=epLeft(e,s);
   const pct=e.limit?Math.min(100,Math.round(used/e.limit*100)):100,full=!epUsable(e)||remain===0;
   return `<div class="src-ch">${avatar(c)}<span class="src-ch-name">${esc(c.name)}</span><span class="src-gauge"><i class="${full?'full':''}" style="width:${pct}%"></i></span><span class="src-cnt">${used}/${e.limit}</span>
    ${canEdit?`<input class="src-used" type="number" min="0" max="99" value="${used}" data-used="${esc(e.ids[0])}" data-ch="${esc(s)}" aria-label="${esc(c.name)} 쓴 수" title="이 채널이 이 회차로 실제 발행한 편수">`:''}
    <small class="src-muted">발행 ${u.pub||0}${u.lg||u.pin?` · 보정 ${(u.lg||0)+(u.pin||0)}`:''}${full?'':` · 남음 ${remain}`}${tries>used?` · 시도 ${tries}${left?'':' (상한)'}`:''}</small></div>`;}).join('');
  const canOpen=(e.videos||[]).some(v=>v.url||v.title);
  const vids=open?`<div class="src-vids">${videoRows(e).map(v=>{const label=v.title||(v.url?v.url.split('v=').pop():v.sid.slice(0,8));
   const tag=!v.usable?`<span class="src-tag off">${v.active?'하한 미만':'비활성'}</span>`:v.sid===sum.nextSid?'<span class="src-tag next">다음 차례</span>':v.left>0?`<span class="src-tag">${v.left}편 남음</span>`:'<span class="src-tag done">소진</span>';
   const pct=v.limit?Math.min(100,Math.round(v.used/v.limit*100)):100;
   return `<div class="src-vid${v.usable?'':' dim'}"><span class="src-vid-title">${v.url?`<a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(label)}</a>`:esc(label)}</span><span class="src-muted">${mmss(v.dur)}</span><span class="src-gauge sm"><i class="${v.left?'':'full'}" style="width:${pct}%"></i></span><span class="src-cnt">${v.used}/${v.limit}</span>${tag}</div>`;}).join('')}</div>`:'';
  return `<article class="src-ep"><header><b>${e.ep!=null?e.ep+'회차':'단편'}</b>${facts?`<small class="src-muted">${esc(facts)}</small>`:''}${canOpen?`<button type="button" class="src-vids-btn" data-vids="${esc(key)}" aria-expanded="${open}">${open?'▾':'▸'} 영상 ${e.files}개</button>`:''}<span class="grow"></span>${lim}</header>${vids}${rows||''}</article>`;
 }
 let guideMode='guide';
 function showGuide(mode){
  hideCopyNotice();releaseAssets();guideMode=mode;const work=works.find(w=>w.id===state.work),record=liveGuides[work.id]||guideData?.works?.[work.id],body=$('.works-guide-body');
  $('.works-guide-kicker').textContent=mode==='assets'?'에셋':mode==='guide'?'권리사 가이드 · 원문':'필수 기입 정보';$('#works-guide-title').textContent=record?.title||work.name;$('.works-guide-meta').textContent=record?.copyrights_holder_name?`권리사 · ${record.copyrights_holder_name}`:'';
  body.replaceChildren();
  if(mode==='assets'){releaseAssets=mountWorkAssets(body,{client,role,work});}
  else if(!record)body.textContent=guideError?'정보를 불러오지 못했습니다. 새로고침 후 다시 확인해 주세요.':guideData?'등록된 정보가 없습니다.':'정보를 불러오는 중…';
  else if(mode==='guide'){
   if(record.guide===undefined&&record.id&&client){   // 목록에는 가이드 원문이 없다 — 열 때 읽는다
    body.textContent='가이드를 불러오는 중…';
    loadGuide(client,record.id).then(g=>{record.guide=g;if(!disposed&&guideDialog.open&&guideMode==='guide')showGuide('guide');}).catch(()=>{if(!disposed)body.textContent='가이드를 불러오지 못했어요. 새로고침 후 다시 확인해 주세요.';});
   }else if(record.guide)body.append(guideFragment(record.guide));else body.textContent='등록된 가이드가 없습니다.';}
  else{
   const derived=GuideDetails.derive(record);
   const rawCode=String(record.identification_code||'').trim().replace(/^#+/,'').trim();
   const rows=[['식별 코드',rawCode?'#'+rawCode:''],['제목 필수 해시태그',record.required_hashtags_title],['설명란 필수 해시태그',record.required_hashtags_description],...derived.descriptions.map(d=>[d.exact?'설명란 필수 문구':'설명란 관련 안내',d.copyText])];
   const region=record.geo_block_regions||[],geo=record.geo_block_required===true?'필수'+(region.length&&['allowed','blocked'].includes(record.geo_block_mode)?` · ${record.geo_block_mode==='allowed'?'허용':'차단'} 국가 ${region.join(', ')}`:' · 국가 설정 확인 필요'):record.geo_block_required===false?'필수 아님 · 등록 정보':'미등록';
   body.innerHTML=rows.map(([label,value],i)=>`<section class="works-required-row"><h3>${label}</h3><div class="works-copy-value"><p>${esc(value||'등록된 값 없음')}</p>${value?`<button type="button" data-copy="${i}" aria-label="${label} 복사" title="복사">${icon('copy')}</button>`:''}</div></section>`).join('')+`<section class="works-required-row"><h3>지오블락</h3><p>${esc(geo)}</p></section>${record.required_hashtags_notice?`<p>${esc(record.required_hashtags_notice)}</p>`:''}${derived.mixedTags?'<p>등록 해시태그에 안내 문구가 섞여 있어요. 가이드 원문을 함께 확인해 주세요.</p>':''}`;
   body.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{try{await navigator.clipboard.writeText(rows[Number(b.dataset.copy)][1]);if(!disposed&&b.isConnected){showCopyNotice('복사했어요');clearTimeout(b.copyTimer);b.innerHTML=icon('check');b.title='복사 완료';b.copyTimer=setTimeout(()=>{if(b.isConnected){b.innerHTML=icon('copy');b.title='복사';}},1500);}}catch{if(!disposed&&b.isConnected)showCopyNotice('자동 복사가 차단되었습니다. 내용을 선택해 직접 복사해 주세요.',4500);}});
  }
  guideDialog.querySelector('footer').textContent=mode==='assets'?'':liveGuides[work.id]?'권리사 등록 정보':guideData?'로컬에 저장된 권리사 등록 정보':'';
  if(!guideDialog.open)guideDialog.showModal();body.scrollTop=0;
 }
 $('.works-options').addEventListener('scroll',fadeEdge,{passive:true});
window.addEventListener('resize',fadeEdge);
 $('.works-sidebar input').oninput=e=>{state.workQuery=e.target.value;renderSidebar();};
 releaseDropdown=enhanceDropdowns(root);render();
 if(client)loadSources(client).then(data=>{if(disposed)return;src=data;render();}).catch(e=>{if(disposed)return;srcError=e.message||'';render();});
 fetch('assets/local-guides.json').then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{if(disposed)return;guideData=data;if(guideDialog.open&&guideMode!=='assets')showGuide(guideMode);}).catch(()=>{if(disposed)return;guideError=true;if(guideDialog.open&&guideMode!=='assets')showGuide(guideMode);});
 if(client)loadCatalog(client).then(data=>{   // 레이블리 작품 정보 사본(웹에서도 된다)
  if(disposed)return;
  const linked=new Set(data.pipeline_titles||[]);
  catalogByTitle=new Map(data.works.map(r=>[norm(r.title),r]));
  const normalize=t=>t.replace(/\s/g,'');
  const samples=sampleWorks.map(w=>{const matches=data.works.filter(r=>normalize(r.title)===normalize(w.name));const rec=matches.length===1?matches[0]:null;if(rec)liveGuides[w.id]=rec;return {...w,licensedId:rec?.id};});
  const ids=new Set(samples.map(w=>w.licensedId));
  works=[...samples,...data.works.filter(r=>linked.has(r.title)&&!ids.has(r.id)).map(r=>{const id='licensed-'+r.id;liveGuides[id]=r;return {id,licensedId:r.id,name:r.title,type:r.video_type||'작품'};})];
  render();if(guideDialog.open)showGuide(guideMode);
 }).catch(()=>{});
 return ()=>{window.removeEventListener('resize',fadeEdge);root.parentElement.classList.remove('works-page');disposed=true;releaseAssets();clearTimeout(copyNoticeTimer);releaseDropdown();if(guideDialog.open)guideDialog.close();};
}
