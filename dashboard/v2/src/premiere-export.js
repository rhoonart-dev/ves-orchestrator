import {icon} from './icons.js';
// 프리미어로 내보내기 — 맥미니 영상(0111 tikitaka_videos) 한 편을 프리미어 프로 · 다빈치 리졸브가 여는 XML 프로젝트로.
// 맥미니·서버를 거치지 않는다: 편 기록(edit_plan · framing · 내레이션 큐 · 자막)은 ves-outputs 에, 원본 회차는 ves-sources 에 있다.
// 브라우저가 기록을 읽어 XML(파이널컷 7 XML, xmeml v4)을 만들고, 내레이션·자막·AI 완성본과 함께 zip 한 개로 준다.
// 원본은 크기가 커서(회차당 1~4GB) zip 에 넣지 않고 따로 받는다 — 회차당 한 번, 같은 media 폴더에 두면 모든 편이 같이 쓴다.
// 타임라인: V1 원본 컷(원본 구간 · 배속 · 세로 화면 자르기 자리 · 줌은 컷을 나눠 확대) · V2 로고 · V3 AI 완성본(꺼 둠, 비교용) · A1 원음 · A2 내레이션.
// 옮겨지지 않는 것: 제목 · 자막 디자인 · 강조 글자(프리미어가 XML 로 글자 디자인을 못 받는다) — 자막 글자는 SRT 두 개로 준다.
const FPS=30,SEQ_W=1080,SEQ_H=1920;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const fr=sec=>Math.round(Number(sec||0)*FPS);
const epName=e=>{const t=String(e??'').trim();return !t?'':/^\d+$/.test(t)?t+'화':t;};   // '1' → '1화', '1화' 는 그대로
const safe=s=>String(s||'').replace(/[\\/:*?"<>|\n\r\t]+/g,' ').replace(/\s+/g,' ').trim().slice(0,60)||'영상';

async function rows(q){const {data,error}=await q;if(error)throw Error(error.message);return data||[];}

// 편 기록 파일 하나(JSON) — tikitaka_videos.files 의 저장소 열쇠로
async function signed(client,bucket,key,opts){const {data,error}=await client.storage.from(bucket).createSignedUrl(key,3600,opts);if(error)throw Error(error.message);return data.signedUrl;}
async function bundleJson(client,files,name,need=true){
 const f=files[name];if(!f){if(need)throw Error(`영상 기록에 ${name} 이 없어요.`);return null;}
 const r=await fetch(await signed(client,'ves-outputs',f.key));if(!r.ok)throw Error(`${name} 를 받지 못했어요.`);return r.json();
}
async function bundleBlob(client,files,name){
 const f=files[name];if(!f)throw Error(`영상 기록에 ${name} 이 없어요.`);
 const r=await fetch(await signed(client,'ves-outputs',f.key));if(!r.ok)throw Error(`${name} 를 받지 못했어요.`);return r.blob();
}

// 원본 정보와 받기 주소(파일 이름을 붙여서 — 원본은 저장소에 확장자 없이 있다)
export async function sourceOf(client,wo){
 const [w]=await rows(client.from('work_orders').select('source_sha256').eq('id',wo).limit(1));
 if(!w?.source_sha256)throw Error('이 영상의 원본을 찾지 못했어요.');
 const [s]=await rows(client.from('sources').select('object_key,bytes,duration_sec,work_title,episode').eq('sha256',w.source_sha256).limit(1));
 if(!s?.object_key)throw Error('이 영상의 원본을 찾지 못했어요.');
 const name=`원본_${safe(s.work_title)}${s.episode!=null?'_'+epName(s.episode):''}.mp4`;
 return {...s,name,sha:w.source_sha256};
}
export async function sourceUrl(client,src){return signed(client,'ves-sources',src.object_key,{download:src.name});}

function srt(list){
 const t=x=>{const ms=Math.max(0,Math.round(x*1000)),h=Math.floor(ms/3600000),m=Math.floor(ms/60000)%60,s=Math.floor(ms/1000)%60;return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')},${String(ms%1000).padStart(3,'0')}`;};
 return list.filter(x=>x&&x.text).map((x,i)=>`${i+1}\n${t(x.start_sec)} --> ${t(x.end_sec)}\n${String(x.text).trim()}\n`).join('\n');
}

// 컷 하나의 화면 자리: 원본에서 자른 네모(framing clips[i].segs 중 가장 긴 것)를 세로 화면의 영상 칸(band)에 맞춘다
function baseSeg(clipFraming,framing){
 const src=framing?.source||{w:1920,h:1080},segs=clipFraming?.segs||[];
 return segs.reduce((a,b)=>(!a||(b.t1-b.t0)>(a.t1-a.t0))?b:a,null)||{x:0,y:0,w:src.w,h:src.h};
}
// 줌 — 엔진처럼 자르는 창을 1/배율로 줄여 anchor(왼·가운데·오른) 쪽으로 당긴다(영상 칸 크기는 그대로)
function zoomSeg(seg,factor,anchor,framing){
 if(!factor||factor===1)return seg;
 const src=framing?.source||{w:1920,h:1080},w=seg.w/factor,h=seg.h/factor;
 let x=anchor==='left'?seg.x:anchor==='right'?seg.x+seg.w-w:seg.x+(seg.w-w)/2,y=seg.y+(seg.h-h)/2;
 x=Math.min(Math.max(0,x),src.w-w);y=Math.min(Math.max(0,y),src.h-h);
 return {x,y,w,h};
}
function motion(seg,framing){
 const src=framing?.source||{w:1920,h:1080},band=framing?.band||{x:0,y:(SEQ_H-SEQ_W*9/16)/2,w:SEQ_W,h:SEQ_W*9/16};
 const s=band.w/seg.w;
 const bx=band.x+band.w/2,by=band.y+band.h/2,cx=seg.x+seg.w/2,cy=seg.y+seg.h/2;
 const px=bx+(src.w/2-cx)*s,py=by+(src.h/2-cy)*s;
 const pct=v=>Math.max(0,Math.min(100,v));
 return {scale:+(s*100).toFixed(3),horiz:+((px-SEQ_W/2)/SEQ_W).toFixed(5),vert:+((py-SEQ_H/2)/SEQ_H).toFixed(5),
  left:pct(seg.x/src.w*100),right:pct((src.w-seg.x-seg.w)/src.w*100),top:pct(seg.y/src.h*100),bottom:pct((src.h-seg.y-seg.h)/src.h*100)};
}
const rate='<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>';
const param=(id,name,val,min,max)=>`<parameter><parameterid>${id}</parameterid><name>${name}</name>${min!=null?`<valuemin>${min}</valuemin><valuemax>${max}</valuemax>`:''}<value>${val}</value></parameter>`;
const effect=(name,id,body,media='video')=>`<filter><effect><name>${name}</name><effectid>${id}</effectid><effectcategory>motion</effectcategory><effecttype>motion</effecttype><mediatype>${media}</mediatype>${body}</effect></filter>`;
const level=db=>`<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid><effectcategory>audiolevels</effectcategory><effecttype>audiolevels</effecttype><mediatype>audio</mediatype>${param('level','Level',Math.pow(10,db/20).toFixed(4),0,3.98109)}</effect></filter>`;
const fileDef=(id,name,frames,media)=>`<file id="${id}"><name>${esc(name)}</name><pathurl>file://localhost/media/${encodeURIComponent(name)}</pathurl>${rate}<duration>${frames}</duration><media>${media}</media></file>`;

// XML 프로젝트(파이널컷 7 XML) — 프리미어 · 리졸브가 연다
// 줌 단계로 컷을 나눈다 — 엔진과 같은 경계 규칙(0.3초 미만 조각은 앞 단계에 흡수). 새 엔진은 원음 컷에도 줌을 쓴다
// (v10 완성본 51초 확인) — 프리미어는 컷을 나눠도 소리가 끊기지 않는다
const ZOOM_MIN=0.3;
function zoomParts(c,z){
 const s0=c.clip_start_sec,e0=c.clip_end_sec,speed=Number(c.playback_speed||1),len=(e0-s0)/speed;
 if(!z)return [{a:s0,b:e0,factor:1,anchor:'center',hold:Number(c.hold_sec||0)}];
 const stages=(z.stages||[]).slice().sort((x,y)=>x.from_sec-y.from_sec);
 const bounds=[];
 for(const st of stages){let fs=Math.max(0,Math.round((st.from_sec||0)*FPS)/FPS);
  if(bounds.length&&(fs-bounds[bounds.length-1][0]<ZOOM_MIN||len-fs<ZOOM_MIN))continue;
  if(!bounds.length&&fs>0&&(fs<ZOOM_MIN||len-fs<ZOOM_MIN))fs=0;
  bounds.push([fs,st]);}
 if(bounds.length&&bounds[0][0]>0)bounds.unshift([0,{factor:1,anchor:bounds[0][1].anchor}]);
 if(!bounds.length)return [{a:s0,b:e0,factor:1,anchor:'center',hold:Number(c.hold_sec||0)}];
 return bounds.map(([fs,st],j)=>({a:s0+fs*speed,b:j+1<bounds.length?s0+bounds[j+1][0]*speed:e0,factor:Number(st.factor||1),anchor:st.anchor||'center',hold:j+1<bounds.length?0:Number(c.hold_sec||0)}));
}

export function buildXml({title,plan,framing,cues,src,finalName,finalFrames,ttsNames,zooms=[],logos=[]}){
 const tl=plan.timeline||[],srcFrames=fr(src.duration_sec||0)||fr(Math.max(...tl.map(c=>c.clip_end_sec))+60);
 const srcW=framing?.source?.w||1920,srcH=framing?.source?.h||1080;
 const gain={orig:plan.audio_mix?.original_gain_db??-3,tts:plan.audio_mix?.tts_gain_db??-3};
 let off=0,first=true;const v=[],a=[];
 const zoomOf=new Map((zooms||[]).map(z=>[z.clip,z]));let k=0;
 tl.forEach((c,i)=>{
  const speed=Number(c.playback_speed||1),seg0=baseSeg(framing?.clips?.[i],framing);
  for(const part of zoomParts(c,zoomOf.get(i))){
  const dur=Math.round(((part.b-part.a)/speed+part.hold)*FPS);
  const start=off,end=off+dur;off=end;
  const inF=fr(part.a),outF=fr(part.b),m=motion(zoomSeg(seg0,part.factor,part.anchor,framing),framing),n=k++;
  const file=first?fileDef('src',src.name,srcFrames,`<video><samplecharacteristics>${rate}<width>${srcW}</width><height>${srcH}</height></samplecharacteristics></video><audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics><channelcount>2</channelcount></audio>`):'<file id="src"/>';first=false;
  const remap=speed!==1?effect('Time Remap','timeremap',param('variablespeed','variablespeed',0,0,1)+param('speed','speed',(speed*100).toFixed(3),-100000,100000)+param('reverse','reverse','FALSE')+param('frameblending','frameblending','FALSE')):'';
  const links=`<link><linkclipref>v${n}</linkclipref><mediatype>video</mediatype><trackindex>1</trackindex><clipindex>${n+1}</clipindex></link><link><linkclipref>a${n}</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex><clipindex>${n+1}</clipindex><groupindex>1</groupindex></link>`;
  v.push(`<clipitem id="v${n}"><name>${i+1}. ${esc(c.role||'컷')} ${part.a.toFixed(1)}s${part.factor!==1?` 줌 ${part.factor}×`:''}</name><enabled>TRUE</enabled><duration>${srcFrames}</duration>${rate}<start>${start}</start><end>${end}</end><in>${inF}</in><out>${outF}</out>${file}
   ${remap}${effect('Basic Motion','basic',param('scale','Scale',m.scale,0,1000)+`<parameter><parameterid>center</parameterid><name>Center</name><value><horiz>${m.horiz}</horiz><vert>${m.vert}</vert></value></parameter>`)}
   ${effect('Crop','crop',param('left','left',m.left.toFixed(3),0,100)+param('right','right',m.right.toFixed(3),0,100)+param('top','top',m.top.toFixed(3),0,100)+param('bottom','bottom',m.bottom.toFixed(3),0,100))}${links}</clipitem>`);
  // 원음 — 내레이션이 걸친 컷은 AI 가 원음을 껐다(use_original_audio=false · 덮개). 끈 채로 두고 필요하면 켠다
  const on=c.use_original_audio!==false&&!c.cover;
  a.push(`<clipitem id="a${n}"><name>원음 ${i+1}</name><enabled>${on?'TRUE':'FALSE'}</enabled><duration>${srcFrames}</duration>${rate}<start>${start}</start><end>${end}</end><in>${inF}</in><out>${outF}</out><file id="src"/><sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>${speed!==1?effect('Time Remap','timeremap',param('variablespeed','variablespeed',0,0,1)+param('speed','speed',(speed*100).toFixed(3),-100000,100000),'audio'):''}${level(gain.orig)}${links}</clipitem>`);
  }
 });
 const total=off;
 const tts=cues.map((q,i)=>{const s=fr(q.cue.start_sec),d=Math.max(1,fr(q.cue.fit_actual_sec||q.cue.duration_sec||(q.cue.end_sec-q.cue.start_sec)));
  return `<clipitem id="t${i}"><name>내레이션 ${i+1}</name><enabled>TRUE</enabled><duration>${d}</duration>${rate}<start>${s}</start><end>${s+d}</end><in>0</in><out>${d}</out>${fileDef('tts'+i,ttsNames[i],d,'<audio><channelcount>1</channelcount></audio>')}<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>${level(gain.tts)}</clipitem>`;}).join('');
 const logoItems=logos.map((L,i)=>{const sc=L.w/L.natW;return `<clipitem id="logo${i}"><name>${esc(L.label)}</name><enabled>TRUE</enabled><duration>${Math.max(total,finalFrames)}</duration>${rate}<start>0</start><end>${Math.max(total,finalFrames)}</end><in>0</in><out>${Math.max(total,finalFrames)}</out>${fileDef('logo'+i,L.name,Math.max(total,finalFrames),`<video><samplecharacteristics><width>${L.natW}</width><height>${L.natH}</height></samplecharacteristics></video>`)}${effect('Basic Motion','basic',param('scale','Scale',(sc*100).toFixed(3),0,1000)+`<parameter><parameterid>center</parameterid><name>Center</name><value><horiz>${((L.x+L.w/2-SEQ_W/2)/SEQ_W).toFixed(5)}</horiz><vert>${((L.y+L.h/2-SEQ_H/2)/SEQ_H).toFixed(5)}</vert></value></parameter>`)}</clipitem>`;}).join('');
 const ref=`<clipitem id="ref"><name>AI 완성본(비교용)</name><enabled>FALSE</enabled><duration>${finalFrames}</duration>${rate}<start>0</start><end>${finalFrames}</end><in>0</in><out>${finalFrames}</out>${fileDef('final',finalName,finalFrames,`<video><samplecharacteristics>${rate}<width>${SEQ_W}</width><height>${SEQ_H}</height></samplecharacteristics></video>`)}</clipitem>`;
 return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4"><sequence id="seq"><name>${esc(title)}</name><duration>${Math.max(total,finalFrames)}</duration>${rate}
<media><video><format><samplecharacteristics>${rate}<width>${SEQ_W}</width><height>${SEQ_H}</height><pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance></samplecharacteristics></format>
<track>${v.join('\n')}</track>
${logoItems?`<track>${logoItems}</track>`:''}
<track>${ref}</track></video>
<audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>
<track>${a.join('\n')}</track>
<track>${tts}</track></audio></media></sequence></xmeml>`;
}

// zip(압축 없이 담기만 — 영상·mp3 는 이미 압축돼 있다). 한글 파일 이름(UTF-8 표시 비트)
const CRC=(()=>{const t=new Uint32Array(256);for(let n=0;n<256;n++){let c=n;for(let k=0;k<8;k++)c=c&1?0xedb88320^(c>>>1):c>>>1;t[n]=c>>>0;}return t;})();
function crc32(buf){let c=0xffffffff;for(let i=0;i<buf.length;i++)c=CRC[(c^buf[i])&0xff]^(c>>>8);return (c^0xffffffff)>>>0;}
export async function zip(entries){   // 시험용으로도 내보냄
 const enc=new TextEncoder(),parts=[],central=[];let off=0;
 for(const [name,data] of entries){
  const bytes=typeof data==='string'?enc.encode(data):new Uint8Array(await data.arrayBuffer()),nm=enc.encode(name),crc=crc32(bytes);
  const h=new DataView(new ArrayBuffer(30));h.setUint32(0,0x04034b50,true);h.setUint16(4,20,true);h.setUint16(6,0x0800,true);h.setUint32(14,crc,true);h.setUint32(18,bytes.length,true);h.setUint32(22,bytes.length,true);h.setUint16(26,nm.length,true);
  parts.push(h,nm,bytes);
  const cd=new DataView(new ArrayBuffer(46));cd.setUint32(0,0x02014b50,true);cd.setUint16(4,20,true);cd.setUint16(6,20,true);cd.setUint16(8,0x0800,true);cd.setUint32(16,crc,true);cd.setUint32(20,bytes.length,true);cd.setUint32(24,bytes.length,true);cd.setUint16(28,nm.length,true);cd.setUint32(42,off,true);
  central.push(cd,nm);off+=30+nm.length+bytes.length;
 }
 const size=central.reduce((n,p)=>n+(p.byteLength??p.length),0),e=new DataView(new ArrayBuffer(22));
 e.setUint32(0,0x06054b50,true);e.setUint16(8,entries.length,true);e.setUint16(10,entries.length,true);e.setUint32(12,size,true);e.setUint32(16,off,true);
 return new Blob([...parts,...central,e],{type:'application/zip'});
}
function save(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),60000);}

// 로고 — 맥미니가 번들에 같이 올린 로고(assets/logo_work · logo_platform, 오케스트레이터 #103)를 렌더 디자인의 자리에.
// 작품 로고 자리는 엔진 finalize.estimate_work_top 과 같은 식(영상 칸 아래 + 간격, 하단 캡션만큼 위로)이지만
// 자막이 길어 엔진이 로고를 더 내린 편은 몇 px 다를 수 있다
async function logoItems(client,files,design,framing){
 const out=[],pick=n=>Object.keys(files).find(k=>k.startsWith('assets/'+n+'.'));
 const band=framing?.band||{x:0,y:420,w:SEQ_W,h:944},bandBottom=band.y+band.h;
 const load=async(rel,label,name)=>{const blob=await bundleBlob(client,files,rel);const bmp=await createImageBitmap(blob);const r={blob,label,name:name+rel.slice(rel.lastIndexOf('.')),natW:bmp.width,natH:bmp.height};bmp.close?.();return r;};
 const w=pick('logo_work');
 if(w&&design.work_type==='image'){
  const L=await load(w,'작품 로고','작품로고');
  const boxW=Number(design.work_image_width||350),boxH=Number(design.work_image_height||0)||L.natH*boxW/L.natW;
  const sc=Math.min(boxW/L.natW,boxH/L.natH);L.w=Math.round(L.natW*sc);L.h=Math.max(2,Math.floor(L.natH*sc/2)*2);
  const off=design.work_band_offset,safe=bandBottom+(off!=null?Number(off):20);
  const cap=design.work_caption?Math.round(Number(design.work_caption_font_size||40)*1.4)+10:0,bottom=SEQ_H-20-cap;
  let y=safe;if(design.work_image_align==='center'&&off==null)y=safe+Math.floor((bottom-safe-L.h)/2);if(y+L.h>bottom)y=bottom-L.h;
  L.x=Math.round((SEQ_W-L.w)/2);L.y=Math.max(safe,y);out.push(L);
 }
 const pf=pick('logo_platform');
 if(pf){
  const L=await load(pf,'플랫폼 로고','플랫폼로고');
  const boxW=Number(design.platform_image_width||180),boxH=Number(design.platform_image_height||0)||L.natH*boxW/L.natW;
  const sc=Math.min(boxW/L.natW,boxH/L.natH);L.w=Math.round(L.natW*sc);L.h=Math.round(L.natH*sc);
  const al=design.platform_align||'left',px=Number(design.platform_x??40);
  L.x=al==='center'?Math.round((SEQ_W-L.w)/2):al==='right'?Math.round(SEQ_W-px-L.w):px;L.y=Number(design.platform_y??60);out.push(L);
 }
 return out;
}

// 묶음 만들기 — progress(글) 로 진행을 알린다
export async function buildPackage(client,{wo,suffix},progress=()=>{}){
 progress('영상 기록을 읽는 중…');
 const [row]=await rows(client.from('tikitaka_videos').select('title,work_title,episode,files,duration_sec').eq('work_order_id',wo).eq('suffix',suffix).limit(1));
 if(!row)throw Error('영상을 찾지 못했어요.');
 const files=row.files||{};
 const [plan,framing,res,caps,subs,src,fx,video]=await Promise.all([bundleJson(client,files,'edit_plan.json'),bundleJson(client,files,'framing.json',false),
  bundleJson(client,files,'checkpoint_resources.json'),bundleJson(client,files,'tts_caption_segments.json',false),bundleJson(client,files,'subtitle_segments.json',false),sourceOf(client,wo),
  bundleJson(client,files,'fx.json',false),bundleJson(client,files,'video.json',false)]);
 const design=video?.provenance?.render?.design||{};
 const cues=(res.tts_cue_files||[]).filter(q=>q.path&&files[q.path]);
 const base=safe(`${row.work_title} ${epName(row.episode)} ${suffix} ${String(row.title||'').replace(/\n/g,' ')}`),dir=base+'/';
 progress(`내레이션 ${cues.length}개를 받는 중…`);
 const tts=await Promise.all(cues.map(q=>bundleBlob(client,files,q.path)));
 progress('AI 완성본을 받는 중…');
 const final=await bundleBlob(client,files,'shorts.mp4'),finalName=`AI완성본_${suffix}.mp4`;
 const ttsNames=cues.map((q,i)=>`내레이션_${String(i+1).padStart(2,'0')}.mp3`);
 progress('로고를 받는 중…');
 const logos=await logoItems(client,files,design,framing);
 const xml=buildXml({title:base,plan,framing,cues,src,finalName,finalFrames:fr(row.duration_sec||0)||fr(plan.timeline.reduce((n,c)=>n+(c.clip_end_sec-c.clip_start_sec)/(c.playback_speed||1),0)),ttsNames,zooms:fx?.zooms||[],logos});
 progress('묶는 중…');
 const blob=await zip([[dir+base+'.xml',xml],[dir+'자막_내레이션.srt',srt(caps||[])],[dir+'자막_대사.srt',srt(subs||[])],
  [dir+'media/'+finalName,final],...tts.map((b,i)=>[dir+'media/'+ttsNames[i],b]),...logos.map(L=>[dir+'media/'+L.name,L.blob])]);
 return {blob,name:base+'.zip',src,xmlName:base+'.xml'};
}

// 창 — 두 단계: 편집 파일 받기 · 원본 받기(회차당 한 번). 여는 방법은 zip 안 글 파일 대신 이 창에 보여 준다
export function openPremiereExport(client,{wo,suffix}){
 const d=document.createElement('dialog');d.className='pr-export';d.setAttribute('aria-labelledby','pr-title');
 d.innerHTML=`<header><h2 id="pr-title">프리미어로 내보내기</h2><button type="button" class="pr-x" aria-label="닫기">×</button></header>
  <p class="pr-lead">AI 가 만든 컷을 프리미어 프로 타임라인으로 열어요. 컷 끝을 늘리거나 원본에서 장면을 더 넣을 수 있어요. 다빈치 리졸브도 같은 파일을 열어요.</p>
  <ol class="pr-steps"><li><div><b>편집 파일 받기</b><small>XML 프로젝트 · 내레이션 · 자막 · AI 완성본(수십 MB)</small></div><button type="button" class="pr-pack">${icon('download')}<span>받기</span></button></li>
  <li><div><b>원본 영상 받기</b><small class="pr-src">원본 정보를 확인하는 중…</small></div><a class="pr-orig" aria-disabled="true">${icon('download')}<span>받기</span></a></li></ol>
  <p class="pr-msg" role="status"></p>
  <section class="pr-how"><h3>프리미어에서 여는 방법</h3><ol>
   <li>받은 zip 을 풀고, 원본 영상을 그 안의 <b>media</b> 폴더에 넣어요.</li>
   <li>프리미어 프로에서 <b>파일 &gt; 가져오기</b>로 폴더 안의 <b class="pr-xml">XML 파일</b>을 열어요.</li>
   <li>파일을 찾으라고 나오면 media 폴더의 파일 하나를 골라요. 나머지는 저절로 연결돼요.</li>
   <li>자막 글자는 <b>자막_내레이션.srt</b> · <b>자막_대사.srt</b> 를 같은 방법으로 가져와요.</li></ol>
   <details><summary>타임라인 구성</summary><ul>
    <li><b>비디오 1</b> 원본 컷 · 컷 끝을 늘리면 원본 앞뒤 장면이 이어서 나와요</li>
    <li><b>비디오 2</b> 로고 · AI 와 같은 그림을 같은 자리에</li>
    <li><b>비디오 3</b> AI 완성본(꺼 둠) · 켜면 비교할 수 있어요</li>
    <li><b>오디오 1</b> 원음 · 내레이션이 나오는 컷은 꺼 두었어요</li>
    <li><b>오디오 2</b> 내레이션</li>
    <li>줌은 AI 처럼 컷을 나눠 확대해 두었어요.</li></ul></details>
   <div class="pr-limit"><b>프리미어로 옮겨지지 않는 것</b><p>제목 · 자막 디자인 · 강조 글자는 우리 엔진이 전용 글꼴과 움직임으로 그리는데, 프리미어는 이런 글자를 XML 로 받지 못해요. 자막 글자는 SRT 로 불러와 프리미어에서 스타일을 입혀 주세요. 로고 자리는 AI 완성본과 몇 px 다를 수 있어요.</p></div>
  </section>`;
 document.body.append(d);d.showModal();
 const close=()=>{d.close();d.remove();};d.querySelector('.pr-x').onclick=close;d.addEventListener('click',e=>{if(e.target===d)close();});
 const msg=d.querySelector('.pr-msg'),orig=d.querySelector('.pr-orig');
 sourceOf(client,wo).then(async src=>{
  d.querySelector('.pr-src').textContent=`${src.name} · ${(src.bytes/1073741824).toFixed(1)}GB · 회차당 한 번이면 돼요`;
  orig.href=await sourceUrl(client,src);orig.removeAttribute('aria-disabled');orig.setAttribute('download',src.name);
 }).catch(e=>{d.querySelector('.pr-src').textContent=e.message;});
 d.querySelector('.pr-pack').onclick=async e=>{
  const b=e.currentTarget;b.disabled=true;msg.classList.remove('pr-err');
  try{const {blob,name,xmlName}=await buildPackage(client,{wo,suffix},t=>{msg.textContent=t;});save(blob,name);msg.textContent=`${name} 을 받았어요.`;d.querySelector('.pr-xml').textContent=xmlName;}
  catch(err){msg.textContent=err.message;msg.classList.add('pr-err');}
  finally{b.disabled=false;}
 };
 return d;
}
