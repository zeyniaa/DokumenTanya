import {api} from './api.js';
import {state} from './state.js';
import {$,node,toast,mobile} from './ui.js';
import {showCitation} from './viewer.js';

const welcome=$('chat-welcome');
export function composer() {
  const ready=Boolean(state.conversation)&&!state.chatPending;
  $('question-input').disabled=!ready;$('send-button').disabled=!ready;$('new-chat').disabled=!state.conversation;
  $('question-input').placeholder=ready?'Tanyakan sesuatu tentang dokumen…':'Pilih dokumen yang sudah siap…';
  $('composer-hint').textContent=state.chatPending?'Mencari bukti dan menyusun jawaban…':'Jawaban disertai sumber';
}
export function resetChat(){state.chatEpoch++;state.conversation=null;state.chatPending=false;$('messages').replaceChildren(welcome);composer();}
export async function initializeChat(ids,forceNew=false) {
  resetChat();state.scope=ids;const epoch=state.chatEpoch;
  if(!ids.length)return;
  if(ids.some(id=>!state.documents.find(d=>d.id===id)?.active_version))return;
  const old=forceNew?[]:await api('/conversations');
  if(epoch!==state.chatEpoch)return;
  const match=old.find(c=>JSON.stringify([...c.document_ids].sort())===JSON.stringify([...ids].sort()));
  const conversation=match||await api('/conversations',{method:'POST',body:{document_ids:ids}});
  if(epoch!==state.chatEpoch)return;
  state.conversation=conversation.id;
  $('chat-scope').textContent=ids.map(id=>state.documents.find(d=>d.id===id)?.name).join(' + ');
  const history=await api(`/conversations/${conversation.id}/messages`);
  if(epoch!==state.chatEpoch)return;
  if(history.length)$('messages').replaceChildren();
  for(const entry of history){appendMessage('user',entry.question);if(entry.response)appendResponse(entry.response);else appendMessage('assistant',entry.status==='failed'?'Permintaan sebelumnya gagal. Kamu dapat mengirim pertanyaan baru.':'Permintaan sebelumnya sedang diproses. Muat ulang riwayat untuk melihat hasilnya.');}
  composer();scrollBottom();
}
function appendMessage(role,text) {
  const article=node('article','message '+role);article.append(node('div','message-role',role==='user'?'Kamu':'DokumenTanya'),node('div','message-text',text));
  $('messages').append(article);return article;
}
function appendResponse(response) {
  const article=appendMessage('assistant',response.answer);
  for(const [i,citation] of response.citations.entries()){
    const button=node('button','citation');button.type='button';button.append(node('strong','',`[${i+1}] ${citation.filename} · Halaman ${citation.page_no}`),node('small','',citation.quote));
    button.addEventListener('click',()=>showCitation(citation));article.append(button);
  }
  if(response.warnings.length)article.append(node('p','message-warning',response.warnings.join(' ')));
  article.append(node('div','message-meta',`${response.provider} · ${response.elapsed_seconds}s · ${response.citations.length} sumber`));
}
function scrollBottom() {$('messages').scrollTop=$('messages').scrollHeight;}
export async function sendQuestion(question) {
  question=question.trim();if(!question||state.chatPending)return;
  if(!state.conversation){toast('Pilih dokumen yang sudah siap terlebih dahulu.');return;}
  const epoch=state.chatEpoch,conversation=state.conversation;
  state.chatPending=true;composer();mobile('chat');welcome.remove();
  appendMessage('user',question);$('question-input').value='';
  const loading=node('div','thinking','Mencari bukti dalam dokumen…');$('messages').append(loading);scrollBottom();
  try{
    const response=await api(`/conversations/${conversation}/messages`,{method:'POST',body:{question,request_id:crypto.randomUUID()}});
    if(epoch!==state.chatEpoch)return;loading.remove();appendResponse(response);scrollBottom();
  }catch(error){if(epoch===state.chatEpoch){loading.remove();appendMessage('assistant',error.message);toast(error.message,true);}}
  finally{if(epoch===state.chatEpoch){state.chatPending=false;composer();$('question-input').focus();}}
}
