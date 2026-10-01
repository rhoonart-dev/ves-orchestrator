// 소스 창고 새 구조(0121) — 회차 → 원본(합본 · 파일) → 작업(#번호). 화면 없이 셈만 한다(테스트 대상).
// 작업 번호는 작품 + 회차 안에서 1, 2, 3… (tikitaka_tasks.work_no). 합본은 원본이라 번호가 없다.

export const UNIT_DEFAULT='화';
export const epText=(key,unit=UNIT_DEFAULT)=>key==null||key===''?'회차 모름':`${key}${unit}`;
const first=key=>parseInt(String(key).split('-')[0],10);
const last=key=>{const p=String(key).split('-');return parseInt(p[p.length-1],10);};
export const keyOrder=(a,b)=>(first(b)-first(a))||(last(b)-last(a));   // 최신 회차가 위

// 회차 묶음 — 2회씩이면 1-2 · 3-4 · 5-6 …(홀수에서 시작), 1회씩이면 그 회차
export function groupKey(ep,group=1){
 const n=parseInt(ep,10);if(!Number.isFinite(n))return null;
 if(group!==2)return String(n);
 const a=n%2?n:n-1;return `${a}-${a+1}`;
}
// 여러 회차를 덮는 표기('5-6')가 어느 묶음에 드는지 — 선공개는 그 묶음, 몰아보기는 그다음 묶음(앞 회차 맥락)
export function clipGroup(c,group=1){
 const lab=c.episode_label;
 if(c.clip_kind==='recap'){const end=lab?last(lab):parseInt(c.episode,10);return Number.isFinite(end)?groupKey(end+1,group):null;}
 if(lab&&group===2){const a=first(lab);return groupKey(a,2);}
 if(lab)return String(first(lab));
 return groupKey(c.episode,group);
}

// 채널 순위 · 이름 · 아이콘
export function sourceMeta(yt,channels){
 const byId=new Map((channels||[]).map(c=>[c.id,c]));
 return new Map((yt||[]).map(s=>{const ch=byId.get(s.channel_id);return [s.id,{rank:s.rank,name:ch?.name?.replace(/\s*:.*$/,'')||s.label||'유튜브',avatar:ch?.avatar_url||'',id:s.id}];}));
}

// 작품 하나 → 회차 묶음 목록
export function buildRoom(d){
 const card=d.card||{},group=Number(card.compile_group)||1,unit=card.episode_unit||UNIT_DEFAULT;
 const meta=sourceMeta(d.yt,d.channels);
 const youtube=(d.yt||[]).length>0||(d.sources||[]).some(s=>s.yt_source_id);
 const groups=new Map();
 const g=key=>{const k=key==null?'':key;if(!groups.has(k))groups.set(k,{key:k,label:epText(key,unit),clips:[],files:[],comps:[],tasks:[]});return groups.get(k);};
 const srcById=new Map((d.sources||[]).map(s=>[s.id,s]));
 for(const s of d.sources||[]){
  if(s.clip_kind==='compilation'||s.is_active===false)continue;
  if(s.yt_source_id||s.clip_kind!=='clip'||(youtube&&s.origin==='youtube')){
   const m=meta.get(s.yt_source_id);
   g(clipGroup(s,group)).clips.push({...s,rank:m?.rank??99,channel:m?.name||'유튜브',avatar:m?.avatar||''});
  }else g(s.episode!=null?String(s.episode):null).files.push(s);
 }
 for(const c of d.comps||[])g(c.episode_key).comps.push({...c,source:srcById.get(c.source_id)||null});
 for(const t of d.tasks||[])g(t.episode_key).tasks.push(t);
 const list=[...groups.values()];
 for(const x of list){
  x.clips.sort((a,b)=>kindOrder(a)-kindOrder(b)||(a.episode??1e9)-(b.episode??1e9)||String(a.published_ts||'').localeCompare(String(b.published_ts||''))||a.rank-b.rank);
  x.comps.sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)));
  x.lastClip=x.clips.map(c=>c.published_ts).filter(Boolean).sort().pop()||null;
  x.byChannel=[...x.clips.filter(c=>c.clip_kind!=='extra').reduce((m,c)=>{const k=c.channel;const v=m.get(k)||{name:k,avatar:c.avatar,rank:c.rank,n:0};v.n++;m.set(k,v);return m;},new Map()).values()].sort((a,b)=>a.rank-b.rank);
 }
 list.sort((a,b)=>a.key===''?1:b.key===''?-1:keyOrder(a.key,b.key));
 return {youtube,group,unit,groups:list,card};
}
const kindOrder=c=>({recap:0,prerelease:1,clip:2,extra:3})[c.clip_kind]??2;

