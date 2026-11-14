const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b)=>{const start=app.indexOf(a);assert(start>=0,a);const end=app.indexOf(b,start+a.length);assert(end>start,b);return app.slice(start,end);};
function node(tag='',cls='',text=''){return {tag,className:cls,textContent:text,children:[],attrs:{},append(...xs){this.children.push(...xs)},replaceChildren(...xs){this.children=xs},setAttribute(k,v){this.attrs[k]=v},classList:{toggle(){}}};}
// A saved link to an empty Review opens the outcomes, while real pending items still open Review.
{
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};let opened=0;
 const c=vm.createContext({$:get,detail:{meeting_review_count:0},view:'detail',syncRoute(){},placeActions(){},perform:fn=>fn(),openMeetingReview(){opened++;}});
 vm.runInContext("let meetingTab='review';"+slice('function meetingReviewCount(','function markTranscript('),c);
 c.switchTab('review');assert.equal(vm.runInContext('meetingTab',c),'outcomes');assert.equal(opened,0);assert.equal(get('review-panel').hidden,true);
 c.detail.meeting_review_count=2;c.switchTab('review');assert.equal(opened,1);assert.equal(get('review-panel').hidden,false);
 assert.match(app,/\$\('tab-review'\)\.hidden=!meetingReviewCount\(detail\)/);
}
// Stored question flags and topic hits never become visible chores in recording analytics.
{
 const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
 const c=vm.createContext({$:get,el:node,detail:{transcript:[{}],analytics:{questions:[{text:'Кой започва?',answered:false}],topics:[{name:'MacBooks',matches:[{text:'Макар че'}]}],speakers:[{speaker:'Иван'}],total_speech_seconds:5}},shortDuration:()=> '5s',speakerStats:(target)=>target.append(node('div','','speaking time')),emptyNote:text=>node('p','',text)});
 vm.runInContext(slice('function renderMeetingAnalytics(','async function loadAnalytics('),c);c.renderMeetingAnalytics();
 const target=get('meeting-analytics-content');assert.equal(target.children.length,1);assert.equal(target.children[0].children[0].textContent,'Talk time');assert.equal(get('reanalyze').disabled,false);
 assert.doesNotMatch(slice('function renderGlobalAnalytics(','function renderTrackers('),/Not marked as answered|metric\('Questions'|topic\.matches/);
 assert.doesNotMatch(html,/TALK TIME · TOPICS · QUESTIONS/);
}
// Empty sections are quiet during reading; the editor code is retained.
assert.match(slice('function noteSection(','function '),/if\(!items\.length\) section\.hidden=true/);
assert.match(app,/section\.hidden=!minutes\.tasks\.length/);
// Selection is explicit in Cards as well as Compact. Sources and history remain reachable.
assert.match(slice('function renderBulkTasks(){','// Only the Tasks'),/if\(!taskSelection\.size&&!bulkPending\)/);
assert.match(app,/select:taskSelecting\|\|taskSelection\.size>0/);
assert.match(app,/el\('details','task-card-sources'\)/);
assert.match(app,/compactMenu=\[timeline,toggle\]/);
assert.doesNotMatch(slice('async function openMeetingReview(','// The publication state'),/What Atlanta understood|review-summary/);
console.log('UI simplification PASS: Review routes, pending reviews, analytics without question chores, explicit selection and retained sources.');
