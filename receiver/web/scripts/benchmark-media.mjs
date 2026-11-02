// Synthetic Node microbenchmark: parser and discarded-frame CPU only; not device FPS or touch latency.
import {readFileSync} from 'node:fs';
import {performance} from 'node:perf_hooks';
import ts from 'typescript';
import { fileURLToPath } from 'node:url';
if (!process.argv[2]) throw new Error('Usage: node scripts/benchmark-media.mjs /path/to/baseline/receiver/web');
const current = fileURLToPath(new URL('..', import.meta.url));
async function load(base,name,tail=''){const code=readFileSync(`${base}/src/${name}.ts`,'utf8').replace(/^import .*?;$/gm,'')+tail;return import('data:text/javascript;base64,'+Buffer.from(ts.transpileModule(code,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText).toString('base64'));}
function measure(fn,count){for(let i=0;i<1000;i++)fn();const times=[];for(let run=0;run<5;run++){const start=performance.now();for(let i=0;i<count;i++)fn();times.push(performance.now()-start);}times.sort((a,b)=>a-b);return {iterations:count,medianMs:+times[2].toFixed(3),usPerFrame:+(times[2]*1000/count).toFixed(3),runsMs:times.map(t=>+t.toFixed(3))};}
globalThis.window={setTimeout:()=>1,clearTimeout(){}};globalThis.document={hidden:true};
let sum=0;
const result={node:process.version,payloadBytes:65536,samples:5};
for(const [label,base] of [['before',process.argv[2]],['after',current]]){
 const protocol=await load(base,'protocol');const bytes=new Uint8Array(65536+11);bytes[0]=2;bytes[11]=0;bytes[12]=0;bytes[13]=0;bytes[14]=1;bytes[15]=0x65;bytes.fill(0x33,16);
 globalThis.annexBToAvcc=protocol.annexBToAvcc;
 const {VideoPlayer}=await load(base,'video','\nconst annexBToAvcc=globalThis.annexBToAvcc;');const player=new VideoPlayer({getContext(){return null;}},()=>{},()=>{},()=>{});player.state={usesDescription:true,decoder:{}};player.skipping=true;
 result[label]={parse:measure(()=>{sum+=protocol.parseWireMessage(bytes.buffer).data[100];},20000),discardBacklog:measure(()=>player.pushFrame({data:bytes.subarray(11),keyframe:false}),5000)};
}
console.log(JSON.stringify({...result,checksum:sum},null,2));
