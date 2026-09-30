import {esc} from './review-details.js';
// 드라이브에서 작품 로고 가져오기(오케스트레이터 0114). 로컬 서버를 거치지 않는다:
// 찾기는 request_work_logo_scan RPC → 맥미니가 rclone 으로 폴더를 훑어 work_logo_scans 에 후보를 적는다.
// 화면은 그 줄을 읽고(미리보기는 ves-outputs 서명 URL), 고른 것을 import_work_logos RPC 로 넣는다.
// 그림마다 용도(작품 로고 · 플랫폼 로고)를 고르고, 플랫폼 로고는 권리사에 넣는다(0115). '이 작품에만 넣기'면 이 작품에.
const POLL_MS=3000,RESUME_MS=24*3600e3;
const stem=n=>String(n||'').replace(/\.[a-z0-9]+$/i,'').replace(/[_-]+/g,' ').replace(/\s+/g,' ').trim().slice(0,30)||'로고';
const norm=t=>String(t||'').toLowerCase().replace(/[\s_.\-·()]+/g,'');
// 파일 이름에 권리사·플랫폼 이름이 있으면 플랫폼 로고로 미리 고른다
const PLATFORM_WORDS=['티빙','tving','쿠팡','coupang','왓챠','watcha','웨이브','wavve','넷플릭스','netflix','디즈니','disney','유플러스','uplus','tvn','cjenm','지니','genie','라프텔','laftel','숏챠','플랫폼','platform','제공','배급'];
// 플랫폼 로고 칸에서 열었으면 모두 플랫폼 로고로, 작품 로고 칸에서 열었으면 파일 이름에 권리사·플랫폼 이름이 있는 것만 플랫폼 로고로
const guessRole=(path,holder,from)=>{if(from==='platform_logo')return 'platform_logo';const n=norm(path);return (holder&&n.includes(norm(holder)))||PLATFORM_WORDS.some(w=>n.includes(w))?'platform_logo':'work_logo';};
const secs=t=>Math.max(0,Math.round((Date.now()-new Date(t).getTime())/1000));

