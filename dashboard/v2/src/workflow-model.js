// Rights policy is independent of internal review status. Unknown must not bypass it.
export function inspectionRoute(policy,{isAired=null}={}){
 if(policy==='required')return 'rights';
 if(policy==='none')return 'direct';
 if(policy==='unaired_only')return isAired===true?'direct':isAired===false?'rights':'check-airing';
 return 'check-policy';
}
export function policyForWork(works,title){
 const rows=works.filter(w=>w.title===title);
 // Titles are legacy lookup hints, never sufficient identity for a submission.
 return rows.length===1?rows[0]:null;
}
export function permissionForWork(applications,youtubeChannelId,workId){
 const rows=applications.filter(a=>a.youtube_channel_id===youtubeChannelId&&a.video_id===workId);
 return rows.length===1?rows[0]:null;
}
export function editorReadiness({review,asset,latestGenerate,assetJob,uploadJob},now=Date.now()){
 if(!review?.work_order_id||!review?.payload?.run_id)return {state:'missing',label:'편집할 작업 정보가 없습니다',canOpen:false};
 if(review.status!=='waiting')return {state:'closed',label:'이미 내부 검수가 끝난 영상입니다',canOpen:false};
 if(['queued','waiting_upload'].includes(review.payload?.workspace?.automation_status))return {state:'submitting',label:'권리사 검수 신청을 진행 중입니다',canOpen:false};
 if(review.payload?.workspace?.upload_job_id&&uploadJob?.status!=='succeeded')return {state:'uploading',label:'유튜브 업로드 결과를 확인한 뒤 편집할 수 있습니다',canOpen:false};
 if(latestGenerate?.result?.run_id!==review.payload.run_id)return {state:'superseded',label:'최신 렌더의 검수 영상에서 열어 주세요',canOpen:false};
 if(assetJob&&['failed','dead'].includes(assetJob.status)&&/run 디렉토리 없음|없거나 정리/.test(assetJob.error||''))return {state:'missing-source',label:'작업한 맥에 원본 폴더가 남아 있지 않습니다',canOpen:false};
 if(asset?.status==='ready'&&asset.work_order_id===review.work_order_id&&new Date(asset.expires_at).getTime()>now){
  return {state:'ready',label:'편집 자료 준비됨',canOpen:true};
 }
 return {state:'prepare',label:assetJob?.status==='running'?'편집 자료 만드는 중':'편집실을 열면 작업한 맥에서 자료를 준비합니다',canOpen:true};
}
export function youtubeId(url){
 if(!url)return null;
 if(/^[\w-]{11}$/.test(url))return url;
 try{const u=new URL(url);if(!['https:','http:'].includes(u.protocol))return null;
  let id=null;
  if(u.hostname==='youtu.be')id=u.pathname.slice(1);
  else if(['youtube.com','www.youtube.com','m.youtube.com'].includes(u.hostname))id=u.searchParams.get('v')||(/^\/(?:shorts|embed)\/([^/]+)$/.exec(u.pathname)||[])[1];
  return /^[\w-]{11}$/.test(id||'')?id:null;
 }catch{return null;}
}
export function exactInspection(records,channelId,videoId){
 if(!channelId||!videoId)return null;
 const rows=records.filter(r=>r.youtube_channel_id===channelId&&(r.yt_video_id||youtubeId(r.youtube_url))===videoId);
 return rows.sort((a,b)=>(b.created_at||'').localeCompare(a.created_at||''))[0]||null;
}
