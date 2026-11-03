/* One status vocabulary. Each group answers one question, and one value never mixes two groups:
   storage (where is it kept), review (did a person check it), external (what reached GitHub),
   verification (how fresh is what we know). Revisions and operation IDs stay out of the labels. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.AtlantaStatus=api;})(globalThis,()=>{
 'use strict';
 const GROUPS={
  storage:{saved:['Saved on this Mac','ok']},
  review:{needs_review:['Needs review','warn'],edited:['Edited · needs confirmation','warn'],confirmed:['Confirmed','ok'],dismissed:['Dismissed','muted']},
  external:{approved:['Draft · not sent','muted'],sending:['Sending…','muted'],created:['Created','ok'],linked:['Linked','ok'],unknown:['Outcome unknown','warn'],
   failed:['Not sent','danger'],offline:['Offline — will not retry without approval','warn'],cancelled:['Draft · replaced','muted'],abandoned:['Not in GitHub','muted']},
  verification:{verified:['Verified','ok'],cached:['Cached','muted'],offline:['Offline · last known state','warn'],unchecked:['Not checked','muted'],changed:['Source changed — review again','warn']},
 };
 function status(group,state){const entry=GROUPS[group]?.[state];if(!entry)throw new Error('Unknown status '+group+'.'+state);return {group,state,label:entry[0],tone:entry[1]};}
 const label=(group,state)=>status(group,state).label;
 // A verified publication is a verification fact. A failure without a connection is the offline state.
 const publication=op=>op.state==='verified'?status('verification','verified'):status('external',op.state==='failed'&&op.result?.offline?'offline':op.state);
 // A GitHub link: a live check is Verified, a cache hit is Cached, no answer is Offline.
 const verification=link=>status('verification',{github:'verified',cached:'cached',offline:'offline'}[link?.verification]||'unchecked');
 return {GROUPS,status,label,publication,verification};
});
