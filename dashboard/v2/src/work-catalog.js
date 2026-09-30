// 작품 목록 — 레이블리 작품 정보의 Supabase 사본(laeebly_works, 오케스트레이터 0116 · 맥미니가 10분마다 맞춘다).
// 예전에는 작업 컴퓨터의 로컬 서버(/api/work-catalog)가 레이블리를 직접 읽었다. 이제 웹 주소에서도 같은 목록을 쓴다.
// 가이드 원문(guide)은 길어서(작품당 최대 1MB) 목록에 싣지 않고 열 때 따로 읽는다(loadGuide).
const LIST_COLS='id,title,video_type,thumbnail,identification_code,required_hashtags_title,required_hashtags_description,required_hashtags_notice,copyrights_holder_name,geo_block_required,geo_block_regions,geo_block_mode,company';
let cache=null;

async function rows(q){const {data,error}=await q;if(error)throw Error(error.message);return data||[];}

// {works:[레이블리 작품], pipeline_titles:[채널·작품 카드에 걸린 제목]} — work_assets_api.catalog 와 같은 모양
export function loadCatalog(client,{fresh=false}={}){
 if(!client)return Promise.reject(Error('로그인하면 작품 목록을 볼 수 있어요.'));
 if(cache&&!fresh)return cache;
 cache=(async()=>{
  const [works,channels,cards,overrides]=await Promise.all([
   rows(client.from('laeebly_works').select(LIST_COLS).order('title').order('id').range(0,4999)),
   rows(client.from('channels_mirror').select('works')),
   rows(client.from('work_cards').select('work_title')),
   rows(client.from('channel_works_overrides').select('works'))]);
  const titles=new Set();
  for(const c of [...channels,...overrides])for(const t of c.works||[])titles.add(t);
  for(const c of cards)if(c.work_title)titles.add(c.work_title);
  return {works,pipeline_titles:[...titles].sort()};
 })().catch(e=>{cache=null;throw e;});
 return cache;
}

const guides=new Map();
export function loadGuide(client,id){
 if(!guides.has(id))guides.set(id,rows(client.from('laeebly_works').select('guide').eq('id',id).limit(1)).then(r=>r[0]?.guide||'').catch(e=>{guides.delete(id);throw e;}));
 return guides.get(id);
}
