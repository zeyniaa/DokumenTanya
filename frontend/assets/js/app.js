import {api} from './api.js';
import {state} from './state.js';
import {$,node,toast,mobile} from './ui.js';
import {refreshDocuments,renderDocuments,uploadFile,trackJob} from './documents.js';
import {loadDocument,resetViewer,setTab,renderPage} from './viewer.js';
import {initializeChat,resetChat,sendQuestion} from './chat.js';

async function selectDocument(id){
  state.scope=[id];renderDocuments();$('job-banner').hidden=true;
  await Promise.all([loadDocument(id),initializeChat([id])]);renderDocuments();mobile('viewer');
  const jobs=await api(`/documents/${id}/jobs`);if(jobs.length){showJob(jobs[0],id);if(['queued','processing'].includes(jobs[0].status))trackJob(id,jobs[0].id);}
}
function showJob(job,id=job.document_id){
  if(state.selectedDoc!==id)return;
  const banner=$('job-banner');banner.hidden=job.status==='ready';banner.classList.toggle('error',job.status==='failed');
  if(job.status==='ready')return;
  if(job.status!=='failed'){
    if(!banner.querySelector('.ocr-progress')){
      banner.replaceChildren();
      const card=node('div','ocr-progress');const heading=node('div','ocr-heading');
      heading.append(node('span','ocr-spinner'),node('strong','ocr-title'),node('span','ocr-percent'));
      const bar=node('div','ocr-track');bar.setAttribute('role','progressbar');bar.setAttribute('aria-label','Halaman selesai dibaca');bar.setAttribute('aria-valuemin','0');bar.setAttribute('aria-valuemax','100');bar.append(node('div','ocr-fill'));
      card.append(heading,bar,node('p','ocr-detail'));banner.append(card);
    }
    const percent=Number(job.progress_percent||0),done=Number(job.pages_done||0),total=Number(job.pages_total||0);
    banner.querySelector('.ocr-title').textContent=job.phase==='index'?'Bacaan selesai · menyiapkan chat':job.phase==='render'?'Menyiapkan halaman':job.status==='queued'?'Menunggu giliran':'Membaca teks, tabel & OCR';
    banner.querySelector('.ocr-percent').textContent=`${percent}%`;
    const bar=banner.querySelector('.ocr-track');bar.setAttribute('aria-valuenow',String(percent));bar.querySelector('.ocr-fill').style.width=`${percent}%`;
    banner.querySelector('.ocr-detail').textContent=job.phase==='index'?`${done}/${total} halaman selesai. Membuat indeks pencarian…`:job.phase==='render'?job.stage:total?`${done}/${total} halaman selesai dibaca. ${done===0?'Model sedang disiapkan; halaman pertama bisa lebih lama.':''}`:'Dokumen akan diproses setelah antrean sebelumnya selesai.';
    return;
  }
  banner.replaceChildren(node('span','',job.error||'Pemrosesan gagal'));
  if(job.status==='failed'){const retry=node('button','','Coba lagi');retry.addEventListener('click',async()=>{try{const next=await api(`/documents/${id}/retry`,{method:'POST'});trackJob(id,next.job_id);}catch(error){toast(error.message,true);}});banner.append(retry);}
}
document.addEventListener('dt:select',event=>selectDocument(event.detail).catch(error=>toast(error.message,true)));
document.addEventListener('dt:preview-changed',renderDocuments);
document.addEventListener('dt:job',event=>showJob(event.detail));
document.addEventListener('dt:ready',async(event)=>{
  if(state.selectedDoc===event.detail){await loadDocument(event.detail);$('job-banner').hidden=true;if(!state.conversation)await initializeChat(state.scope);}
  renderDocuments();
});
document.addEventListener('dt:deleted',event=>{state.jobs.delete(event.detail);if(state.scope.includes(event.detail)){resetChat();state.scope=[];}if(state.selectedDoc===event.detail)resetViewer();});
$('file-input').addEventListener('change',event=>uploadFile(event.target.files[0]));
$('upload-zone').addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();$('file-input').click();}});
$('upload-zone').addEventListener('dragover',event=>{event.preventDefault();$('upload-zone').classList.add('dragging');});
$('upload-zone').addEventListener('dragleave',()=>$('upload-zone').classList.remove('dragging'));
$('upload-zone').addEventListener('drop',event=>{event.preventDefault();uploadFile(event.dataTransfer.files[0]);});
$('empty-upload').addEventListener('click',()=>$('file-input').click());
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>setTab(button.dataset.tab)));
document.querySelectorAll('[data-mobile]').forEach(button=>button.addEventListener('click',()=>mobile(button.dataset.mobile)));
$('prev-page').addEventListener('click',()=>{if(state.page>1){state.page--;renderPage();}});
$('next-page').addEventListener('click',()=>{if(state.extraction&&state.page<state.extraction.pages.length){state.page++;renderPage();}});
$('zoom-in').addEventListener('click',()=>{state.zoom=Math.min(200,state.zoom+10);renderPage();});
$('zoom-out').addEventListener('click',()=>{state.zoom=Math.max(50,state.zoom-10);renderPage();});
$('export-button').addEventListener('click',()=>{if(state.extraction){const a=node('a');a.href=`/api/documents/${state.selectedDoc}/export?format=json&version_id=${state.extraction.version_id}`;a.download='extraction.json';a.click();}});
$('reprocess-button').addEventListener('click',async()=>{if(!state.selectedDoc)return;try{const result=await api(`/documents/${state.selectedDoc}/reprocess`,{method:'POST'});trackJob(result.document_id,result.job_id);toast('Dokumen diproses ulang. Versi sebelumnya tetap tersedia sampai versi baru siap.');}catch(error){toast(error.message,true);}});
$('chat-form').addEventListener('submit',event=>{event.preventDefault();sendQuestion($('question-input').value);});
$('question-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();sendQuestion(event.target.value);}});
document.querySelectorAll('[data-question]').forEach(button=>button.addEventListener('click',()=>sendQuestion(button.dataset.question)));
$('new-chat').addEventListener('click',()=>initializeChat(state.scope,true).catch(error=>toast(error.message,true)));
$('apply-scope').addEventListener('click',async()=>{const ids=[...$('scope-options').querySelectorAll('input:checked')].map(input=>input.value);if(!ids.length||ids.length>5){toast('Pilih 1 sampai 5 dokumen.',true);return;}try{await initializeChat(ids);$('scope-selector').open=false;renderDocuments();mobile('chat');}catch(error){toast(error.message,true);}});
$('help-button').addEventListener('click',()=>$('help-dialog').showModal());$('close-help').addEventListener('click',()=>$('help-dialog').close());

try{
  state.config=await api('/config');
  const provider=state.config.provider;
  $('help-mode').textContent=provider==='extractive'?'Mode saat ini menampilkan kutipan relevan dari dokumen. Aktifkan Gemini atau Ollama pada konfigurasi backend untuk jawaban LLM.':'Model menyusun jawaban dari bukti yang ditemukan. Periksa sumber untuk memastikan ketepatannya.';
  $('upload-limit').textContent=`PDF · Maks. ${state.config.max_upload_mb} MB / ${state.config.max_pages} hal.`;
  await refreshDocuments();
  if(state.documents.length)await selectDocument(state.documents[0].id);
}catch(error){toast(error.message,true);}
