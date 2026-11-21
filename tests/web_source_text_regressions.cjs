const assert=require('assert'),fs=require('fs'),vm=require('vm');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
const ctx={};vm.runInNewContext(slice('function inlineMarkdown(','// Rendered markdown for texts')+';this.inlineMarkdown=inlineMarkdown;this.renderMarkdown=renderMarkdown;',ctx);
const md=ctx.renderMarkdown;
// Links: https only, opened in the default browser, after all HTML is escaped.
assert.equal(ctx.inlineMarkdown('See [the plan](https://example.com/a?x=1&y=2).'),'See <a href="https://example.com/a?x=1&amp;y=2" target="_blank" rel="noopener noreferrer">the plan</a>.');
assert.equal(ctx.inlineMarkdown('Open https://example.com/x, then reply'),'Open <a href="https://example.com/x" target="_blank" rel="noopener noreferrer">https://example.com/x</a>, then reply');
assert.doesNotMatch(ctx.inlineMarkdown('[x](javascript:alert(1)) <img src=x onerror=1>'),/<a|<img/,'no script links and no raw HTML');
assert.doesNotMatch(ctx.inlineMarkdown('http://plain.example'),/<a/,'plain http stays text');
assert.equal(ctx.inlineMarkdown('https://a.example/**x**'),'<a href="https://a.example/**x**" target="_blank" rel="noopener noreferrer">https://a.example/**x**</a>','emphasis does not break a link');
assert.match(md('```\nhttps://example.com\n```'),/<pre><code>https:\/\/example\.com<\/code><\/pre>/,'code keeps links as text');
// The Markdown that the backend makes from HTML mail renders as structure.
const html=md('## Report\n\nHello **team**,\nsee [the plan](https://example.com).\n\n- First\n- Second\n\n> Old message\n>\n> line two');
assert.match(html,/<h2>Report<\/h2>/);assert.match(html,/<strong>team<\/strong>,<br>see <a /);assert.match(html,/<ul><li>First<\/li><li>Second<\/li><\/ul>/);assert.match(html,/<blockquote>Old message<br><br>line two<\/blockquote>/);
// Gmail, Chat and GitHub use one view.
assert.match(app,/function sourceText\(text\)\{const box=markdownBlock\(text\);box\.classList\.add\('source-text'\);return box;\}/);
assert.match(app,/card\.append\(top,message\.body\?sourceText\(message\.body\):el\('p','message-text'/,'Gmail');
assert.match(app,/const text=m\.available&&m\.body\?sourceText\(m\.body\):el\('p','message-text'/,'Chat');
assert.match(app,/body\.append\(r\.available&&r\.body\?sourceText\(r\.body\):el\('p','message-text'/,'GitHub');
assert.match(css,/\.source-text a\{color:var\(--green\);text-decoration:underline/);
console.log('source text regressions ok');
