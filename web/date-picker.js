/* Shared local-date controls. Keep ISO values for the API; never use UTC to move a calendar day. */
(() => {
 'use strict';
 const make=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const fields=new WeakMap(),ranges=[];
 const pad=n=>String(n).padStart(2,'0'),iso=d=>`${String(d.getFullYear()).padStart(4,'0')}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
 const parse=value=>{if(!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;const [y,m,d]=value.split('-').map(Number),date=new Date(2000,m-1,d,12);date.setFullYear(y);return iso(date)===value&&y>=1?date:null;};
 const today=()=>{const d=new Date();d.setHours(12,0,0,0);return d;};
 const move=(date,days)=>{const d=new Date(date);d.setDate(d.getDate()+days);return d;};
 const month=(date,delta)=>{const d=new Date(date);d.setDate(1);d.setMonth(d.getMonth()+delta);return d;};
 const monthName=m=>new Intl.DateTimeFormat(undefined,{month:'long'}).format(new Date(2000,m,1));
 let active=null,visible=today(),focused=today();
 const popup=make('div','date-popup');popup.hidden=true;popup.setAttribute('role','dialog');popup.setAttribute('aria-label','Choose a date');
 const top=make('div','date-popup-head'),previous=make('button','quiet','‹'),next=make('button','quiet','›'),months=make('select'),years=make('select');
 for(const [b,label] of [[previous,'Previous month'],[next,'Next month']]){b.type='button';b.setAttribute('aria-label',label);}
 months.setAttribute('aria-label','Calendar month');years.setAttribute('aria-label','Calendar year');
 for(let m=0;m<12;m++){const o=make('option','',monthName(m));o.value=String(m);months.append(o);}top.append(previous,months,years,next);
 const grid=make('div','date-grid');grid.setAttribute('role','grid');grid.setAttribute('aria-label','Days');
 const week=make('div','date-week');week.setAttribute('aria-hidden','true');for(const day of ['Mo','Tu','We','Th','Fr','Sa','Su'])week.append(make('span','',day));
 const footer=make('div','date-popup-footer'),current=make('button','quiet','Today'),clear=make('button','quiet','Clear'),close=make('button','quiet','Close');
 for(const b of [current,clear,close])b.type='button';footer.append(current,clear,close);popup.append(top,week,grid,footer);
 const allowed=d=>(!active?.min||iso(d)>=active.min)&&(!active?.max||iso(d)<=active.max);
 function shut(restore=true){const input=active;popup.hidden=true;active=null;if(input){input.parentElement.querySelector('.date-trigger')?.setAttribute('aria-expanded','false');if(restore)(fields.get(input)?.display||input).focus();}}
 function choose(date){if(!active||active.disabled||active.readOnly||!allowed(date))return;const input=active;input.value=date?iso(date):'';input.setCustomValidity('');emit(input);shut();}
 function draw(focus=false){
  months.value=String(visible.getMonth());years.replaceChildren();const y=visible.getFullYear(),base=today().getFullYear();for(let year=Math.min(base-20,y);year<=Math.max(base+10,y);year++){if(year<1||year>9999)continue;const o=make('option','',String(year));o.value=String(year);years.append(o);}years.value=String(y);
  grid.replaceChildren();const first=new Date(visible);first.setDate(1);const start=move(first,-((first.getDay()+6)%7)),selected=active?.value,now=iso(today());
  let row;for(let n=0;n<42;n++){if(n%7===0){row=make('div');row.setAttribute('role','row');grid.append(row);}const date=move(start,n),value=iso(date),b=make('button','date-day'+(date.getMonth()!==visible.getMonth()?' outside':'')+(value===selected?' selected':'')+(value===now?' today':''),String(date.getDate()));b.type='button';b.dataset.date=value;b.setAttribute('role','gridcell');b.setAttribute('aria-label','Choose '+AtlantaUX.display(value));b.setAttribute('aria-selected',String(value===selected));if(value===now)b.setAttribute('aria-current','date');b.tabIndex=value===iso(focused)?0:-1;b.disabled=!allowed(date)||date.getFullYear()<1||date.getFullYear()>9999;b.onclick=()=>choose(date);row.append(b);}
  clear.hidden=!!active?.required;place();if(focus)grid.querySelector(`[data-date="${iso(focused)}"]`)?.focus({preventScroll:true});
 }
 function place(){if(!active)return;const rect=active.parentElement.getBoundingClientRect();popup.style.width=Math.min(340,innerWidth-24)+'px';popup.style.left=Math.max(12,Math.min(rect.left,innerWidth-popup.offsetWidth-12))+'px';popup.style.top=Math.max(12,rect.bottom+8+popup.offsetHeight<innerHeight?rect.bottom+8:rect.top-popup.offsetHeight-8)+'px';}
 function open(input){if(input.disabled||input.readOnly)return;if(active===input&&!popup.hidden){shut();return;}shut(false);active=input;(input.closest('dialog[open]')||document.body).append(popup);focused=parse(input.value)||today();if(input.max&&iso(focused)>input.max)focused=parse(input.max)||focused;if(input.min&&iso(focused)<input.min)focused=parse(input.min)||focused;visible=new Date(focused);popup.hidden=false;input.parentElement.querySelector('.date-trigger').setAttribute('aria-expanded','true');draw(true);}
 previous.onclick=()=>{visible=month(visible,-1);focused=new Date(visible);draw();};next.onclick=()=>{visible=month(visible,1);focused=new Date(visible);draw();};
 months.onchange=()=>{visible.setDate(1);visible.setMonth(Number(months.value));focused=new Date(visible);draw();};years.onchange=()=>{visible.setDate(1);visible.setFullYear(Number(years.value));focused=new Date(visible);draw();};
 current.onclick=()=>choose(today());clear.onclick=()=>{if(active){const input=active;input.value='';input.setCustomValidity('');emit(input);shut();}};close.onclick=()=>shut();
 grid.onkeydown=e=>{let target=null;if(e.key==='ArrowLeft')target=move(focused,-1);if(e.key==='ArrowRight')target=move(focused,1);if(e.key==='ArrowUp')target=move(focused,-7);if(e.key==='ArrowDown')target=move(focused,7);if(e.key==='Home')target=move(focused,-((focused.getDay()+6)%7));if(e.key==='End')target=move(focused,6-((focused.getDay()+6)%7));if(e.key==='PageUp')target=month(focused,e.shiftKey?-12:-1);if(e.key==='PageDown')target=month(focused,e.shiftKey?12:1);if(target){e.preventDefault();focused=target;visible=new Date(target);draw(true);}};
 document.addEventListener('keydown',e=>{if(active&&e.key==='Escape'){e.preventDefault();e.stopPropagation();shut();}},true);
 document.addEventListener('pointerdown',e=>{if(active&&!popup.contains(e.target)&&!active.parentElement.contains(e.target))shut(false);});
 document.addEventListener('focusin',e=>{if(active&&!popup.contains(e.target)&&!active.parentElement.contains(e.target))shut(false);});
 addEventListener('resize',()=>shut(false));document.addEventListener('scroll',e=>{if(active&&!popup.contains(e.target))shut(false);},true);
 function emit(input){input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));validateRanges();}
 function validateRanges(){for(const [from,to] of ranges){const display=fields.get(to)?.display;if(display&&!display.dataset.invalidDate){display.setCustomValidity(from.value&&to.value&&from.value>to.value?'From must precede Through':'');display.setAttribute('aria-invalid',String(!display.checkValidity()));}}}
 function enhance(input){
  if(input.dataset.dateControl)return;input.dataset.dateControl='true';
  let committed=input.value;const original=input.value,labels=[...(input.labels||[])],wrap=make('span','date-control'),display=make('input','date-display'),trigger=make('button','date-trigger','▦'),note=make('small','date-error');
  const label=input.getAttribute('aria-label')||labels[0]?.textContent.trim()||'Date';
  display.type='text';display.placeholder='dd.mm.yyyy';display.inputMode='numeric';display.autocomplete='off';display.maxLength=10;display.setAttribute('aria-label',label);display.dataset.dateDisplay='true';
  display.id=(input.id||'date-'+Math.random().toString(36).slice(2))+'-display';note.id=display.id+'-error';note.hidden=true;display.setAttribute('aria-describedby',note.id);
  for(const label of labels)if(label.htmlFor===input.id)label.htmlFor=display.id;
  trigger.textContent='';const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('fill','none');icon.setAttribute('stroke','currentColor');icon.setAttribute('stroke-width','1.6');icon.setAttribute('aria-hidden','true');const shape=document.createElementNS('http://www.w3.org/2000/svg','path');shape.setAttribute('d','M5 5h14v15H5zM8 2v6M16 2v6M5 10h14M8 13h2M14 13h2M8 17h2');icon.append(shape);trigger.append(icon);trigger.type='button';trigger.setAttribute('aria-label','Open calendar for '+label);trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-haspopup','dialog');
  input.before(wrap);wrap.append(input,display,trigger);wrap.after(note);input.type='hidden';
  const descriptor=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');
  const update=()=>{display.value=AtlantaUX.display(descriptor.get.call(input));display.disabled=input.disabled;display.readOnly=input.readOnly;display.required=input.required;trigger.disabled=input.disabled||input.readOnly;};
  Object.defineProperty(input,'value',{configurable:true,get(){return descriptor.get.call(this);},set(value){descriptor.set.call(this,value??'');committed=descriptor.get.call(this);update();display.setCustomValidity('');delete display.dataset.invalidDate;display.setAttribute('aria-invalid','false');note.hidden=true;}});
  fields.set(input,{display,update});input.value=original;
  const validate=()=>{const normalized=AtlantaUX.inputISO(display.value),invalid=normalized===null||!!normalized&&((input.min&&normalized<input.min)||(input.max&&normalized>input.max));const message=invalid?'Enter a valid date as dd.mm.yyyy within the allowed range.':'';if(invalid)display.dataset.invalidDate='true';else delete display.dataset.invalidDate;display.setCustomValidity(message);display.setAttribute('aria-invalid',String(invalid));note.textContent=message;note.hidden=!invalid;return invalid?null:normalized;};
  display.oninput=()=>{const value=validate();if(value!==null){descriptor.set.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));validateRanges();}};
  const commit=()=>{const value=validate();if(value===null)return;if(value!==committed){input.value=value;emit(input);}else display.value=AtlantaUX.display(value);};
  display.onchange=commit;display.onblur=commit;
  trigger.onclick=()=>open(input);display.addEventListener('keydown',e=>{if(e.key==='ArrowDown'&&e.altKey){e.preventDefault();open(input);}});
  input.addEventListener('change',()=>{committed=input.value;update();validateRanges();});

 }
 function enhanceRange(fromId,toId){
  const from=document.getElementById(fromId),to=document.getElementById(toId);if(!from||!to)return;const left=from.closest('label'),right=to.closest('label');if(!left||!right)return;
  for(const label of [left,right])for(const node of [...label.childNodes])if(node.nodeType===3&&node.textContent.trim()){const caption=make('span','date-part-label',node.textContent);node.replaceWith(caption);}
  ranges.push([from,to]);const period=make('div','period-field'),heading=make('span','field-label visually-hidden','Period'),dates=make('div','period-dates'),presets=make('div','period-presets');left.before(period);dates.append(left,right);period.append(heading,dates,presets);
  for(const [label,days] of [['Today',0],['Yesterday',-1],['Last 7 days',-6]]){const b=make('button','quiet',label);b.type='button';b.onclick=()=>{const end=days===-1?move(today(),-1):today();from.value=iso(move(today(),days));to.value=iso(end);for(const input of [from,to]){input.setCustomValidity('');emit(input);}};presets.append(b);}
 }
 document.addEventListener('change',event=>{const input=event.target;if(input.matches?.('input[data-date-control]')&&input.value&&!parse(input.value)){input.setCustomValidity('Enter a valid date as YYYY-MM-DD');event.stopImmediatePropagation();input.reportValidity();}},true);
 function init(){document.body.append(popup);document.querySelectorAll('input[type=date]').forEach(enhance);for(const pair of [['conversation-from','conversation-to'],['report-start','report-end'],['analytics-from','analytics-to']])enhanceRange(...pair);new MutationObserver(records=>{if(active&&!document.contains(active))shut(false);for(const record of records){if(record.type==='attributes'&&record.target.dataset.dateControl){const input=record.target;fields.get(input)?.update();input.parentElement?.querySelector('.date-trigger')?.toggleAttribute('disabled',input.disabled||input.readOnly);if(active===input&&(input.disabled||input.readOnly))shut(false);}}for(const record of records)for(const node of record.addedNodes)if(node.nodeType===1){if(node.matches('input[type=date]'))enhance(node);node.querySelectorAll('input[type=date]').forEach(enhance);}}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','readonly','required','min','max']});}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
