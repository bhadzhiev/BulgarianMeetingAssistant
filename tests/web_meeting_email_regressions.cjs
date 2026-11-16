const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
for(const id of ['meeting-email','followup-intro','followup-preview'])assert(html.includes('id="'+id+'"'));
assert(src.includes("api('/api/meeting-email/draft',{meeting_id:followupEmailMeeting,self_person_id:managerSelf||null,to"));
class Node{constructor(tag,cls,text){Object.assign(this,{tag,cls,textContent:text,children:[],value:'',hidden:false,disabled:false,classList:{toggle(){}}});}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;}showModal(){this.open=true;}focus(){}querySelectorAll(){return this.children.filter(n=>n.checked);}}
const nodes={},$=id=>nodes[id]??=new Node('div'),requests=[],el=(...v)=>new Node(...v);
const data={mode:'meeting',subject:'Meeting',body:'Обобщение:\n\nPublic <text>\n\n—\nГенерирано от АТЛАНТА',recipients:[{name:'Maria',email:'maria@example.test',involved:true}],excluded_emails:['self@example.test'],missing_participants:['Unknown participant'],ai:{available:false,reason:'No AI'},gmail:{drafts:true}};
const c=vm.createContext({$,el,Set,emptyNote:text=>el('p','',text),selected:'m',managerSelf:'self-id',leaveEdits:async()=>true,api:async(path,body)=>{requests.push({path,body});return data;},perform:fn=>fn(),editorDirty:{clear(){}}});
vm.runInContext(src.slice(src.indexOf('let followupEmailMeeting='),src.indexOf("$('followup-close').onclick=")),c);
(async()=>{
 await $('meeting-email').onclick();assert.equal(requests[0].path,'/api/meeting-email/prepare');assert.equal(requests[0].body.self_person_id,'self-id');
 assert.equal($('followup-title').textContent,'Email meeting notes');assert($('followup-ai').hidden);assert($('followup-dialog').open);
 assert($('followup-status').textContent.includes('Your addresses are excluded'));assert($('followup-status').textContent.includes('Unknown participant'));
 assert.equal($('followup-people').children[0].children[0].checked,true);assert.equal($('followup-preview').children[1].textContent,'Public <text>','preview renders text safely');
 assert.equal($('followup-preview').children[0].cls,'email-preview-heading');
 console.log('Meeting email PASS: visible entry point, self profile, participant defaults, missing-email notice and safe live preview.');
})().catch(e=>{console.error(e);process.exitCode=1});
