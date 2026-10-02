// 맥미니 영상(0111 tikitaka_videos) 편집실 — 로컬 서버 없이 브라우저가 Supabase 에서 바로 연다(웹 주소에서도 된다).
// 예전: 작업 컴퓨터가 번들을 내려받아(remote_videos_api.sync) local_videos_api.editor_payload 로 만들고 patch_payload 로 고쳤다.
// 지금: 같은 번들 파일(ves-outputs/tikitaka/<작업지시>/<편>/…)을 서명 URL 로 읽어 같은 모양의 payload 를 만든다.
// ⚠ local_videos_api.editor_payload 와 쌍둥이 — 한쪽 모양을 바꾸면 다른 쪽도 맞춘다(작업 컴퓨터 영상은 아직 그쪽이 만든다).
// 쓰기: 초안은 save_tikitaka_draft, 제출은 request_tikitaka_edit(0113) → 그 편을 만든 맥미니가 다시 렌더한다.
import {HOLDER_PREFIX} from './work-assets-data.js?v=1';
const CLIP_FPS=30,LABEL_SIZE=56,SPRITE_INTERVAL=2,SPRITE_GRID=10,URL_TTL=12*3600;   // 편집이 길어도 미디어 주소가 끊기지 않게 12시간
const TTS_NAME=/^tts\/[0-9a-f]{8,64}\.mp3$/;
const EMPH_COLORS={white:'#FFFFFF',red:'#FF5540',blue:'#7ED0FF',orange:'#FFB637'},EMPH_LEVELS={1:[1.18,'white'],2:[1.35,'red']};

export const isRemoteKey=key=>/^remote-[0-9a-f-]{36}\/v\d{1,2}(?:_[\w-]+)?$/.test(String(key||''));
export function parseKey(key){const m=String(key||'').match(/^remote-([0-9a-f-]{36})\/(.+)$/);if(!m)throw Error('영상 식별자가 올바르지 않습니다.');return {wo:m[1],suffix:m[2]};}

async function rows(q){const {data,error}=await q;if(error)throw Error(error.message);return data||[];}
async function signMany(client,keys){
 const out=new Map(),list=[...new Set(keys.filter(Boolean))];if(!list.length)return out;
 const {data,error}=await client.storage.from('ves-outputs').createSignedUrls(list,URL_TTL);if(error)throw Error(error.message);
 for(const r of data||[])if(r.signedUrl)out.set(r.path,r.signedUrl);return out;
}
async function json(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw Error('영상 기록을 받지 못했어요.');return r.json();}

