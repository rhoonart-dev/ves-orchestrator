export const roles=['viewer','reviewer','operator','admin'];
// The UI exposes role state only. PostgreSQL RLS and RPCs remain authoritative.
export function createAuthController(client,onChange){
 let sequence=0;
 let state={status:'loading',user:null,role:null,message:''};
 const update=next=>{state=next;onChange(state)};
 async function acceptSession(session){
  const ticket=++sequence;
  if(!session?.user){update({status:'signed-out',user:null,role:null,message:''});return;}
  update({status:'checking-role',user:session.user,role:null,message:''});
  try{
   const {data,error}=await client.from('user_roles').select('role').eq('user_id',session.user.id).maybeSingle();
   if(ticket!==sequence)return;
   if(error)throw error;
   if(!data||!roles.includes(data.role)){update({status:'denied',user:session.user,role:null,message:'VES 사용 권한이 등록되지 않은 계정입니다.'});return;}
   update({status:'ready',user:session.user,role:data.role,message:''});
  }catch{
   if(ticket===sequence)update({status:'error',user:session.user,role:null,message:'권한 정보를 확인하지 못했습니다. 다시 로그인해 주세요.'});
  }
 }
 // Keep Supabase calls outside the auth callback's lock.
 const {data:{subscription}}=client.auth.onAuthStateChange((_event,session)=>{
  const queued=++sequence;
  setTimeout(()=>{if(queued===sequence)acceptSession(session)},0);
 });
 return {
  getState:()=>state,
  signIn:async(email,password)=>{const {error}=await client.auth.signInWithPassword({email:email.trim(),password});if(error)throw error;},
  signOut:async()=>{const {error}=await client.auth.signOut({scope:'local'});if(error)throw error;await acceptSession(null)},
  dispose:()=>{sequence++;subscription.unsubscribe()},
 };
}
