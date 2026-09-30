import {loadCatalog} from './work-catalog.js';
// 작품 로고 읽기·쓰기 — Supabase 로 바로(오케스트레이터 0112·0115·0116). 예전 로컬 서버 work_assets_api 와 같은 모양·규칙.
// 읽기: 로고 표(work_asset_variants/versions) · 채널 선택 · 플랫폼 로고 출처 + 저장소 서명 URL
// 쓰기: 파일은 저장소 최종 자리(works/<id>/<sha>.<ext>)에 바로 올리고 register_work_asset RPC 로 적는다. 나머지는 RPC.
const BUCKET='ves-work-assets',ROLES=['work_logo','platform_logo'],LIMIT=6*1024*1024,MAX_PIXELS=16e6;
export const HOLDER_PREFIX='권리사:';
const holderKey=h=>HOLDER_PREFIX+String(h).trim();

async function rows(q){const {data,error}=await q;if(error)throw Error(error.message);return data||[];}
async function rpc(client,fn,args){const {data,error}=await client.rpc(fn,args);if(error)throw Error(error.message);return data;}

async function workOf(client,workId){
 const {works}=await loadCatalog(client);
 const w=works.find(r=>String(r.id)===String(workId));
 if(!w)throw Error('작품을 찾지 못했어요.');
 if(works.filter(r=>r.title===w.title).length!==1)throw Error('같은 제목의 작품이 여러 개입니다. 작품 연결을 먼저 확인해 주세요.');
 return {w,works};
}

// 열쇠 여러 개(작품 제목 · 권리사 열쇠)의 이름 붙은 로고 — 열쇠 → 용도 → [로고]
async function logosFor(client,keys,chans=[],picks=[]){
 const [variants,versions]=await Promise.all([
  rows(client.from('work_asset_variants').select('work_title,role,label,is_default,created_at').in('work_title',keys).is('retired_at',null).order('is_default',{ascending:false}).order('created_at').order('label')),
  rows(client.from('work_asset_versions').select('id,work_title,role,label,object_key,filename,mime,bytes,width,height,render_width,render_height,created_at').in('work_title',keys).order('created_at',{ascending:false}))]);
 const cur=new Map();for(const v of versions){const k=v.work_title+'|'+v.role+'|'+v.label;if(!cur.has(k))cur.set(k,v);}
 const urls=new Map(),paths=[...new Set([...cur.values()].map(v=>v.object_key))];
 if(paths.length){const {data}=await client.storage.from(BUCKET).createSignedUrls(paths,900);for(const r of data||[])if(r.signedUrl)urls.set(r.path,r.signedUrl);}
 const chosen=new Map(picks.map(p=>[p.token_slug+'|'+p.role,p.label]));
 const out={};for(const k of keys)out[k]=Object.fromEntries(ROLES.map(r=>[r,[]]));
 for(const v of variants){
  const row=cur.get(v.work_title+'|'+v.role+'|'+v.label);if(!row)continue;
  const users=chans.filter(c=>chosen.get(c.token_slug+'|'+v.role)===v.label||(v.is_default&&!chosen.has(c.token_slug+'|'+v.role))).map(c=>c.name);
  out[v.work_title][v.role].push({...row,id:String(row.id),label:v.label,is_default:v.is_default,channels:users,preview_url:urls.get(row.object_key)||''});
 }
 return out;
}

