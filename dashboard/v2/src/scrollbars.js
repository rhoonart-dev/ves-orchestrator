// Capture also covers scroll containers mounted later, including modal panels.
export function setupScrollbars(){
  const timers=new WeakMap();
  document.addEventListener('scroll',event=>{
    const element=event.target===document?document.documentElement:event.target;
    if(!(element instanceof Element))return;
    clearTimeout(timers.get(element));
    element.setAttribute('data-scrolling','');
    timers.set(element,setTimeout(()=>{
      element.removeAttribute('data-scrolling');
      timers.delete(element);
    },900));
  },{capture:true,passive:true});
}
