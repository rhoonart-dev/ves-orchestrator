import {esc} from './review-details.js?v=web-1';
// 맥미니 작업 진행 단계(0125) — 작업지시 하나의 잡들(원본 받기 → 영상 만들기 → 올리기)과 엔진 진행 기록(job_queue.progress)으로
// "지금 어디까지 했나"를 한 줄 · 막대 · 단계 목록으로 만든다. 작업 목록 카드 · 단계 창 · 소스 창고 · 작업 이력 · 홈이 같이 쓴다.

export const JOB_COLS='id,work_order_id,kind,status,attempt,max_attempts,error,progress,progress_at,started_at,finished_at,created_at,node_id,params,result';
const STEP_LABEL={acquire:'원본 받기',transcribe:'받아쓰기',analyze:'장면 분석',script:'대본 쓰기',render:'영상 확인 · 렌더',upload:'작업 목록에 올리기'};
const kst=v=>v?new Intl.DateTimeFormat('ko-KR',{hour:'numeric',minute:'2-digit',timeZone:'Asia/Seoul'}).format(new Date(v)):'';
const mins=s=>s>=3600?`${Math.floor(s/3600)}시간 ${Math.round(s%3600/60)}분`:`${Math.max(1,Math.round(s/60))}분`;

// 엔진 진행 기록 한 줄(작업 이력 · 홈 · 소스 창고에 그대로 쓴다)
export const progressLabel=p=>p?.label||'';

// 작업지시의 잡들 → {state, label, pct, eta, steps:[{key,label,state,at,note}], node}
export function summarize(jobs,now=Date.now()){
 const by=k=>(jobs||[]).filter(j=>j.kind===k).sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at)))[0];
 const acq=by('acquire'),gen=by('tikitaka_generate'),up=by('tikitaka_upload');
 if(!gen)return null;
 const p=gen.progress||{},done=new Set(p.done||[]);
 const total=p.total||Number(gen.params?.count)||null,rendered=p.rendered||0;
 const skipped=(gen.result?.skipped||[]).length||(p.skipped||[]).length;   // 검사에서 빠진 편 — 나머지는 끝까지 만든다(엔진 2026-10-02)
 const dead=[acq,gen,up].find(j=>j&&(j.status==='dead'||j.status==='failed'&&j.attempt>=j.max_attempts));
 const retry=gen.status==='pending'&&gen.error?gen.attempt+1:0;
 let state='busy',label;
 if(up?.status==='succeeded')state='done',label=`${(gen.result?.videos||[]).length||rendered||total||0}편 완성${skipped?` · ${skipped}편 검사에서 빠짐`:''}`;
 else if(dead)state='failed',label='만들지 못했어요';
 else if(up?.status==='running')label='작업 목록에 올리는 중';
 else if(!acq||acq.status!=='succeeded')label=acq?.status==='running'?'원본 받는 중':'차례 기다리는 중';
 else if(gen.status==='pending')label=retry?`다시 시도 ${retry}번째 준비 중`:'차례 기다리는 중';
 else label=p.label||'영상 만드는 중';
 // 막대: 원본 5 · 받아쓰기 15 · 장면 분석 35 · 대본 50 · 렌더 50~95 · 올리기 100
 let pct=acq?.status==='succeeded'?5:0;
 if(done.has('transcribe'))pct=15;if(done.has('analyze'))pct=Math.max(pct,35);if(done.has('script'))pct=Math.max(pct,done.has('analyze')?50:40);
 if(total&&done.has('script')&&done.has('analyze'))pct=50+Math.round(45*Math.min(rendered+skipped,total)/total);
 if(up?.status==='running')pct=97;if(state==='done')pct=100;
 let eta=null;
 if(state==='busy'&&p.stage==='render'&&p.sec_per_video&&total&&rendered+skipped<total){
  const left=Math.max(0,total-rendered-skipped),from=p.steps?.last_render?Date.parse(p.steps.last_render+'+09:00'):Date.parse(gen.progress_at||now);
  eta=new Date((Number.isFinite(from)?from:now)+left*p.sec_per_video*1000);
 }
 const st=(key,isDone,isNow,at,note='')=>({key,label:STEP_LABEL[key],state:isDone?'done':isNow?'now':'wait',at,note});
 const now_=state==='busy'?(up?.status==='running'?'upload':acq?.status!=='succeeded'?'acquire':gen.status==='running'?(p.stage||'transcribe'):null):null;
 const steps=[
  st('acquire',acq?.status==='succeeded',now_==='acquire',acq?.finished_at),
  st('transcribe',done.has('transcribe'),now_==='transcribe',p.steps?.transcribe),
  st('analyze',done.has('analyze'),now_==='analyze',p.steps?.analyze),
  st('script',done.has('script'),now_==='script',p.steps?.script,total?`${total}편`:''),
  st('render',done.has('render')||state==='done'||up?.status==='running',now_==='render',p.steps?.last_render,total?`${Math.min(rendered+skipped,total)}/${total}편${skipped?` · ${skipped}편 검사에서 빠짐`:''}${p.sec_per_video?` · 편당 약 ${mins(p.sec_per_video)}`:''}`:''),
  st('upload',up?.status==='succeeded',now_==='upload',up?.finished_at),
 ];
 return {state,label,pct,eta,steps,total,rendered,skipped,node:gen.node_id||acq?.node_id||null,started:acq?.started_at||gen.started_at,error:dead?.error||null};
}