// 작업이 달린 원본 — 합본이면 그 합본의 원본, 파일이면 그 파일
export const tasksOf=(grp,sourceId)=>grp.tasks.filter(t=>t.source_id===sourceId&&t.status!=='deleted').sort((a,b)=>b.work_no-a.work_no);
export const nextNo=grp=>Math.max(0,...grp.tasks.map(t=>t.work_no))+1;

// 합본 기본 구성 — 몰아보기(넣을 때, 가장 최근 회차까지 덮는 것 하나) → 선공개 → 본편 클립(회차 → 올라온 순).
// 아래 순위 채널 클립은 겹침 결과대로: 다 겹치면 빼고, 일부면 남는 구간마다 한 줄.
export function defaultItems(grp,{recap=true}={}){
 const items=[],skipped=[];
 const recaps=grp.clips.filter(c=>c.clip_kind==='recap'&&c.source_url);
 if(recap&&recaps.length){
  const best=recaps.slice().sort((a,b)=>(first(b.episode_label||b.episode)-first(a.episode_label||a.episode))||(a.rank-b.rank)||String(b.published_ts||'').localeCompare(String(a.published_ts||'')))[0];
  items.push(item(best));
 }
 for(const c of grp.clips.filter(c=>c.clip_kind==='prerelease'&&c.source_url))pushClip(c);
 for(const c of grp.clips.filter(c=>c.clip_kind==='clip'&&c.source_url&&c.episode!=null))pushClip(c);
 return {items,skipped};
 function pushClip(c){
  const o=c.overlap;
  if(!o||c.rank<=1||!(o.covered||[]).length){items.push(item(c));return;}
  if(o.skip||!(o.keep||[]).length){skipped.push({...item(c),reason:o.reason||'겹쳐서 빼요'});return;}
  for(const [s,e] of o.keep)items.push(item(c,s,e,o));
 }
}
function item(c,start=null,end=null,o=null){
 const dur=Number(c.duration_sec)||null;
 return {source_id:c.id,title:c.title||'',kind:c.clip_kind,episode:c.episode,label:c.episode_label,channel:c.channel,avatar:c.avatar,rank:c.rank,
  duration:dur,start,end,use:start!=null?Math.max(0,(end??dur??0)-start):dur,overlap:o,url:c.source_url};
}
export const itemsSeconds=items=>items.reduce((s,i)=>s+(Number(i.use)||0),0);
export function compileName(items,group){
 const main=items.some(i=>i.kind==='clip');
 return main?(group===2?'본편 합본':'회차 합본'):items.some(i=>i.kind==='prerelease')?'선공개 합본':'합본';
}

// 겹침 한 줄 설명(클립 줄 · 합본 창)
export function overlapNote(c,fmt){
 const o=c.overlap;if(!o||!(o.covered||[]).length)return '';
 const dur=Number(o.duration||c.duration_sec)||0,keep=(o.keep||[]).reduce((s,[a,b])=>s+(b-a),0);
 if(o.skip)return keep===0&&dur-(o.covered_sec||0)<1?`${fmt(dur)} 모두 위 채널과 겹쳐서 빼요`:`${fmt(dur)} 중 ${fmt(o.covered_sec||0)}가 겹치고 남는 부분이 짧아서 빼요`;
 return `${fmt(dur)} 중 ${fmt(o.covered_sec||0)}가 위 채널과 겹쳐서 ${fmt(keep)}만 써요`;
}

// 작업 상태 한 줄
export function taskState(t,stat){
 if(t.status==='draft')return {kind:'draft',text:'시작 전'};
 const s=stat||{};
 if(s.failed)return {kind:'failed',text:'만들지 못했어요'};
 if(!s.videos)return {kind:'busy',text:'만들고 있어요'};
 return {kind:'done',text:`${s.videos}편 중 ${s.published||0}편 발행`};
}

// 클립 제목에서 작품명 머리말을 덜어 낸다 — '[로또 1등도 출근합니다] …' → '…', '[#로또1등도출근합니다 6화] …' → '[6화] …'
export function shortTitle(title,work){
 const t=String(title||''),w=String(work||'').replace(/[\s#]/g,''),m=t.match(/^\s*\[([^\]]*)\]\s*/);
 if(!m||!w)return t;
 const inner=m[1],body=t.slice(m[0].length);
 if(!inner.replace(/[\s#]/g,'').startsWith(w))return t;
 let i=0,j=0;
 while(i<inner.length&&j<w.length){if(/[\s#]/.test(inner[i])){i++;continue;}if(inner[i]!==w[j])break;i++;j++;}
 const rest=inner.slice(i).trim();
 return (rest?`[${rest}] `:'')+body;
}
