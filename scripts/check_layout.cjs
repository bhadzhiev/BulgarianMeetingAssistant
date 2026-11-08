#!/usr/bin/env node
/* Layout check for the browser UI (decision D01).
   It opens each main view at the six required widths and at every width between them (smooth resizing),
   and reports a page that scrolls sideways or a visible control that goes out of the window.
   A row that scrolls inside its own box (overflow-x: auto) is allowed.

   Usage: run Atlanta on a COPY of a library, then
     NODE_PATH=<folder with playwright> node scripts/check_layout.cjs http://127.0.0.1:8799 <token> [step]
   The token is the launch token from the server log. Nothing is changed in the library. */
const {webkit}=require('playwright');
const [base,token,stepText]=process.argv.slice(2);
if(!base||!token){console.error('Usage: node scripts/check_layout.cjs <base URL> <token> [step px]');process.exit(2);}
const REQUIRED=[360,430,768,1280,1440,1920],STEP=Number(stepText||40);
const VIEWS=['/','/?view=work&tab=task','/?view=work&tab=decision','/?view=conversations','/?view=calendar','/?view=find','/?view=projects','/?view=team'];
const widths=[...new Set([...REQUIRED,...Array.from({length:Math.floor((1920-360)/STEP)+1},(_,i)=>360+i*STEP)])].sort((a,b)=>a-b);

// What goes out of the window: the page width, and visible elements past the right edge
// that are not inside a box that scrolls or clips sideways.
function measure(){
 const clipped=e=>{for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement){const s=getComputedStyle(p);if(['auto','scroll','hidden','clip'].includes(s.overflowX))return true;}return false;};
 const out=[...document.querySelectorAll('body *')].filter(e=>{
  if(!e.getClientRects().length||e.closest('dialog:not([open]),[hidden],[popover]:not(:popover-open)'))return false;
  // The content of a closed menu or disclosure is not on the screen.
  const closed=e.closest('details:not([open])');if(closed&&!e.closest('summary'))return false;
  const r=e.getBoundingClientRect(),s=getComputedStyle(e);
  return r.width>0&&r.right>innerWidth+1&&s.position!=='fixed'&&s.visibility!=='hidden'&&!clipped(e);
 }).slice(0,5).map(e=>e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+(typeof e.className==='string'&&e.className?'.'+e.className.split(' ')[0]:'')+'→'+Math.round(e.getBoundingClientRect().right));
 return {page:document.documentElement.scrollWidth,out};
}

(async()=>{
 const browser=await webkit.launch(),ctx=await browser.newContext({viewport:{width:1440,height:900}});
 await ctx.addCookies([{name:'meeting_session',value:token,url:base}]);
 const page=await ctx.newPage();await page.goto(base+'/?token='+token);await page.waitForTimeout(1200);
 const failures=[];
 for(const view of VIEWS){
  await page.setViewportSize({width:1440,height:900});await page.goto(base+view);await page.waitForTimeout(1200);
  // Smooth resizing: one page, the width changes step by step, as a person drags the window.
  for(const width of widths){
   await page.setViewportSize({width,height:900});await page.waitForTimeout(60);
   const m=await page.evaluate(measure);
   if(m.page>width||m.out.length)failures.push({view,width,page:m.page,out:m.out});
  }
 }
 await browser.close();
 if(!failures.length){console.log(`Layout PASS: ${VIEWS.length} views × ${widths.length} widths (${widths[0]}–${widths.at(-1)} px), no sideways overflow.`);return;}
 for(const f of failures)console.log(`${f.view} @ ${f.width}px: page ${f.page}px ${f.out.join(', ')}`);
 console.log(`Layout FAIL: ${failures.length} view/width combinations overflow.`);process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});
