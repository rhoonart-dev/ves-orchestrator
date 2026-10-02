// 편집실 제출 전 검사: 새 파이프라인(ai-video apply_edit)이 조용히 빼거나 거절하는 것을 편집하는 자리에서 먼저 보여 준다.
// ves-editor.js 가 runEngineRules 끝에 analyze() 를 불러 cur.model.checks 에 담고, 경고 목록·블록 표시·인스펙터가 그것을 읽는다
// (ves-editor.js 에서 window.__edChecks 로 부른다). 엔진 규칙(apply_edit.py):
//  · 내레이션·보조 자막은 원본 시각으로 새 구간 위에 다시 놓고, 그 시각을 담은 구간이 없으면 뺀다(editor_tts·editor_labels).
//  · 내레이션 길이는 실제 합성 길이다. 겹치거나 영상 끝을 넘으면 적용을 거절한다.
//  · 덮개 구간은 원음이 꺼져 있다. 내레이션이 없고 1배속·멈춤 없음일 때만 원음을 다시 켠다(narration_mute).
//    새 구간은 원본이 가장 많이 겹치는 이전 구간의 덮개 여부를 물려받는다(new_timeline).
// 내레이션 길이는 사람이 적지 않는다: 문구·목소리·속도가 바뀌면 엔진(apply_edit --measure)으로 실제 합성 길이를 재서 막대에 넣는다.
// 재기 전에는 글자 수 추정치에 20% 여유를 둔다(추정 1.84초 → 실제 2.2초였던 사례).
const MARGIN=1.2;
const measured=new Map();                // cueKey → 실제 합성 길이(초)
const measuredPh=new Map();              // cueKey → {list:[{text,start,end}](그 줄 음성 시작 기준 초), note} — 엔진이 잰 자막 구절
const pending=new Set(),failed=new Set();
let timer=0;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const q=(t,n=18)=>{const s=String(t||'').replace(/\s+/g,' ').trim();return '「'+(s.length>n?s.slice(0,n)+'…':s)+'」';};
// 받침 따라 이/가: 따옴표·문장부호는 건너뛰고 마지막 글자를 본다
const ig=t=>{const ch=[...String(t||'')].reverse().find(c=>/[가-힣A-Za-z0-9]/.test(c))||'';
 return ch>='가'&&ch<='힣'&&(ch.charCodeAt(0)-0xAC00)%28?'이':'가';};
const sec=x=>(Math.round(x*10)/10).toFixed(1)+'초';
const ovl=(a0,a1,b0,b1)=>Math.max(0,Math.min(a1,b1)-Math.max(a0,b0));
const placeholder=t=>/^\(.*\)$/.test(String(t.text||'').trim())||!String(t.text||'').trim();
const local=()=>window.__workspaceLocal||{};

function newPipeline(cur){return !!(cur&&cur.row&&cur.row.timeline&&cur.row.timeline.engine_rules===false);}

// 내레이션 한 줄이 완성본에서 차지할 길이: 실제 합성 길이를 알면 그것, 모르면 추정치에 여유를 더한다
export function cueLength(cur,t,H){
 const k=H.cueKey(t);
 if(measured.has(k))return {sec:measured.get(k),real:true};
 if(t.key&&!t.stale){                  // 렌더 때 만든 소리 그대로: 그때 잰 길이
  const o=(cur.row.timeline.tts||[]).find(x=>Math.abs((+x.source_sec||0)-t.src)<0.01&&String(x.text||'')===String(t.text||''));
  if(o&&+o.duration_sec>0)return {sec:+o.duration_sec,real:true};
 }
 return {sec:H.ttsEst(t)*MARGIN,real:false,pending:pending.has(k),failed:failed.has(k)};
}