// ── local_videos_api 와 같은 작은 변환들 ─────────────────────────────
function labelsAsTexts(labels){
 const out=[];
 for(const lb of labels?.labels||[]){
  if(lb.source_time_sec==null)continue;
  const t={text:lb.text,source_time_sec:lb.source_time_sec,duration_sec:lb.duration_sec||Math.round((lb.end_sec-lb.start_sec)*1000)/1000,
   x:lb.x??.5,y:lb.y??.35,rotate:lb.rotate??0,color:lb.color||'#FFE94A',size:lb.size||LABEL_SIZE,origin:'ai',label_id:lb.id};
  for(const k of ['fx','kind','person'])if(lb[k]!=null)t[k]=lb[k];
  out.push(t);
 }
 return out;
}
const displayDesign=d=>Object.fromEntries(Object.entries(d||{}).map(([k,v])=>[k,typeof v==='string'&&v.startsWith('/')?v.split('/').pop():v]));
export function fillDraftVoices(draft,video){
 const render=video?.provenance?.render||{};
 if(!draft||typeof draft!=='object'||!render.voice||!draft.tts)return draft;
 return {...draft,tts:draft.tts.map(t=>t&&typeof t==='object'&&!t.voice?{...t,voice:render.voice,speed:render.speed||t.speed||'normal'}:t)};
}
function emphLook(e){
 const lv=EMPH_LEVELS[e.semantic_level]?e.semantic_level:EMPH_LEVELS[e.level]?e.level:null;
 const zoom=typeof e.zoom==='boolean'?e.zoom:lv===2;
 if(lv)return {level:lv,zoom};
 const c=String(e.color||''),name=EMPH_COLORS[c]?c:(Object.keys(EMPH_COLORS).find(k=>EMPH_COLORS[k]===c.toUpperCase())||'red');
 let scale=Math.round((Number(e.scale)||1.23)*100)/100;
 for(const [l,[sc,cn]] of Object.entries(EMPH_LEVELS))if(Math.abs(scale-sc)<0.005&&name===cn)return {level:+l,zoom};
 return {color:name,scale,zoom};
}
function emphIndex(e,segs){
 const idx=Number.isInteger(+e.index)&&e.index!==null&&e.index!==''?+e.index:null,text=String(e.text||'').trim();
 if(idx!=null&&idx>=0&&idx<segs.length&&(!text||String(segs[idx].text||'').trim()===text))return idx;
 const same=segs.map((s,i)=>[s,i]).filter(([s])=>text&&String(s.text||'').trim()===text).map(([,i])=>i);
 if(same.length)return e.start_sec!=null?same.reduce((a,b)=>Math.abs((segs[b].start_sec||0)-e.start_sec)<Math.abs((segs[a].start_sec||0)-e.start_sec)?b:a):same[0];
 return idx!=null&&idx>=0&&idx<segs.length?idx:null;
}
function loadFx(fx,segs){
 const emph={},zooms={};
 for(const e of fx?.emphasis||[]){if(!e||typeof e!=='object')continue;const i=emphIndex(e,segs);if(i!=null)emph[i]=emphLook(e);}
 segs.forEach((sg,i)=>{if(EMPH_LEVELS[sg.emphasis_level]&&!(i in emph))emph[i]={level:sg.emphasis_level,zoom:sg.emphasis_level===2};});
 for(const z of fx?.zooms||[]){
  if(!z||!Number.isInteger(z.clip))continue;
  const stages=(z.stages||[{from_sec:z.from_sec||0,factor:z.factor,anchor:z.anchor||'center'}]).filter(x=>x&&x.factor!=null)
   .map(x=>({from_sec:Math.round((+x.from_sec||0)*1000)/1000,factor:Math.round((+x.factor||1)*1000)/1000,anchor:x.anchor||'center'}));
  if(stages.length)zooms[z.clip]={stages};
 }
 return {emph,zooms};
}
function attachPhrases(tts,segs){
 if(!Array.isArray(segs))return;
 for(const t of tts){const a=t.edited_start,z=t.edited_end;if(a==null||z==null)continue;
  const got=segs.filter(c=>c&&c.start_sec!=null&&a-1e-3<=c.start_sec&&c.start_sec<z+1e-3).map(c=>({text:String(c.text||''),start:Math.round((c.start_sec-a)*1000)/1000,end:Math.round((c.end_sec-a)*1000)/1000}));
  if(got.length)t.phrases=got;}
}
// 다시 렌더 기록 → 사람이 읽는 문장(local_videos_api.apply_notes 와 같은 규칙)
const josa=(w,pair)=>{const ch=[...String(w||'')].reverse().find(c=>/[가-힣0-9A-Za-z]/.test(c))||'';const has=ch>='가'&&ch<='힣'&&(ch.charCodeAt(0)-0xAC00)%28!==0;return has?pair[0]:pair[1];};
const quote=(t,n=24)=>{const s=String(t||'').split(/\s+/).join(' ').trim();return '「'+(s.length>n?s.slice(0,n)+'…':s)+'」';};
export function applyNotes(log,logText=''){
 const names={tts:'내레이션',texts:'보조 자막',subtitles:'자막',emphasis:'강조'},why={'새 구간에 그 원본 장면이 없음':'새 구간에 그 장면이 없어요.','영상 길이 밖':'영상 끝을 넘었어요.','그 글자가 든 자막 줄이 없어짐':'그 글자가 든 자막 줄이 바뀌었어요.'};
 const out=[];let zooms=0;
 for(const it of log||[]){
  if(!it||typeof it!=='object')continue;
  if(it.kind==='dropped'){
   if(it.what==='zoom'){zooms++;continue;}
   const name=names[it.what]||'연출',q=it.text?quote(it.text):'';
   out.push({level:'warn',text:`${name} ${q}${josa(it.text||name,'이가')} 빠졌어요. ${why[it.reason]??String(it.reason||'')}`.replace(/  /g,' ')});
  }else if(it.kind==='audio'&&Number.isInteger(it.clip)){
   const r=String(it.result||'');
   if(r.includes('무음 유지'))out.push({level:'warn',text:`${it.clip+1}번 구간은 배속이나 멈춤이 걸려 있어 원음 없이 나가요.`});
   else if(r.includes('원음 켬'))out.push({level:'info',text:`${it.clip+1}번 구간 원음을 켰어요.`});
  }
 }
 if(zooms)out.push({level:'warn',text:`줌 ${zooms}곳이 빠졌어요. 구간이 바뀌었어요.`});
 for(const m of String(logText||'').matchAll(/⚠ (\d+(?:\.\d+)?)~(\d+(?:\.\d+)?)s 인물 얼굴이 (왼쪽|오른쪽) 잘림 띠에 걸림/g)){
  const at=m[1]===m[2]?`${+m[1]}초`:`${+m[1]}~${+m[2]}초`;out.push({level:'warn',text:`${at} 인물 얼굴이 ${m[3]} 가장자리에 걸려 잘릴 수 있어요.`});
 }
 return out;
}

