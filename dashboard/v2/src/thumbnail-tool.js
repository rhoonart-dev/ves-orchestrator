import {esc} from './review-details.js?v=web-1';
import {assetRequest} from './work-assets.js?v=web-1';
import {localMedia} from './local-jobs.js?v=room-1';
// 썸네일 창 — 엔진(ai-video app.tikitaka.thumbnail)을 부르고, thumbnails.json 을 읽고, 사람이 고른 목록을 manual.json 으로 넘긴다.
// 미리보기의 글자는 대략(엔진 글꼴·색만 맞춤) — 정확한 결과는 [이 목록으로 만들기]의 합성본이다.
const COLOR_NAMES={white:'흰색',yellow:'노랑',lime:'라임',neon:'형광(번짐)',peach:'살구',sky:'하늘'};
const COLOR_CSS={white:'#FFFFFF',yellow:'#FFE23C',lime:'#C6FF3D',neon:'#B8FF5A',peach:'#FFB48A',sky:'#8FD8FF'};
const HOW={flash:'AI 추천',manual:'직접 고른 목록',score:'장면 점수 순'};
const MAX=8;
const when=v=>{const d=new Date(v);return v&&Number.isFinite(d.getTime())?d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'numeric',minute:'2-digit'}):''};

function fromPick(p){
 const parts=String(p.label||'').split(' / ');
 return p.style==='split'&&parts.length===2?{frame:p.frame,style:'split',parts,color:p.color||'white',y:p.y??''}
  :{frame:p.frame,style:'line',label:p.label||'',color:p.color||'white',y:''};
}
function fromManual(m){return m.style==='split'?{frame:m.frame,style:'split',parts:[...m.parts],color:m.color||'white',y:m.y??'',why:m.why}
 :{frame:m.frame,style:'line',label:m.label||'',color:m.color||'white',y:m.y??'',why:m.why};}

