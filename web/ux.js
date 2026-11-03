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
 function count(value,singular,plural=singular+'s'){return value+' '+(value===1?singular:plural);}
 function requests(){let epoch=0;const versions=new Map();return {start(key){const version=(versions.get(key)||0)+1;versions.set(key,version);return {key,version,epoch};},current(t){return t.epoch===epoch&&versions.get(t.key)===t.version;},invalidate(){epoch++;}};}
 // Calendar dates share the display timezone; date-only imports retain their literal day.
 function meetingDay(meeting){const value=meeting.started_at||meeting.created;if(parseISO(value))return value;const shown=date(value);return shown?shown.split('.').reverse().join('-'):null;}
 function calendarDays(day){const selected=parseISO(day);if(!selected)return [];const first=parseISO(day.slice(0,7)+'-01'),offset=(first.getDay()+6)%7;first.setDate(first.getDate()-offset);return Array.from({length:42},(_,i)=>{const d=new Date(first);d.setDate(d.getDate()+i);return iso(d);});}
 function shiftDay(day,amount){const d=parseISO(day);if(!d)return day;d.setDate(d.getDate()+amount);return d.getFullYear()>=1&&d.getFullYear()<=9999?iso(d):day;}
 function shiftMonth(day,amount){const d=parseISO(day);if(!d)return day;const wanted=d.getDate();d.setDate(1);d.setMonth(d.getMonth()+amount);const end=new Date(d);end.setMonth(end.getMonth()+1,0);d.setDate(Math.min(wanted,end.getDate()));return d.getFullYear()>=1&&d.getFullYear()<=9999?iso(d):day;}
 function calendarMeetings(meetings,project){return meetings.filter(m=>!project||(project==='__none__'?!m.project_id:m.project_id===project)).map(m=>({...m,day:meetingDay(m)})).filter(m=>m.day).sort((a,b)=>(Date.parse(a.started_at||a.created)-Date.parse(b.started_at||b.created))||a.id.localeCompare(b.id));}
 function dirtyRegistry(){const entries=new Map();return {set(key,value){if(value)entries.set(key,true);else entries.delete(key);},has(){return entries.size>0;},clear(key){entries.delete(key);},keys(){return [...entries.keys()];}};}
 return {parseISO,iso,display,inputISO,date,dateTime,count,requests,dirtyRegistry,meetingDay,calendarDays,shiftDay,shiftMonth,calendarMeetings};
});
