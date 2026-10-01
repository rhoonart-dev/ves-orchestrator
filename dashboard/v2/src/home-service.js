import {readAll} from './review-service.js?v=web-1';
export async function loadOperations(client){
 const [nodes,running]=await Promise.all([
  readAll(()=>client.from('node_registry').select('node_id,status,last_seen_at').order('node_id')),
  readAll(()=>client.from('job_queue').select('id,work_order_id,node_id,kind,updated_at,work:params->>work_title,channel:params->>channel_name').eq('status','running').order('id')),
 ]);
 return {nodes,running};
}
