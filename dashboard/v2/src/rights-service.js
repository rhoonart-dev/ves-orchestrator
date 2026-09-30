import {needWorkPc} from './local-only.js';
export async function fetchRights(client,signal){
 needWorkPc();
 const {data,error}=await client.auth.getSession();
 if(error||!data.session)throw new Error('로그인이 필요합니다.');
 if(signal?.aborted)throw new DOMException('Aborted','AbortError');
 const response=await fetch('/api/rights-inspections',{headers:{Authorization:`Bearer ${data.session.access_token}`},cache:'no-store',signal});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'검수 조회 실패');
 return result;
}

export async function fetchWorkPolicies(client,signal){
 needWorkPc();
 const {data,error}=await client.auth.getSession();
 if(error||!data.session)throw new Error('로그인이 필요합니다.');
 const response=await fetch('/api/work-policies',{headers:{Authorization:`Bearer ${data.session.access_token}`},cache:'no-store',signal});
 const result=await response.json();if(!response.ok)throw new Error(result.error||'작품 검수 정책 조회 실패');
 return result;
}
