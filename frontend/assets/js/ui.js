export const $ = (id) => document.getElementById(id);
export function node(tag, className='', text='') {
  const element = document.createElement(tag);
  if(className) element.className=className;
  if(text) element.textContent=text;
  return element;
}
let toastTimer;
export function toast(message, error=false) {
  const box=$('toast'); box.textContent=message; box.classList.toggle('error',error);box.hidden=false;
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>box.hidden=true,6000);
}
export function mobile(panel) {
  document.querySelector('.workspace').dataset.mobilePanel=panel;
  document.querySelectorAll('[data-mobile]').forEach(button=>button.classList.toggle('active',button.dataset.mobile===panel));
}
export function emit(name, detail) {document.dispatchEvent(new CustomEvent(name,{detail}));}
