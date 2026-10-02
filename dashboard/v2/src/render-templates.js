import {esc} from './review-details.js?v=web-1';
import {fontFull} from './font-picker.js?v=1';   // 폰트 칸 — 이름을 그 폰트로(저절로 바뀐다)
const FONT_DEF={title_font:'Jalnan',subtitle_font:'NotoSansCJKkr-Black',tts_font:'NotoSansCJKkr-Black'};   // 비우면 엔진 기본
// 영상 모양(0133 · 0134) 공용 — 새 파이프라인이 실제로 쓰는 칸, 값 정리, '적용 모습 미리보기'(맥미니가 실제 영상 한 편을 이 값으로 다시 렌더한 두 장).
// 화면은 채널 템플릿(channel-templates.js): 채널 → 작품 탭 → 이 채널 값 / 모든 채널(작품 기본).
const BASE_FONTS=[['JalnanGothic','여기어때 잘난체 고딕'],['Jalnan','여기어때 잘난체 2'],['NotoSansCJKkr-Black','Noto Sans 블랙'],['mulmaru','물마루'],['Griun','그리운 경찰공평체']];
// 굵기가 여러 개인 폰트는 제목에는 굵은 것, 자막 · 내레이션에는 중간 굵기만 보인다 · 와구리체는 제목 전용(2026-10-02 사용자)
export const TITLE_FONTS=[...BASE_FONTS,['WAGURI','와구리체'],['Paperlogy-9Black','페이퍼로지 블랙'],['Paperlogy-8ExtraBold','페이퍼로지 엑스트라볼드'],['Freesentation-9Black','프리젠테이션 블랙'],['Freesentation-8ExtraBold','프리젠테이션 엑스트라볼드'],['A2Z-9Black','에이투지체 블랙'],['A2Z-8ExtraBold','에이투지체 엑스트라볼드']];
export const TEXT_FONTS=[...BASE_FONTS,['Paperlogy-7Bold','페이퍼로지 볼드'],['Paperlogy-6SemiBold','페이퍼로지 세미볼드'],['Freesentation-7Bold','프리젠테이션 볼드'],['Freesentation-6SemiBold','프리젠테이션 세미볼드'],['A2Z-7Bold','에이투지체 볼드'],['A2Z-6SemiBold','에이투지체 세미볼드']];
export const FONTS=[...TITLE_FONTS,...TEXT_FONTS.slice(BASE_FONTS.length)];   // 이름 찾기용(전부)
const fontsFor=k=>k==='title_font'?TITLE_FONTS:TEXT_FONTS;
export const PLATFORM_LOGOS=[['tving_logo','티빙 로고'],['coupangplay_icon','쿠팡플레이 아이콘'],['coupangplay_logo','쿠팡플레이 로고']];
export const GROUPS=[
 ['제목',[['title_font','폰트','font'],['title_color','첫째 줄 색','color'],['title_color2','둘째 줄 색','color']]],
 ['대사 자막',[['subtitle_font','폰트','font'],['subtitle_color','색','color']]],
 ['내레이션 자막',[['tts_font','폰트','font'],['tts_color','색','color']]],
 ['작품 로고 아래 문구',[['work_caption','문구','text'],['work_caption_color','색','color']]],
 ['권리사',[['platform_image','로고','logo'],['platform_text','문구','text'],['platform_color','문구 색','color']]],
];
export const TEMPLATE_KEYS=GROUPS.flatMap(([,f])=>f.map(x=>x[0]));
// 제목 색 두 개 — 목록 · 탭에서 한눈에
export const swatch=d=>`<span class="rt-sw"><i style="background:${esc(d?.title_color||'#FFFFFF')}"></i><i style="background:${esc(d?.title_color2||'#FFFF00')}"></i></span>`;
export function cleanDesign(values){
 const out={};
 for(const k of TEMPLATE_KEYS){const v=String(values[k]??'').trim();if(!v)continue;
  if(k==='platform_image'&&v.startsWith('asset:')){out.platform_asset_id=v.slice(6);continue;}   // 작품 관리에 올린 권리사 로고
  if(/color/.test(k)&&!/^#[0-9a-f]{6}$/i.test(v))throw Error('색은 #RRGGBB 형식으로 적어 주세요');
  out[k]=/color/.test(k)?v.toUpperCase():v;}
 return out;
}
export const sameDesign=(a,b)=>JSON.stringify(Object.entries(a||{}).sort())===JSON.stringify(Object.entries(b||{}).sort());

// 칸 묶음 HTML(form 안에 넣는다) — 비워 둔 칸은 placeholder 로 '따르는 값'을 보여 준다
export function fieldsHtml(d={},inherit={}){
 const ph=(k,fallback)=>inherit[k]?String(FONTS.find(f=>f[0]===inherit[k])?.[1]||PLATFORM_LOGOS.find(f=>f[0]===inherit[k])?.[1]||inherit[k]):fallback;
 const field=(k,label,type)=>{const v=d[k]||'';
  if(type==='font')return `<label>${label}<select name="${k}" data-font data-default-value="${esc(inherit[k]||FONT_DEF[k])}" data-default="${esc(fontFull(inherit[k]||FONT_DEF[k]))}"><option value="">${esc(ph(k,'엔진 기본'))}</option>${fontsFor(k).map(([id,n])=>`<option value="${id}"${v===id?' selected':''}>${esc(n)}</option>`).join('')}</select></label>`;
  if(type==='logo')return `<label>${label}<select name="${k}" data-asset="${esc(d.platform_asset_id||'')}"><option value="">${esc(inherit[k]?ph(k):inherit.platform_asset_id?'올린 로고(기본값)':'없음')}</option>${PLATFORM_LOGOS.map(([id,n])=>`<option value="${id}"${v===id?' selected':''}>${esc(n)}</option>`).join('')}</select></label>`;
  if(type==='color')return `<label>${label}<span class="rt-color"><input type="color" value="${esc(v||inherit[k]||'#FFFFFF')}" data-for="${k}" aria-label="${label} 고르기"><input name="${k}" value="${esc(v)}" placeholder="${esc(ph(k,'엔진 기본'))}" maxlength="7" spellcheck="false"></span></label>`;
  return `<label>${label}<input name="${k}" value="${esc(v)}" maxlength="60" placeholder="${esc(ph(k,'없음'))}"></label>`;};
 return GROUPS.map(([g,fs])=>`<section><h3>${g}</h3><div class="template-fields">${fs.map(([k,l,t])=>field(k,l,t)).join('')}</div></section>`).join('');
}
// 색 고르기와 글자 칸을 서로 맞춘다
export function wireColors(form,onChange){
 form.querySelectorAll('input[type=color]').forEach(c=>{c.oninput=()=>{form.elements[c.dataset.for].value=c.value.toUpperCase();onChange?.();};});
 form.querySelectorAll('input[name$=color]').forEach(t=>t.addEventListener('input',()=>{if(/^#[0-9a-f]{6}$/i.test(t.value))form.querySelector(`[data-for="${t.name}"]`).value=t.value;}));
}

// 적용 모습 미리보기 — box 안에 영상 고르기 · 버튼 · 두 장. getDesign() 은 지금 칸의 (저장 전 포함) 최종 값
export function mountPreview(box,{client,videos,writable,getDesign,status,target,emptyText}){
 let preview=null,poll=0,dead=false;
 box.innerHTML=`<h3>적용 모습 미리보기</h3><p>맥미니가 고른 영상 한 편을 지금 칸의 값으로 다시 렌더해요. 저장하지 않은 값도 그대로 보여요. 1분쯤 걸려요.</p>
  <div class="rt-pick"><select data-video>${videos.map(v=>`<option value="${v.id}">${esc(v.work_title)} · ${esc(String(v.title||v.suffix).replace(/\s*\n\s*/g,' '))}</option>`).join('')||`<option value="">${esc(emptyText||'맥미니에서 만든 영상이 없어요')}</option>`}</select><button type="button" class="rt-go" ${writable&&videos.length?'':'disabled'}>적용 모습 미리보기</button></div><div class="rt-shots"></div>`;
 const shots=box.querySelector('.rt-shots');
 const draw=()=>{
  if(!preview){shots.innerHTML='<p class="rt-none">영상을 고르고 적용 모습 미리보기를 눌러 주세요.</p>';return;}
  if(preview.state==='running'){shots.innerHTML='<p class="rt-wait">맥미니가 만들고 있어요. 창을 닫아도 계속 만들어요.</p>';return;}
  if(preview.state==='failed'){shots.innerHTML=`<p class="rt-fail">${esc(preview.error||'만들지 못했어요')}</p>`;return;}
  let now=null;try{now=getDesign();}catch{}
  shots.innerHTML=`${now&&!sameDesign(now,preview.design)?'<p class="rt-stale">그 뒤로 값을 바꿨어요. 다시 누르면 바뀐 모양이 보여요.</p>':''}<div class="rt-shot-grid">${[['dialogue','대사 장면'],['narration','내레이션 장면']].filter(([k])=>preview.urls?.[k]).map(([k,l])=>`<figure><img src="${esc(preview.urls[k])}" alt="${l}"><figcaption>${l}</figcaption></figure>`).join('')}</div>`;};
 const watch=async()=>{clearTimeout(poll);if(dead||!preview)return;
  const {data}=await client.from('render_template_previews').select('id,state,error,files').eq('id',preview.id).maybeSingle();
  if(dead||!data||preview?.id!==data.id)return;
  if(data.state==='done'){const keys=Object.values(data.files||{});const {data:u}=keys.length?await client.storage.from('ves-outputs').createSignedUrls(keys,6*3600):{data:[]};
   const url=new Map((u||[]).map(x=>[x.path,x.signedUrl]));preview={...preview,...data,urls:Object.fromEntries(Object.entries(data.files||{}).map(([k,v])=>[k,url.get(v)]))};}
  else preview={...preview,...data};
  draw();if(preview.state==='running')poll=setTimeout(watch,4000);};
 box.querySelector('.rt-go').onclick=async()=>{let design;try{design=getDesign();}catch(x){status?.(x.message);return;}
  const btn=box.querySelector('.rt-go');btn.disabled=true;
  const {data,error}=await client.rpc('request_template_preview',{p_design:design,p_video:box.querySelector('[data-video]').value,...(target?.()||{p_work:null,p_slug:null})});
  btn.disabled=false;if(error){status?.(error.message);return;}
  preview={id:data,state:'running',design};draw();watch();};
 draw();
 // 화면을 다시 열면 이 영상들로 본 마지막 미리보기를 보여 준다(만드는 중이면 이어서 기다린다)
 // 채널 화면이면 그 채널 값으로 만든 것만(0138) — 종전엔 같은 작품의 가장 최근 것을 모든 채널에 보여 줬다
 const slug=target?.()?.p_slug??null;
 if(videos.length){let q=client.from('render_template_previews').select('id,state,error,files,design').in('video_id',videos.map(v=>v.id));
  q=slug?q.eq('token_slug',slug):q.is('token_slug',null);
  q.order('created_at',{ascending:false}).limit(1)
  .then(({data})=>{const last=data?.[0];if(dead||preview||!last)return;const {work_asset_id,...design}=last.design||{};preview={id:last.id,state:last.state,design};draw();watch();});}
 return {refresh:draw,release:()=>{dead=true;clearTimeout(poll);}};
}
