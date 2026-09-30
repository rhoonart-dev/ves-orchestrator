import {esc} from './review-details.js';
import {fetchWorkPolicies} from './rights-service.js';
import {loadWorkAssets} from './work-assets-data.js?v=1';
import {hiddenChannels,setChannelHidden,withWorkOverrides} from './channel-visibility.js';
import {readAll} from './review-service.js';
import {assetRequest} from './work-assets.js';
import {policyForWork,permissionForWork} from './workflow-model.js';
export function mountChannels(root,{client,role}={}){
 const canEdit=['operator','admin'].includes(role);
 let dead=false,all=[],hidden=new Set(),channels=[],policy={works:[],applications:[]},current=null,policyError='';
 root.innerHTML='<div class="template-layout"><aside class="template-sidebar"><label>채널 검색<input type="search" placeholder="채널 검색" aria-label="채널 검색"></label><div class="template-channels"></div><button type="button" class="ch-hidden-open" hidden></button></aside><dialog class="ch-hidden-dialog" aria-labelledby="ch-hidden-title"></dialog><section class="template-main"><p role="status">채널을 불러오는 중…</p></section></div>';
 const main=root.querySelector('.template-main'),list=root.querySelector('.template-channels'),search=root.querySelector('input');
 function renderList(){list.innerHTML=channels.filter(c=>c.name.includes(search.value.trim())).map(c=>`<button type="button" data-slug="${esc(c.token_slug)}" class="has-av${current===c?' active':''}"><span class="tc-av">${c.avatar_url?`<img src="${esc(c.avatar_url)}" alt="" referrerpolicy="no-referrer">`:esc((c.name||'?').slice(0,1))}</span><span class="tc-txt">${esc(c.name)}<small>${c.works?.length||0}개 작품</small></span></button>`).join('');list.querySelectorAll('button').forEach(b=>b.onclick=()=>{current=channels.find(c=>c.token_slug===b.dataset.slug);render();});}
 // 숨긴 채널 관리 — 왼쪽 채널 칸 맨 아래 회색 칸. 전체 채널에 보이기/숨기기 스위치(운영자·관리자만 바꿀 수 있다)
 const openBtn=root.querySelector('.ch-hidden-open'),dlg=root.querySelector('.ch-hidden-dialog');
 function drawOpen(){openBtn.hidden=false;openBtn.innerHTML=`숨긴 채널 관리${hidden.size?`<small>${hidden.size}</small>`:''}`;}
 function applyHidden(){channels=all.filter(c=>!hidden.has(c.token_slug));if(!channels.includes(current))current=channels[0]||null;drawOpen();}
 function drawDialog(msg=''){
  const av=c=>c.avatar_url?`<img src="${esc(c.avatar_url)}" alt="" referrerpolicy="no-referrer">`:`<span>${esc((c.name||'?').slice(0,1))}</span>`;
  dlg.innerHTML=`<div class="ch-hidden-body"><header><h2 id="ch-hidden-title">숨긴 채널 관리</h2><button type="button" class="ch-hidden-close" aria-label="닫기">×</button></header>
   <p class="ch-hidden-hint">숨긴 채널은 대시보드에서 숨겨져요.${canEdit?'':'<br>바꾸려면 운영자 권한이 필요해요.'}</p>
   <p class="ch-hidden-msg" role="status">${esc(msg)}</p>
   <div class="ch-hidden-list">${all.map(c=>{const on=!hidden.has(c.token_slug);return `<label class="ch-hidden-row${on?'':' is-hidden'}"><span class="ch-hidden-av">${av(c)}</span><span class="ch-hidden-name"><strong>${esc(c.name)}</strong><small>${on?'보이는 중':'숨김'}</small></span><input type="checkbox" role="switch" data-slug="${esc(c.token_slug)}" ${on?'checked':''} ${canEdit?'':'disabled'} aria-label="${esc(c.name)} 보이기"></label>`;}).join('')}</div></div>`;
  dlg.querySelector('.ch-hidden-close').onclick=()=>dlg.close();
  dlg.querySelectorAll('input[data-slug]').forEach(t=>t.onchange=async()=>{
   t.disabled=true;
   try{hidden=await setChannelHidden(client,t.dataset.slug,!t.checked);applyHidden();if(current)render();else{renderList();main.textContent='보이는 채널이 없어요.';}drawDialog();}
   catch(e){t.checked=!t.checked;t.disabled=false;drawDialog(e.message);}
  });
 }
 openBtn.onclick=()=>{drawDialog();dlg.showModal();};
 dlg.addEventListener('click',e=>{if(e.target===dlg)dlg.close();});
 function render(){renderList();
  const assigned=current.works||[],applicationWorks=policy.applications.filter(a=>a.youtube_channel_id===current.channel_id).map(a=>a.work_title).filter(Boolean),names=[...new Set([...assigned,...applicationWorks])];
  main.innerHTML=`<header><div><h2>${esc(current.name)}</h2><p>작품 사용 신청은 레이블리에서 관리해요.</p></div><a class="works-button" href="#channel-templates?channel=${encodeURIComponent(current.token_slug)}">디자인 템플릿</a></header><section class="channel-works"><h3>사용 작품</h3>${policyError?`<p class="asset-error">${esc(policyError)}</p>`:''}${names.map(title=>{const work=policyForWork(policy.works,title),app=permissionForWork(policy.applications,current.channel_id,work?.id),status=policyError?'확인 불가':!work?'작품 연결 확인 필요':!app?'신청 정보 확인 필요':app.rejected_bool===true?'사용 신청 반려':app.status===true?'사용 승인':'사용 승인 대기';return `<article${assigned.includes(title)&&work?.id?` data-logo-work="${esc(title)}" data-logo-id="${esc(work.id)}"`:''}><div><strong>${esc(title)}</strong><p>${assigned.includes(title)?'생성 대상 작품':'사용 신청한 작품'}</p></div><div><span>${status}</span><small>${({required:'권리사 검수 필요',none:'내부 검수 후 발행',unaired_only:'미방영분 권리사 검수'})[work?.inspection_policy]||'검수 정책 확인 필요'}</small></div></article>`;}).join('')||'<p>연결된 작품이 없습니다.</p>'}</section>`;
  loadLogos(current);
 }
 // 작품 로고 고르기(0112) — 생성 대상 작품마다. 작품 에셋에 로고가 있으면 칩으로, 안 고르면 기본. 운영자·관리자만 바꾼다
 let logoTicket=0;
 async function loadLogos(ch){
  const ticket=++logoTicket,rows=[...main.querySelectorAll('[data-logo-work]')];if(!rows.length)return;
  const {data:picks}=await client.from('channel_work_assets').select('work_title,label').eq('token_slug',ch.token_slug).eq('role','work_logo');
  const chosen=new Map((picks||[]).map(p=>[p.work_title,p.label]));
  await Promise.all(rows.map(async art=>{
   let logos=[];try{logos=(await loadWorkAssets(client,art.dataset.logoId)).logos?.work_logo||[];}catch{return;}
   if(dead||ticket!==logoTicket||!logos.length)return;
   const title=art.dataset.logoWork,pick=chosen.get(title)&&logos.some(l=>l.label===chosen.get(title))?chosen.get(title):null;
   const box=document.createElement('div');box.className='ch-logo-pick';
   box.innerHTML=`<span class="ch-logo-lab">로고</span><div class="ch-logo-chips">${logos.map(l=>{const on=pick?l.label===pick:l.is_default;return `<button type="button" class="ch-logo-chip${on?' on':''}" data-label="${esc(l.label)}" data-default="${l.is_default?1:''}" aria-pressed="${on}" ${canEdit?'':'disabled'}><span class="ch-logo-mini">${l.preview_url?`<img src="${esc(l.preview_url)}" alt="">`:''}</span>${l.is_default?'기본':esc(l.label)}${l.is_default&&l.label!=='기본'?`<small>${esc(l.label)}</small>`:''}</button>`;}).join('')}</div>`;
   art.append(box);
   box.querySelectorAll('.ch-logo-chip').forEach(b=>b.onclick=async()=>{
    if(b.getAttribute('aria-pressed')==='true')return;
    box.querySelectorAll('button').forEach(x=>x.disabled=true);
    const {error}=await client.rpc('set_channel_work_asset',{p_slug:ch.token_slug,p_work:title,p_role:'work_logo',p_label:b.dataset.default?null:b.dataset.label});
    if(error){box.querySelectorAll('button').forEach(x=>x.disabled=!canEdit);alert(error.message);return;}
    box.querySelectorAll('.ch-logo-chip').forEach(x=>{const on=x===b;x.classList.toggle('on',on);x.setAttribute('aria-pressed',String(on));x.disabled=!canEdit;});
   });
  }));
 }
 search.oninput=renderList;
 if(!client)main.innerHTML='<p>로그인하면 채널과 작품 사용 상태를 확인할 수 있어요.</p>';
 else Promise.all([readAll(()=>client.from('channels_mirror').select('token_slug,name,channel_id,works,avatar_url').order('name')).then(c=>withWorkOverrides(client,c)),hiddenChannels(client),fetchWorkPolicies(client).catch(e=>{policyError=e.message;return {works:[],applications:[]};})]).then(([c,h,p])=>{if(dead)return;all=c;hidden=h;policy=p;applyHidden();current=channels[0]||null;if(current)render();else{renderList();main.textContent='보이는 채널이 없어요.';}}).catch(e=>{if(!dead)main.textContent='채널을 불러오지 못했어요. '+e.message;});
 return()=>{dead=true;if(dlg.open)dlg.close();};
}