// 끝나는 예상 — 지난 시각이면 그 시각 대신 상태로 말한다(예상보다 오래 걸리는 중)
export function etaText(s,now=Date.now()){
 if(s.state==='failed')return '다시 걸어 주세요';
 if(!s.eta)return '';
 const late=now-s.eta.getTime();
 return late<=0?`${kst(s.eta)}쯤 끝나요`:late<10*60e3?'곧 끝나요':'예상보다 오래 걸리고 있어요';
}
// 카드 안 막대 + 한 줄
export function barHtml(s){
 if(!s)return '';
 return `<div class="jp-bar"><i style="width:${s.pct}%"></i></div><div class="jp-line"><b>${esc(s.label)}</b><span>${etaText(s)}</span></div>`;
}

const ICON={done:'<path d="m5 12 4 4L19 6"/>',now:'<circle cx="12" cy="12" r="8"/><path d="M12 8v4l2.5 1.5"/>',wait:'<circle cx="12" cy="12" r="1.2"/>'};
// 카드를 누르면 — 단계 자세히
export function openProgress(job,s){
 const d=document.createElement('dialog');d.className='jp-dlg';d.tabIndex=-1;
 d.innerHTML=`<header><div><h3>${esc(job.title)} ${s.state==='failed'?'· 만들지 못했어요':s.state==='done'?'· 다 만들었어요':'만드는 중'}</h3><p>${esc(job.work)} · ${esc(job.channel||'')}${s.node?` · ${esc(s.node)}`:''}${job.note?` · ${esc(job.note)}`:''}</p></div><button type="button" class="jp-x" aria-label="닫기">×</button></header>
  <ol class="jp-steps">${s.steps.map(x=>`<li class="${x.state}"><span class="jp-dot"><svg viewBox="0 0 24 24" aria-hidden="true">${ICON[x.state]}</svg></span><span class="jp-nm">${esc(x.label)}${x.note?`<small>${esc(x.note)}</small>`:''}${x.key==='render'&&s.total?`<span class="jp-mini">${Array.from({length:s.total},(_,i)=>`<i class="${i<s.rendered?'d':i===s.rendered&&x.state==='now'?'n':''}"></i>`).join('')}</span>`:''}</span><span class="jp-tm">${x.at?esc(kst(x.at.length===19?x.at+'+09:00':x.at)):''}</span></li>`).join('')}</ol>
  ${s.eta?`<p class="jp-eta">남은 ${s.total-s.rendered-(s.skipped||0)}편 → ${esc(etaText(s))}</p>`:''}${s.error?`<p class="jp-eta bad">${esc(String(s.error).slice(-300))}</p>`:''}`;
 const close=()=>{d.close();d.remove();};
 d.querySelector('.jp-x').onclick=close;d.addEventListener('close',()=>d.remove());d.addEventListener('click',e=>{if(e.target===d)close();});
 document.body.append(d);d.showModal();d.focus();
}
