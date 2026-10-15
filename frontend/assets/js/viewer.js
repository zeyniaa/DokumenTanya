import {api} from './api.js';
import {state} from './state.js';
import {$,node,toast,mobile,emit} from './ui.js';
import {trackJob} from './documents.js';

let loadEpoch=0;
export async function loadDocument(documentId, versionId=null) {
  const epoch=++loadEpoch;state.selectedDoc=documentId;state.page=1;state.zoom=100;
  $('viewer-title').textContent=state.documents.find(d=>d.id===documentId)?.name||'Preview dokumen';
  const suffix=versionId?'?version_id='+encodeURIComponent(versionId):'';
  const doc=state.documents.find(d=>d.id===documentId);
  state.extraction=null;renderViewer();
  if(!doc?.active_version && !versionId){$('viewer-subtitle').textContent='Tunggu dokumen selesai diproses';return;}
  const content=await api(`/documents/${documentId}/extraction${suffix}`);
  if(epoch!==loadEpoch)return;
  state.extraction=content;renderViewer();
}
export function resetViewer() {loadEpoch++;state.extraction=null;state.selectedDoc=null;renderViewer();}
export function renderViewer() {
  const content=state.extraction;
  $('viewer-empty').hidden=Boolean(content);
  $('page-view').hidden=!content||state.tab!=='document';
  $('text-view').hidden=!content||state.tab!=='text';
  $('tables-view').hidden=!content||state.tab!=='tables';
  $('page-controls').hidden=!content||state.tab!=='document';
  $('export-button').disabled=!content;
  $('reprocess-button').disabled=!content;
  $('version-badge').hidden=!content;
  $('extraction-warning').hidden=!content||!content.warnings.length;
  if(!content)return;
  $('viewer-title').textContent=content.name;
  $('viewer-subtitle').textContent=`${content.pages.length} halaman · ${content.parser} · v${content.version_number}`;
  $('version-badge').textContent='v'+content.version_number;
  $('extraction-warning').hidden=!content.warnings.length;
  $('extraction-warning').textContent=content.warnings.join(' ');
  if(state.tab==='document')renderPage();
  if(state.tab==='text')renderText();
  if(state.tab==='tables')renderTables();
}
export function setTab(tab) {
  state.tab=tab;document.querySelectorAll('[data-tab]').forEach(button=>{
    button.classList.toggle('active',button.dataset.tab===tab);button.setAttribute('aria-selected',String(button.dataset.tab===tab));
  });renderViewer();
}
export function renderPage(boxes=[]) {
  const content=state.extraction;if(!content)return;
  $('page-image').src=`/api/documents/${content.document_id}/pages/${state.page}?version_id=${content.version_id}`;
  $('page-image').alt=`${content.name} — halaman ${state.page}`;
  $('paper').style.width=state.zoom+'%';$('paper').style.maxWidth='none';
  $('page-label').textContent=`Halaman ${state.page} / ${content.pages.length}`;
  $('zoom-label').textContent=state.zoom+'%';
  $('prev-page').disabled=state.page<=1;$('next-page').disabled=state.page>=content.pages.length;
  const layer=$('highlight-layer');layer.replaceChildren();
  for(const box of boxes){const mark=node('span','highlight');mark.style.left=box[0]*100+'%';mark.style.top=box[1]*100+'%';mark.style.width=(box[2]-box[0])*100+'%';mark.style.height=(box[3]-box[1])*100+'%';layer.append(mark);}
  if(boxes.length)layer.firstElementChild?.scrollIntoView({block:'center'});
}
export async function showCitation(citation) {
  try{await loadDocument(citation.document_id,citation.version_id);state.page=citation.page_no;setTab('document');renderPage(citation.bboxes||[]);mobile('viewer');emit('dt:preview-changed');}
  catch(error){toast(error.message,true);}
}
function renderText() {
  const root=$('text-view');root.replaceChildren();
  for(const item of state.extraction.items.filter(i=>i.type==='text')) {
    const card=node('article','text-card');const head=node('div','text-card-head');
    head.append(node('span','',`Halaman ${item.page_no}${item.corrected?' · dikoreksi':''}`));
    const edit=node('button','button secondary','Koreksi');edit.type='button';head.append(edit);
    const text=node('p','',item.text);card.append(head,text);
    edit.addEventListener('click',()=>{
      const input=node('textarea');input.value=item.text;input.setAttribute('aria-label','Koreksi teks halaman '+item.page_no);text.replaceWith(input);
      edit.textContent='Simpan & indeks ulang';input.focus();
      const versionId=state.extraction.version_id, docId=state.extraction.document_id;
      edit.onclick=async()=>{
        edit.disabled=true;
        try{const result=await api(`/documents/${docId}/items/${item.id}`,{method:'PATCH',body:{text:input.value,expected_version_id:versionId}});
          trackJob(docId,result.job_id);toast('Koreksi disimpan. Indeks versi baru sedang dibuat.');}
        catch(error){toast(error.message,true);edit.disabled=false;}
      };
    },{once:true});root.append(card);
  }
  if(!root.children.length)root.append(node('p','muted','Tidak ada item teks pada dokumen ini.'));
}
function renderTables() {
  const root=$('tables-view');root.replaceChildren();
  const content=state.extraction;
  for(const [index,table] of content.tables.entries()) {
    const card=node('article','table-card');card.append(node('h3','',`Tabel ${index+1} · Halaman ${table.page_no}`));
    const wrap=node('div','table-scroll'), grid=node('table');
    const caption=node('caption','sr-only',`Tabel ${index+1} halaman ${table.page_no}`);grid.append(caption);
    table.rows.forEach((row,i)=>{const tr=node('tr');row.forEach(value=>tr.append(node(i?'td':'th','',value)));grid.append(tr);});wrap.append(grid);card.append(wrap);
    const form=node('form','calc-form');const column=node('select');column.setAttribute('aria-label','Kolom untuk dihitung');
    table.rows[0]?.forEach((name,i)=>{const opt=node('option','',name||`Kolom ${i+1}`);opt.value=i;column.append(opt);});
    const operation=node('select');operation.setAttribute('aria-label','Operasi perhitungan');
    for(const [value,label] of [['sum','Jumlah'],['average','Rata-rata'],['min','Minimum'],['max','Maksimum'],['count','Jumlah sel']]){const opt=node('option','',label);opt.value=value;operation.append(opt);}
    const button=node('button','button secondary','Hitung');button.type='submit';const result=node('div','calc-result');result.hidden=true;
    form.append(column,operation,button);card.append(form,result);
    form.addEventListener('submit',async(event)=>{
      event.preventDefault();button.disabled=true;
      try{const data=await api(`/documents/${content.document_id}/calculate`,{method:'POST',body:{version_id:content.version_id,table_id:table.id,column:Number(column.value),operation:operation.value}});
        result.textContent=`${operation.selectedOptions[0].textContent} ${data.column}: ${data.result} (${data.unit})\nDihitung dari ${data.count} sel · v${content.version_number} · halaman ${data.page_no}`;result.hidden=false;}
      catch(error){result.textContent=error.message;result.hidden=false;}
      finally{button.disabled=false;}
    });root.append(card);
  }
  if(!root.children.length)root.append(node('p','muted','Belum ditemukan tabel terstruktur. Periksa halaman asli atau gunakan parser Docling.'));
}
