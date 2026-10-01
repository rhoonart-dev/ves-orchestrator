import {needWorkPc,apiUrl,localize} from './local-only.js?v=web-1';
import {isRemoteKey,remoteEditorPayload,remoteLogos,remoteSaveDraft,remoteSubmit,remoteCheck} from './remote-editor-data.js?v=3';
// Local bundle mode for the ported editor: auth stays on the real VES client; every data call the
// editor makes is answered from /api/local-videos (ai-video videos/<suffix>/ bundles). Nothing is
// written to VES tables; the only VES reads are the voice settings (ops_config) and voice preview. Submissions are recorded as edits and re-render the video in the background — see scripts/local_videos_api.py.
async function api(client,path,body){
 needWorkPc('편집실은 아직 작업 컴퓨터에서만 열 수 있어요.');
 const {data:{session}}=await client.auth.getSession();
 const headers={'Authorization':`Bearer ${session?.access_token||''}`};
 if(body)headers['Content-Type']='application/json';
 const res=await fetch(apiUrl(path),{method:body?'POST':'GET',headers,body:body?JSON.stringify(body):undefined,cache:'no-store'});
 const payload=await res.json().catch(()=>({error:'작업 컴퓨터의 답을 읽지 못했어요.'}));
 if(!res.ok)throw new Error(payload.error||'작업 컴퓨터에 요청하지 못했어요.');
 return localize(payload);   // 웹 주소로 열었으면 미디어 주소도 127.0.0.1:8769 로
}
// 맥미니 영상(remote-<작업지시>/<편>)은 로컬 서버 없이 브라우저가 저장소에서 바로 연다(remote-editor-data.js) — 웹 주소에서도 된다
export const loadLocalVideo=(client,key)=>isRemoteKey(key)?remoteEditorPayload(client,key):api(client,`/api/local-videos/editor?key=${encodeURIComponent(key)}`);

// Minimal PostgREST-shaped query: the editor only awaits {data,error} from select/eq/in/order/limit/maybeSingle chains.
function query(table,answer){
 const q={table,filters:{}};
 const chain={select:()=>chain,eq:(k,v)=>{q.filters[k]=v;return chain},in:()=>chain,order:()=>chain,limit:()=>chain,
  maybeSingle:()=>chain,single:()=>chain,then:(ok,fail)=>Promise.resolve().then(()=>answer(q)).then(ok,fail)};
 return chain;
}

// 맥미니 영상 — 같은 모양의 local·sb 를 Supabase 로(초안·제출은 0113 RPC, 로고는 작품 관리 표)
function remoteClient(client,payload,answer){
 const key=payload.meta.key,basedOn=payload.meta.render_fingerprint;
 let role=null;
 const myRole=async()=>{if(role)return role;const {data:{user}}=await client.auth.getUser();const {data}=await client.from('user_roles').select('role').eq('user_id',user?.id||'').limit(1);return role=data?.[0]?.role||null;};
 const local={
  key,basedOn,
  submit:async(overrides,note)=>{try{return await remoteSubmit(client,payload,overrides,note)}catch(e){return {error:e.message}}},
  dryRun:null,measure:null,   // 제출 전 미리 검사·내레이션 길이 재기는 잡 폴더가 맥미니에 있어 여기선 못 한다(예상 길이로 검사)
  logos:async()=>remoteLogos(client,payload,await myRole()),
  uploadLogo:async(workId,roleKey,file,label,box)=>{
   const {uploadWorkAsset}=await import('./work-assets-data.js?v=1');
   return uploadWorkAsset(client,workId,{role:roleKey,target:roleKey==='platform_logo'?'holder':'work',file,renderWidth:box[0],renderHeight:box[1],label});
  },
  check:()=>remoteCheck(client,payload),
 };
 const sb={
  auth:client.auth,
  from:table=>query(table,answer),
  rpc:async(name,args)=>{
   if(name!=='save_editor_draft')return {data:null,error:{message:'여기서는 쓸 수 없는 기능이에요.'}};
   try{await remoteSaveDraft(client,payload,args.p_draft);return {data:null,error:null}}
   catch(e){return {data:null,error:{message:e.message}}}
  },
  storage:{from:()=>({
   createSignedUrl:async k=>({data:{signedUrl:k},error:null}),
   createSignedUrls:async keys=>({data:keys.map(k=>({path:k,signedUrl:k,error:null})),error:null}),
  })},
  functions:{invoke:(name,opts)=>name==='tts-preview'?client.functions.invoke(name,opts)
   :Promise.resolve({data:null,error:{message:'여기서는 쓸 수 없는 기능이에요.'}})},
 };
 return {sb,local};
}

