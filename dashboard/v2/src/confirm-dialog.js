// 브라우저 기본 confirm() 대신 쓰는 확인 창 — 제목 · 설명 · 알약 버튼 두 개. 확인이면 true.
// 되돌릴 수 있는 일은 확인 창 없이 하고 토스트의 '되돌리기'를 준다(toast.js). 이 창은 되돌릴 수 없는 일에만.
export function askConfirm({title,body='',ok='확인',cancel='취소',danger=false}={}){
 return new Promise(resolve=>{
  const d=document.createElement('dialog');d.className='ask-confirm';d.setAttribute('aria-labelledby','ask-confirm-title');
  d.innerHTML=`<h2 id="ask-confirm-title"></h2>${body?'<p></p>':''}<div class="ask-confirm-acts"><button type="button" class="ask-cancel"></button><button type="button" class="ask-ok${danger?' is-danger':''}"></button></div>`;
  d.querySelector('h2').textContent=title;if(body)d.querySelector('p').textContent=body;
  d.querySelector('.ask-cancel').textContent=cancel;d.querySelector('.ask-ok').textContent=ok;
  const done=v=>{d.close();d.remove();resolve(v);};
  d.querySelector('.ask-cancel').onclick=()=>done(false);d.querySelector('.ask-ok').onclick=()=>done(true);
  d.addEventListener('cancel',e=>{e.preventDefault();done(false);});
  d.addEventListener('click',e=>{if(e.target===d)done(false);});   // 바깥을 누르면 닫기
  document.body.append(d);d.showModal();d.querySelector('.ask-cancel').focus();
 });
}
