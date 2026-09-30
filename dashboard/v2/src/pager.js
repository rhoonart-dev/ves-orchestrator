// 쪽 넘기기 — 모든 탭이 같은 모양(‹ 2/8 ›, 권리사 검수 탭과 같다). 모양은 styles.css .ws-pager
// prev/next: 버튼에 붙일 속성 문자열(예: data-page="1" · onclick="…"). 쪽이 하나뿐이면 빈 문자열.
const chev=d=>`<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${d}"/></svg>`;
export function pagerHtml({cur,pages,label='페이지',prev='',next=''}){
 if(pages<=1)return '';
 return `<nav class="ws-pager" aria-label="${label}"><button type="button" ${prev} ${cur<=0?'disabled':''} aria-label="이전 페이지">${chev('m12 5-5 5 5 5')}</button><span class="ws-page-pos" role="status" aria-live="polite">${cur+1}/${pages}</span><button type="button" ${next} ${cur>=pages-1?'disabled':''} aria-label="다음 페이지">${chev('m8 5 5 5-5 5')}</button></nav>`;
}