// 아직 못 잰 줄을 모아 한 번에 잰다(저장 직후). 같은 문구·목소리·속도는 엔진 캐시라 다시 합성하지 않는다.
function scheduleMeasure(cur,H){
 const m=local().measure;if(!m)return;
 clearTimeout(timer);
 timer=setTimeout(async()=>{
  const todo=[],seen=new Set();
  for(const t of cur.model.tts||[]){
   const k=H.cueKey(t);
   if(placeholder(t)||measured.has(k)||pending.has(k)||failed.has(k)||seen.has(k)||cueLength(cur,t,H).real)continue;
   seen.add(k);todo.push({k,text:String(t.text).trim(),voice:t.voice||'',speed:t.speed||''});
  }
  if(!todo.length)return;
  todo.forEach(x=>pending.add(x.k));window.__edRedraw&&window.__edRedraw();
  const res=await m(todo.map(({text,voice,speed})=>({text,voice,speed})));
  todo.forEach((x,i)=>{pending.delete(x.k);const r=res&&res.ok!==false&&(res.tts||[])[i];
   if(r&&+r.duration_sec>0)measured.set(x.k,+r.duration_sec);else failed.add(x.k);
   if(r&&Array.isArray(r.phrases)&&r.phrases.length)measuredPh.set(x.k,{list:r.phrases.map(p=>({text:p.text,start:+p.start_sec,end:+p.end_sec})),note:r.phrases_note||''});});
  if(!res||res.ok===false)window.__edToast&&window.__edToast('내레이션 길이를 재지 못했어요. '+((res&&res.error)||''));
  syncDur(cur,H);
  window.__edRedraw&&window.__edRedraw();
 },500);
}
// 잰 길이를 타임라인 블록 길이로 — 새로 넣거나 고친 내레이션 블록이 실제 목소리 길이만큼 그려져, 그 길이에 맞춰 덮개 구간을 만들 수 있다.
// 편집 기록(실행 취소)에는 넣지 않는다 — 사람이 고친 게 아니라 잰 값이다. 바뀐 줄이 있으면 true
function syncDur(cur,H){
 let ch=false;
 for(const t of (cur&&cur.model&&cur.model.tts)||[]){const v=measured.get(H.cueKey(t));
  if(v>0&&Math.abs((+t.dur||0)-v)>0.01){t.dur=+v.toFixed(3);ch=true;}}
 return ch;
}