export function openThumbnails({client,video,onChange=()=>{}}){
 const key=video.key,ver=video.suffix;
 // 제목 — 'v11_r3325-3638' 같은 폴더 이름 대신 영상 제목을 보여 준다(없으면 그냥 '썸네일').
 const name=String(video.title||'').replace(/\s*\n\s*/g,' ').trim();
 const heading=`<small class="thumb-kicker">썸네일</small><h2>${esc(name||'썸네일')}</h2>`;
 let data=null,items=[],poll=0,busy=false,closed=false;
 const dlg=document.createElement('dialog');dlg.className='thumb-dialog';
 document.body.append(dlg);
 // 맥미니 영상(0129) — 그 맥미니가 만들고 결과는 저장소(ves-outputs)에서 서명 주소로 읽는다. 작업 컴퓨터 영상은 예전처럼 로컬 서버
 const remote=!!video.remote,vid=video.video_id;let urls={};
 const media=f=>remote?(urls[f]||''):localMedia(key,'thumbnails/'+f)+(data?.version?`&v=${data.version}`:'');
 async function loadRemote(){
  const {data:row,error}=await client.from('tikitaka_thumbnails').select('*').eq('video_id',vid).maybeSingle();
  if(error)throw Error(error.message);
  const files=row?.files||{},rels=Object.keys(files);urls={};
  if(rels.length){const {data:su}=await client.storage.from('ves-outputs').createSignedUrls(rels.map(r=>files[r]),6*3600);
   (su||[]).forEach((u,i)=>{if(u.signedUrl)urls[rels[i]]=u.signedUrl;});}
  return {state:{state:row?.state||'none',has_result:!!row?.doc,error:row?.error,manual:!!row?.manual,publish_rank:row?.publish?.rank??null,updated_at:row?.updated_at},
   doc:row?.doc||null,manual:row?.manual||null,publish:row?.publish||null,version:row?.version||0};
 }
 const rpc=async(fn,args)=>{const {error}=await client.rpc(fn,args);if(error)throw Error(error.message);};
 const frameOf=id=>data?.doc?.frames?.find(f=>f.id===id);
 const close=()=>{closed=true;clearTimeout(poll);dlg.close();dlg.remove();onChange();};
 dlg.addEventListener('cancel',e=>{e.preventDefault();close();});

 async function load(){
  clearTimeout(poll);
  try{data=remote?await loadRemote():await assetRequest(client,`/api/local-videos/thumbnails?key=${encodeURIComponent(key)}`);}
  catch(e){dlg.innerHTML=`<div class="thumb-head"><div>${heading}</div><button class="thumb-close" aria-label="닫기">✕</button></div><p class="thumb-error">${esc(e.message)}</p>`;dlg.querySelector('.thumb-close').onclick=close;return;}
  if(closed)return;
  if(!items.length&&data.doc)items=(data.manual||[]).length?data.manual.map(fromManual):data.doc.picks.map(fromPick);
  render();
  if(data.state.state==='running')poll=setTimeout(load,remote?4000:2000);
 }
 async function act(action){
  if(busy)return;busy=true;
  try{
   const manual=action==='manual'?items.map(({why,...it})=>({...it,...(why?{why}:{})})):null;
   if(remote)await rpc('request_tikitaka_thumbnails',{p_video:vid,p_action:action,p_manual:manual});
   else await assetRequest(client,'/api/local-videos/thumbnails',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key,action,...(manual?{manual}:{})})});
   if(action==='reset')items=[];
  }catch(e){busy=false;const m=dlg.querySelector('.thumb-msg');if(m)m.textContent=e.message;return;}
  busy=false;load();
 }

 // 발행용 고르기 — 새로 만들지 않고 어떤 번호를 올릴지만 남긴다(rank 비우면 취소)
 async function choose(rank){
  if(busy)return;busy=true;
  try{if(remote)await rpc('choose_tikitaka_thumbnail',{p_video:vid,p_rank:rank===''?null:+rank});
   else await assetRequest(client,'/api/local-videos/thumbnails',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key,action:'choose',rank:rank===''?null:+rank})});}
  catch(e){busy=false;const m=dlg.querySelector('.thumb-msg');if(m)m.textContent=e.message;return;}
  busy=false;load();
 }

 function preview(it){
  const f=frameOf(it.frame);if(!f)return '<div class="thumb-frame missing">장면 없음</div>';
  const band=data.doc.band||[450,1080];
  const y=it.y!==''&&it.y!=null?+it.y:band[0]+band[1]*.72;
  const face=(f.faces||[])[0];
  const style=c=>`color:${COLOR_CSS[it.color]||'#fff'};${it.color==='neon'?'text-shadow:0 0 .35em #7CFF2A,0 0 .7em #57E00F;':''}`;
  let text='';
  if(it.style==='split'&&face){const cx=face[0]+face[2]/2;
   text=`<span class="thumb-text" style="top:${y/19.2}%;left:${Math.max(4,(cx-face[2]*1.4)/10.8)}%;transform:translate(-50%,-50%);${style()}">${esc(it.parts[0]||'')}</span>
    <span class="thumb-text" style="top:${y/19.2}%;left:${Math.min(96,(cx+face[2]*1.4)/10.8)}%;transform:translate(-50%,-50%);${style()}">${esc(it.parts[1]||'')}</span>`;}
  else{const t=it.style==='split'?(it.parts||[]).join(''):it.label;
   if(t)text=`<span class="thumb-text" style="top:${y/19.2}%;left:50%;transform:translate(-50%,-50%);${style()}">${esc(t)}</span>`;}
  return `<div class="thumb-frame"><img src="${esc(media(f.file))}" alt="" loading="lazy">${text}</div>`;
 }

 function render(){
  const st=data.state,doc=data.doc,running=st.state==='running';
  const picks=doc?.picks||[];
  const chosen=data.publish?.rank??null;
  const cand=new Set((doc?.candidates||[]).map(c=>c.id));
  dlg.innerHTML=`<div class="thumb-head"><div>${heading}
    ${doc?`<p>${running?'다시 만드는 중이에요':`${esc(HOW[doc.how]||doc.how)} · ${esc(when(st.updated_at))}`}</p>`:''}</div>
    <button class="thumb-close" aria-label="닫기">✕</button></div>
   ${st.stale?'<p class="thumb-warn">영상이 다시 렌더됐어요. 화면이 달라졌을 수 있으니 다시 만들어 주세요.</p>':''}
   ${st.state==='failed'?`<p class="thumb-warn">${esc(st.error||'썸네일을 만들지 못했어요.')}</p>`:''}
   <p class="thumb-msg" role="status"></p>
   ${!doc?`<div class="thumb-empty"><h3>${running?'썸네일을 만드는 중이에요':'아직 만든 썸네일이 없어요'}</h3>
     <p>${running?(remote?'이 영상을 만든 맥미니가 만들어요. 1~2분쯤 걸리고, 창을 닫아도 계속 만들어요.':'처음이면 15초쯤 걸려요. 창을 닫아도 계속 만들어요.'):'AI가 썸네일 후보를 만들고, 이후에 장면·문구를 직접 바꿀 수 있어요.'}</p>
     <button class="primary" data-act="run" ${running?'disabled':''}>${running?'만드는 중…':'썸네일 만들기'}</button></div>`:`
   <section class="thumb-sec"><div class="thumb-sec-head"><h3>만든 썸네일 <span>${picks.length}</span></h3><div>
     ${st.manual?`<button data-act="reset" ${running?'disabled':''}>처음 추천으로 되돌리기</button>`:''}
     <button data-act="run" ${running?'disabled':''}>다시 만들기</button></div></div>
    <div class="thumb-picks">${picks.map(p=>`<figure><img src="${esc(media(p.file))}" alt="썸네일 ${p.rank}">
     <figcaption><b>${esc(p.label||'라벨 없음')}</b>${p.why?`<small>${esc(p.why)}</small>`:''}${doc.how==='flash'&&p.label?'<small class="thumb-check">라벨을 확인해 주세요. 다른 인물의 대사일 수 있어요</small>':''}
     <span class="thumb-pick-acts">${chosen===p.rank?`<button class="thumb-chosen" data-choose="" title="누르면 고른 것을 취소해요">✓ 발행용</button>`:`<button data-choose="${p.rank}">발행용으로 고르기</button>`}
     <a class="thumb-dl" href="${esc(media(p.file))}" download="${esc(ver)}_썸네일_${p.rank}.png">내려받기</a></span></figcaption></figure>`).join('')}</div>
    <p class="thumb-hint">발행용으로 고른 썸네일은 대시보드에서 발행할 때 같이 올라가고, 발행 일정 달력에도 이 그림으로 보여요.</p></section>
   <section class="thumb-sec"><div class="thumb-sec-head"><h3>고를 목록 <span>${items.length}/${MAX}</span></h3>
     <button class="primary" data-act="manual" ${running||!items.length?'disabled':''}>이 목록으로 만들기</button></div>
    <p class="thumb-hint">순서대로 썸네일 1, 2, 3…이 돼요. 장면은 아래 '다른 장면 고르기'에서 더할 수 있어요.</p>
    <div class="thumb-items">${items.map((it,i)=>`<article data-i="${i}">${preview(it)}<div class="thumb-fields">
      <div class="thumb-row"><b>${i+1}</b><span class="thumb-id">${esc(it.frame)}</span><span class="grow"></span>
       <button data-mv="-1" ${i?'':'disabled'} aria-label="앞으로">↑</button><button data-mv="1" ${i<items.length-1?'':'disabled'} aria-label="뒤로">↓</button><button data-rm aria-label="빼기">빼기</button></div>
      <label>형식<select data-k="style"><option value="line" ${it.style==='line'?'selected':''}>한 줄</option><option value="split" ${it.style==='split'?'selected':''}>얼굴 양옆 둘로</option></select></label>
      ${it.style==='split'?`<label>문구<span class="thumb-two"><input data-k="p0" value="${esc(it.parts?.[0]||'')}" placeholder="(긴"><input data-k="p1" value="${esc(it.parts?.[1]||'')}" placeholder="장)"></span></label>`
       :`<label>문구<input data-k="label" value="${esc(it.label||'')}" placeholder="비우면 라벨 없음"></label>`}
      <label>색<select data-k="color">${(doc.colors||[]).map(c=>`<option value="${c}" ${it.color===c?'selected':''}>${esc(COLOR_NAMES[c]||c)}</option>`).join('')}</select></label>
      <label>세로 위치<input data-k="y" type="number" min="0" max="1920" value="${esc(it.y??'')}" placeholder="자동(얼굴 피해서)"></label>
     </div></article>`).join('')||'<p class="thumb-hint">목록이 비었어요.</p>'}</div></section>
   <section class="thumb-sec"><div class="thumb-sec-head"><h3>다른 장면 고르기 <span>${(doc.frames||[]).length}</span></h3></div>
    <p class="thumb-hint">누르면 고를 목록 끝에 더해져요. ★은 장면 점수가 높은 후보예요.</p>
    <div class="thumb-grid">${(doc.frames||[]).map(f=>`<button class="thumb-cell${cand.has(f.id)?' cand':''}" data-add="${esc(f.id)}" title="${esc(f.id)}"><img src="${esc(media(f.file))}" alt="" loading="lazy"><span>${cand.has(f.id)?'★ ':''}${esc(f.id)}</span></button>`).join('')}</div></section>`}`;
  dlg.querySelector('.thumb-close').onclick=close;
  dlg.querySelectorAll('[data-act]').forEach(b=>b.onclick=()=>act(b.dataset.act));
  dlg.querySelectorAll('[data-choose]').forEach(b=>b.onclick=()=>choose(b.dataset.choose));
  dlg.querySelectorAll('[data-add]').forEach(b=>b.onclick=()=>{
   if(items.length>=MAX){dlg.querySelector('.thumb-msg').textContent=`썸네일은 ${MAX}장까지 고를 수 있어요.`;return;}
   items.push({frame:b.dataset.add,style:'line',label:'',color:'white',y:''});render();
   dlg.querySelector('.thumb-items article:last-child')?.scrollIntoView({block:'nearest',behavior:'smooth'});});
  dlg.querySelectorAll('.thumb-items article').forEach(a=>{
   const i=+a.dataset.i,it=items[i];
   a.querySelectorAll('[data-k]').forEach(el=>el.oninput=el.onchange=()=>{
    const k=el.dataset.k;
    if(k==='style'){it.style=el.value;if(it.style==='split'&&!it.parts){const t=it.label||'';it.parts=[t.slice(0,Math.ceil(t.length/2)),t.slice(Math.ceil(t.length/2))];}
     if(it.style==='line'&&it.parts&&!it.label)it.label=it.parts.join('');render();return;}
    if(k==='p0'||k==='p1'){it.parts=it.parts||['',''];it.parts[+k[1]]=el.value;}else it[k]=el.value;
    a.querySelector('.thumb-frame').outerHTML=preview(it);});
   a.querySelector('[data-rm]').onclick=()=>{items.splice(i,1);render();};
   a.querySelectorAll('[data-mv]').forEach(b=>b.onclick=()=>{const j=i+ +b.dataset.mv;[items[i],items[j]]=[items[j],items[i]];render();});
  });
 }
 // 내용을 다 그린 뒤에 연다 — 빈 창('불러오는 중…' 한 줄짜리 넓은 상자)이 잠깐 번쩍이지 않게
 load().finally(()=>{if(!closed&&!dlg.open)dlg.showModal();});
 return close;
}
