const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
class Node{
 constructor(tag,cls,text){Object.assign(this,{tag,className:cls,textContent:text,children:[],value:'',checked:false,disabled:false});}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=nodes;}
 showModal(){this.open=true;}
 close(){this.open=false;}
}
const nodes={},el=(...args)=>new Node(...args),$=id=>nodes[id]??=el('div');
const task=(id,extra={})=>({id,kind:'task',text:'Task '+id,owner:'Maria',due_date:'2026-11-16',links:[{meeting_id:'m'}],...extra});
const opened=[],context=vm.createContext({el,$,btn:(cls,text)=>el('button',cls,text),date:v=>v,toast(){},perform:fn=>fn(),openTaskEmail:async ids=>opened.push([...ids]),detail:{id:'m',title:'Daily',items:{a:task('a'),b:task('b'),c:task('c',{dismissed:true}),d:task('d',{acceptance_state:'proposed'}),e:task('e',{links:[{meeting_id:'other'}]})}}});
vm.runInContext(src.slice(src.indexOf('function meetingTaskEmailButton('),src.indexOf('function renderNotes(')),context);
vm.runInContext(src.slice(src.indexOf('function renderTaskEmailPreview('),src.indexOf("$('task-email-body').oninput")),context);
(async()=>{
 const button=vm.runInContext('meetingTaskEmailButton()',context);assert(!button.disabled);button.onclick();
 assert.equal($('meeting-email-tasks').children.length,2,'only accepted visible tasks from this meeting');
 assert($('meeting-email-continue').disabled,'empty selection cannot compose');
 const first=$('meeting-email-tasks').children[0].children[0];first.checked=true;first.onchange();
 assert(!$('meeting-email-continue').disabled);await $('meeting-email-continue').onclick();assert.deepEqual(opened[0],['a']);
 button.onclick();$('meeting-email-all').onclick();await $('meeting-email-continue').onclick();assert.deepEqual(opened[1],['a','b']);
 $('meeting-email-all').onclick();assert($('meeting-email-continue').disabled,'clear all resets selection');
 assert(vm.runInContext('meetingTaskEmailButton(true)',context).disabled,'busy meeting disables composer');
 $('task-email-body').value='Здравейте,\n\n1. <script>example</script>\nОтговорник: Maria\n\n—\nГенерирано от Atlanta';
 vm.runInContext('renderTaskEmailPreview()',context);
 const preview=$('task-email-preview');assert.equal(preview.children[1].className,'email-preview-task');
 assert.equal(preview.children[1].children[0].textContent,'1. <script>example</script>','preview uses text, never innerHTML');
 assert.equal(preview.children[2].className,'email-preview-footer');
 console.log('Meeting task email PASS: selection, filtering, select/clear all, busy guard and edited text preview.');
})().catch(error=>{console.error(error);process.exitCode=1});