export function analyze(cur,H){
 if(!newPipeline(cur)||!cur.model)return null;
 if(syncDur(cur,H))setTimeout(()=>window.__edRedraw&&window.__edRedraw(),0);   // 전에 잰 문구로 되돌아온 줄 등 — 다음 그리기에 반영
 const m=cur.model,items=[],muted=new Map(),subWarn=new Set(),lens=new Map();
 const live=(m.final||[]).filter(c=>!c.dead);
 // 1) 구간 밖으로 밀려난 내레이션·보조 자막: 엔진은 조용히 뺀다
 (m.cues||[]).forEach(c=>{
  c.lost=!c.dropped&&!c.contained;c.ckBad=c.lost;
  if(c.dropped||c.lost)items.push({level:'bad',kind:'tts',i:c.ti,text:`내레이션 ${q(c.text)}${ig(c.text)} 빠져요. 원래 장면(${H.fmt(c.src)})이 지금 구간에 없어요.`});
 });
 (m.textCues||[]).forEach(c=>{
  c.lost=!c.dropped&&!c.contained;c.ckBad=c.lost;
  if(c.dropped||c.lost)items.push({level:'warn',kind:'txt',i:c.ti,text:`보조 자막 ${q(c.text)}${ig(c.text)} 빠져요. 원래 장면(${H.fmt(c.src)})이 지금 구간에 없어요.`});
 });
 (m.subs||[]).forEach((su,i)=>{
  if(su.del||!su.follow||su.src==null)return;
  if(!live.some(c=>c.start<=+su.src&&+su.src<c.end)){subWarn.add(i);
   items.push({level:'warn',kind:'sub',i,text:`자막 ${q(su.text)}의 원래 장면(${H.fmt(+su.src)})이 지금 구간에 없어요. 다른 장면 위에 뜨거나 빠질 수 있어요.`});}
 });
 // 2) 내레이션 길이: 막대를 읽는 길이로 맞추고, 겹침·영상 끝 넘김(엔진이 적용을 거절한다)을 본다
 (m.tts||[]).forEach((t,i)=>{
  const L=cueLength(cur,t,H);lens.set(i,L);
  const d=+L.sec.toFixed(3);if(d>0&&Math.abs(t.dur-d)>1e-3)t.dur=d;
  const c=(m.cues||[])[i];if(c)c.dur=t.dur;
 });
 const placed=(m.cues||[]).filter(c=>!c.dropped&&!c.lost).map(c=>({c,a:c.out,b:c.out+c.dur,real:lens.get(c.ti).real})).sort((x,y)=>x.a-y.a);
 const guess=r=>r?'':' 아직 길이를 재기 전이라 예상으로 본 거예요.';
 for(let k=0;k+1<placed.length;k++){
  const x=placed[k],y=placed[k+1],over=x.b-y.a;
  if(over<=1e-3)continue;
  x.c.ckBad=y.c.ckBad=true;
  items.push({level:'bad',kind:'tts',i:x.c.ti,block:true,real:x.real,
   text:`내레이션 ${q(x.c.text,14)}, ${q(y.c.text,14)} 두 줄이 ${sec(over)} 겹쳐요. 한쪽을 옮기거나 문구를 줄여 주세요.${guess(x.real)}`});
 }
 const last=placed.length&&placed.reduce((a,b)=>b.b>a.b?b:a);
 if(last&&last.b>m.total+1e-3){last.c.ckBad=true;
  items.push({level:'bad',kind:'tts',i:last.c.ti,block:true,real:last.real,
   text:`내레이션 ${q(last.c.text)}${ig(last.c.text)} 영상 끝을 ${sec(last.b-m.total)} 넘어요. 구간을 늘리거나 문구를 줄여 주세요.${guess(last.real)}`});}
 // 4) 원본 소리가 비어 있는 자리(0130 — 완성본에서 원음이 나와야 하는데 소리가 완전히 빈 곳). 렌더한 시간축을 원본 시각으로 바꿔
 //    지금 구간에 아직 남아 있으면 지금 시간축 자리로 알린다(잘라냈으면 사라진다)
 {const gaps=(cur.row&&cur.row.audio_gaps)||[],rb=(cur.row.timeline.clips||[]);
  gaps.forEach(g=>{let t=0,src=null;
   for(const b of rb){const sp=+b.playback_speed||1,d=(+b.end_sec-+b.start_sec)/sp+(+b.hold_sec||0);
    if(+g.start>=t-1e-3&&+g.start<t+d){src=+b.start_sec+Math.min(+g.start-t,(+b.end_sec-+b.start_sec)/sp)*sp;break;}t+=d;}
   if(src==null)return;
   const c=live.find(x=>src>=x.start-1e-3&&src<x.end);if(!c)return;
   const out=c.out+(src-c.start)/H.clipSpd(c),len=Math.max(0.1,+g.end-+g.start);
   // 그 자리를 내레이션이나 효과음이 채웠으면(빈 곳의 절반 이상) 알리지 않는다
   const sounds=[...(m.cues||[]).filter(q=>!q.dropped&&!q.lost).map(q=>[q.out,q.out+q.dur]),
    ...(window.__edSfx&&H.srcToOut?window.__edSfx.items(cur,H).filter(x=>!x.off).map(x=>[x.at,x.at+x.dur]):[])];
   const filled=sounds.reduce((n,[a,b])=>n+Math.max(0,Math.min(b,out+len)-Math.max(a,out)),0);
   if(filled>=len*0.5)return;
   items.push({level:'warn',kind:'clip',i:c.i,text:`${H.fmt(out)}부터 ${len.toFixed(1)}초 동안 원본 소리가 비어 있어요(${c.i+1}번 구간).`});
  });}
 // 3) 원음이 꺼진 구간: 덮개는 이전 구간에서 물려받는다
 const base=(cur.row.timeline.clips||[]).map(c=>({s:+c.start_sec,e:+c.end_sec,cover:!!c.cover}));
 const voiced=placed.map(p=>[p.a,p.b]),silent=[];
 live.forEach(c=>{
  let best=null,bo=0;base.forEach(b=>{const o=ovl(c.start,c.end,b.s,b.e);if(o>bo){bo=o;best=b;}});
  if(!best||!best.cover)return;
  const a=c.out,b=c.out+H.clipDur(c),talk=voiced.some(([x,y])=>ovl(a,b,x,y)>1e-3);
  const slow=H.clipSpd(c)!==1||+c.hold>0;
  if(!talk&&!slow)return;              // 내레이션 없는 1배속 덮개 → 엔진이 원음을 켠다
  muted.set(c.i,{talk,slow,a,b});silent.push({c,a,b,talk,slow});
  if(!talk)items.push({level:'warn',kind:'clip',i:c.i,text:`${c.i+1}번 구간은 원음 없이 나가요. 내레이션이 빠졌지만 배속이나 멈춤이 걸려 있어서 원음이 켜지지 않아요.`});
 });
 // 대사 자막이 소리 없이 나가는 자리(엔진 muted_dialogue 와 같은 규칙): 원음 꺼진 구간 위, 또는 내레이션과 겹쳐 원음이 꺼지는 자리
 (m.subs||[]).forEach((su,i)=>{
  if(su.del)return;
  const x=silent.find(z=>ovl(z.a,z.b,su.start,su.end)>0.1);
  if(x){subWarn.add(i);items.push({level:'bad',kind:'sub',i,
   text:`대사 ${q(su.text)}${ig(su.text)} 원음이 꺼진 ${x.c.i+1}번 구간 위에 있어 소리 없이 나가요.${x.slow&&!x.talk?' 그 구간을 1배속으로 되돌리면 원음이 켜져요.':''}`});return;}
  if(voiced.some(([a,b])=>ovl(a,b,su.start,su.end)>0.1)){subWarn.add(i);items.push({level:'warn',kind:'sub',i,
   text:`대사 ${q(su.text)}${ig(su.text)} 내레이션과 겹쳐 소리 없이 나가요. 내레이션이 나오는 동안은 원음이 꺼져요.`});}
 });
 scheduleMeasure(cur,H);
 return {items,muted,subWarn,lens};
}

