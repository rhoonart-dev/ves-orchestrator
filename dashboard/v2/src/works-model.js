export const WORKS_PAGE_SIZE=9;
export function paginateFolders(folders,requestedPage=1){
 const totalPages=Math.max(1,Math.ceil(folders.length/WORKS_PAGE_SIZE));
 const page=Math.min(totalPages,Math.max(1,Math.trunc(requestedPage)||1));
 return {page,totalPages,items:folders.slice((page-1)*WORKS_PAGE_SIZE,page*WORKS_PAGE_SIZE)};
}