// 가장 최근 다시 렌더(tikitaka_apply_edit 잡) — remote_videos_api.apply_state 와 같은 모양
export async function applyState(client,videoId){
 const [j]=await rows(client.from('job_queue').select('id,status,error,result,created_at,started_at,finished_at,updated_at,node_id,required_caps').eq('kind','tikitaka_apply_edit').eq('params->>video_id',videoId).order('created_at',{ascending:false}).limit(1));
 if(!j)return null;
 const state={pending:'queued',running:'running',succeeded:'done'}[j.status]||'failed';
 const out={edit_id:j.id,state,started_at:j.started_at||j.created_at,finished_at:j.finished_at||(state==='failed'?j.updated_at:null),error:state==='failed'?String(j.error||'').slice(-300):null,
  node:j.node_id||(j.required_caps||[]).find(c=>String(c).startsWith('node:'))?.slice(5)||null};   // 실패하면 node_id 가 비어 required_caps 로
 if(state==='done'){const r=j.result||{};out.notes=applyNotes(r.log,r.log_text||'');if(r.duration_sec!=null)out.duration_sec=r.duration_sec;}
 return out;
}

async function videoRow(client,wo,suffix){
 const [r]=await rows(client.from('tikitaka_videos').select('id,node_id,render_fingerprint,files,work_title,episode,title,audio_gaps').eq('work_order_id',wo).eq('suffix',suffix).limit(1));
 if(!r)throw Error('맥미니 영상을 찾을 수 없습니다.');return r;
}

