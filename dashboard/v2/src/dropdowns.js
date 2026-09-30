// Shared single-select control. The native select remains the data/event source.
let sequence=0;
const chevron='<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="m6 8 4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
export function enhanceDropdowns(root){
 const releases=[...root.querySelectorAll('select:not([multiple]):not([data-dropdown])')].map(enhance);
 return ()=>releases.forEach(release=>release());
}
function enhance(select){
 // Older browsers keep the functional native control.
 if(!('showPopover' in HTMLElement.prototype))return ()=>{};
 const label=select.getAttribute('aria-label')||[...select.labels||[]].map(l=>l.childNodes[0]?.textContent.trim()).join(' ')||'선택';
 const width=Math.ceil(select.getBoundingClientRect().width);
 const wrapper=document.createElement('span');wrapper.className='dropdown';
 wrapper.style.minWidth=`${Math.max(width,104)}px`;
 const trigger=document.createElement('button');trigger.type='button';trigger.className='dropdown-trigger';
 trigger.setAttribute('role','combobox');trigger.setAttribute('aria-label',label);
 trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
 const caption=document.createElement('span');caption.className='dropdown-caption';trigger.append(caption);
 trigger.insertAdjacentHTML('beforeend',chevron);
 const menu=document.createElement('div');menu.className='dropdown-menu';menu.id=`dropdown-${++sequence}`;
 menu.setAttribute('role','listbox');menu.setAttribute('aria-label',label);menu.setAttribute('popover','manual');
 trigger.setAttribute('aria-controls',menu.id);
 select.before(wrapper);wrapper.append(select,trigger,menu);
 select.dataset.dropdown='';select.hidden=true;
 let open=false,active=-1,options=[],query='',typedAt=0;
 const enabled=()=>options.map((o,i)=>o.disabled?-1:i).filter(i=>i>=0);
 function sync(){
  caption.textContent=select.selectedOptions[0]?.textContent||'선택';trigger.disabled=select.disabled;
 }
 function highlight(index){
  active=index;
  [...menu.children].forEach((item,i)=>item.classList.toggle('is-active',i===index));
  const item=menu.children[index];
  if(item){trigger.setAttribute('aria-activedescendant',item.id);item.scrollIntoView({block:'nearest'});}
 }
 function position(){
  if(!trigger.getClientRects().length){close();return;}
  const r=trigger.getBoundingClientRect(),gap=7,pad=10;
  const below=innerHeight-r.bottom-gap-pad,above=r.top-gap-pad;
  const up=below<Math.min(menu.scrollHeight,220)&&above>below;
  menu.style.width=`${Math.min(Math.max(r.width,150),innerWidth-pad*2)}px`;
  menu.style.maxHeight=`${Math.max(60,Math.min(300,up?above:below))}px`;
  menu.style.left=`${Math.max(pad,Math.min(r.left,innerWidth-menu.offsetWidth-pad))}px`;
  menu.style.top=`${up?Math.max(pad,r.top-gap-menu.offsetHeight):r.bottom+gap}px`;
  menu.style.transformOrigin=up?'bottom left':'top left';
 }
 function close(){
  if(!open)return;open=false;menu.hidePopover();trigger.setAttribute('aria-expanded','false');
  trigger.removeAttribute('aria-activedescendant');query='';
 }
 function show(){
  if(open||select.disabled)return;
  options=[...select.options];menu.replaceChildren();
  options.forEach((option,i)=>{
   const item=document.createElement('div');item.className='dropdown-option';item.id=`${menu.id}-${i}`;
   item.setAttribute('role','option');item.setAttribute('aria-selected',String(i===select.selectedIndex));
   if(option.disabled)item.setAttribute('aria-disabled','true');
   const text=document.createElement('span');text.textContent=option.textContent;item.append(text);
   const check=document.createElement('span');check.className='dropdown-check';check.setAttribute('aria-hidden','true');check.textContent='✓';item.append(check);
   item.addEventListener('pointermove',()=>{if(!option.disabled&&active!==i)highlight(i);});
   item.addEventListener('pointerdown',e=>e.preventDefault());
   item.addEventListener('click',()=>choose(i));menu.append(item);
  });
  open=true;menu.showPopover();position();trigger.setAttribute('aria-expanded','true');
  highlight(options[select.selectedIndex]?.disabled?enabled()[0]:select.selectedIndex);
 }
 function choose(index){
  if(index<0||!options[index]||options[index].disabled)return;
  const changed=select.selectedIndex!==index;select.selectedIndex=index;sync();close();trigger.focus({preventScroll:true});
  if(changed){select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));}
 }
 trigger.onclick=()=>open?close():show();
 trigger.onkeydown=e=>{
  if(e.key==='Tab'){close();return;}
  if(e.key==='Escape'){if(open){e.preventDefault();e.stopPropagation();close();}return;}
  if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
   e.preventDefault();const wasOpen=open;show();const list=enabled();
   if(!list.length)return;
   if(e.key==='Home')highlight(list[0]);else if(e.key==='End')highlight(list.at(-1));
   else if(wasOpen){const step=e.key==='ArrowDown'?1:-1;highlight(list[Math.max(0,Math.min(list.length-1,list.indexOf(active)+step))]);}
   return;
  }
  if(e.key==='Enter'||e.key===' '){e.preventDefault();open?choose(active):show();return;}
  if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){
   e.preventDefault();show();const now=Date.now();query=now-typedAt>650?e.key:query+e.key;typedAt=now;
   const found=options.findIndex(o=>!o.disabled&&o.textContent.trim().toLocaleLowerCase().startsWith(query.toLocaleLowerCase()));
   if(found>=0)highlight(found);
  }
 };
 const outside=e=>{if(open&&!wrapper.contains(e.target))close();};
 const blur=()=>{if(open&&!wrapper.contains(document.activeElement))close();};
 const relocate=e=>{if(open&&!menu.contains(e.target))position();};
 document.addEventListener('pointerdown',outside);document.addEventListener('focusin',blur);
 document.addEventListener('scroll',relocate,true);window.addEventListener('resize',relocate);
 select.addEventListener('change',sync);select.addEventListener('input',sync);
 sync();
 return ()=>{
  close();document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',blur);
  document.removeEventListener('scroll',relocate,true);window.removeEventListener('resize',relocate);
  select.removeEventListener('change',sync);select.removeEventListener('input',sync);
  wrapper.before(select);wrapper.remove();select.hidden=false;delete select.dataset.dropdown;
 };
}
