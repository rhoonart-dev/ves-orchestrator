// Local folder metadata snapshot; channel assignments are preview-only.
export const sampleJobs = [
  {
    "id": "LOCAL-D43E6333",
    "channelId": "fun",
    "channel": "재미쇼츠",
    "workId": "lotto",
    "work": "로또 1등도 출근합니다",
    "episode": "1–2화",
    "title": "1–2화 선공개 · 티키타카",
    "raw": "로또_1등도_출근합니다_1-2화_선공개_staged",
    "createdAt": "2026-09-22T09:22:43.250233+00:00",
    "videos": 12,
    "status": "로컬 렌더",
    "fileCountLabel": "렌더 파일",
    "dateKind": "수정일"
  },
  {
    "id": "LOCAL-7BD7EDBC",
    "channelId": "room",
    "channel": "락커룸",
    "workId": "lotto",
    "work": "로또 1등도 출근합니다",
    "episode": "1–2화",
    "title": "1–2화 · 통합 작업",
    "raw": "로또_1등도_출근합니다_1-2화_concat",
    "createdAt": "2026-09-18T06:57:08.544151+00:00",
    "videos": 13,
    "status": "로컬 렌더",
    "fileCountLabel": "렌더 파일",
    "dateKind": "수정일"
  },
  {
    "id": "LOCAL-70D47C09",
    "channelId": "pub",
    "channel": "한입주막",
    "workId": "gawang",
    "work": "가왕쇼",
    "episode": "10화",
    "title": "10화 · 기본 작업",
    "raw": "가왕쇼_10_20260917",
    "createdAt": "2026-09-17T07:39:40.878275+00:00",
    "videos": 14,
    "status": "로컬 렌더",
    "fileCountLabel": "렌더 파일",
    "dateKind": "수정일"
  },
  {
    "id": "LOCAL-89DA5935",
    "channelId": "pub",
    "channel": "한입주막",
    "workId": "gawang",
    "work": "가왕쇼",
    "episode": "9화",
    "title": "9화 · 기본 작업",
    "raw": "가왕쇼_9_20260916_full",
    "createdAt": "2026-09-17T02:06:44.604802+00:00",
    "videos": 7,
    "status": "로컬 렌더",
    "fileCountLabel": "렌더 파일",
    "dateKind": "수정일"
  },
  {
    "id": "LOCAL-9BBF9EB9",
    "channelId": "dip",
    "channel": "부먹?찍먹?",
    "workId": "jigeum",
    "work": "지금 불륜이 문제가 아닙니다(c)",
    "episode": "4화",
    "title": "4화 · 최종 수정본",
    "raw": "지금불륜_4화_납품",
    "createdAt": "2026-09-18T12:32:53.433468+00:00",
    "videos": 8,
    "status": "로컬 렌더",
    "fileCountLabel": "렌더 파일",
    "dateKind": "수정일"
  },
  {
    "id": "LOCAL-B7940F5E",
    "channelId": "fun",
    "channel": "재미쇼츠",
    "workId": "jigeum",
    "work": "지금 불륜이 문제가 아닙니다(c)",
    "episode": "3화",
    "title": "3화 · 단계별 구성",
    "raw": "지금_불륜이_문제가_아닙니다_3_staged_ab",
    "createdAt": "2026-09-21T08:56:01.005986+00:00",
    "videos": 5,
    "status": "로컬 렌더",
    "fileCountLabel": "렌더 파일",
    "dateKind": "수정일"
  },
  {
    "id": "LOCAL-C32BFEAF",
    "channelId": "room",
    "channel": "락커룸",
    "workId": "sinbyeong",
    "work": "신병",
    "episode": "회차 미지정",
    "title": "회차 미지정 · 기본 작업",
    "raw": "신병4_4bf77cff",
    "createdAt": "2026-09-04T10:23:03.139055+00:00",
    "videos": 1,
    "status": "로컬 렌더",
    "fileCountLabel": "렌더 파일",
    "dateKind": "수정일"
  }
];
export function filterOptions(jobs,mode){
 if(mode==='all')return [];
 const groups=new Map();
 for(const job of jobs){
  const id=mode==='channel'?job.channelId:job.workId;
  const name=mode==='channel'?job.channel:job.work;
  if(!id)continue;
  const entry=groups.get(id)||{id,name,count:0,avatar:mode==='channel'?job.channelAvatar||null:null};entry.count++;groups.set(id,entry);
 }
 return [...groups.values()].sort((a,b)=>a.name.localeCompare(b.name,'ko'));
}
export function visibleJobs(jobs,{mode='all',selected=null,query='',sort='newest'}={}){
 const q=query.trim().toLocaleLowerCase('ko');
 return jobs.filter(j=>(mode==='all'||!selected||(mode==='channel'?j.channelId:j.workId)===selected)&&(!q||[j.id,j.title,j.work,j.channel,j.episode].filter(Boolean).join(' ').toLocaleLowerCase('ko').includes(q)))
 .sort((a,b)=>(sort==='oldest'?1:-1)*(Date.parse(a.createdAt)-Date.parse(b.createdAt))||a.id.localeCompare(b.id));
}