// 편집실 payload — local_videos_api.editor_payload + remote_videos_api.patch_payload 와 같은 결과
export async function remoteEditorPayload(client,key){
 const {wo,suffix}=parseKey(key),r=await videoRow(client,wo,suffix),files=r.files||{};
 const need=['video.json','edit_plan.json','subtitle_segments.json','checkpoint_resources.json','labels.json','fx.json','framing.json','tts_caption_segments.json','sfx.json'];
 const cues=[],media=['shorts.mp4','editor_scan.mp4',...Object.keys(files).filter(k=>TTS_NAME.test(k)||/^sprites\/sprite_\d{3}\.jpg$/.test(k)||/^assets\/logo_(work|platform)\./.test(k))];
 const url=await signMany(client,[...need,...media].map(n=>files[n]?.key));
 const at=n=>files[n]?url.get(files[n].key):null;
 const [video,plan,segs,res,labels,fx,framing,caps,sfxDoc]=await Promise.all(need.map(n=>at(n)?json(at(n)).catch(()=>null):Promise.resolve(null)));
 if(!video||!plan)throw Error('서버의 영상 묶음이 비어 있어요.');
 const [src]=await rows(client.from('work_orders').select('source_sha256').eq('id',wo).limit(1));
 const [source]=src?.source_sha256?await rows(client.from('sources').select('duration_sec').eq('sha256',src.source_sha256).limit(1)):[];
 const duration=source?.duration_sec!=null?Number(source.duration_sec):null;
 const segments=Array.isArray(segs)?segs:[];
 const clips=(plan.timeline||[]).map((c,i)=>{const clip={idx:i,role:c.role||'build',start_sec:+c.clip_start_sec,end_sec:+c.clip_end_sec};
  if(Number(c.playback_speed||1)!==1)clip.playback_speed=+c.playback_speed;if(Number(c.hold_sec||0))clip.hold_sec=+c.hold_sec;if(c.cover)clip.cover=true;return clip;});
 if(!clips.length)throw Error('편집 계획에 구간이 없습니다.');
 const subs=segments.map(s=>({edited_start:s.start_sec,edited_end:s.end_sec,text:s.text||'',source_sec:s.source_time_sec}));
 const {emph,zooms}=loadFx(fx,segments);
 for(const [i,look] of Object.entries(emph))if(subs[i])subs[i].emph=look;
 for(const [i,z] of Object.entries(zooms))if(clips[i])clips[i].zoom=z;
 const render=video.provenance?.render||{},tts=[];
 (res?.tts_cue_files||[]).forEach((f,i)=>{const cue=f.cue||{};if(cue.source_time_sec==null)return;
  const item={idx:i,source_sec:cue.source_time_sec,duration_sec:cue.duration_sec||3,text:cue.text||'',edited_start:cue.start_sec,edited_end:cue.end_sec,
   voice:cue.voice||render.voice||'',speed:cue.speed||render.speed||'normal'};
  if(TTS_NAME.test(f.path||'')&&at(f.path))item.key=at(f.path);tts.push(item);});
 tts.sort((a,b)=>a.source_sec-b.source_sec);attachPhrases(tts,caps);
 const layout=plan.layout||{};
 const sheets=Object.keys(files).filter(k=>/^sprites\/sprite_\d{3}\.jpg$/.test(k)).sort().map(at).filter(Boolean);
 const scan=at('editor_scan.mp4');
 const sprites=sheets.length?{interval:SPRITE_INTERVAL,grid:SPRITE_GRID,count:duration?Math.floor(duration/SPRITE_INTERVAL)+1:sheets.length*SPRITE_GRID*SPRITE_GRID,assets:{media:{scan},global:sheets}}:{assets:{media:{scan}}};
 // 초안 — 사람별로 데이터베이스(0113). 제출했다 실패했으면 그때 낸 초안으로 다시 연다
 const {data:{user}}=await client.auth.getUser();
 const [d]=user?await rows(client.from('tikitaka_edit_drafts').select('based_on,draft,saved_at,submitted_job').eq('video_id',r.id).eq('user_id',user.id).limit(1)):[];
 const apply=await applyState(client,r.id);
 let draft=null,draftAt=null,note='',restored=null;
 if(d&&d.based_on===r.render_fingerprint){
  if(!d.submitted_job){draft=fillDraftVoices(d.draft,video);draftAt=d.saved_at;}
  else if(apply?.state==='failed'&&apply.edit_id===d.submitted_job){draft=fillDraftVoices(d.draft,video);draftAt=d.saved_at;restored=apply.edit_id;}
 }else if(d)note='이전 판에서 저장한 내용은 불러오지 않았어요.';
 const logos={};for(const k of ['work','platform']){const f=Object.keys(files).find(n=>n.startsWith(`assets/logo_${k}.`));if(f&&at(f))logos[k]=at(f);}
 const speed=(plan.timeline||[]).filter(c=>Number(c.playback_speed||1)!==1||c.hold_sec);
 const band=framing?.band;
 return {row:{run_id:key,status:'ready',duration_sec:duration,work_order_id:null,draft,draft_at:draftAt,audio_gaps:Array.isArray(r.audio_gaps)?r.audio_gaps:[],sfx:Array.isArray(sfxDoc?.sfx)?sfxDoc.sfx:[],
   timeline:{schema:'editor_timeline/v1',clip_fps:CLIP_FPS,engine_rules:false,clips,subtitles:subs,tts,top_title:layout.top_title||'',title_segments:layout.title_segments||[],bottom_label:layout.bottom_label||''},sprites},
  prevOv:{texts:labelsAsTexts(labels)},
  meta:{key,title:video.title,work:video.work,episode:video.episode,status:video.status,render_fingerprint:r.render_fingerprint,
   labels:(labels?.labels||[]).length,dropped_labels:labels?.dropped||[],final_url:at('shorts.mp4'),draft_note:note,
   timing_note:speed.length?`배속이나 멈춤이 걸린 구간 ${speed.length}개는 완성본과 같은 속도로 재생해요.`:'',
   logos,apply,restored_from:restored,can_check:false,fx_edit:true,frame_edit:true,phrase_edit:true,placement:true,sfx_edit:true,   // 맥미니가 ai-video ffe1002f·ae8cc2f7·f39398f7 이후라 화면 위치·구절 줄바꿈·같은 장면 여러 구간 배치를 받는다(remote_videos_api 와 같이)
   framing:framing?.schema==='tikitaka_framing/v1'&&Array.isArray(framing.clips)?framing:null,render_layout:typeof band?.y==='number'?{band_y:Math.round(band.y)}:{},
   render_design:displayDesign(render.design||{}),remote_node:r.node_id,serverless:true,
   video_id:r.id,files_sha:{work:files[Object.keys(files).find(n=>n.startsWith('assets/logo_work.'))]?.sha256||null,platform:files[Object.keys(files).find(n=>n.startsWith('assets/logo_platform.'))]?.sha256||null}}};
}

