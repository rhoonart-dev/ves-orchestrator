import {esc} from './review-details.js?v=web-1';
// 채널 템플릿 미리보기 — 1080×1920 쇼츠 위에 채널 디자인을 얹는다. 배치와 기본값은 VES Studio 의
// layoutShorts(ves-editor.js)·ai-video config 와 같다: 영상 1:1 가운데, 제목 70/90 흰색·노랑(밴드 위 가운데),
// 대사 자막 65 노랑(밴드 하단 안쪽), 내레이션 70 하늘색(하단 550), 작품명 44(하단 140), 플랫폼 표기(밴드 모서리 24).
// 근사 미리보기다 — 자막 스타일 프리셋·외곽선·얼굴 크롭은 그리지 않는다.
const W=1080,H=1920;
// engine font name → CSS family (@font-face in templates.css, files served from ai-video by serve.py)
const FONT_FAMILY={'Jalnan':'EngineJalnan','여기어때 잘난체 2 TTF':'EngineJalnan','여기어때 잘난체 고딕 TTF':'EngineJalnanGothic',
 '물마루':'EngineMulmaru','그리운 경찰공평체':'EngineGriun','NotoSansCJKkr-Black':'EngineNotoBlack','Noto Sans CJK KR':'EngineNotoBlack'};
const family=name=>`"${FONT_FAMILY[name]||'EngineJalnan'}",Pretendard,sans-serif`;
const num=(v,d)=>v===''||v==null||!Number.isFinite(+v)?d:+v;
export function shortsLayout(d={}){
 const ar=String(d.aspect_ratio||'1:1').split(':').map(Number);
 const vw=Math.min(W,num(d.video_width,W));
 const vh=ar[0]>0&&ar[1]>0?vw*ar[1]/ar[0]:vw;
 const vtop=num(d.video_y,(H-vh)/2);
 const s1=num(d.title_size,70),s2=num(d.title_size2,Math.round(s1*90/70));
 const blockH=(s1+s2)*1.25;
 return {
  band:{top:vtop,height:vh,left:(W-vw)/2,width:vw},
  title:{top:num(d.title_y,Math.max(30,(vtop-blockH)/2)),font:family(d.title_font||'Jalnan'),
   lines:[{size:s1,color:d.title_color||'#FFFFFF',box:d.title_box,boxColor:d.title_box_color,bold:d.title_bold},
          {size:s2,color:d.title_color2||'#FFFF00',box:d.title_box2,boxColor:d.title_box_color2,bold:d.title_bold2}]},
  subtitle:{top:Math.min(H-200,vtop+vh-170),size:num(d.subtitle_size,65)*.9,color:d.subtitle_color||'#FFFF00',font:family(d.subtitle_font||'여기어때 잘난체 2 TTF'),off:d.subtitles===false||d.subtitles==='false'},
  tts:{top:H-num(d.tts_y_margin,550),size:num(d.tts_size,70),color:d.tts_color||'#87CEEB',font:family(d.subtitle_font||'여기어때 잘난체 2 TTF')},
  work:{top:num(d.work_title_y,H-140),size:num(d.work_font_size,44),color:d.work_color||'rgba(255,255,255,.75)',image:d.work_image},
  platform:d.platform_text||d.platform_image?{top:vtop+num(d.platform_y,24),side:(d.platform_align||'left')==='right'?'right':'left',
   inset:(W-vw)/2+num(d.platform_x,24),text:d.platform_text,image:d.platform_image,size:num(d.platform_font_size,36),color:d.platform_color||'#FFFFFF'}:null,
 };
}
const pct=(v,b)=>`${v/b*100}%`,cq=px=>`${px/H*100}cqh`;
const lineHtml=(text,l)=>{
 const box=l.box&&l.box!=='none'?`background:${esc(l.boxColor||'#000000')};padding:0 .25em;border-radius:${l.box==='round'?'.3em':'0'};`:'';
 return `<div style="font-size:${cq(l.size)};color:${esc(l.color)};font-weight:${l.bold===false?600:800}"><span style="${box}">${esc(text)}</span></div>`;
};
// Dialogue and narration captions never show at the same moment in a render — `scene` picks one.
export function renderPreview(el,design,{title=['첫째 줄 제목','둘째 줄 강조 문구'],work='작품 이름',subtitle='대사 자막은 여기에 나와요',tts='내레이션 자막 예시',scene='dialogue'}={}){
 const L=shortsLayout(design);
 const ratio=design.aspect_ratio||'1:1';
 el.innerHTML=`<div class="sp-band" style="top:${pct(L.band.top,H)};height:${pct(L.band.height,H)};left:${pct(L.band.left,W)};width:${pct(L.band.width,W)}"><span>영상 ${esc(ratio)}</span></div>
<div class="sp-title" style="top:${pct(L.title.top,H)};font-family:${L.title.font}">${lineHtml(title[0],L.title.lines[0])}${lineHtml(title[1],L.title.lines[1])}</div>
${L.subtitle.off||scene!=='dialogue'?'':`<div class="sp-line" style="top:${pct(L.subtitle.top,H)};font-size:${cq(L.subtitle.size)};color:${esc(L.subtitle.color)};font-family:${L.subtitle.font}">${esc(subtitle)}</div>`}
${scene==='tts'?`<div class="sp-line sp-tts" style="top:${pct(L.tts.top,H)};font-size:${cq(L.tts.size)};color:${esc(L.tts.color)};font-family:${L.tts.font}">${esc(tts)}</div>`:''}
<div class="sp-line sp-work" style="top:${pct(L.work.top,H)};font-size:${cq(L.work.size)};color:${esc(L.work.color)}">${L.work.image?`<span class="sp-chip">작품 로고 · ${esc(L.work.image)}</span>`:esc(work)}</div>
${L.platform?`<div class="sp-platform" style="top:${pct(L.platform.top,H)};${L.platform.side}:${pct(L.platform.inset,W)};font-size:${cq(L.platform.size)};color:${esc(L.platform.color)}">${L.platform.image?`<span class="sp-chip">${esc(L.platform.image)}</span>`:esc(L.platform.text)}</div>`:''}`;
}
