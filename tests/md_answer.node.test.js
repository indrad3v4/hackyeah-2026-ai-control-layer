/* Node-level proof of the answer renderer (AC3 + AC4).
 *
 * Two things are proven here, and only real bytes are used:
 *   1. the VENDORED markdown-it file (loaded from the repo, exactly the file GET
 *      /vendor/markdown-it.umd.min.js serves) with the SAME options mdAnswer() builds
 *      (html:false) turns `**bold**` into <strong>, a `-` list into <ul><li>, and does NOT
 *      turn `<script>alert(1)</script>` into a script element;
 *   2. the REAL mdAnswer() sliced out of index.html, with the markdown-it / DOMPurify globals
 *      DELETED, returns escaped plain text and does not throw (AC4).
 *
 * Usage: node tests/md_answer.node.test.js <index.html>
 * Exit code 0 = every assertion held; non-zero = at least one failed.
 */
'use strict';
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const indexHtml = process.argv[2] || path.join(root, 'index.html');
const vendorJs = path.join(root, 'vendor', 'markdown-it.umd.min.js');

let failures = 0;
function ok(name, cond, detail) {
  const verdict = cond ? 'PASS' : 'FAIL';
  if (!cond) failures++;
  console.log(`${verdict}  ${name}${detail ? '  -> ' + detail : ''}`);
}

// --- 1. the vendored library, isolated (as the /vendor route serves it) -----------------------
const factory = require(vendorJs);              // UMD: module.exports is markdown-it
const MarkdownIt = factory.default || factory;  // tolerate a wrapped default export
const md = new MarkdownIt({ html: false, linkify: true, breaks: true, typographer: false });

const bold = md.render('**bold**');
ok('markdown-it: **bold** renders a <strong>', bold.includes('<strong>bold</strong>'), bold.trim());

const list = md.render('- one\n- two\n');
ok('markdown-it: a "-" list renders <ul><li>',
   list.includes('<ul>') && list.includes('<li>one</li>') && list.includes('<li>two</li>'),
   list.replace(/\n/g, ''));

const script = md.render('<script>alert(1)</script>');
ok('markdown-it: <script> does NOT become a script element',
   !/<script\b/i.test(script) && script.includes('&lt;script&gt;'), script.trim());

// --- 2. the REAL mdAnswer() from index.html, with the globals deleted (AC4) --------------------
const src = fs.readFileSync(indexHtml, 'utf8');
function sliceFn(name, nextName) {
  const start = src.indexOf('function ' + name + '(');
  const end = src.indexOf('\nfunction ' + nextName + '(', start);
  if (start < 0 || end < 0) { console.error(`could not slice ${name}`); process.exit(2); }
  return src.slice(start, end);
}
// esc() is the page's own escaper; mdAnswer() must use it in the fallback path.
const escFn = src.slice(src.indexOf('function esc('), src.indexOf('\n', src.indexOf('function esc(')));
const mdAnswerFn = sliceFn('mdAnswer', 'setAskFailure');

// Build the function with NO markdown-it and NO DOMPurify in scope, exactly the "both scripts 404"
// world the page must survive.
const makeMdAnswer = new Function('esc', `
  ${escFn}
  ${mdAnswerFn}
  return mdAnswer;
`);
const mdAnswer = makeMdAnswer(
  v => String(v == null ? '—' : v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
);

ok('mdAnswer is defined when sliced from index.html', typeof mdAnswer === 'function');

let threw = false, out = '';
try {
  out = mdAnswer('<b>x</b> & <img src=x onerror=alert(1)>');
} catch (e) { threw = true; }
ok('mdAnswer: does not throw with the libraries absent', !threw);
ok('mdAnswer: fallback escapes markup (no raw < or >)', !threw && out.indexOf('<') === -1 && out.indexOf('>') === -1,
   out);
ok('mdAnswer: fallback escapes the ampersand', out.includes('&amp;'));

let out2 = '';
try { out2 = mdAnswer(null); } catch (e) { threw = true; }
ok('mdAnswer: null input is safe and does not throw', !threw && typeof out2 === 'string', JSON.stringify(out2));

console.log(failures ? `\n${failures} assertion(s) FAILED` : '\nall md-answer assertions held');
process.exit(failures ? 1 : 0);
