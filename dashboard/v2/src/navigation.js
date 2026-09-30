export const groups=[
 {name:'홈',items:[['home','홈','home']]},
 {name:'검수',items:[['review','작업 목록','list'],['rights','권리사 검수','file'],['videos','전체 영상','video'],['editor','편집실','pencil'],['history','작업 이력','clock']]},
 {name:'채널',items:[['channels','채널 관리','tv'],['channel-templates','채널 템플릿','layout'],['performance','성과','chart']]},
 {name:'작품',items:[['works','작품 관리','library'],['archive','소재 아카이브','archive']]},
 {name:'발행 일정',items:[['schedule','발행 일정','calendar']]},
 {name:'운영·관리',items:[['nodes','맥·배포','monitor'],['trends','트렌드','trend'],['access','권한 관리','key']]}
];
export const routes=new Map(groups.flatMap(g=>g.items.map(([id,title,icon])=>[id,{id,title,icon}])));
