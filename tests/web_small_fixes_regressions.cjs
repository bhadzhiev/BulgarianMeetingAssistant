const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// Prepare me starts with the project of the newest meeting that has a known project.
const c=vm.createContext({projectList:()=>[{id:'net'},{id:'lift'}],state:{meetings:[
 {project_id:'net',started_at:'2026-11-01T09:00:00Z'},{project_id:'gone',started_at:'2026-11-06T09:00:00Z'},
 {project_id:null,started_at:'2026-11-07T09:00:00Z'},{project_id:'lift',created:'2026-10-01T09:00:00Z'}]}});
vm.runInContext(slice('function latestMeetingProject(','async function openPrepare('),c);
assert.equal(vm.runInContext('latestMeetingProject()',c),'net');
vm.runInContext("state.meetings=[{project_id:null,started_at:'2026-11-07T09:00:00Z'}]",c);
assert.equal(vm.runInContext('latestMeetingProject()',c),'','without a meeting in a project, the person chooses');
assert.match(slice('async function openPrepare(','async function loadPrepare('),/project:projectId\|\|prepareScope\.project\|\|latestMeetingProject\(\)/);
assert.doesNotMatch(app,/projectList\(\)\[0\]\?\.id/);
// Settings: each tab has its own name; the duplicate vocabulary button is gone.
assert.match(html,/data-tab="recording">Transcription<\/button>/);
assert.doesNotMatch(html,/open-vocabulary-settings/);assert.doesNotMatch(app,/open-vocabulary-settings/);
// Search: the empty result keeps its padding.
assert.match(app,/el\('p','empty-content card find-empty','Nothing matches/);assert.match(css,/\.find-empty\{padding:20px 24px\}/);
console.log('Small fixes PASS: Prepare me project, one name per Settings tab, padded empty search.');
