import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import ts from 'typescript';
const code=fs.readFileSync(new URL('./public/browser-check.js',import.meta.url),'utf8');
const tree=ts.createSourceFile('classic.js',code,ts.ScriptTarget.ES5,true,ts.ScriptKind.JS);
function syntax(n){assert(![ts.SyntaxKind.ArrowFunction,ts.SyntaxKind.ClassDeclaration,ts.SyntaxKind.TemplateExpression,ts.SyntaxKind.AwaitExpression].includes(n.kind));if(ts.isVariableDeclarationList(n))assert.equal(n.flags&(ts.NodeFlags.Let|ts.NodeFlags.Const),0);ts.forEachChild(n,syntax);} syntax(tree);
function setup(modern,codec=true){
 const nodes={}; function node(){return {style:{},children:[],disabled:true,appendChild(n){this.children.push(n);}};}
 const d={getElementById(id){return nodes[id]??=node();},createElement(tag){const n=node();if(tag==='canvas')n.getContext=()=>({});if(modern&&tag==='script')n.noModule=false;if(modern&&tag==='dialog')n.showModal=()=>{};return n;},createTextNode(s){return s;},documentElement:modern?{requestFullscreen(){}}:{}};
 const w={navigator:{userAgent:modern?'Modern':'Android 4.2.2 Firefox/68'},setTimeout(){return 1;},clearTimeout(){},isSecureContext:true,WebSocket:function(){}};
 if(modern)Object.assign(w,{AudioContext:function(){},PointerEvent:function(){},AudioDecoder:function(){},VideoDecoder:{isConfigSupported:()=>Promise.resolve({supported:codec})},MediaSource:{isTypeSupported:()=>true}});
 vm.runInNewContext(code,{window:w,document:d});return {w,nodes};
}
let old=setup(false);assert.equal(old.w.F50BrowserCheck.allowed,false);assert.equal(old.w.F50BrowserCheck.done,true);assert.equal(old.nodes['browser-check'].style.display,'block');assert(old.nodes['browser-check-list'].children.some(n=>n.children[0].includes('缺少：WebCodecs')));
// Driver view (viewer audit V10): one headline, the missing things in plain words (each cause once), the Tesla advice.
assert.equal(old.nodes['browser-check-title'].textContent,'这台车机的浏览器无法显示 CarPlay 画面');
assert.equal(old.nodes['browser-check-note'].textContent,'缺少：视频解码（H.264 / WebCodecs）；浏览器太旧');
assert(old.nodes['browser-check-advice'].textContent.indexOf('特斯拉')===0,'the car advice names the Tesla');
assert.equal(old.nodes['browser-check-details-title'].textContent,'技术详情');
{ // English when this browser saved it; an insecure page is named as such, not as a missing API.
  const nodes={}; function node(){return {style:{},children:[],disabled:true,appendChild(n){this.children.push(n);}};}
  const d={getElementById(id){return nodes[id]??=node();},createElement(tag){const n=node();if(tag==='canvas')n.getContext=()=>({});if(tag==='script')n.noModule=false;if(tag==='dialog')n.showModal=()=>{};return n;},createTextNode(s){return s;},documentElement:{}};
  const w={navigator:{userAgent:'Modern'},setTimeout(){return 1;},clearTimeout(){},isSecureContext:false,WebSocket:function(){},AudioContext:function(){},PointerEvent:function(){},AudioDecoder:function(){},VideoDecoder:{isConfigSupported:()=>Promise.resolve({supported:true})},localStorage:{getItem:k=>k==='f50-language'?'en':null}};
  vm.runInNewContext(code,{window:w,document:d});await Promise.resolve();
  assert.equal(w.F50BrowserCheck.allowed,false);
  assert.equal(nodes['browser-check-title'].textContent,'This car browser cannot show the CarPlay picture');
  assert.equal(nodes['browser-check-note'].textContent,'Missing: not a secure connection (certificate not trusted, or http://)');
}
let good=setup(true);await Promise.resolve();assert.equal(good.w.F50BrowserCheck.allowed,true);good.w.F50BrowserCheck.appReady();assert.equal(good.nodes['browser-check-continue'].disabled,false);assert.equal(good.nodes['browser-check'].style.display,'none');
let bad=setup(true,false);await Promise.resolve();assert.equal(bad.w.F50BrowserCheck.allowed,false);
good.w.F50BrowserCheck.appFailed();assert.equal(good.nodes['browser-check'].style.display,'block');assert.equal(good.nodes['browser-check-continue'].disabled,true);
console.log('Browser check: legacy API failures, supported browser, H264 rejection and bundle failure passed.');
