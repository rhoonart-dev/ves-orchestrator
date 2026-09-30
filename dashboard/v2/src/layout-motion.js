// FLIP positions only: resizing never stretches the video or recreates its DOM.
export function setupLayoutMotion(){
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const selector='.page-head,.review-toolbar,.review-layout,.workbench-top,.video-rail,.video-stage,.video-inspector,.rights-toolbar,.rights-list,.rights-detail';
 const previous=new Map(),animations=new Map();
 let frame=0,resizing=false,idle=0;
 const elements=()=>[...document.querySelectorAll(selector)].filter(el=>el.getClientRects().length&&!el.closest('dialog:not([open])'));
 const rect=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height};};
 function remember(){
  previous.clear();for(const el of elements())previous.set(el,rect(el));
 }
 function move(){
  frame=0;
  const nodes=elements(),measurements=[];
  for(const el of nodes){
   const before=previous.get(el),transform=getComputedStyle(el).transform;
   const matrix=transform==='none'?null:new DOMMatrixReadOnly(transform);
   const offset={x:matrix?.m41||0,y:matrix?.m42||0};
   animations.get(el)?.cancel();animations.delete(el);
   measurements.push({el,before,after:rect(el),offset});
  }
  previous.clear();
  for(const {el,before,after,offset} of measurements){
   previous.set(el,after);
   if(reduced.matches||!before||!after.width||!after.height)continue;
   const x=before.x+offset.x-after.x,y=before.y+offset.y-after.y;
   if(Math.abs(x)<1&&Math.abs(y)<1)continue;
   const animation=el.animate([{transform:`translate(${x}px,${y}px)`},{transform:'translate(0,0)'}],{duration:280,easing:'cubic-bezier(.22,1,.36,1)'});
   animations.set(el,animation);
   animation.onfinish=()=>{if(animations.get(el)===animation)animations.delete(el);};
  }
 }
 window.addEventListener('resize',()=>{
  resizing=true;clearTimeout(idle);idle=setTimeout(()=>{resizing=false;},350);
  if(!frame)frame=requestAnimationFrame(move);
 },{passive:true});
 document.addEventListener('scroll',()=>{if(!resizing&&!animations.size)remember();},{capture:true,passive:true});
 // New route/content establishes its own starting layout without an entrance effect.
 const observer=new MutationObserver(()=>{if(!resizing&&!animations.size)remember();});
 observer.observe(document.querySelector('.workspace'),{childList:true,subtree:true});
 reduced.addEventListener('change',()=>{for(const animation of animations.values())animation.cancel();animations.clear();remember();});
 requestAnimationFrame(remember);
}
