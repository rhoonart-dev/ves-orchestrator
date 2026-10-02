import {esc} from './review-details.js?v=web-1';
import {visibleChannels,withWorkOverrides} from './channel-visibility.js';
import {templateFields,changedDesign} from './template-model.js';
import {readAll} from './review-service.js?v=web-1';
import {swatch,cleanDesign,sameDesign,fieldsHtml,wireColors,mountPreview} from './render-templates.js?v=tpl-5';
import './font-picker.js?v=1';   // 작품 고르기 드롭다운
import {loadCatalog} from './work-catalog.js?v=hide-1';
import {loadWorkAssets} from './work-assets-data.js?v=1';
// 채널 템플릿 — 채널을 고르고 작품 탭마다 영상 모양을 정한다(0134). '이 채널에서만'은 작품 기본 위에 칸 단위로 얹고,
// '모든 채널 기본'은 그 작품의 기본값이다. 맥미니는 작업을 시작할 때 이 값을 읽어 그대로 렌더한다(이미 만든 영상은 그대로).
// 아래 '예전 칸'(크기 · 위치 · 화면비)은 예전 파이프라인 채널 값 — 새 파이프라인 렌더에는 아직 안 쓰이지만 나중을 위해 그대로 둔다.
const OLD_KEYS=new Set(['title_size','title_size2','subtitles','subtitle_size','tts_size','tts_y_margin','aspect_ratio','video_width','video_y']);
export function mountChannelTemplates(root,{client,role,channel}={}){
 let dead=false,voiceList=[],chanVoices=new Map(),workArgs=new Map(),audio=null,assets=new Map(),logoPicks=new Map(),channels=[],overrides=[],current=null,work=null,scope='channel',designs=new Map(),workDefaults=new Map(),presets=[],videos=[],saving=false,preview=null;
 const writable=['operator','admin'].includes(role);
 root.innerHTML='<div class="template-layout"><aside class="template-sidebar"><label>채널 검색<input type="search" placeholder="채널 검색" aria-label="템플릿 채널 검색"></label><div class="template-channels"></div></aside><section class="template-main"><p role="status">채널 템플릿을 불러오는 중…</p></section></div>';
 const main=root.querySelector('.template-main'),list=root.querySelector('.template-channels'),search=root.querySelector('input');
 const key=(slug,w)=>slug+'\u0000'+w;
 const chanDesign=()=>designs.get(key(current.token_slug,work))||null;
 const workDesign=()=>workDefaults.get(work)||null;
 const effective=(slug,w)=>({...(workDefaults.get(w)||{}),...(designs.get(key(slug,w))||{})});
 const form=()=>main.querySelector('.rt-form');
 const formDesign=()=>cleanDesign(Object.fromEntries(new FormData(form())));
 const saved=()=>(scope==='channel'?chanDesign():workDesign())||{};
 const dirty=()=>{try{return !!form()&&!sameDesign(formDesign(),saved());}catch{return true;}};
 const leave=()=>!dirty()||confirm('저장하지 않은 값이 있어요. 그래도 옮길까요?');
 function renderList(){list.innerHTML=channels.filter(c=>c.name.includes(search.value.trim())).map(c=>`<button type="button" data-slug="${esc(c.token_slug)}" class="has-av${c===current?' active':''}"><span class="tc-av">${c.avatar_url?`<img src="${esc(c.avatar_url)}" alt="" referrerpolicy="no-referrer">`:esc((c.name||'?').slice(0,1))}</span><span class="tc-txt">${esc(c.name)}<small>${c.works?.length||0}개 작품</small></span></button>`).join('');
  list.querySelectorAll('button').forEach(b=>b.onclick=()=>{if(saving||!leave())return;current=channels.find(c=>c.token_slug===b.dataset.slug);work=current.works?.[0]||null;scope='channel';render();});}
 function render(){
  renderList();preview?.release();preview=null;if(audio){audio.pause();audio=null;}
  const works=current.works||[];
  if(work&&!works.includes(work))work=works[0]||null;
  const override=overrides.find(o=>o.token_slug===current.token_slug),old=override?.design??current.design??{};
  const oldHtml=`<details class="ct-old"><summary>예전 칸 · 크기 · 위치 · 화면비 <small>채널 전체 값 · 새 파이프라인 렌더에는 아직 안 쓰여요</small></summary>
    <form class="template-form ct-old-form"><fieldset ${writable?'':'disabled'}>${['제목','자막','내레이션 자막','영상 영역'].map(g=>{const fs=templateFields.filter(f=>f[0]===g&&OLD_KEYS.has(f[1]));return fs.length?`<section><h3>${g}</h3><div class="template-fields">${fs.map(([,k,l,t,min,max])=>{const v=old[k]??'';return `<label>${l}${t==='onoff'?`<select name="${k}"><option value="">켬 (기본)</option><option value="false" ${v===false||v==='false'?'selected':''}>끔</option></select>`:`<input name="${k}" type="${t==='number'?'number':'text'}" value="${esc(v)}" placeholder="${t==='ratio'?'예: 13:9':'기본값 사용'}" ${t==='number'?`min="${min}" max="${max}" step="1"`:''}>`}</label>`;}).join('')}</div></section>`:'';}).join('')}
     <p class="rt-status" role="status"></p>${writable?'<div class="rt-actions"><span></span><button type="submit" class="primary">예전 칸 저장</button></div>':''}</fieldset></form></details>`;
  // 작품 고르기 — 채널 이름 옆 드롭다운(src/font-picker.js 목록 모양). 줄마다 이 채널 값의 제목 두 색 알약(오른쪽 끝), 아직 안 정한 작품은 '아직 안 정함'(2026-10-02 사용자)
  const tabs=works.length?`<div class="ct-work"><select data-work-pick data-font data-pill-btn aria-label="작품">${works.map(w=>{const d=effective(current.token_slug,w),mine=designs.has(key(current.token_slug,w))||chanVoices.has(key(current.token_slug,w));
   return `<option value="${esc(w)}" data-ff=""${w===work?' selected':''} data-c1="${esc(d.title_color||'#FFFFFF')}" data-c2="${esc(d.title_color2||'#FFFF00')}"${mine?'':' data-note="아직 안 정함"'}>${esc(w)}</option>`;}).join('')}</select></div>`:'';
  let top='',body='<p class="workbench-note">이 채널에 생성 대상 작품이 없어요. 채널 관리에서 작품을 붙이면 여기서 모양을 정할 수 있어요.</p>';
  if(work){
   const ch=chanDesign(),wd=workDesign();
   const state=scope==='channel'?(ch?`${esc(current.name)}에서만 따로 정한 값이 있어요. 비워 둔 칸은 모든 채널 기본을 따라요.`:wd?`지금은 모든 채널 기본을 따라요. 여기서 고친 칸만 ${esc(current.name)}에서 바뀌어요.`:'아직 정한 값이 없어 엔진 기본으로 만들어요.')
    :(wd?'이 작품을 만드는 모든 채널의 기본이에요. 채널에서 따로 정한 칸은 그 값이 이겨요.':'아직 기본값이 없어요. 채널마다 따로 정하지 않은 칸은 엔진 기본이에요.');
   const others=[...designs.entries()].filter(([k])=>k.endsWith('\u0000'+work)&&!k.startsWith(current.token_slug+'\u0000')).map(([k,d])=>{const slug=k.split('\u0000')[0];return {label:`${channels.find(c=>c.token_slug===slug)?.name||slug}의 값`,d};});
   const loads=[...(scope==='channel'&&wd?[{label:'모든 채널 기본 값',d:wd}]:[]),...others,...presets.map(p=>({label:`기존 템플릿 · ${p.name}`,d:p.design}))];
   // '이 채널에서만 / 모든 채널 기본' 고르기는 뺐다 — 채널을 골라 정하는 화면이라 값은 늘 이 채널 × 이 작품(2026-10-02 사용자). 작품 기본은 불러오기에만 남는다
   void state;
   body=`<div class="template-split ct-split"><div class="ct-left"><form class="template-form rt-form"><fieldset ${writable?'':'disabled'}>
     ${loads.length&&writable?`<div class="ct-load"><select data-load data-font><option value="" data-ff="">불러오기…</option>${loads.map((l,i)=>`<option value="${i}" data-ff="${esc(l.d?.title_font||'Jalnan')}"${l.d?.title_color?` data-c1="${esc(l.d.title_color)}"`:''}${l.d?.title_color2?` data-c2="${esc(l.d.title_color2)}"`:''}>${esc(l.label)}</option>`).join('')}</select></div>`:''}
     <section class="ct-logo"><h3>작품 로고</h3><div class="ct-logo-row"><span class="rt-none">작품 관리에 올린 로고를 불러오는 중…</span></div></section>
     ${voiceHtml()}
     ${fieldsHtml(scope==='channel'?(ch||{}):(wd||{}),scope==='channel'?(wd||{}):{})}
     <p class="rt-status" role="status"></p>
     <div class="rt-actions">${writable&&(scope==='channel'?ch:wd)?`<button type="button" class="rt-retire" data-clear>${scope==='channel'?'따로 정한 값 지우기':'기본값 지우기'}</button>`:''}<span></span>${writable?'<button type="button" data-reset>되돌리기</button><button type="submit" class="primary">저장</button>':'<span class="rt-none">운영자만 바꿀 수 있어요.</span>'}</div>
    </fieldset></form>${oldHtml}</div><aside class="template-preview ct-side rt-preview" aria-label="적용 모습 미리보기"></aside></div>`;
  }
  main.innerHTML=`<header><div class="ct-head"><h2>${esc(current.name)}</h2>${tabs}<p>작품마다 영상 모양을 정해요. 저장한 값은 다음 작업부터 써요.</p></div></header>
   ${top?`<div class="ct-top">${top}</div>`:''}${body}`;
  const pick=main.querySelector('[data-work-pick]');
  if(pick)pick.onchange=()=>{if(pick.value===work)return;if(!leave()){pick.value=work;pick.dispatchEvent(new Event('change'));return;}work=pick.value;render();};
  const oldForm=main.querySelector('.ct-old-form');
  if(oldForm)oldForm.onsubmit=async e=>{e.preventDefault();if(!writable)return;const st=oldForm.querySelector('.rt-status');
   try{const next=changedDesign(old,Object.fromEntries(new FormData(oldForm)));st.textContent='저장 중…';
    const {error}=await client.rpc('set_channel_design',{p_slug:current.token_slug,p_design:next});if(error)throw error;
    overrides=overrides.filter(o=>o.token_slug!==current.token_slug).concat({token_slug:current.token_slug,design:next});st.textContent='저장했어요.';}
   catch(x){st.textContent=x.message||'저장하지 못했어요.';}};
  const f=form();if(!f)return;
  const status=t=>{f.querySelector('.rt-status').textContent=t;};
  const changed=()=>{status(dirty()?'저장하지 않은 값이 있어요':'');preview?.refresh();};
  wireColors(f,changed);f.oninput=changed;f.onchange=e=>{if(!e.target.matches('[data-load]'))changed();};
  f.querySelector('[data-load]')?.addEventListener('change',e=>{const i=e.target.value;if(i==='')return;
   const ch=scope==='channel'?chanDesign():workDesign(),wd=workDesign();
   const loads=[...(scope==='channel'&&wd?[{d:wd}]:[]),...[...designs.entries()].filter(([k])=>k.endsWith('\u0000'+work)&&!k.startsWith(current.token_slug+'\u0000')).map(([,d])=>({d})),...presets.map(p=>({d:p.design}))];
   const d=loads[+i]?.d||{};
   for(const el of f.querySelectorAll('[name]')){el.value=d[el.name]||'';const c=f.querySelector(`[data-for="${el.name}"]`);if(c&&d[el.name])c.value=d[el.name];}
   e.target.value='';changed();status('불러온 값이에요. 저장해야 바뀌어요.');void ch;});
  f.querySelector('[data-reset]')?.addEventListener('click',()=>render());
  f.querySelector('[data-clear]')?.addEventListener('click',async()=>{
   if(!confirm(scope==='channel'?`${current.name}에서 정한 값을 지울까요? 그 뒤로는 엔진 기본으로 만들어요.`:`'${work}' 작품의 기본값을 지울까요?`))return;
   const r=scope==='channel'?await client.rpc('set_channel_work_design',{p_slug:current.token_slug,p_work:work,p_design:null}):await client.rpc('set_work_design',{p_work:work,p_design:null});
   if(r.error){status(r.error.message);return;}
   scope==='channel'?designs.delete(key(current.token_slug,work)):workDefaults.delete(work);render();});
  f.onsubmit=async e=>{e.preventDefault();if(!writable||saving)return;let d;try{d=formDesign();}catch(x){status(x.message);return;}
   saving=true;status('저장 중…');
   const r=scope==='channel'?await client.rpc('set_channel_work_design',{p_slug:current.token_slug,p_work:work,p_design:Object.keys(d).length?d:null}):await client.rpc('set_work_design',{p_work:work,p_design:Object.keys(d).length?d:null});
   saving=false;if(r.error){status(r.error.message);return;}
   if(scope==='channel'){r.data&&Object.keys(r.data).length?designs.set(key(current.token_slug,work),r.data):designs.delete(key(current.token_slug,work));}
   else{r.data?workDefaults.set(work,r.data):workDefaults.delete(work);}
   render();main.querySelector('.rt-form .rt-status').textContent='저장했어요. 다음 작업부터 이 모양으로 만들어요.';};
  // 같은 작품 영상으로만 — 로고 크기가 다르면 영상 칸 · 로고 자리가 달라진다(0135)
  const vids=videos.filter(v=>v.work_title===work);
  preview=mountPreview(main.querySelector('.ct-side'),{client,videos:vids,writable,status,emptyText:'이 작품을 맥미니에서 만든 영상이 아직 없어요. 한 번 만든 뒤 볼 수 있어요.',
   target:()=>({p_work:work,p_slug:scope==='channel'?current.token_slug:null}),
   getDesign:()=>scope==='channel'?{...(workDesign()||{}),...formDesign()}:formDesign()});
  fillAssets();wireVoice();
 }
 // 내레이션 목소리(0136) — '이 채널에서만'은 채널 × 작품 목소리(비우면 모든 채널 기본), '모든 채널 기본'은 작품 엔진 설정의 voice. 고르면 바로 저장
 const voiceName=id=>{const v=voiceList.find(x=>x.id===id);return v?`${v.name}${v.gender?` (${v.gender})`:''}`:(id?id.replace(/^elevenlabs:/,''):'');};
 function voiceHtml(){
  const wv=(workArgs.get(work)||{}).voice||'',cv=chanVoices.get(key(current.token_slug,work))||'';
  const cur=scope==='channel'?cv:wv;
  // 목소리도 채널마다 직접 고른다(2026-10-02 사용자) — 고르지 않으면 작품 엔진 설정 목소리, 그것도 없으면 엔진 기본으로 만든다
  const first=scope==='channel'?`고르지 않음 · ${wv?voiceName(wv):'엔진 기본'}으로 만들어요`:'엔진 기본';
  return `<section class="ct-voice"><h3>내레이션 목소리</h3><div class="ct-voice-row"><select data-voice ${writable?'':'disabled'}><option value="">${esc(first)}</option>${voiceList.map(v=>`<option value="${esc(v.id)}"${v.id===cur?' selected':''}>${esc(voiceName(v.id))}</option>`).join('')}</select><button type="button" class="ct-listen" data-listen>들어 보기</button></div><p class="rt-none">고르면 바로 저장돼요. 다음 작업부터 이 목소리로 만들어요.</p></section>`;
 }
 function wireVoice(){
  const sel=main.querySelector('[data-voice]'),btn=main.querySelector('[data-listen]');if(!sel)return;
  const stop=()=>{if(audio){audio.pause();audio=null;}btn.textContent='들어 보기';};
  btn.onclick=()=>{if(audio){stop();return;}const id=sel.value||(scope==='channel'?(workArgs.get(work)||{}).voice:'');const v=voiceList.find(x=>x.id===id);
   if(!v?.preview_url){btn.textContent='들을 수 있는 소리가 없어요';setTimeout(()=>{btn.textContent='들어 보기';},1500);return;}
   audio=new Audio(v.preview_url);audio.onended=stop;audio.play().catch(stop);btn.textContent='멈추기';};
  sel.onchange=async()=>{const v=sel.value||null,k=key(current.token_slug,work);sel.disabled=true;let r;
   if(scope==='channel')r=await client.rpc('set_channel_work_voice',{p_slug:current.token_slug,p_work:work,p_voice:v});
   else{const args={...(workArgs.get(work)||{})};if(v)args.voice=v;else delete args.voice;r=await client.rpc('set_work_engine_args',{p_work:work,p_args:args});if(!r.error)workArgs.set(work,args);}
   sel.disabled=!writable;const st=main.querySelector('.rt-form .rt-status');
   if(r.error){if(st)st.textContent=r.error.message;return;}
   if(scope==='channel'){v?chanVoices.set(k,v):chanVoices.delete(k);}
   if(st)st.textContent=v?`목소리를 ${voiceName(v)}(으)로 바꿨어요.`:'목소리를 고르지 않았어요. 작품 기본 목소리로 만들어요.';};
 }
 // 작품 로고(작품 관리 에셋) — '이 채널에서만'이면 고르기(채널 관리 로고 칸과 같은 값), '모든 채널 기본'이면 작품 기본 로고 보기만.
 // 권리사 칸에는 작품 관리에 올린 권리사 로고도 고를 수 있게 넣는다
 async function fillAssets(){
  const w=work,slug=current.token_slug,row=main.querySelector('.ct-logo-row');if(!row)return;
  try{
   if(!assets.has(w)){const {works}=await loadCatalog(client);const id=works.find(x=>x.title===w)?.id;assets.set(w,id?await loadWorkAssets(client,id):null);}
   if(!logoPicks.has(w)){const {data}=await client.from('channel_work_assets').select('token_slug,label').eq('work_title',w).eq('role','work_logo');logoPicks.set(w,new Map((data||[]).map(x=>[x.token_slug,x.label])));}
  }catch(e){if(work===w)row.innerHTML=`<span class="rt-fail">${esc(e.message||'로고를 불러오지 못했어요')}</span>`;return;}
  if(dead||work!==w||current.token_slug!==slug||!main.querySelector('.ct-logo-row'))return;
  const a=assets.get(w),logos=a?.logos?.work_logo||[],picked=logoPicks.get(w).get(slug)||null;
  const chip=l=>{const on=scope==='channel'?(picked?l.label===picked:l.is_default):l.is_default;
   return `<button type="button" class="ch-logo-chip${on?' on':''}" data-logo="${esc(l.label)}" data-default="${l.is_default?1:''}" ${scope==='channel'&&writable?'':'disabled'}><span class="ch-logo-mini">${l.preview_url?`<img src="${esc(l.preview_url)}" alt="">`:''}</span>${esc(l.label)}${l.is_default?' <small>기본</small>':''}</button>`;};
  main.querySelector('.ct-logo-row').innerHTML=logos.length?`<div class="ch-logo-chips">${logos.map(chip).join('')}</div>${scope==='work'?'<span class="rt-none">기본 로고는 작품 관리에서 바꿔요.</span>':''}`
   :'<span class="rt-none">작품 관리에 올린 로고가 없어요. 작품 관리에서 올리면 여기서 고를 수 있어요.</span>';
  main.querySelectorAll('[data-logo]').forEach(b=>b.onclick=async()=>{if(b.classList.contains('on'))return;
   const {error}=await client.rpc('set_channel_work_asset',{p_slug:slug,p_work:w,p_role:'work_logo',p_label:b.dataset.default?null:b.dataset.logo});
   if(error){alert(error.message);return;}
   b.dataset.default?logoPicks.get(w).delete(slug):logoPicks.get(w).set(slug,b.dataset.logo);
   main.querySelectorAll('[data-logo]').forEach(x=>x.classList.toggle('on',x===b));
   const st=main.querySelector('.rt-form .rt-status');if(st)st.textContent='로고를 바꿨어요. 적용 모습 미리보기를 다시 누르면 이 로고로 그려요.';});
  const sel=main.querySelector('select[name=platform_image]');
  const up=[...(a?.platform?.holder_logos||[]),...(a?.logos?.platform_logo||[])];
  if(sel&&up.length&&!sel.querySelector('[data-up]')){
   sel.insertAdjacentHTML('beforeend',up.map(l=>`<option data-up value="asset:${esc(l.id)}">올린 로고 · ${esc(l.label)}</option>`).join(''));
   if(sel.dataset.asset)sel.value='asset:'+sel.dataset.asset;}
 }
 search.oninput=renderList;
 if(!client)main.innerHTML='<p>로그인하면 채널 템플릿을 불러와요.</p>';
 else Promise.all([
  readAll(()=>client.from('channels_mirror').select('token_slug,name,design,works,avatar_url').order('name')).then(c=>visibleChannels(client,c)).then(c=>withWorkOverrides(client,c)),
  readAll(()=>client.from('channel_design_overrides').select('token_slug,design').order('token_slug')),
  readAll(()=>client.from('channel_work_designs').select('token_slug,work_title,design,voice').order('token_slug')),
  readAll(()=>client.from('work_cards').select('work_title,render_design').not('render_design','is',null).order('work_title')),
  readAll(()=>client.from('render_templates').select('id,name,design').is('retired_at',null).order('name')),
  client.from('tikitaka_videos').select('id,title,suffix,work_title,created_at').order('created_at',{ascending:false}).limit(60).then(r=>r.data||[]),
  client.from('tts_voices').select('id,name,gender,preview_url,sort').eq('active',true).order('sort').order('name').then(r=>r.data||[]),
  readAll(()=>client.from('work_cards').select('work_title,engine_args').order('work_title'))
 ]).then(([c,o,cw,wd,t,v,vl,wa])=>{if(dead)return;channels=c;overrides=o;voiceList=vl;workArgs=new Map(wa.map(x=>[x.work_title,x.engine_args||{}]));
  chanVoices=new Map(cw.filter(x=>x.voice).map(x=>[key(x.token_slug,x.work_title),x.voice]));
  designs=new Map(cw.filter(x=>x.design&&Object.keys(x.design).length).map(x=>[key(x.token_slug,x.work_title),x.design]));workDefaults=new Map(wd.map(x=>[x.work_title,x.render_design]));presets=t;videos=v;
  current=c.find(x=>x.token_slug===channel)||c[0];
  if(current){work=current.works?.[0]||null;render();list.querySelector('.active')?.scrollIntoView({block:'nearest'});}else main.textContent='등록된 채널이 없습니다.';})
  .catch(e=>{if(!dead)main.textContent='템플릿을 불러오지 못했어요. '+(e.message||'');});
 return()=>{dead=true;preview?.release();if(audio)audio.pause();};
}
