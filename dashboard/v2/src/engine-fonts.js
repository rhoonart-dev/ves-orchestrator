// 엔진 폰트 중 파일을 나눠 주면 안 되는 것(배포 금지 · 수정 금지 사용권)은 공개 저장소에 두지 않는다.
// Supabase 비공개 저장소(ves-fonts)에 두고, 로그인한 사람에게만 서명 링크로 불러와 같은 이름으로 등록한다(2026-10-02).
// 미리보기 CSS 는 이름(EngineJalnan 등)만 쓰므로 그대로다. OFL 폰트(본고딕 · 물마루)는 assets/fonts/engine 에 그대로 있다.
const PRIVATE={EngineJalnan:'Jalnan.ttf',EngineJalnanGothic:'JalnanGothic.ttf',EngineGriun:'Griun.ttf',EngineWaguri:'WAGURI.ttf'};
const KEY='ves-engine-fonts',TTL=6*24*3600;   // 서명 링크 7일 — 하루 남기고 새로 받는다(같은 링크면 브라우저 캐시를 그대로 쓴다)
let started=null;

function cached(){
 try{const v=JSON.parse(localStorage.getItem(KEY)||'null');if(v&&v.until>Date.now()&&v.urls&&v.files===JSON.stringify(PRIVATE))return v.urls;}catch{}   // 폰트 목록이 바뀌면 새로 받는다
 return null;
}
async function signed(client){
 const hit=cached();if(hit)return hit;
 const files=Object.values(PRIVATE);
 const {data,error}=await client.storage.from('ves-fonts').createSignedUrls(files,TTL+24*3600);
 if(error)throw error;
 const byFile=new Map((data||[]).filter(x=>x.signedUrl).map(x=>[x.path,x.signedUrl]));
 const urls=Object.fromEntries(Object.entries(PRIVATE).filter(([,f])=>byFile.has(f)).map(([n,f])=>[n,byFile.get(f)]));
 try{localStorage.setItem(KEY,JSON.stringify({until:Date.now()+TTL*1000,urls,files:JSON.stringify(PRIVATE)}));}catch{}
 return urls;
}

// 한 번만 — 다 들어오면 미리보기 배치(제목 줄바꿈 · 크기 맞춤)를 다시 잰다
export function loadEngineFonts(client){
 if(started||!client)return started;
 started=signed(client).then(urls=>Promise.all(Object.entries(urls).map(([name,url])=>
  new FontFace(name,`url("${url}")`,{display:'swap'}).load().then(f=>{document.fonts.add(f);return name;}).catch(()=>null))))
  .then(done=>{
   window.layoutShorts?.();window.dispatchEvent(new CustomEvent('engine-fonts',{detail:done.filter(Boolean)}));
   return done;
  })
  .catch(()=>{started=null;return [];});   // 다음에 다시 시도(로그인 전이었거나 저장소가 잠깐 안 될 때)
 return started;
}
