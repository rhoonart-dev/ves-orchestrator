// 로컬 영상 제출 확인 창 — 브라우저 confirm/prompt 두 번 대신 한 창에서 보낼 항목·결과·메모를 보여 준다.
// 편집실(ves-editor.js)의 로컬 제출 분기가 window.__workspaceConfirmSubmit 으로 부른다.
// 제출 전 검사(src/editor-checks.js beforeSubmit) 결과도 여기서 보인다: stop 이 있으면 제출하지 않고 고치러 돌아간다.
// 합성 전 예상 길이로만 걸린 것(estimated)은 '그래도 제출'을 남긴다 — 실제로 겹치면 엔진이 거절하고 편집실에 사유가 뜬다.
const NAMES={clips:'구간',tts:'내레이션',title:'제목',subtitles:'자막',texts:'텍스트·보조 자막',design:'디자인',emphasis:'강조',zooms:'줌',sfx:'효과음'};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const list=(cls,title,items)=>items.length?`<section class="submit-${cls}"><h3>${title}</h3><ul>${items.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></section>`:'';
export function confirmSubmit(keys,{version='',stop=[],warnings=[],estimated=false}={}){
 return new Promise(resolve=>{
  const dlg=document.createElement('dialog');dlg.className='submit-dialog';
  const blocked=stop.length>0,hard=blocked&&!estimated;
  dlg.innerHTML=`<form method="dialog">
   <h2>${blocked?'이대로는 다시 렌더할 수 없어요':'수정 내용을 제출할까요?'}</h2>
   <div class="submit-chips">${keys.map(k=>`<span>${esc(NAMES[k]||k)}</span>`).join('')}</div>
   ${list('stop','먼저 고쳐 주세요',stop)}
   ${list('warn','제출하면 이렇게 돼요',warnings)}
   ${blocked?'':`<ul>
    <li>고친 그대로 다시 렌더해요. 몇 분 걸려요.</li>
    <li>끝나면 같은 번호${version?` (${esc(version)})`:''}의 새 판으로 바뀌고, 이전 판은 보관돼요.</li>
    <li>렌더하는 동안에는 이 영상을 편집할 수 없어요.</li>
   </ul>`}
   ${hard?'':`<label><span>메모 <small>선택</small></span><textarea rows="2" placeholder="무엇을 고쳤는지 적어 두면 작업 이력에 남아요"></textarea></label>`}
   <footer><button type="button" value="cancel"${blocked?' class="primary"':''}>${blocked?'돌아가서 고치기':'취소'}</button>${hard?'':`<button type="submit" value="ok"${blocked?'':' class="primary"'}>${blocked?'그래도 제출':'제출하고 다시 렌더'}</button>`}</footer>
  </form>`;
  document.body.append(dlg);
  const note=dlg.querySelector('textarea');
  const done=v=>{dlg.close();dlg.remove();resolve(v);};
  dlg.querySelector('[value=cancel]').onclick=()=>done(null);
  dlg.querySelector('form').onsubmit=e=>{e.preventDefault();if(!hard)done({note:note?note.value.trim():''});};
  dlg.addEventListener('cancel',e=>{e.preventDefault();done(null);});   // Esc
  dlg.showModal();dlg.querySelector('.primary').focus();
 });
}
