(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AtlantaTasks=api;})(globalThis,()=>{
 const STATES={todo:'To do',in_progress:'In progress',waiting:'Waiting',done:'Done',cancelled:'Cancelled'};
 const workflow=item=>item.workflow_state||(item.status==='done'?'done':'todo');
 function inView(item,view,{self='',people=[],today='',search='',proposalFilter='pending'}={}){
  if(search&&![item.text,item.details,item.owner].join(' ').toLowerCase().includes(search.toLowerCase()))return false;
  const proposed=item.acceptance_state==='proposed';if(view==='inbox')return proposed&&(proposalFilter==='all'||(proposalFilter==='dismissed'?!!item.dismissed:!item.dismissed&&(proposalFilter==='snoozed'?item.snoozed_until>today:!item.snoozed_until||item.snoozed_until<=today)));
  if(proposed)return false;
  const me=people.find(p=>p.id===self),names=me?[me.name,...(me.aliases||[])].map(n=>n.toLowerCase()):[];
  const mine=!!self&&(item.owner_person_id===self||!!item.manual?.includes('owner')&&names.includes((item.owner||'').toLowerCase()));
  if(view==='mine')return mine;
  if(view==='delegated')return !!self&&item.assigned_by_person_id===self&&!mine;
  if(view==='followup')return !['done','cancelled'].includes(workflow(item))&&((item.follow_up_date&&item.follow_up_date<=today)||(item.due_date&&item.due_date<today)||workflow(item)==='waiting');
  return true;
 }
 function lastUpdate(item){return [...(item.history||[])].reverse().filter(e=>e.event==='progress_update'&&e.text).sort((a,b)=>(b.at||'').localeCompare(a.at||''))[0]||null;}
 // A deadline said in words that names a clear date: one click applies it as the due date.
 const MONTHS={януари:0,февруари:1,март:2,април:3,май:4,юни:5,юли:6,август:7,септември:8,октомври:9,ноември:10,декември:11};
 const WEEKDAYS={понеделник:1,вторник:2,сряда:3,четвъртък:4,петък:5,събота:6,неделя:0};
 function suggestDueDate(text,meetingDay){
  if(!text||!/[\dпонвтсрчпетън]/.test(text))return null;
  const meeting=new Date(String(meetingDay||'').slice(0,10)+'T12:00:00');
  if(isNaN(meeting))return null;
  const lower=text.toLocaleLowerCase('bg');
  const iso=/\b(\d{4})-(\d{2})-(\d{2})\b/.exec(text);
  const numeric=/\b(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\b/.exec(text);
  const named=new RegExp('\\b(\\d{1,2})(?:-и|-ти|ти)?\\s+('+Object.keys(MONTHS).join('|')+')','i').exec(lower);
  const weekday=Object.keys(WEEKDAYS).find(name=>lower.includes(name));
  const valid=(y,m,d)=>{const date=new Date(y,m,d,12);return date.getFullYear()===y&&date.getMonth()===m&&date.getDate()===d?date:null;};
  const asISO=date=>date.getFullYear()+'-'+String(date.getMonth()+1).padStart(2,'0')+'-'+String(date.getDate()).padStart(2,'0');
  if(iso){const date=valid(Number(iso[1]),Number(iso[2])-1,Number(iso[3]));return date&&date>=meeting?asISO(date):null;}
  if(numeric){const year=numeric[3]?(numeric[3].length<=2?2000:0)+Number(numeric[3]):meeting.getFullYear();
   const date=valid(year,Number(numeric[2])-1,Number(numeric[1]));
   if(!date)return null;
   if(!numeric[3]&&date<meeting)return asISO(valid(date.getFullYear()+1,date.getMonth(),date.getDate()));
   return date>=meeting?asISO(date):null;}
  if(named){const date=valid(meeting.getFullYear(),MONTHS[named[2]],Number(named[1]));
   if(!date)return null;
   const next=date<meeting?valid(date.getFullYear()+1,date.getMonth(),date.getDate()):date;
   return next?asISO(next):null;}
  if(weekday){const delta=(WEEKDAYS[weekday]-meeting.getDay()+7)%7||7;const date=new Date(meeting.getTime()+delta*86400000);return asISO(date);}
  return null;
 }
 function personMatches(item,{owner='',requester='',follower=''}={}){
  return (!owner||(owner==='__none__'?!item.owner:item.owner===owner))&&(!requester||(requester==='__none__'?!item.requester_person_id:item.requester_person_id===requester))&&(!follower||(follower==='__none__'?!item.follower_person_id:item.follower_person_id===follower));
 }
 function visibleSelection(selection,rows){const visible=new Set(rows.filter(i=>i.acceptance_state!=='proposed'&&!i.dismissed).map(i=>i.id));return new Map([...selection].filter(([id])=>visible.has(id)));}
 function meetingGroups(mentions){const groups=[],byId=new Map();mentions.forEach((mention,index)=>{const key=mention.item_id;if(key&&byId.has(key)){byId.get(key).mentions.push(mention);return;}const group={task:mention,index,mentions:[mention]};groups.push(group);if(key)byId.set(key,group);});return groups;}
 // The tasks of one meeting by owner, in the order each owner first appears; tasks without an owner come last.
 // One spelling of a name with other letter case is the same owner (2026-11-13).
 function ownerGroups(groups,ownerOf){const byOwner=new Map();for(const group of groups){const name=String(ownerOf(group)||'').trim(),key=name.toLocaleLowerCase();if(!byOwner.has(key))byOwner.set(key,{owner:name,groups:[]});byOwner.get(key).groups.push(group);}const rows=[...byOwner.values()];return [...rows.filter(r=>r.owner),...rows.filter(r=>!r.owner)];}
 return {STATES,workflow,inView,lastUpdate,suggestDueDate,personMatches,visibleSelection,meetingGroups,ownerGroups};
});
