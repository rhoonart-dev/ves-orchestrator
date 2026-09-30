// Reuse the same navigation and theme control in a modal drawer on small screens.
export function setupMobileNavigation(){
 const media=matchMedia('(max-width: 760px)');
 const rail=document.querySelector('.rail');
 const placeholder=document.createComment('desktop navigation');rail.before(placeholder);
 const dialog=document.getElementById('mobile-menu');
 const open=document.getElementById('open-mobile-menu');
 const close=document.getElementById('close-mobile-menu');
 const sync=()=>{
  if(dialog.open)dialog.close();
  if(media.matches)dialog.append(rail);else placeholder.after(rail);
  open.setAttribute('aria-expanded','false');
 };
 open.onclick=()=>{dialog.showModal();open.setAttribute('aria-expanded','true');close.focus();};
 close.onclick=()=>dialog.close();
 dialog.addEventListener('close',()=>open.setAttribute('aria-expanded','false'));
 dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();});
 rail.addEventListener('click',event=>{if(media.matches&&event.target.closest('a[href]')&&dialog.open)dialog.close();});
 media.addEventListener('change',sync);sync();
}
