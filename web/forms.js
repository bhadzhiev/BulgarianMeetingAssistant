/* One rule for required fields and errors in every form (D06).
   - A required field has a visible mark on its label.
   - An error shows next to its field and stays there until the field is correct.
   - After a submit that fails, a summary at the top of the form names each field; a click on a name moves to the field.
   The browser's own error bubble is not used: it closes by itself and a screen reader can miss it. */
(function(root){
 'use strict';
 const FIELDS='input:not([type=hidden]):not([type=button]):not([type=submit]),select,textarea';
 // The name of a field in its own words: its label, else its aria-label.
 function fieldName(field){
  const label=field.labels?.[0]||field.closest?.('label');
  let text='';
  if(label){for(const node of label.childNodes)if(node.nodeType===3||node.matches?.('span:not(.field-error)'))text+=node.textContent;}
  text=text.replace(/\*/g,'').replace(/\s+/g,' ').trim();
  return text||field.getAttribute('aria-label')||field.placeholder||'This field';
 }
 // The message: what to do, in plain words.
 function message(field){
  const v=field.validity||{},name=fieldName(field);
  if(v.valueMissing)return field.tagName==='SELECT'?'Choose '+name.toLowerCase()+'.':'Enter '+name.toLowerCase()+'.';
  if(v.typeMismatch&&field.type==='email')return 'Enter a valid email address.';
  if(v.typeMismatch&&field.type==='url')return 'Enter a full address that starts with https://.';
  if(v.tooLong)return 'Use at most '+field.maxLength+' characters.';
  if(v.rangeUnderflow||v.rangeOverflow)return 'Enter a value from '+(field.min||'…')+' to '+(field.max||'…')+'.';
  return field.validationMessage||'Check this field.';
 }
 // The date picker shows its own error under the field; the rule only counts it in the summary.
 const ownError=field=>field.dataset?.dateDisplay==='true';
 function errorNode(field){
  const anchor=field.closest('label')&&field.closest('label').contains(field)?field.closest('label'):field.closest('.date-control')||field;
  let node=field.id&&field.ownerDocument.getElementById(field.id+'-field-error');
  if(!node){
   node=field.ownerDocument.createElement('p');node.className='field-error';
   if(!field.id)field.id='field-'+Math.random().toString(36).slice(2);
   node.id=field.id+'-field-error';anchor.after(node);
   field.setAttribute('aria-describedby',[field.getAttribute('aria-describedby'),node.id].filter(Boolean).join(' '));
  }
  return node;
 }
 function showError(field){
  field.setAttribute('aria-invalid','true');if(ownError(field))return;
  const node=errorNode(field);node.textContent=message(field);node.hidden=false;
 }
 function clearError(field){
  field.removeAttribute('aria-invalid');
  const node=field.id&&field.ownerDocument.getElementById(field.id+'-field-error');if(node){node.hidden=true;node.textContent='';}
 }
 function summary(form,fields){
  let box=form.querySelector(':scope .form-error-summary');
  if(!box){box=form.ownerDocument.createElement('div');box.className='form-error-summary';box.setAttribute('role','alert');box.tabIndex=-1;
   const head=form.querySelector(':scope>.card-heading,:scope>h2,:scope>h3');if(head)head.after(box);else form.prepend(box);}
  box.replaceChildren();
  const title=form.ownerDocument.createElement('p');title.textContent=fields.length===1?'Fix 1 field to continue:':'Fix '+fields.length+' fields to continue:';box.append(title);
  const list=form.ownerDocument.createElement('ul');
  for(const field of fields){const item=form.ownerDocument.createElement('li'),go=form.ownerDocument.createElement('button');go.type='button';go.className='quiet';
   go.textContent=fieldName(field)+' · '+message(field);go.onclick=()=>{field.closest('details')&&(field.closest('details').open=true);field.focus();};item.append(go);list.append(item);}
  box.append(list);box.hidden=false;
 }
 function refreshSummary(form){
  const box=form.querySelector(':scope .form-error-summary');if(!box||box.hidden)return;
  const bad=[...form.querySelectorAll(FIELDS)].filter(f=>f.getAttribute('aria-invalid')==='true'&&!f.validity.valid);
  if(bad.length)summary(form,bad);else box.hidden=true;
 }
 // A required field shows a mark on its label. Fields come and go, so the marks follow the page.
 function markRequired(scope){
  for(const field of scope.querySelectorAll('[required]')){
   if(field.type==='hidden')continue;
   for(const label of field.labels?.length?field.labels:[field.closest('label')].filter(Boolean))label.classList.add('required-label');
  }
 }
 function install(doc){
  const pending=new Map();let attempt=0;
  // A press of a button or Enter is a submit attempt. A check that the code makes (checkValidity) is not:
  // it marks the field, but it does not show the summary or move the focus.
  doc.addEventListener('click',event=>{if(event.target.closest?.('button,[type=submit]'))attempt=Date.now();},true);
  doc.addEventListener('keydown',event=>{if(event.key==='Enter')attempt=Date.now();},true);
  // The invalid events of one submit come together; the summary follows them.
  doc.addEventListener('invalid',event=>{
   const field=event.target;if(!field.matches?.(FIELDS))return;
   event.preventDefault();showError(field);
   if(Date.now()-attempt>1000)return;
   const form=field.form||field.closest('form,dialog');if(!form)return;
   if(!pending.has(form)){pending.set(form,[]);setTimeout(()=>{const fields=pending.get(form);pending.delete(form);summary(form,fields);fields[0]?.focus();},0);}
   pending.get(form).push(field);
  },true);
  // The error stays until the field is correct.
  const check=event=>{const field=event.target;if(!field.matches?.(FIELDS)||field.getAttribute('aria-invalid')!=='true')return;
   if(field.validity.valid){clearError(field);}else if(!ownError(field))errorNode(field).textContent=message(field);
   const form=field.form||field.closest('form,dialog');if(form)refreshSummary(form);};
  doc.addEventListener('input',check,true);doc.addEventListener('change',check,true);
  markRequired(doc);
  if(typeof MutationObserver==='function'){let queued=false;new MutationObserver(()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;markRequired(doc);});}).observe(doc.body,{childList:true,subtree:true});}
 }
 const api={fieldName,message,markRequired,install,showError,clearError};
 if(typeof module==='object'&&module.exports)module.exports=api;
 else{root.AtlantaForms=api;if(root.document)root.document.readyState==='loading'?root.document.addEventListener('DOMContentLoaded',()=>install(root.document)):install(root.document);}
})(typeof window!=='undefined'?window:globalThis);
