import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import ts from 'typescript';
const code=fs.readFileSync(new URL('./public/browser-check.js',import.meta.url),'utf8');
const tree=ts.createSourceFile('classic.js',code,ts.ScriptTarget.ES5,true,ts.ScriptKind.JS);
function syntax(n){assert(![ts.SyntaxKind.ArrowFunction,ts.SyntaxKind.ClassDeclaration,ts.SyntaxKind.TemplateExpression,ts.SyntaxKind.AwaitExpression].includes(n.kind));if(ts.isVariableDeclarationList(n))assert.equal(n.flags&(ts.NodeFlags.Let|ts.NodeFlags.Const),0);ts.forEachChild(n,syntax);} syntax(tree);
function setup(modern,codec=true){
 const nodes={}; function node(){return {style:{},children:[],disabled:true,attributes:{},appendChild(n){this.children.push(n);},setAttribute(k,v){this.attributes[k]=v;}};}
 const d={getElementById(id){return nodes[id]??=node();},createElement(tag){const n=node();if(tag==='canvas')n.getContext=()=>({});if(modern&&tag==='script')n.noModule=false;if(modern&&tag==='dialog')n.showModal=()=>{};return n;},createTextNode(s){return s;},documentElement:modern?{requestFullscreen(){}}:{}};
 const w={navigator:{userAgent:modern?'Modern':'Android 4.2.2 Firefox/68'},setTimeout(){return 1;},clearTimeout(){},isSecureContext:true,WebSocket:function(){}};
 if(modern)Object.assign(w,{AudioContext:function(){},PointerEvent:function(){},AudioDecoder:function(){},VideoDecoder:{isConfigSupported:()=>Promise.resolve({supported:codec})},MediaSource:{isTypeSupported:()=>true}});
 vm.runInNewContext(code,{window:w,document:d});return {w,nodes};
}
let old=setup(false);assert.equal(old.w.F50BrowserCheck.allowed,false);assert.equal(old.w.F50BrowserCheck.done,true);assert.equal(old.nodes['browser-check'].style.display,'block');// 1.6.0: a row per check in the settings panel's look - the name, the result as the value, the reason only under a
// check that failed.
{const rows=old.nodes['browser-check-list'].children,row=rows.find(n=>n.children[0].children[0]==='视频解码');
 assert.equal(row.className,'missing');assert.equal(row.children[1].children[0],'缺少');
 assert.equal(row.children[0].children[1].children[0],'缺少 VideoDecoder 无法显示画面。');
 const passed=rows.find(n=>n.children[0].children[0]==='安全连接');
 assert.equal(passed.className,'ok');assert.equal(passed.children[1].children[0],'通过');assert.equal(passed.children[0].children.length,1,'no reason under a passed check');}
// Driver view (viewer audit V10): one headline, the missing things in plain words (each cause once), the Tesla advice.
assert.equal(old.nodes['browser-check-title'].textContent,'兼容性检测','the panel row\'s name (1.6.4, owner: row and title one name); short (Apple: under 15 characters), the result is the first line');
assert.equal(old.nodes['browser-check-status'].textContent,'此浏览器无法显示 CarPlay 画面');
assert.equal(old.nodes['browser-check-note'].textContent,'缺少：视频解码；较新的浏览器','plain words, no asides in brackets (1.6.0)');
assert.equal(old.nodes['browser-check-advice'].textContent,'请在「控制 › 软件」更新车辆软件后再试。','one thing to do, in the Tesla\'s own menu (1.6.0)');
assert.equal(old.nodes['browser-check-agent'].textContent,'浏览器上报：Android 4.2.2 Firefox/68','the browser\'s own report, only when something failed');
assert(!/轻点|声音|tap/i.test(code.split('var T={')[1].split('};')[0]),'no word about a first sound: the page has played none since 1.3.0');
{ // English when this browser saved it; an insecure page is named as such, not as a missing API.
  const nodes={}; function node(){return {style:{},children:[],disabled:true,attributes:{},appendChild(n){this.children.push(n);},setAttribute(k,v){this.attributes[k]=v;}};}
  const d={getElementById(id){return nodes[id]??=node();},createElement(tag){const n=node();if(tag==='canvas')n.getContext=()=>({});if(tag==='script')n.noModule=false;if(tag==='dialog')n.showModal=()=>{};return n;},createTextNode(s){return s;},documentElement:{}};
  const w={navigator:{userAgent:'Modern'},setTimeout(){return 1;},clearTimeout(){},isSecureContext:false,WebSocket:function(){},AudioContext:function(){},PointerEvent:function(){},AudioDecoder:function(){},VideoDecoder:{isConfigSupported:()=>Promise.resolve({supported:true})},localStorage:{getItem:k=>k==='f50-language'?'en':null}};
  vm.runInNewContext(code,{window:w,document:d});await Promise.resolve();
  assert.equal(w.F50BrowserCheck.allowed,false);
  assert.equal(nodes['browser-check-title'].textContent,'Compatibility check');
  assert.equal(nodes['browser-check-status'].textContent,'This browser can’t show the CarPlay picture');
  assert.equal(nodes['browser-check-note'].textContent,'Missing: a secure connection');
  assert.equal(nodes['browser-check-advice'].textContent,'Open this page at the box’s https:// address.','the advice for that cause');
}
let good=setup(true);await Promise.resolve();assert.equal(good.w.F50BrowserCheck.allowed,true);
assert.equal(good.nodes['browser-check-status'].textContent,'兼容性检测通过');
{ // the page's title is the name of the panel's row that opens it (1.6.4)
  const i18n=fs.readFileSync(new URL('./src/i18n.ts',import.meta.url),'utf8'),html=fs.readFileSync(new URL('./index.html',import.meta.url),'utf8');
  assert.match(i18n,/browserCheck: \['兼容性检测', 'Compatibility check'\]/);assert.match(html,/<h2 id="browser-check-title">兼容性检测<\/h2>/);}
assert.equal(good.nodes['browser-check-agent'].textContent,undefined,'nothing failed: no browser report');
assert.equal(good.nodes['browser-check-continue'].attributes['aria-label'],'返回','the chevron back to the panel (1.6.0: it said 完成)');assert.equal(good.nodes['browser-check-continue'].hidden,true,'the bar button waits for the player');
good.w.F50BrowserCheck.appReady();assert.equal(good.nodes['browser-check-continue'].disabled,false);assert.equal(good.nodes['browser-check-continue'].hidden,false);assert.equal(good.nodes['browser-check'].style.display,'none');
{ // Opened from the panel, ‹ goes back to the panel (main.ts reopens it), not to CarPlay (owner, 2026-11-14); once
  let back=0;good.w.F50BrowserCheck.show(()=>back++);assert.equal(good.nodes['browser-check'].style.display,'block');
  good.nodes['browser-check-continue'].onclick();assert.equal(good.nodes['browser-check'].style.display,'none');assert.equal(back,1,'back to the panel');
  good.w.F50BrowserCheck.show();good.nodes['browser-check-continue'].onclick();assert.equal(back,1,'shown without a way back: just hides');}
let bad=setup(true,false);await Promise.resolve();assert.equal(bad.w.F50BrowserCheck.allowed,false);
good.w.F50BrowserCheck.appFailed();assert.equal(good.nodes['browser-check'].style.display,'block');assert.equal(good.nodes['browser-check-continue'].disabled,true);assert.equal(good.nodes['browser-check-continue'].hidden,true);
console.log('Browser check: legacy API failures, supported browser, H264 rejection and bundle failure passed.');
