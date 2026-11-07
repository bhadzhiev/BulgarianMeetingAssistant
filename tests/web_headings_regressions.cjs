const fs=require('node:fs'),assert=require('node:assert/strict');
const html=fs.readFileSync('web/index.html','utf8');
// Every main view introduces itself: a title plus a one-line description.
// Live and dynamic views (recording, detail, attention) describe themselves through their content instead.
const sections=[...html.matchAll(/<section id="(\w+)"[^>]*>([\s\S]*?)(?=<section|<\/main|$)/g)];
const described=['setup','importing','conversations','projects','calendar','tasks','find','prepare','analytics'];
for(const id of described){
 const body=sections.find(m=>m[1]===id)?.[2]||'';
 assert(body,`section ${id} exists`);
 assert(/<h1[^>]*>[^<]+<\/h1>/.test(body),`${id} has a visible title`);
 const sub=body.match(/class="subheading"[^>]*>([^<]+)<\/p>/);
 assert(sub&&sub[1].trim(),`${id} has a description line`);
}
// Page titles match their navigation labels: Library tabs, sidebar buttons and headings use one name each.
const findTab=html.match(/data-library="find"[^>]*>([^<]+)</)[1],findH1=html.match(/<section id="find"[\s\S]*?<h1[^>]*>([^<]+)</)[1],decode=s=>s.replace(/&amp;/g,'&');
assert.equal(decode(findH1),decode(findTab),'the find page is named like its tab');
const analyticsH1=html.match(/<section id="analytics"[\s\S]*?<h1[^>]*>([^<]+)</)[1];
assert.equal(analyticsH1,'Conversation analytics','analytics keeps the product name used by the sidebar');
// Each description describes its own page, not another one.
const projects=sections.find(m=>m[1]==='projects')[2];
assert(projects.includes('grouped by project'),'Projects describes grouping, not the whole library');
const tasks=sections.find(m=>m[1]==='tasks')[2];
assert(tasks.includes('tasks and decisions'),'My Work names what it collects');
console.log('Headings regression PASS: every view has a title and a description, and titles match their navigation labels.');
