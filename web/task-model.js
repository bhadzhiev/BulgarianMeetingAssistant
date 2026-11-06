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
 function personMatches(item,{owner='',requester='',follower=''}={}){
  return (!owner||(owner==='__none__'?!item.owner:item.owner===owner))&&(!requester||(requester==='__none__'?!item.requester_person_id:item.requester_person_id===requester))&&(!follower||(follower==='__none__'?!item.follower_person_id:item.follower_person_id===follower));
 }
 function visibleSelection(selection,rows){const visible=new Set(rows.filter(i=>i.acceptance_state!=='proposed'&&!i.dismissed).map(i=>i.id));return new Map([...selection].filter(([id])=>visible.has(id)));}
 return {STATES,workflow,inView,lastUpdate,personMatches,visibleSelection};
});
