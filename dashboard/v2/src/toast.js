// 잠깐 떴다 사라지는 안내(토스트) — 완료 안내용. 실패 안내는 그 자리에 남긴다.
// host 안(창이 있으면 그 창) 아래 가운데에 뜬다. action: {label, run} 을 주면 버튼이 붙고 조금 더 오래 머문다.
const timers=new WeakMap();
export function showToast(host,text,{action=null,ms}={}){
 if(!text)return;
 const box=host.closest('dialog')||document.body;
 let t=box.querySelector(':scope>.ws-toast');
 if(!t){t=document.createElement('div');t.className='ws-toast';t.setAttribute('role','status');t.setAttribute('aria-live','polite');box.append(t);}
 t.classList.toggle('in-page',box===document.body);
 t.replaceChildren();const span=document.createElement('span');span.textContent=text;t.append(span);
 if(action){const b=document.createElement('button');b.type='button';b.textContent=action.label;b.onclick=()=>{hide();action.run();};t.append(b);}
 const hide=()=>{clearTimeout(timers.get(t));t.classList.remove('visible');};
 clearTimeout(timers.get(t));requestAnimationFrame(()=>t.classList.add('visible'));
 timers.set(t,setTimeout(hide,ms??(action?6000:2600)));
}
