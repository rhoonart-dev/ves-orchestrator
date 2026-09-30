export const templateFields=[
 ['제목','title_font','폰트','font'],['제목','title_size','첫째 줄 크기','number',20,200],['제목','title_size2','둘째 줄 크기','number',20,200],['제목','title_color','첫째 줄 색','color'],['제목','title_color2','둘째 줄 색','color'],
 ['자막','subtitles','대사 자막','onoff'],['자막','subtitle_font','폰트','font'],['자막','subtitle_size','글자 크기','number',20,200],['자막','subtitle_color','글자 색','color'],
 ['내레이션 자막','tts_color','글자 색','color'],['내레이션 자막','tts_size','글자 크기','number',20,200],['내레이션 자막','tts_y_margin','아래 여백 (px)','number',0,1920],
 ['영상 영역','aspect_ratio','영상 비율','ratio'],['영상 영역','video_width','가로 폭 (px)','number',320,1080],['영상 영역','video_y','상단 위치 (px)','number',0,1920],
];
export const fonts=['여기어때 잘난체 2 TTF','여기어때 잘난체 고딕 TTF','물마루','그리운 경찰공평체','NotoSansCJKkr-Black'];
export function changedDesign(original,values){
 const next=structuredClone(original||{});
 for(const [,key,label,type,min,max] of templateFields){
  if(!Object.hasOwn(values,key))continue;
  const value=String(values[key]).trim();
  if(value===String(original?.[key]??''))continue;
  if(!value){delete next[key];continue;}
  if(type==='number'){
   const n=Number(value);if(!Number.isInteger(n)||n<min||n>max)throw Error(`${label}: ${min}~${max} 사이의 정수를 입력해 주세요.`);next[key]=n;
  }else if(type==='color'){
   if(!/^#[0-9a-f]{6}$/i.test(value))throw Error(`${label}: #RRGGBB 형식으로 입력해 주세요.`);next[key]=value;
  }else if(type==='onoff'){
   next[key]=false;   // only '끔' is stored; '' (켬) deletes the key above
  }else if(type==='ratio'){
   if(!/^\d{1,3}:\d{1,3}$/.test(value)||value.split(':').some(v=>Number(v)<=0))throw Error('영상 비율은 13:9처럼 입력해 주세요.');next[key]=value;
  }else next[key]=value;
 }
 return next;
}