export function createLocalEditorClient(client,payload){
 const key=payload.meta.key,basedOn=payload.meta.render_fingerprint;
 // A non-null work order makes the editor load prevOv (the AI labels as texts[]) from the fake job_queue.
 const row={...payload.row,work_order_id:'local'};
 const answer=q=>{
  if(q.table==='editor_assets')return {data:q.filters.run_id===key?row:null,error:null};
  if(q.table==='job_queue')return {data:{params:{edit_overrides:payload.prevOv||{}}},error:null};
  // Voice list and the ElevenLabs switch are VES settings, not video data — read them from VES (read-only).
  if(q.table==='ops_config')return client.from('ops_config').select('key,value').in('key',['editor_tts_voices','editor_tts_elevenlabs']);
  if(q.table==='editor_templates')return {data:[],error:null};
  // No VES card/channel locally: the design this video was rendered with stands in for the channel design,
  // so the preview and the '기본값' placeholders match the render and design edits sit on top of it.
  if(q.table==='review_queue')return {data:{payload:{},channel_slug:'local-render'},error:null};
  if(q.table==='channel_design_overrides')return {data:{design:payload.meta.render_design||{}},error:null};
  return {data:null,error:null};
 };
 if(payload.meta.serverless)return remoteClient(client,payload,answer);
 const local={
  key,basedOn,
  submit:async(overrides,note)=>{
   try{return await api(client,'/api/local-videos/submit',{key,overrides,based_on:basedOn,note})}
   catch(e){return {error:e.message}}
  },
  // 적용 미리 검사(엔진 apply_edit --check) — 엔진이 모르면 없음(편집실은 예상 길이로만 검사한다)
  dryRun:payload.meta.can_check?async overrides=>{
   try{return await api(client,'/api/local-videos/check',{key,overrides,based_on:basedOn})}
   catch(e){return {supported:false,error:e.message}}
  }:null,
  // 내레이션 실제 길이(엔진 apply_edit --measure) — 편집실이 문구를 저장할 때 부른다
  measure:payload.meta.can_check?async tts=>{
   try{return await api(client,'/api/local-videos/measure',{key,tts,based_on:basedOn})}
   catch(e){return {ok:false,error:e.message}}
  }:null,
  // 로고 탭 — 이 영상 작품의 로고(작품 관리에 올린 것). 올리기는 작품 관리와 같은 길(운영자·관리자)
  logos:()=>api(client,`/api/local-videos/logos?key=${encodeURIComponent(key)}`),
  uploadLogo:async(workId,role,file,label,box)=>{
   const {data:{session}}=await client.auth.getSession();
   const q=new URLSearchParams({role,filename:file.name,width:String(box[0]),height:String(box[1]),label});
   const res=await fetch(apiUrl(`/api/work-assets/${encodeURIComponent(workId)}?${q}`),{method:'POST',body:file,
    headers:{'Authorization':`Bearer ${session?.access_token||''}`,'Content-Type':file.type||'application/octet-stream'}});
   const payload=await res.json().catch(()=>({error:'작업 컴퓨터의 답을 읽지 못했어요.'}));
   if(!res.ok)throw new Error(payload.error||'로고를 올리지 못했어요.');
   return payload;
  },
  check:async()=>{
   try{const now=await loadLocalVideo(client,key);
    if(now.meta.render_fingerprint!==basedOn)return {canOpen:false,label:'편집실을 연 뒤에 영상이 새로 만들어졌어요. 다시 열어 주세요.'};
    if(now.meta.status!=='ready')return {canOpen:false,label:'이 영상은 새로 만들어야 해요. 새로 만든 뒤 열어 주세요.'};
    if(['queued','running'].includes(now.meta.apply?.state))return {canOpen:false,label:'이 영상을 다시 렌더하는 중이에요. 끝나면 새 판에서 고쳐 주세요.'};
    return {canOpen:true};
   }catch(e){return {canOpen:false,label:e.message}}
  },
 };
 const sb={
  auth:client.auth,
  from:table=>query(table,answer),
  rpc:async(name,args)=>{
   if(name!=='save_editor_draft')return {data:null,error:{message:'여기서는 쓸 수 없는 기능이에요.'}};
   try{await api(client,'/api/local-videos/draft',{key,draft:args.p_draft,based_on:basedOn});return {data:null,error:null}}
   catch(e){return {data:null,error:{message:e.message}}}
  },
  storage:{from:()=>({
   createSignedUrl:async k=>({data:{signedUrl:k},error:null}),
   createSignedUrls:async keys=>({data:keys.map(k=>({path:k,signedUrl:k,error:null})),error:null}),
  })},
  // 목소리 미리듣기는 VES 편집실과 같은 엣지 함수(tts-preview)를 그대로 쓴다 — 영상 데이터는 보내지 않는다.
  functions:{invoke:(name,opts)=>name==='tts-preview'?client.functions.invoke(name,opts)
   :Promise.resolve({data:null,error:{message:'여기서는 쓸 수 없는 기능이에요.'}})},
 };
 return {sb,local};
}
