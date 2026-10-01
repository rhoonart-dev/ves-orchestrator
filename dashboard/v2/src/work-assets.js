import {esc} from './review-details.js?v=web-1';
import {needWorkPc,apiUrl,localize} from './local-only.js?v=web-1';
import {mountLogoDrive} from './work-logo-drive.js?v=web-1';
import {showToast} from './toast.js?v=1';
import {loadWorkAssets,uploadWorkAsset,logoVariant,setPlatformSource} from './work-assets-data.js?v=1';
export async function assetRequest(client,path,options={}){
 if(String(path).startsWith('/api/'))needWorkPc();   // 웹 주소에서는 로컬 서버가 없다
 if(!client)throw Error('로그인하면 VES 에셋을 관리할 수 있어요.');
 const {data,error}=await client.auth.getSession();if(error||!data.session)throw Error('로그인이 필요합니다.');
 const r=await fetch(apiUrl(path),{...options,headers:{...options.headers,Authorization:'Bearer '+data.session.access_token}});
 const body=await r.json();if(!r.ok)throw Error(body.error||'에셋 요청에 실패했습니다.');return localize(body);
}
// 작품 에셋 — 로고를 용도마다 여러 개(이름·기본 하나, 0112). 채널은 채널 관리에서 그 작품에 쓸 로고를 고르고, 안 고르면 기본.
// 플랫폼 로고는 권리사마다(0115): 레이블리 권리사 로고(기본) · 다른 권리사 · 이 작품만 · 안 씀 중에서 작품마다 고른다.
export function mountWorkAssets(root,{client,role,work}){
 let dead=false,data=null,form=null,drive=null,releaseDrive=()=>{},picking=false;const canWrite=['operator','admin'].includes(role);   // form: {role, label(교체·새 로고면 null)} · drive: 열린 '드라이브에서 가져오기' 칸(다시 그려도 같은 칸을 옮겨 붙여 고른 것이 안 날아가게) · picking: '다른 권리사'를 누르고 아직 안 고름
 const roles={work_logo:['작품 로고','영상 하단의 작품명 자리에 들어가요.',620,300],platform_logo:['플랫폼 로고','채널 템플릿의 플랫폼 표기 위치에 들어가요.',180,80]};
 const wid=String(work?.licensedId||'');   // 로고 읽기·쓰기는 Supabase 로 바로(work-assets-data.js) — 웹 주소에서도 된다
 const uses=l=>l.channels.length?`채널 ${l.channels.length}곳`:'안 씀';
 const pf=()=>data.platform||{mode:'work',holders:[],holder_logos:[]};
 const onHolder=()=>['holder','other'].includes(pf().mode);                 // 플랫폼 로고를 권리사 열쇠에서 읽는가
 const target=key=>key==='platform_logo'&&onHolder()?'holder':'work';
 const listOf=key=>key==='platform_logo'?(onHolder()?pf().holder_logos:pf().mode==='work'?data.logos.platform_logo:[]):data.logos[key]||[];
 root.innerHTML='<p role="status">에셋을 불러오는 중…</p>';
 function card(key,l){
  const held=target(key)==='holder',meta=held?`권리사 작품 ${pf().holder_works}개`:l.is_default?uses(l):'';
  return `<div class="asset-logo${l.is_default?' is-default':''}" data-label="${esc(l.label)}">
   ${canWrite&&!l.is_default?`<button type="button" class="asset-remove" data-act="retire" aria-label="'${esc(l.label)}' 로고 빼기" title="빼기"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6"/></svg></button>`:''}
   <div class="asset-preview">${l.mime.startsWith('image/')?`<img src="${esc(l.preview_url)}" alt="${esc(l.label)}">`:'PDF'}</div>
   <div class="asset-logo-row"><strong>${esc(l.label)}</strong>${l.is_default?'<span class="asset-badge">기본</span>':!held&&l.channels.length?`<span class="asset-uses" title="${esc(l.channels.join(', '))}">${uses(l)}</span>`:''}</div>
   <small class="asset-logo-meta"${!held&&l.is_default&&l.channels.length?` title="${esc(l.channels.join(', '))}"`:''}>${l.render_width}×${l.render_height}${meta?' · '+meta:''}</small>
   ${canWrite?`<div class="asset-logo-acts"><button type="button" data-act="replace">교체</button><button type="button" data-act="rename">이름</button>${l.is_default?'':'<button type="button" data-act="default">기본으로</button>'}</div>`:''}
  </div>`;
 }
 function uploadForm(key,list){
  const replacing=form.label?list.find(l=>l.label===form.label):null,[, ,w,h]=roles[key];
  return `<form class="asset-uploader" data-role="${key}"><fieldset><div class="asset-up-body">
   <p class="asset-upload-title">${replacing?`'${esc(replacing.label)}' 파일 교체`:target(key)==='holder'?`${esc(pf().holder)} 로고 올리기`:'새 로고 올리기'}</p>
   ${replacing?'':`<label class="asset-upload-name">이름<input name="label" maxlength="30" placeholder="예: 흰색 · 컬러 · 가로형" value="${list.length?'':'기본'}" ${list.length?'required':''}></label>`}
   <div class="asset-size"><label>최대 가로<input name="width" type="number" min="16" max="1080" value="${replacing?.render_width??w}" required></label><label>최대 세로<input name="height" type="number" min="16" max="1920" value="${replacing?.render_height??h}" required></label></div>
   <div class="asset-file-row"><label class="asset-file-label"><span>파일 선택</span><input type="file" name="file" accept="image/png,image/jpeg,image/webp" required></label><span class="asset-selected-file">선택한 파일 없음</span></div>
   <div class="asset-upload-row">${replacing||!list.length?'<small>px · 원본 비율 유지</small>':'<label class="asset-check"><input type="checkbox" name="default"> 기본 로고로</label>'}<span><button type="button" class="asset-cancel">취소</button><button type="submit" class="works-button asset-upload-btn">올리기</button></span></div>
  </div></fieldset><p role="status" aria-live="polite"></p></form>`;
 }
 function logoGrid(key,list){
  return `<div class="asset-logos">${list.map(l=>card(key,l)).join('')}${canWrite&&!(form&&form.role===key)?`<button type="button" class="asset-add" data-add="${key}"><b>+</b>${list.length?'로고 추가':'로고 올리기'}</button>`:''}${!list.length&&!canWrite?'<div class="asset-preview">아직 파일이 없어요</div>':''}</div>`;
 }
 function platformBody(){
  const p=pf(),list=listOf('platform_logo'),auto=p.auto_holder;
  const modes=[['holder',auto?`${auto} 로고`:'권리사 로고'],['other','다른 권리사'],['work','이 작품만'],['none','안 씀']];
  const cur=picking?'other':p.mode;
  const seg=`<div class="asset-psrc" role="radiogroup" aria-label="플랫폼 로고 어디서 쓸지">${modes.map(([m,t])=>`<button type="button" role="radio" data-mode="${m}" aria-checked="${cur===m}"${canWrite?'':' disabled'}>${esc(t)}</button>`).join('')}</div>`;
  let body='';
  if(cur==='other')body=`<label class="asset-holder-pick">권리사<select${canWrite?'':' disabled'}><option value="">권리사 고르기</option>${p.holders.map(h=>`<option${h===p.holder&&p.mode==='other'?' selected':''}>${esc(h)}</option>`).join('')}</select></label>`;
  if(picking)return seg+body;
  if(cur==='none')return seg+'<p class="asset-pnote">이 작품 영상에는 플랫폼 로고를 넣지 않아요.</p>';
  if(cur==='work')return seg+`<p class="asset-pnote">${auto?`${esc(auto)} 로고 대신 `:''}<b>이 작품에만 올린 로고</b>를 써요.${auto?` 다른 ${esc(auto)} 작품에는 영향 없어요.`:''}</p>`+logoGrid('platform_logo',list)+(form&&form.role==='platform_logo'?uploadForm('platform_logo',list):'');
  if(!p.holder)return seg+body+'<p class="asset-pnote">레이블리에 이 작품의 권리사가 없어요. 다른 권리사를 고르거나 이 작품만 따로 올려 주세요.</p>';
  if(!list.length&&!(form&&form.role==='platform_logo'))return seg+body+`<div class="asset-pempty"><p>${esc(p.holder)} 로고가 아직 없어요</p><small>한 번 넣으면 ${esc(p.holder)} 작품이 모두 같이 써요.</small>${canWrite?`<span><button type="button" class="asset-drive-open">드라이브에서 가져오기</button><button type="button" class="asset-pempty-up" data-add="platform_logo">로고 올리기</button></span>`:''}</div>`;
  return seg+body+logoGrid('platform_logo',list)+(form&&form.role==='platform_logo'?uploadForm('platform_logo',list):'')+`<p class="asset-pnote asset-pnote-foot">권리사 로고를 바꾸거나 더하면 ${esc(p.holder)} 작품 ${p.holder_works}개에 모두 반영돼요.</p>`;
 }
 function headSide(key,list){
  if(key==='work_logo')return list.length?`${list.length}개`:'미등록';
  const p=pf();if(picking)return '권리사 고르는 중';
  return p.mode==='none'?'안 씀':p.mode==='work'?`이 작품만 · ${list.length?list.length+'개':'미등록'}`:p.holder?`${p.holder} 로고${list.length?' 사용 중':' 없음'}`:'권리사 모름';
 }
 function draw(msg=''){
  if(dead)return;
  root.innerHTML=`<p class="asset-intro">작품 파일은 VES에 보관해요. 로고는 여러 개 올려 두고 채널 관리에서 채널마다 고를 수 있어요. 안 고른 채널은 기본 로고를 써요.</p><p class="asset-version-note">교체한 파일은 다음 새 작업부터 쓰고, 기존 영상은 원래 버전을 유지해요.</p>
   <p class="asset-msg asset-error" role="alert">${esc(msg)}</p>
   <div class="asset-grid">${Object.entries(roles).map(([key,[name,desc]])=>{const list=listOf(key);return `<section class="asset-slot" data-role="${key}"><header><h3>${name}</h3><span class="asset-head-side"><span>${esc(headSide(key,list))}</span>${canWrite&&!drive&&(key==='work_logo'||list.length)?'<button type="button" class="asset-drive-open">드라이브에서 가져오기</button>':''}</span></header><p>${desc}</p>
    ${key==='platform_logo'?platformBody():logoGrid(key,list)+(form&&form.role===key?uploadForm(key,list):'')}</section>`;}).join('')}</div>
   ${drive?'<section class="asset-drive" aria-label="드라이브에서 로고 가져오기"></section>':''}
   <div class="asset-footnote"><p>파일 형식: PNG · JPG · WebP</p><p>용량: 파일당 6MB 이하</p></div>`;
  const dz=root.querySelector('.asset-drive');if(dz&&drive)dz.replaceWith(drive);
  root.querySelectorAll('.asset-drive-open').forEach(dopen=>dopen.onclick=()=>openDrive(dopen.closest('.asset-slot')?.dataset.role||'work_logo'));
  root.querySelectorAll('.asset-psrc [data-mode]').forEach(b=>b.onclick=()=>{
   const m=b.dataset.mode;if(m==='other'){picking=pf().mode!=='other';form=null;draw();return;}
   picking=false;if(m===pf().mode)return draw();
   setPlatform({mode:m},{holder:'권리사 로고를 써요.',work:'이 작품에만 올린 플랫폼 로고를 써요.',none:'플랫폼 로고를 쓰지 않아요.'}[m]);});
  const sel=root.querySelector('.asset-holder-pick select');if(sel)sel.onchange=()=>{if(sel.value){picking=false;setPlatform({mode:'other',holder:sel.value},`${sel.value} 로고를 써요.`);}};
  root.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>{form={role:b.dataset.add,label:null};draw();root.querySelector('.asset-uploader input[name=label]')?.focus();});
  root.querySelectorAll('.asset-logo [data-act]').forEach(b=>b.onclick=()=>act(b.closest('.asset-slot').dataset.role,b.closest('.asset-logo').dataset.label,b.dataset.act,b));
  const f=root.querySelector('.asset-uploader');if(!f)return;
  f.querySelector('.asset-cancel').onclick=()=>{form=null;draw();};
  f.elements.file.onchange=()=>{f.querySelector('.asset-selected-file').textContent=f.elements.file.files[0]?.name||'선택한 파일 없음';};
  f.onsubmit=async e=>{e.preventDefault();const file=f.elements.file.files[0],status=f.querySelector('[role=status]');
   try{if(!file||file.size>6*1024*1024)throw Error('6MB 이하 파일을 선택해 주세요.');f.querySelector('fieldset').disabled=true;status.textContent='VES에 올리는 중…';
    const label=form.label||f.elements.label?.value.trim()||'';
    await uploadWorkAsset(client,wid,{role:form.role,target:target(form.role),file,renderWidth:f.elements.width.value,renderHeight:f.elements.height.value,label,makeDefault:!!f.elements.default?.checked});
    form=null;await load(`'${label||'기본'}' 로고를 저장했어요.`);}
   catch(err){if(!dead){status.textContent=err.message;status.classList.add('asset-error');f.querySelector('fieldset').disabled=false;}}};
 }
 // 드라이브 칸 — 어느 칸에서 열었는지 기억해 두고(창을 닫았다 열면 그 용도로 다시 연다), 사람이 '닫기'를 누르면 그 뒤 찾은 것만 다시 띄운다
 const memo=(k,v)=>{try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v);}catch{return null;}};
 const wkey=String(work?.licensedId||'');
 function openDrive(from,{scroll=true}={}){
  const shut=()=>{releaseDrive();releaseDrive=()=>{};drive=null;};
  const p=pf();memo('ld-role:'+wkey,from);
  drive=document.createElement('section');drive.className='asset-drive';drive.setAttribute('aria-label','드라이브에서 로고 가져오기');
  releaseDrive=mountLogoDrive(drive,{client,work,role:from,holder:p.holder||null,holderWorks:p.holder_works||0,
   onClose:()=>{memo('ld-closed:'+wkey,String(Date.now()));shut();draw();},onImported:m=>{memo('ld-closed:'+wkey,String(Date.now()));shut();load(m);}});
  form=null;draw();if(scroll)drive.scrollIntoView({block:'nearest',behavior:'smooth'});
 }
 async function resumeDrive(){   // 에셋 창을 다시 열었을 때: 찾는 중이거나, 찾아 놓고 아직 안 넣은 게 있으면 드라이브 칸부터 띄운다
  if(!canWrite||drive||!client?.from)return;
  try{
   const {data:rows}=await client.from('work_logo_scans').select('status,created_at,candidates').eq('work_id',wkey).order('created_at',{ascending:false}).limit(1);
   const s=rows?.[0];if(!s||dead||drive)return;
   const at=new Date(s.created_at).getTime(),closed=Number(memo('ld-closed:'+wkey)||0);
   const live=['pending','running'].includes(s.status)||(s.status==='done'&&(s.candidates||[]).some(c=>!c.imported));
   if(live&&Date.now()-at<24*3600e3&&at>closed)openDrive(memo('ld-role:'+wkey)||'work_logo',{scroll:false});
  }catch{}
 }
 async function setPlatform(body,ok){
  try{await setPlatformSource(client,wid,body);form=null;await load(ok);}
  catch(e){draw(e.message);}
 }
 async function act(roleKey,label,action,btn){
  if(action==='replace'){form={role:roleKey,label};draw();return;}
  if(action==='rename'){                       // 카드 이름 자리를 입력칸으로 — '이름' 버튼이 검은 '수정' 버튼이 된다(엔터도 저장, Esc 취소)
   const row=btn.closest('.asset-logo').querySelector('.asset-logo-row strong');
   const input=document.createElement('input');input.value=label;input.maxLength=30;input.className='asset-rename';input.setAttribute('aria-label','로고 이름');row.replaceWith(input);input.focus();input.select();
   const save=async()=>{const next=input.value.trim();if(!next||next===label)return draw();btn.disabled=true;await send({role:roleKey,label,action:'rename',new_label:next,target:target(roleKey)},`이름을 '${next}'(으)로 바꿨어요.`);};
   btn.textContent='수정';btn.classList.add('is-save');btn.onclick=save;
   input.onkeydown=e=>{if(e.key==='Escape')draw();else if(e.key==='Enter'){e.preventDefault();save();}};
   return;
  }
  if(action==='retire'){   // 확인 창 없이 빼고, 토스트의 '되돌리기'로 살린다(뺄 때 풀린 채널 선택까지)
   const t=target(roleKey),r=await send({role:roleKey,label,action,target:t});if(!r)return;
   await load();
   showToast(root,`'${label}' 로고를 뺐어요.`,{action:{label:'되돌리기',run:async()=>{if(await send({role:roleKey,label,action:'restore',target:t,picks:r.picks||[]}))load(`'${label}' 로고를 되돌렸어요.`);}}});
   return;
  }
  if(await send({role:roleKey,label,action,target:target(roleKey)}))load(`'${label}'을(를) 기본 로고로 정했어요.`);
 }
 async function send(body,ok){   // ok 를 주면 다시 불러오고 토스트. 돌려주는 값: 서버 답(실패면 null)
  try{const r=await logoVariant(client,wid,body);if(ok)await load(ok);return r;}
  catch(e){draw(e.message);return null;}
 }
 async function load(msg=''){
  try{
   if(!work?.licensedId)throw Error('권리사 작품 정보를 연결한 뒤 에셋을 등록할 수 있어요.');
   data=await loadWorkAssets(client,wid);if(dead)return;draw();showToast(root,msg);   // 완료 안내는 토스트로
  }catch(e){if(!dead){root.replaceChildren();const p=document.createElement('p');p.className='asset-error';p.setAttribute('role','alert');p.textContent=e.message;root.append(p);}}
 }
 load().then(resumeDrive);return()=>{dead=true;releaseDrive();};
}
