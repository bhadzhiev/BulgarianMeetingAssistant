const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8'),css=fs.readFileSync('web/style.css','utf8');
const extract=(s,a,b)=>s.slice(s.indexOf(a),s.indexOf(b,s.indexOf(a)));
// The helper builds a real SVG element in the nav-icon style.
const node=(ns,tag)=>{const classes=[];return {ns,tag,attrs:{},children:[],classes,classList:{add(...xs){classes.push(...xs)}},setAttribute(k,v){this.attrs[k]=v},append(...xs){this.children.push(...xs)}};};
const c=vm.createContext({document:{createElementNS:node}});
vm.runInContext(extract(app,'const ICON_PATHS=','function option('),c);
const svg=vm.runInContext('icon("close")',c);
assert.equal(svg.tag,'svg');assert.equal(svg.attrs.viewBox,'0 0 24 24');assert.equal(svg.attrs['aria-hidden'],'true');assert(svg.classes.includes('icon'));
assert.equal(svg.children[0].attrs.d,vm.runInContext('ICON_PATHS.close',c));
assert.equal(vm.runInContext('icon("nonsense").children[0].attrs.d',c),vm.runInContext('ICON_PATHS.sparkle',c),'unknown icons fall back to sparkle');
for(const name of ['close','prev','next','jump','external','download','restore','edit','gear','sparkle','star','check','mic','screen'])assert(vm.runInContext(`ICON_PATHS[${JSON.stringify(name)}]`,c),name+' path exists');
// No icon-role glyphs remain: buttons and links carry SVG, sentences keep their arrows.
for(const glyph of ['✕','✎','⚙','↺','◉','▣','✦'])assert(!html.includes(glyph),'index.html keeps no '+glyph);
assert(!/>[←→↓]</.test(html),'navigation and download arrows are SVG now');
for(const snippet of ["'✕'","'↗ '","'↗'","'↓ '","'⚙'","' ✎'","' ↺'"])assert(!app.includes(snippet),'app.js keeps no '+snippet);
assert(css.includes('.icon{'),'icon styles exist');
console.log('Icons regression PASS: SVG helper, 14 named paths, no icon-role glyphs left in buttons or links.');