export function mountLogoDrive(root,{client,work,role:from='work_logo',holder=null,holderWorks=0,onImported,onClose}){
 let dead=false,timer=0,scan=null,urls={},picked=new Map(),msg='',asking=false;   // picked: id → {label, role, scope(holder|work), def}
 const rpc=async(fn,args)=>{const {data,error}=await client.rpc(fn,args);if(error)throw Error(error.message);return data;};
 const fromLine=s=>{
  const src=s?.source==='manual'?'넣은 링크':'레이블리에 등록된 폴더';
  const url=s?.used_url||s?.folder_url;
  return `<p class="ld-from">${src}${s?.work_title?` · ${url?`<a href="${esc(url)}" target="_blank" rel="noopener">${esc(s.work_title)}</a>`:esc(s.work_title)}`:''}${s&&!['pending','running'].includes(s.status)?' · <button type="button" class="ld-other">다른 폴더에서 찾기</button>':''}</p>`;
 };
 const ask=(title,why)=>`<div class="ld-ask"><p>${esc(title)}</p><small>${esc(why)}</small>
  <form class="ld-link"><input name="url" type="url" required placeholder="https://drive.google.com/drive/folders/…" aria-label="드라이브 폴더 링크"><button class="ld-primary">이 폴더에서 찾기</button></form>
  <p class="ld-note">맥미니 계정에 공유된 폴더만 열 수 있어요. 안 열리면 폴더 공유를 확인해 주세요.</p></div>`;
 const hold=()=>scan?.holder||holder;   // 맥미니가 적은 권리사, 없으면 작품 관리가 아는 권리사
 function cand(c){
  const it=picked.get(c.id),on=!!it,u=urls[c.thumb_key],h=hold();
  const plat=on&&it.role==='platform_logo',toHolder=plat&&it.scope==='holder'&&h;
  return `<div class="ld-cand${on?' on':''}" data-id="${esc(c.id)}"><button type="button" class="ld-toggle" aria-pressed="${on}" aria-label="${esc(c.name)} ${on?'빼기':'고르기'}">
   <span class="ld-thumb">${u?`<img src="${esc(u)}" alt="">`:'<span>미리보기 없음</span>'}</span><span class="ld-box" aria-hidden="true"></span></button>
   <p class="ld-fn">${esc(c.path.includes('/')?c.path.slice(0,c.path.lastIndexOf('/')+1):'')}<b>${esc(c.name)}</b><br>${c.width}×${c.height}</p>
   ${on?`<div class="ld-role" role="radiogroup" aria-label="용도"><button type="button" role="radio" data-role="work_logo" aria-checked="${!plat}">작품 로고</button><button type="button" role="radio" data-role="platform_logo" aria-checked="${plat}">플랫폼 로고</button></div>
   <input class="ld-label" maxlength="30" value="${esc(it.label)}" aria-label="로고 이름">
   ${plat?`<p class="ld-to">${toHolder?`${esc(h)} 로고로 등록 · ${esc(h)} 작품 ${holderWorks||''}${holderWorks?'개가':'이'} 같이 써요`:'이 작품에만 넣어요'}</p>${h?`<button type="button" class="ld-only${it.scope==='work'?' on':''}" aria-pressed="${it.scope==='work'}"><i></i>이 작품에만 넣기</button>`:''}`:''}
   <button type="button" class="ld-def${it.def?' on':''}" aria-pressed="${!!it.def}"><i></i>기본으로</button>`:''}</div>`;
 }
 function draw(){
  if(dead)return;
  const s=scan,st=s?.status;let body='';
  if(!s||st==='pending'||st==='running'){
   body=`<div class="ld-wait"><span class="ld-spin"></span><p>${st==='running'?'맥미니가 폴더를 훑고 있어요':'맥미니에 부탁하는 중이에요'}</p><small>하위 폴더까지 그림 파일을 모으는 중이에요.<br>${s?.node_id?esc(s.node_id)+' · ':''}${s?secs(s.started_at||s.created_at)+'초 지남':''}</small></div><div class="ld-skel"><i></i><i></i><i></i><i></i></div>`;
  }else if(asking){body=ask('다른 폴더에서 찾기','로고가 들어 있는 드라이브 폴더 링크를 넣어 주세요.');}
  else if(st==='need_folder'){body=ask('이 링크에서는 로고를 찾지 못했어요',s.reason||'');}
  else if(st==='failed'){body=ask('찾지 못했어요',s.reason||'잠시 뒤 다시 해 주세요.')+'<button type="button" class="ld-retry">레이블리 폴더로 다시 찾기</button>';}
  else{
   const left=(s.candidates||[]).filter(c=>!c.imported),top=left.filter(c=>c.logoish),rest=left.filter(c=>!c.logoish);
   const main=top.length?top:rest,more=top.length?rest:[];
   body=left.length?`<div class="ld-bar"><span>그림 ${s.total??left.length}개${top.length?` 중 로고로 보이는 것 ${top.length}개`:''}</span>${s.skipped?`<span>이미 넣은 그림 ${s.skipped}개는 뺐어요</span>`:''}</div>
    <div class="ld-cands">${main.map(cand).join('')}</div>
    ${more.length?`<details class="ld-more"${more.some(c=>picked.has(c.id))?' open':''}><summary>나머지 그림 ${more.length}개 보기</summary><p>로고가 여기 섞여 있으면 똑같이 골라 넣을 수 있어요.</p><div class="ld-cands">${more.map(cand).join('')}</div></details>`:''}
    <div class="ld-foot"><span>${picked.size?pickedLine():'넣을 그림을 골라 주세요'}</span><span><button type="button" class="ld-close">닫기</button><button type="button" class="ld-primary ld-import"${picked.size?'':' disabled'}>${picked.size?picked.size+'개 넣기':'넣기'}</button></span></div>`
    :ask('이 폴더의 그림은 다 넣었어요','다른 폴더에서 찾으려면 링크를 넣어 주세요.');
  }
  root.innerHTML=`<header class="ld-head"><h3>드라이브에서 ${from==='platform_logo'?'플랫폼':'작품'} 로고 가져오기</h3><button type="button" class="ld-x" aria-label="닫기">×</button></header>${s?fromLine(s):''}<p class="ld-msg" role="status">${esc(msg)}</p>${body}`;
  wire();
 }
 function pickedLine(){
  const v=[...picked.values()],w=v.filter(i=>i.role==='work_logo').length,pl=v.length-w;
  return [w&&`작품 로고 ${w}개`,pl&&`플랫폼 로고 ${pl}개`].filter(Boolean).join(' · ')+(v.some(i=>i.def)?' · 고른 것을 기본으로':' · 기본은 지금 것 그대로');
 }
 function wire(){
  const q=s=>root.querySelector(s);
  root.querySelectorAll('.ld-x,.ld-close').forEach(b=>b.onclick=()=>onClose?.());
  const other=q('.ld-other');if(other)other.onclick=()=>{asking=true;msg='';draw();q('.ld-link input')?.focus();};
  const retry=q('.ld-retry');if(retry)retry.onclick=()=>start(null);
  const form=q('.ld-link');if(form)form.onsubmit=e=>{e.preventDefault();start(form.elements.url.value.trim());};
  root.querySelectorAll('.ld-cand').forEach(el=>{
   const id=el.dataset.id,c=scan.candidates.find(x=>x.id===id);
   el.querySelector('.ld-toggle').onclick=()=>{if(picked.has(id))picked.delete(id);else picked.set(id,{label:stem(c.name),role:guessRole(c.path,hold(),from),scope:'holder',def:false});draw();};
   const it=picked.get(id);if(!it)return;
   const lab=el.querySelector('.ld-label');lab.oninput=()=>{it.label=lab.value;};
   el.querySelectorAll('.ld-role [data-role]').forEach(b=>b.onclick=()=>{it.role=b.dataset.role;it.def=false;draw();});
   const only=el.querySelector('.ld-only');if(only)only.onclick=()=>{it.scope=it.scope==='work'?'holder':'work';it.def=false;draw();};
   const d=el.querySelector('.ld-def');d.onclick=()=>{   // 기본은 넣을 곳(작품 로고 · 권리사 로고 · 이 작품 플랫폼 로고)마다 하나
    const on=!it.def,where=x=>x.role+(x.role==='platform_logo'?x.scope:'');
    if(on)for(const o of picked.values())if(where(o)===where(it))o.def=false;
    it.def=on;draw();};
  });
  const imp=q('.ld-import');if(imp)imp.onclick=save;
 }
 async function signThumbs(){
  const keys=(scan?.candidates||[]).map(c=>c.thumb_key).filter(k=>k&&!urls[k]);
  if(!keys.length)return;
  const {data}=await client.storage.from('ves-outputs').createSignedUrls(keys,3600);
  for(const r of data||[])if(r.signedUrl)urls[r.path]=r.signedUrl;
 }
 async function poll(){
  clearTimeout(timer);if(dead||!scan)return;
  const {data,error}=await client.from('work_logo_scans').select('*').eq('id',scan.id).single();
  if(dead)return;
  if(!error&&data)scan=data;
  if(['pending','running'].includes(scan.status)&&scan.job_id){   // 잡이 먼저 죽으면(맥미니가 아직 옛 코드 등) 표는 '찾는 중'에 남는다 — 잡 상태로 끝을 본다
   const {data:j}=await client.from('job_queue').select('status,error').eq('id',scan.job_id).maybeSingle();
   if(dead)return;
   if(j&&['failed','dead','cancelled'].includes(j.status))scan={...scan,status:'failed',reason:/어댑터 없음/.test(j.error||'')?'맥미니가 아직 이 기능을 받지 못했어요. 한 시간쯤 뒤에 다시 해 주세요.':(j.error||'맥미니가 찾다가 멈췄어요.').slice(0,200)};
  }
  if(scan.status==='done')await signThumbs();
  draw();
  if(['pending','running'].includes(scan.status))timer=setTimeout(poll,POLL_MS);
 }
 async function start(folder){
  asking=false;msg='';picked.clear();scan=null;draw();
  try{const r=await rpc('request_work_logo_scan',{p_work_id:String(work.licensedId),p_folder:folder||null});scan={id:r.scan_id,status:'pending',created_at:new Date().toISOString(),source:folder?'manual':'laeebly'};poll();}
  catch(e){scan={status:'failed',reason:e.message};draw();}
 }
 async function save(){
  const items=[...picked].map(([id,it])=>({id,label:String(it.label).trim(),role:it.role,scope:it.role==='platform_logo'&&hold()?it.scope:'work',default:!!it.def}));
  if(items.some(i=>!i.label)){msg='로고 이름을 적어 주세요.';return draw();}
  const btn=root.querySelector('.ld-import');btn.disabled=true;btn.textContent='넣는 중…';
  try{const r=await rpc('import_work_logos',{p_scan:scan.id,p_items:items,p_holder:holder});picked.clear();onImported?.(`드라이브에서 로고 ${r.imported}개를 넣었어요.`);}
  catch(e){msg=e.message;draw();}
 }
 (async()=>{   // 최근에 찾은 게 있으면 이어서(창을 닫아도 맥미니는 계속 찾는다)
  draw();
  try{
   const {data}=await client.from('work_logo_scans').select('*').eq('work_id',String(work.licensedId)).order('created_at',{ascending:false}).limit(1);
   const last=data?.[0];
   if(last&&Date.now()-new Date(last.created_at).getTime()<RESUME_MS&&(['pending','running'].includes(last.status)||(last.status==='done'&&last.candidates.some(c=>!c.imported)))){scan=last;return poll();}
  }catch{}
  start(null);
 })();
 return()=>{dead=true;clearTimeout(timer);};
}
