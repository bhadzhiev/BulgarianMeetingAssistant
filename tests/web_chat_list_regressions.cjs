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
