// Runs before CSS to restore the saved palette without a light flash.
(()=>{
 const key='ves-workspace-theme';
 const root=document.documentElement;
 let theme='light';
 try{if(localStorage.getItem(key)==='dark')theme='dark';}catch{}
 root.dataset.theme=theme;
 document.addEventListener('DOMContentLoaded',()=>{
  const button=document.getElementById('theme-toggle');
  const label=document.getElementById('theme-label');
  const sync=()=>{
   const dark=root.dataset.theme==='dark';
   button.setAttribute('aria-pressed',String(dark));
   button.title=dark?'라이트 모드로 전환':'다크 모드로 전환';
   label.textContent=dark?'라이트 모드':'다크 모드';
  };
  button.addEventListener('click',()=>{
   root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';
   try{localStorage.setItem(key,root.dataset.theme);}catch{}
   sync();
  });
  window.addEventListener('storage',event=>{
   if(event.key===key){root.dataset.theme=event.newValue==='dark'?'dark':'light';sync();}
  });
  sync();
 });
})();