// 로고 탭 — editor_logos.list_for 와 같은 모양. path 는 이 컴퓨터 파일이 아니라 'asset:<id>'(미리보기 주소 찾기용 · 렌더는 에셋 id 로)
export async function remoteLogos(client,payload,role){
 const title=String(payload.meta.work||'').trim(),out={work:null,work_title:title,can_upload:['operator','admin'].includes(role),work_logos:[],platform_logos:[]};
 if(!title)return out;
 const works=await rows(client.from('laeebly_works').select('id,title,company').eq('title',title).limit(2));
 if(works.length!==1)return out;
 const w=works[0];out.work={id:w.id,title:w.title};
 const [src]=await rows(client.from('work_platform_logo_source').select('mode,holder').eq('work_title',title).limit(1));
 const mode=src?.mode||'holder',holder=mode==='other'?src.holder:(w.company||'').trim()||null;
 const pkey=['holder','other'].includes(mode)&&holder?HOLDER_PREFIX+holder:mode==='work'?title:null;
 const keys=[title,...(pkey&&pkey!==title?[pkey]:[])];
 const [variants,versions]=await Promise.all([
  rows(client.from('work_asset_variants').select('work_title,role,label,is_default,created_at').in('work_title',keys).is('retired_at',null).order('is_default',{ascending:false}).order('created_at')),
  rows(client.from('work_asset_versions').select('id,work_title,role,label,object_key,sha256,filename,width,height,render_width,render_height,created_at').in('work_title',keys).order('created_at',{ascending:false}))]);
 const cur=new Map();for(const v of versions){const k=v.work_title+'|'+v.role+'|'+v.label;if(!cur.has(k))cur.set(k,v);}
 const picked=variants.filter(v=>(v.role==='work_logo'&&v.work_title===title)||(v.role==='platform_logo'&&v.work_title===pkey)).map(v=>[v,cur.get(v.work_title+'|'+v.role+'|'+v.label)]).filter(([,r])=>r);
 const {data:signed}=picked.length?await client.storage.from('ves-work-assets').createSignedUrls(picked.map(([,r])=>r.object_key),URL_TTL):{data:[]};
 const urlOf=new Map((signed||[]).map(s=>[s.path,s.signedUrl]));
 out.platform_source={mode,holder};
 for(const [v,r] of picked){
  const role=v.role==='work_logo'?'work':'platform';
  out[v.role==='work_logo'?'work_logos':'platform_logos'].push({id:r.id,label:v.label,is_default:v.is_default,filename:r.filename,path:'asset:'+r.id,url:urlOf.get(r.object_key)||'',
   width:r.width,height:r.height,box:[r.render_width,r.render_height],same_as_render:!!(payload.meta.files_sha?.[role]&&payload.meta.files_sha[role]===r.sha256)});
 }
 return out;
}

// 쓰기 — 초안 저장 · 제출(그 맥미니가 다시 렌더) · 지금 판 확인
export async function remoteSaveDraft(client,payload,draft){
 const {error}=await client.rpc('save_tikitaka_draft',{p_video:payload.meta.video_id,p_based_on:payload.meta.render_fingerprint,p_draft:draft});
 if(error)throw Error(error.message);
}
export async function remoteSubmit(client,payload,overrides,note){
 const {data,error}=await client.rpc('request_tikitaka_edit',{p_video:payload.meta.video_id,p_overrides:overrides,p_based_on:payload.meta.render_fingerprint,p_note:note||null});
 if(error)throw Error(error.message);
 return {edit_id:data?.edit_id,rendering:true,node:data?.node};
}
export async function remoteCheck(client,payload){
 const {wo,suffix}=parseKey(payload.meta.key),r=await videoRow(client,wo,suffix);
 if(r.render_fingerprint!==payload.meta.render_fingerprint)return {canOpen:false,label:'편집실을 연 뒤에 영상이 새로 만들어졌어요. 다시 열어 주세요.'};
 const st=await applyState(client,r.id);
 if(['queued','running'].includes(st?.state))return {canOpen:false,label:'이 영상을 다시 렌더하는 중이에요. 끝나면 새 판에서 고쳐 주세요.'};
 return {canOpen:true};
}