// work_assets_api.list_assets 와 같은 모양: {logos:{work_logo,platform_logo}, channels, platform:{mode,auto_holder,holder,holder_works,holders,holder_logos}}
export async function loadWorkAssets(client,workId){
 const {w,works}=await workOf(client,workId);const title=w.title;
 const [mirror,overrides,picks,src]=await Promise.all([
  rows(client.from('channels_mirror').select('token_slug,name,works').order('name')),
  rows(client.from('channel_works_overrides').select('token_slug,works')),
  rows(client.from('channel_work_assets').select('token_slug,role,label').eq('work_title',title)),
  rows(client.from('work_platform_logo_source').select('mode,holder').eq('work_title',title))]);
 const ovr=new Map(overrides.map(o=>[o.token_slug,o.works]));
 const chans=mirror.filter(c=>(ovr.get(c.token_slug)||c.works||[]).includes(title));
 const counts=new Map();for(const r of works){const c=(r.company||'').trim();if(c)counts.set(c,(counts.get(c)||0)+1);}
 const mode=src[0]?.mode||'holder',auto=(w.company||'').trim()||null,holder=mode==='other'?src[0].holder:auto;
 const keys=[title,...(holder?[holderKey(holder)]:[])];
 const got=await logosFor(client,keys,chans,picks);
 return {logos:got[title],channels:chans.map(c=>({slug:c.token_slug,name:c.name})),
  platform:{mode,auto_holder:auto,holder,holder_works:holder?counts.get(holder)||0:0,holders:[...counts.keys()].sort((a,b)=>a.localeCompare(b,'ko')),
   holder_logos:holder?got[holderKey(holder)].platform_logo:[]},pipeline_ready:true};
}

// 파일 확인(형식은 내용으로 · 6MB · 1,600만 화소) → sha256 → 저장소 최종 자리 → register_work_asset
async function sniff(file){
 const b=new Uint8Array(await file.slice(0,16).arrayBuffer());
 if(b[0]===0x89&&b[1]===0x50&&b[2]===0x4e&&b[3]===0x47)return ['image/png','png'];
 if(b[0]===0xff&&b[1]===0xd8&&b[2]===0xff)return ['image/jpeg','jpg'];
 if(String.fromCharCode(...b.slice(0,4))==='RIFF'&&String.fromCharCode(...b.slice(8,12))==='WEBP')return ['image/webp','webp'];
 return null;
}
export async function uploadWorkAsset(client,workId,{role,target='work',file,renderWidth,renderHeight,label=null,makeDefault=false}){
 if(!file||file.size<1||file.size>LIMIT)throw Error('6MB 이하 파일을 선택해 주세요.');
 const fmt=await sniff(file);if(!fmt)throw Error('정적인 PNG·JPG·WebP 이미지(최대 1,600만 화소)를 선택해 주세요.');
 let bmp;try{bmp=await createImageBitmap(file);}catch{throw Error('이미지를 읽지 못했어요. 다른 파일을 골라 주세요.');}
 const width=bmp.width,height=bmp.height;bmp.close?.();
 if(width*height>MAX_PIXELS)throw Error('정적인 PNG·JPG·WebP 이미지(최대 1,600만 화소)를 선택해 주세요.');
 const sha=[...new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer()))].map(x=>x.toString(16).padStart(2,'0')).join('');
 const key=`works/${crypto.randomUUID()}/${sha}.${fmt[1]}`;
 const {error}=await client.storage.from(BUCKET).upload(key,file,{contentType:fmt[0],upsert:false,cacheControl:'3600'});
 if(error)throw Error('파일을 올리지 못했어요. '+error.message);
 return rpc(client,'register_work_asset',{p_work_id:String(workId),p_role:role,p_target:target,p_object_key:key,p_sha256:sha,p_filename:file.name||'logo',
  p_width:width,p_height:height,p_render_width:+renderWidth,p_render_height:+renderHeight,p_label:label||null,p_default:!!makeDefault});
}

// 로고 기본·이름·빼기·되돌리기 — 돌려주는 값 {ok, picks}(빼기는 풀린 채널 선택)
export const logoVariant=(client,workId,{role,target='work',label,action,new_label=null,picks=null})=>
 rpc(client,'work_logo_variant',{p_work_id:String(workId),p_role:role,p_target:target,p_label:label,p_action:action,p_new_label:new_label,p_picks:picks});

export const setPlatformSource=(client,workId,{mode,holder=null})=>rpc(client,'set_platform_logo_source',{p_work_id:String(workId),p_mode:mode,p_holder:holder});