export function warnHtml(checks){
 if(!checks)return [];
 return checks.items.map(x=>`<div class="alert warn ck-${x.level}" role="button" tabindex="0" onclick="window.__edSelect&&window.__edSelect('${x.kind}',${x.i})">${esc(x.text)}</div>`);
}

const MUTE_ICON='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="m17 9 5 6m0-6-5 6"/></svg>';
export function clipBadge(checks,i){
 const x=checks&&checks.muted.get(i);
 return x?`<span class="ck-mute" title="${x.talk?'내레이션 자리라 원음이 꺼져 있어요':'원음 없이 나가는 구간이에요'}">${MUTE_ICON}</span>`:'';
}

export function clipPanel(cur,i){
 const checks=cur.model&&cur.model.checks,x=checks&&checks.muted.get(i);
 if(!x)return '';
 const c=cur.model.clips[i];
 if(x.talk)return `<div class="alert warn ck-info">내레이션이 나오는 자리라 이 구간은 원음이 꺼져 있어요.</div>`;
 return `<div class="alert warn ck-bad">이 구간은 원음 없이 나가요. 배속이나 멈춤이 걸린 내레이션 자리라서 원음이 꺼져 있어요.</div>
  ${c&&(+c.speed!==1||+c.hold)?`<button onclick="coverNormalSpeed(${i})">1배속으로 되돌려 원음 켜기</button>`:''}`;
}

export function ttsPanel(cur,i){
 const checks=cur.model&&cur.model.checks;
 if(!checks)return '';
 const cue=cur.model.cues[i];
 if(cue&&(cue.lost||cue.dropped))return `<div class="alert warn ck-bad">이 내레이션은 빠져요. 원래 장면이 지금 구간에 없어요. 구간을 늘리거나 내레이션을 옮겨 주세요.</div>`;
 const L=checks.lens.get(i);
 if(!L)return '';
 const how=L.real?'':L.pending?' (재는 중)':L.failed?' (예상, 재지 못했어요)':' (예상)';
 return `<div class="kv"><span class="k">읽는 길이</span><span class="v">${L.sec.toFixed(2)}초${how}</span></div>`;
}

// 제출 직전: 엔진 미리 검사(apply_edit --check)가 정본이다. 엔진이 답하지 않으면 편집실 검사로 막는다.
// {stop: 막을 문장[], warnings: 확인 창에 보일 문장[], estimated: 엔진 없이 예상으로만 본 것인지}
export async function beforeSubmit(cur,H,ov){
 const dry=local().dryRun;
 let engine=null;
 if(dry){try{engine=await dry(ov);}catch(e){engine=null;}}
 if(engine&&engine.supported!==false&&'ok' in engine){
  if(Array.isArray(engine.tts))for(const r of engine.tts){
   const t=(cur.model.tts||[]).find(x=>Math.abs(x.src-(+r.source_time_sec))<0.05&&String(x.text).trim()===String(r.text).trim());
   if(t&&+r.duration_sec>0)measured.set(H.cueKey(t),+r.duration_sec);
  }
  const probs=(engine.problems||[]).filter(p=>p&&typeof p==='object');
  const stop=probs.filter(p=>p.blocking).map(p=>p.say||p.message);
  if(engine.ok===false&&!stop.length)stop.push(engine.error||'이대로는 적용할 수 없어요.');
  const warnings=[...probs.filter(p=>!p.blocking).map(p=>p.say||p.message),...(engine.notes||[]).map(n=>n.text)];
  return {stop:[...new Set(stop)],warnings:[...new Set(warnings)],estimated:false};
 }
 const checks=cur.model.checks,stop=[],warnings=[];
 if(checks)checks.items.forEach(x=>(x.block?stop:warnings).push(x.text));
 return {stop,warnings,estimated:true};
}

// 내레이션 한 줄의 자막 구절 — 엔진이 잰 것이 있으면 그것, 재는 중이면 그 상태
export function phrasesFor(t,H){
 const k=H.cueKey(t);
 if(measuredPh.has(k)){const m=measuredPh.get(k);return {list:m.list,state:'exact',note:m.note};}
 return pending.has(k)?{state:'pending'}:null;
}
window.__edChecks={analyze,warnHtml,clipBadge,clipPanel,ttsPanel,beforeSubmit,phrasesFor};
