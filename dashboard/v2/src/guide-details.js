/* Derived on every open from the same raw record used by the full guide.
   No stored AI summaries or independently edited required phrases. */
export const GuideDetails = (() => {
 function activeText(el){const clone=el.cloneNode(true);clone.querySelectorAll('s,strike,del').forEach(n=>n.remove());return clone.textContent.trim()}
 function derive(record){
  const doc=new DOMParser().parseFromString(record.guide||'','text/html');
  const blocks=Array.from(doc.body.querySelectorAll('p,li,h1,h2,h3,h4,blockquote')).filter(e=>!e.querySelector('p,li,h1,h2,h3,h4,blockquote'));
  const descriptions=[];
  for(let i=0;i<blocks.length;i++){
   const block=blocks[i],text=activeText(block);
   // Surface evidence, never infer a new requirement from prose.
   if(!/(?:설명란.{0,28}(?:필수|삽입|문구)|(?:필수|문구).{0,15}설명란)/.test(text))continue;
   if(/검수.*(?:링크|제출)/.test(text))continue;
   let evidence=[block];
   const next=blocks.slice(i+1).find(e=>activeText(e));
   if(block.querySelector('s,strike,del')&&next&&/(?:업데이트|이후|제외|변경)/.test(activeText(next)))evidence.push(next);
   let copyText=text,exact=false;
   const quoted=text.match(/["“]([^"”]+)["”]/);
   if(quoted&&/필수.*(?:기입|삽입)|(?:기입|삽입).*필수/.test(text)){copyText=quoted[1];exact=true}
   else if(/필수\s*(?:삽입\s*)?문구\s*[:：]/.test(text)&&!block.querySelector('s,strike,del')){copyText=text.split(/필수\s*(?:삽입\s*)?문구\s*[:：]/).slice(1).join(':').trim();exact=!!copyText}
   else copyText=evidence.map(activeText).join('\n');
   descriptions.push({copyText,exact,evidence:evidence.map(e=>e.outerHTML).join('')});
  }
  const geoEvidence=blocks.filter(e=>/지오\s*블[락록]|geo.?block/i.test(activeText(e))).map(e=>e.outerHTML).join('');
  const hashtagValue=record.required_hashtags_description||'';
  const mixedTags=hashtagValue.trim()&&!/^(?:\s*#[^\s,#]+[\s,]*)+$/.test(hashtagValue);
  return {descriptions,geoEvidence,mixedTags};
 }
 return {derive};
})();
