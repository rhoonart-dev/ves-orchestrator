// 가로로만 넘치는 영역(좁은 화면의 포스터·칩 줄, 넓은 표 등)을 마우스 휠(세로)로도 옆으로 넘긴다 — 앱 전체에 한 번 건다.
// 휠 아래에서 가장 가까운 '가로로 넘치고 세로로는 안 넘치는' 영역을 찾아 옆으로 민다. 끝에 닿으면 원래대로 페이지가 스크롤된다.
// 트랙패드 가로 밀기(deltaX)와 Shift+휠은 브라우저에 맡긴다.
const scrollsX=el=>{const o=getComputedStyle(el).overflowX;return (o==='auto'||o==='scroll')&&el.scrollWidth>el.clientWidth+1;};
const scrollsY=el=>{const o=getComputedStyle(el).overflowY;return (o==='auto'||o==='scroll')&&el.scrollHeight>el.clientHeight+1;};
export function setupWheelScroll(){
 document.addEventListener('wheel',e=>{
  if(e.ctrlKey||e.shiftKey||Math.abs(e.deltaX)>=Math.abs(e.deltaY))return;
  for(let el=e.target instanceof Element?e.target:null;el&&el!==document.body;el=el.parentElement){
   if(scrollsY(el))return;                       // 세로로 넘기는 영역 안이면 그대로 둔다
   if(!scrollsX(el))continue;
   const max=el.scrollWidth-el.clientWidth;
   if((e.deltaY<0&&el.scrollLeft<=0)||(e.deltaY>0&&el.scrollLeft>=max-1))return;
   e.preventDefault();el.scrollLeft+=e.deltaY;return;
  }
 },{passive:false,capture:true});
}
