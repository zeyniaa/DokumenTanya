export async function api(path, options={}) {
  const init={credentials:'same-origin',...options};
  if(init.body && !(init.body instanceof FormData)) {
    init.headers={'Content-Type':'application/json',...init.headers};
    init.body=JSON.stringify(init.body);
  }
  const response=await fetch('/api'+path,init);
  const data=await response.json().catch(()=>({detail:'Respons server tidak dapat dibaca.'}));
  if(!response.ok) {
    const detail=typeof data.detail==='string'?data.detail:'Periksa format input dan coba lagi.';
    const error=new Error(detail);error.status=response.status;throw error;
  }
  return data;
}
