/* Shared date-only formatting and request/dirty state; no locale or UTC ambiguity. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AtlantaUX=api;})(globalThis,()=>{
 'use strict';
 const pad=n=>String(n).padStart(2,'0');
 function parseISO(value){if(typeof value!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;const [y,m,d]=value.split('-').map(Number),date=new Date(2000,m-1,d,12);date.setFullYear(y);return y>=1&&date.getFullYear()===y&&date.getMonth()===m-1&&date.getDate()===d?date:null;}
 const iso=d=>`${String(d.getFullYear()).padStart(4,'0')}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
 const display=value=>parseISO(value)?value.split('-').reverse().join('.'):'';
 function inputISO(value){if(!value.trim())return '';const match=/^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value.trim());const normalized=match?`${match[3]}-${match[2]}-${match[1]}`:value;return parseISO(normalized)?normalized:null;}
 function date(value){if(parseISO(value))return display(value);const d=new Date(value);if(!Number.isFinite(d.getTime()))return '';const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Sofia',day:'2-digit',month:'2-digit',year:'numeric'}).formatToParts(d).map(p=>[p.type,p.value]));return `${p.day}.${p.month}.${p.year}`;}
 function dateTime(value){const d=new Date(value);return Number.isFinite(d.getTime())?date(value)+' · '+new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/Sofia',hour:'2-digit',minute:'2-digit',hour12:false}).format(d):'';}
 function requests(){let epoch=0;const versions=new Map();return {start(key){const version=(versions.get(key)||0)+1;versions.set(key,version);return {key,version,epoch};},current(t){return t.epoch===epoch&&versions.get(t.key)===t.version;},invalidate(){epoch++;}};}
 function dirtyRegistry(){const entries=new Map();return {set(key,value){if(value)entries.set(key,true);else entries.delete(key);},has(){return entries.size>0;},clear(key){entries.delete(key);},keys(){return [...entries.keys()];}};}
 return {parseISO,iso,display,inputISO,date,dateTime,requests,dirtyRegistry};
});
