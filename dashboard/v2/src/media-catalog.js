let pending;
export function loadLocalMedia(){
 if(!pending)pending=fetch('assets/local-media/catalog.json').then(response=>{if(!response.ok)throw new Error('catalog unavailable');return response.json()}).catch(error=>{pending=null;throw error});
 return pending;
}
export const timeLabel=seconds=>`${Math.floor(seconds/60)}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;
