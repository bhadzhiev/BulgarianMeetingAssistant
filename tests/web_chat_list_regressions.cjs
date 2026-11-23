const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// A direct message without activity in the last 30 days is hidden; a search still finds it (2026-11-23).
const c=vm.createContext({});vm.runInContext(slice('const CHAT_LIST_AGE=','function renderChatList(')+';this.chatQuiet=chatQuiet;',c);
const now=Date.UTC(2026,10,23),day=86400;
assert.equal(c.chatQuiet({type:'DIRECT_MESSAGE',last:0},now),true);
assert.equal(c.chatQuiet({type:'DIRECT_MESSAGE',last:now/1000-31*day},now),true);
assert.equal(c.chatQuiet({type:'DIRECT_MESSAGE',last:now/1000-2*day},now),false);
assert.equal(c.chatQuiet({type:'GROUP_CHAT',last:0},now),false,'group chats and spaces always show');
assert.equal(c.chatQuiet({type:'SPACE',last:0},now),false);
const list=slice('function renderChatList(','\n$(\'chat-search\')');
assert.match(list,/query\?chatLabel\(s\)\.toLocaleLowerCase\(\)\.includes\(query\):!chatQuiet\(s\)\|\|s\.name===chatSpace/);
assert.match(list,/' without activity in the last 30 days hidden\. Search to find one\.'/);
// The list refreshes itself when Chat opens and the last refresh is older than 10 minutes.
const load=slice('async function loadChat(','\nconst CHAT_LIST_AGE');
assert.match(load,/Date\.now\(\)-chatDiscoveredAt>CHAT_LIST_AGE&&\(!chatSpaces\.length\|\|Date\.now\(\)\/1000-\(discovery\.last_sync\|\|0\)>CHAT_LIST_AGE\/1000\)\)\{chatDiscoveredAt=Date\.now\(\);return chatAction\('discover'\);\}/);
assert.doesNotMatch(app,/Load more conversations/);
console.log('Chat list PASS: quiet direct messages hidden but searchable; the list refreshes itself after 10 minutes.');
// A click picks the burst of one sender; Shift+click extends across senders; Suggest a task sends every picked message.
{
 const toasts=[],c2=vm.createContext({chatPicked:[],toast:m=>toasts.push(m)});
 vm.runInContext(slice('const CHAT_PICK_LIMIT=','function renderChatActions(')+';this.chatPick=chatPick;this.setPicked=v=>{chatPicked=v};',c2);
 const m=(name,sender,date)=>({name,sender,date});
 const messages=[m('a','Ana',0),m('b','Ana',60),m('c','Ana',200),m('d','Ben',230),m('e','Ana',900),m('f','Ana',960)];
 const names=list=>Array.from(list,x=>x.name).join('');
 assert.equal(names(c2.chatPick(messages,1,false)),'abc','a click picks the whole burst');
 assert.equal(names(c2.chatPick(messages,4,false)),'ef','a gap of 5 minutes starts a new burst');
 assert.equal(names(c2.chatPick(messages,3,false)),'d');
 c2.setPicked(['a','b','c']);assert.equal(names(c2.chatPick(messages,4,true)),'abcde','Shift+click extends across senders');
 c2.setPicked(['d']);assert.equal(names(c2.chatPick(messages,0,true)),'abcd','Shift+click extends backwards');
 const many=Array.from({length:40},(_,i)=>m('m'+i,'Ana',i*10));c2.setPicked([]);
 assert.equal(c2.chatPick(many,5,false).length,30);assert.deepEqual(toasts,['A task can use up to 30 messages']);
}
const actions=slice('function renderChatActions(','\n$(\'chat-connect\')');
assert.match(actions,/usable\.length>1\?\{provider:'chat',name:usable\[0\]\.name,names:usable\.map\(m=>m\.name\),revisions:usable\.map\(m=>m\.revision\)\}/);
assert.match(actions,/'Select a message to turn it into a task\. Shift-click adds more messages\.'/);
console.log('Chat picks PASS: a click picks a burst, Shift+click extends, Suggest a task sends every picked message.');
