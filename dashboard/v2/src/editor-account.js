// 편집실 계정 — Workspace 처럼 오른쪽 위 동그란 로봇(avatar-robots.js). 누르면 이메일·권한·내 로봇 고르기·로그아웃(2026-09-29).
// 예전 상단바의 이메일 글자와 '로그아웃' 버튼(#who·#logout)을 대신한다. 로봇 고르기는 Workspace 와 같은 계정 정보(user_metadata.avatar_robot)에 남는다.
import {avatarRobot,userRobotIndex,ROBOT_COUNT} from './avatar-robots.js';
const ROLE_NAME={viewer:'보기만',reviewer:'검수',operator:'운영',admin:'관리자'};
const RANK=['viewer','reviewer','operator','admin'];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function mountAccount(client,user,roles){
 const logout=document.getElementById('logout');if(!logout||document.getElementById('accountBtn'))return;
 const role=[...(roles||[])].sort((a,b)=>RANK.indexOf(b)-RANK.indexOf(a))[0];
 const btn=document.createElement('button');btn.id='accountBtn';btn.type='button';
 btn.setAttribute('aria-haspopup','dialog');btn.setAttribute('aria-expanded','false');btn.setAttribute('aria-label','계정');btn.title='계정';
 logout.before(btn);
 const pop=document.createElement('div');pop.id='accountPop';pop.setAttribute('role','dialog');pop.setAttribute('aria-label','계정');pop.hidden=true;
 document.body.append(pop);
 let me=user;
 const draw=()=>{
  const pick=userRobotIndex(me),bot=avatarRobot(me.id,pick);
  btn.innerHTML=bot;
  pop.innerHTML=`<div class="acc-who"><span class="acc-av">${bot}</span><div><strong>${esc(me.email)}</strong><small>${esc(ROLE_NAME[role]||'')}</small></div></div>
   <div class="acc-robots" role="radiogroup" aria-label="내 로봇 고르기">${Array.from({length:ROBOT_COUNT},(_,i)=>
    `<button type="button" role="radio" data-robot="${i}" aria-checked="${i===pick}" aria-label="로봇 ${i+1}">${avatarRobot('',i)}</button>`).join('')}</div>
   <p class="acc-msg" role="status"></p>
   <button type="button" class="acc-out">로그아웃</button>`;
  pop.querySelectorAll('[data-robot]').forEach(b=>b.onclick=async e=>{
   e.stopPropagation();const i=Number(b.dataset.robot);if(i===pick)return;
   const {data,error}=await client.auth.updateUser({data:{avatar_robot:i}});
   if(error){pop.querySelector('.acc-msg').textContent='로봇을 바꾸지 못했어요. 다시 해 주세요.';return;}
   me=data.user;draw();
  });
  pop.querySelector('.acc-out').onclick=async()=>{
   try{await client.auth.signOut();location.reload();}
   catch{pop.querySelector('.acc-msg').textContent='로그아웃하지 못했어요. 다시 해 주세요.';}
  };
 };
 const place=()=>{const r=btn.getBoundingClientRect();pop.style.top=(r.bottom+8)+'px';pop.style.right=Math.max(12,innerWidth-r.right)+'px';};
 const open=on=>{pop.hidden=!on;btn.setAttribute('aria-expanded',String(on));if(on)place();};
 btn.onclick=e=>{e.stopPropagation();open(pop.hidden);};
 document.addEventListener('click',e=>{if(!pop.hidden&&!pop.contains(e.target)&&!btn.contains(e.target))open(false);});
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!pop.hidden){open(false);btn.focus();}});
 addEventListener('resize',()=>{if(!pop.hidden)place();});
 draw();
}
