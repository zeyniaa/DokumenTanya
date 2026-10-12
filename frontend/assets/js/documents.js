import {api} from './api.js';
import {state} from './state.js';
import {$,node,toast,emit} from './ui.js';

export async function refreshDocuments() {
  state.documents=await api('/documents');renderDocuments();
  for(const doc of state.documents.filter(d=>d.status==='processing')) {
    if(!state.jobs.has(doc.id)) {
      const jobs=await api(`/documents/${doc.id}/jobs`);
      if(jobs.length) trackJob(doc.id,jobs[0].id);
    }
  }
}
export function renderDocuments() {
  $('document-count').textContent=state.documents.length;
  const list=$('document-list');list.replaceChildren();
  if(!state.documents.length) list.append(node('p','list-empty','Belum ada dokumen.\nMulai dengan PDF pertamamu.'));
  for(const doc of state.documents) {
    const row=node('div','doc-row');row.classList.toggle('active',doc.id===state.selectedDoc);
    const open=node('button','doc-open');open.type='button';open.title=doc.name;
    const copy=node('span','doc-copy');copy.append(node('span','doc-name',doc.name));
    const labels={ready:'Siap ditanya',processing:'Memproses…',failed:'Gagal · pilih untuk mencoba lagi'};
    copy.append(node('span','doc-status '+doc.status,`${labels[doc.status]||doc.status}${doc.pages?' · '+doc.pages+' hal.':''}`));
    open.append(node('span','doc-file-icon','PDF'),copy);open.addEventListener('click',()=>emit('dt:select',doc.id));
    const remove=node('button','doc-delete','×');remove.type='button';remove.setAttribute('aria-label','Hapus '+doc.name);
    remove.addEventListener('click',async()=>{
      if(!window.confirm(`Hapus ${doc.name}, seluruh versi, dan percakapan yang terkait?`))return;
      try {await api(`/documents/${doc.id}`,{method:'DELETE'});emit('dt:deleted',doc.id);await refreshDocuments();toast('Dokumen dan indeksnya dihapus.');}
      catch(error){toast(error.message,true);}
    });row.append(open,remove);list.append(row);
  }
  const scopes=$('scope-options');scopes.replaceChildren();
  for(const doc of state.documents.filter(d=>d.active_version)) {
    const label=node('label');const check=node('input');check.type='checkbox';check.value=doc.id;check.checked=state.scope.includes(doc.id);
    check.addEventListener('change',()=>{const n=scopes.querySelectorAll('input:checked').length;$('scope-count').textContent=`${n}/5`;});
    label.append(check,node('span','',doc.name));scopes.append(label);
  }
  $('scope-count').textContent=`${state.scope.length}/5`;
}
export async function uploadFile(file) {
  if(!file)return;
  if(file.size>(state.config?.max_upload_mb||20)*1024*1024){toast('File terlalu besar.',true);return;}
  $('upload-zone').classList.add('dragging');
  const form=new FormData();form.append('file',file);
  try {
    const result=await api('/documents',{method:'POST',body:form});
    await refreshDocuments();emit('dt:select',result.document_id);
    if(result.job_id)trackJob(result.document_id,result.job_id);
    toast(result.duplicate?'Dokumen ini sudah ada di workspace.':'Dokumen diterima. Pemrosesan dimulai.');
  } catch(error){toast(error.message,true);}
  finally{$('upload-zone').classList.remove('dragging');$('file-input').value='';}
}
export async function uploadDemo() {
  $('demo-button').disabled=true;$('empty-demo').disabled=true;
  try{const response=await fetch('/api/demo/file');if(!response.ok)throw new Error('Contoh PDF belum tersedia.');
    await uploadFile(new File([await response.blob()],'Panduan Akademik Demo.pdf',{type:'application/pdf'}));
  }catch(error){toast(error.message,true);}
  finally{$('demo-button').disabled=false;$('empty-demo').disabled=false;}
}
export function trackJob(documentId,jobId) {
  if(state.jobs.get(documentId)===jobId)return;
  state.jobs.set(documentId,jobId);
  const deadline=Date.now()+35*60*1000;
  const poll=async()=>{
    if(state.jobs.get(documentId)!==jobId)return;
    try {
      const job=await api(`/jobs/${jobId}`);emit('dt:job',job);
      if(['ready','failed'].includes(job.status)) {
        state.jobs.delete(documentId);await refreshDocuments();
        if(job.status==='ready')emit('dt:ready',documentId);
        else toast(job.error||'Pemrosesan gagal.',true);
        return;
      }
      if(Date.now()>deadline){state.jobs.delete(documentId);toast('Pemrosesan masih berlangsung. Muat ulang untuk mengecek status.',true);return;}
      setTimeout(poll,1500);
    }catch(error){state.jobs.delete(documentId);toast(error.message,true);}
  };poll();
}
