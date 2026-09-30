// 쇼츠 안전 영역 — 미리보기 화면 오른쪽 옆 아래 둥근 버튼으로 켜고 끈다(2026-09-29).
// 켜면 유튜브 쇼츠 앱이 영상 위에 덮는 자리(위 검색·카메라, 오른쪽 버튼 줄, 아래 채널·제목·음악)를 옅게 겹친다(점선 상자는 뺐다). 위치는 1080×1920 기준 근사값이다(기기·제목 길이에 따라 조금 다르다).
// 영상 칸의 자르기(검은 띠·얼굴 따라가기)는 아직 완성본과 다를 수 있다 — 글자·로고 자리를 보는 용도.
const ICON='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="2.5" width="12" height="19" rx="2.5"/><rect x="8.5" y="6" width="7" height="10" rx="1" stroke-dasharray="2 1.6"/></svg>';
const P=(x,y,w,h)=>`left:${x/10.8}%;top:${y/19.2}%;width:${w/10.8}%;height:${h/19.2}%`;
const dot=(x,y,s,a)=>`<i style="${P(x,y,s,s)};border-radius:50%;background:rgba(255,255,255,${a})"></i>`;
const bar=(x,y,w,h,a)=>`<i style="${P(x,y,w,h)};border-radius:8px;background:rgba(255,255,255,${a})"></i>`;
const OVERLAY=`${dot(870,70,70,.28)}${dot(970,70,70,.28)}
 ${[1040,1180,1320,1460,1600].map(y=>dot(950,y,100,.28)).join('')}
 ${dot(40,1600,80,.35)}${bar(140,1618,300,44,.28)}
 ${bar(40,1712,820,40,.28)}${bar(40,1770,560,40,.22)}${bar(40,1836,420,34,.18)}`;
const KEY='ves-studio-safe';

export function mountSafeArea(){
 const sh=document.querySelector('#shortsWrap .shorts');if(!sh||document.getElementById('safeBtn'))return;
 const wrap=sh.parentElement;
 const ov=document.createElement('div');ov.id='safeOverlay';ov.setAttribute('aria-hidden','true');ov.innerHTML=OVERLAY;sh.append(ov);
 const btn=document.createElement('button');btn.id='safeBtn';btn.type='button';btn.innerHTML=ICON;wrap.append(btn);
 let on=false;try{on=localStorage.getItem(KEY)==='1'}catch{}
 const paint=()=>{ov.hidden=!on;btn.classList.toggle('on',on);btn.setAttribute('aria-pressed',String(on));
  btn.title=on?'쇼츠 안전 영역 숨기기':'쇼츠 안전 영역 보기';btn.setAttribute('aria-label',btn.title);};
 btn.onclick=()=>{on=!on;try{localStorage.setItem(KEY,on?'1':'0')}catch{}paint();};
 // 미리보기 화면 오른쪽 옆, 아래 끝에 맞춘다(화면 크기·자리가 바뀌면 따라간다)
 const place=()=>{btn.style.left=(sh.offsetLeft+sh.offsetWidth+12)+'px';btn.style.top=(sh.offsetTop+sh.offsetHeight-36)+'px';};
 new ResizeObserver(place).observe(sh);addEventListener('resize',place);
 paint();place();
}
