import {editorReadiness} from './workflow-model.js';
function value(result){if(result.error)throw result.error;return result.data;}
export async function inspectEditor(client,reviewId){
 const review=value(await client.from('review_queue').select('id,status,kind,work_order_id,payload').eq('id',reviewId).single());
 if(!review.work_order_id||!review.payload?.run_id)return {review,...editorReadiness({review})};
 const [asset,latestGenerate,assetJob,uploadJob]=await Promise.all([
  client.from('editor_assets').select('run_id,work_order_id,status,expires_at,node_id,error,updated_at').eq('run_id',review.payload.run_id).maybeSingle().then(value),
  client.from('job_queue').select('id,result,node_id,finished_at').eq('work_order_id',review.work_order_id).eq('kind','generate').eq('status','succeeded').order('created_at',{ascending:false}).limit(1).maybeSingle().then(value),
  client.from('job_queue').select('status,error,node_id').eq('idempotency_key','editor_assets:'+review.payload.run_id).maybeSingle().then(value),
  review.payload?.workspace?.upload_job_id?client.from('job_queue').select('status').eq('id',review.payload.workspace.upload_job_id).maybeSingle().then(value):Promise.resolve(null),
 ]);
 return {review,asset,latestGenerate,assetJob,uploadJob,...editorReadiness({review,asset,latestGenerate,assetJob,uploadJob})};
}
export function editorUrl(reviewId,jobId){
 const q=new URLSearchParams({rid:reviewId,back:jobId||''});return 'editor.html?'+q;
}
