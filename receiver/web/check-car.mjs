import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
async function load(name, transform = s => s) {
  const source=transform(readFileSync(new URL(`./src/${name}.ts`,import.meta.url),'utf8'));
  const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}});
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
}
const {suggestedResolution,windowResolution,windowShape,aspectChanged,shownSize,areaPlan,areaSize,areaFor,sameStream,showsShape,MAX_AREAS,frameRateCheck}=await load('display-fit');
{ // 60 fps the decoder cannot keep up with (Zeekr 7X): two 10 s reports in a row with two catch-ups each go to 30 fps.
  let c=frameRateCheck(0,3,60);assert.deepEqual(c,{run:1,lower:false},'one report is not enough');
  assert.deepEqual(frameRateCheck(c.run,2,60),{run:0,lower:true},'two in a row lower it');
  assert.deepEqual(frameRateCheck(c.run,1,60),{run:0,lower:false},'a single catch-up in between starts over');
  assert.deepEqual(frameRateCheck(1,5,30),{run:0,lower:false},'30 fps is never lowered'); }
{ // XPeng fullscreen is 876x579 or 876x641 CSS px (dock shown or not): 1280x846 or 1280x936 (F50 drive 2026-10-13).
  // With view areas the page (1280x756) and both fullscreen heights are areas: learned once, then switched.
  const s846=suggestedResolution(876,579),s936=suggestedResolution(876,641),page=suggestedResolution(876,518);
  assert.deepEqual([s846,s936],[{width:1280,height:846},{width:1280,height:936}]);
  const start={width:1280,height:756,hevc:false,fps:30};
  let plan=areaPlan(start,s846,false,[page]); let display=plan.display, shapes=plan.shapes;
  plan=areaPlan(display,s936,false,shapes); display=plan.display; shapes=plan.shapes;
  assert.deepEqual([display.width,display.height,display.areas.length],[1280,936,3],'three shapes, the stream as tall as the tallest');
  for (const [shape,index] of [[page,0],[s846,1],[s936,2],[page,0]]) {
    const next=areaPlan(display,shape,false,shapes);
    assert.deepEqual(next.display,{...display,area:index},'every later change only switches area');
    display=next.display; }
  assert.equal(areaPlan(display,page,false,shapes),null,'the same shape never'); }
// Auto with a fast decoder goes up to 2560 on the long side (user 2026-10-19: owners set 2560 by hand on 2.5K screens);
// a Tesla's 1920x1200 panel (1254x784 CSS px at 1.53) stays as it was.
assert.deepEqual(suggestedResolution(2560,1440,2560),{width:2560,height:1440},'a 2.5K screen gets its own pixels');
assert.deepEqual(suggestedResolution(3840,2160,2560),{width:2560,height:1440},'never beyond 2560');
assert.deepEqual(suggestedResolution(1254*1.53,784*1.53,2560),{width:1918,height:1200},'Tesla: same as before');
assert.deepEqual(suggestedResolution(2560,1440),{width:1920,height:1080},'1920 unless asked for more');
{ // Tesla defaults (2026-10-26): performance mode off, long side capped at 1920 (the f50-allow-2560 switch went in 1.3.2). The two shapes a
  // Tesla page takes (Model 3/Y, DPR 1.53): windowed 773x601 CSS, borderless 1256x706 CSS (view-areas header).
  const dpr=1.53;
  assert.deepEqual(windowResolution(773,601,1920),{width:774,height:602},'first session, slow or unproven decoder: the window as it is');
  assert.deepEqual(windowResolution(773*dpr,601*dpr,1920),{width:1182,height:920},'fast decoder, windowed: real pixels');
  assert.deepEqual(windowResolution(1256*dpr,706*dpr,1920),{width:1920,height:1080},'fast decoder, borderless: 1922 px capped to 1920');
  assert.deepEqual(suggestedResolution(773,601,1920),{width:1280,height:996},'performance mode on, windowed: upsized to 1280');
  assert.deepEqual(windowResolution(1256*dpr,706*dpr,2560),{width:1922,height:1080},'why the 2560 switch went (1.3.2): in a Tesla it only ever added 2 px'); }
// Normal mode: the window's own size, a 720 minimum width, the same maximum (2026-10-23).
assert.deepEqual(windowResolution(876,518),{width:876,height:518},'a 2/3 window keeps its size');
assert.deepEqual(windowResolution(490,580),{width:720,height:852},'the 1/3 window gets the minimum width');
assert.deepEqual(windowResolution(1372,686),{width:1372,height:686},'the full window stays');
assert.deepEqual(windowResolution(3840,2160),{width:1920,height:1080},'and the maximum still applies');
{ // A Tesla page (2026-10-16 diagnosis): 1280x996 H.264 first, then the browser proves a fast decoder. Real pixels and
  // H.265 for the same window are sharper only: that waits for the session to end. A new shape cannot wait.
  const live={width:1280,height:996,fps:60,uiScale:100,hevc:false};
  const sharp=suggestedResolution(1254*1.53,976*1.53,2560);
  const plan=areaPlan(live,sharp,true,[{width:1280,height:996}]);
  assert.ok(plan&&!sameStream(live,plan.display),'sharper and H.265 is a new stream');
  assert.ok(showsShape(live,sharp),'but the phone already has this shape: it waits');
  const full=suggestedResolution(1254,744);
  assert.ok(!showsShape(live,full),'fullscreen the first time is a new shape: now');
  const both=areaPlan(live,full,false,[{width:1280,height:996}]).display;
  assert.ok(showsShape(both,{width:1280,height:996})&&showsShape(both,full),'each declared area counts');
  assert.ok(sameStream(both,{...both,area:0}),'switching area keeps the stream');
  assert.ok(!sameStream(both,{...both,fps:30}),'another fps does not');
  assert.ok(!showsShape(live,{width:720,height:1280}),'the other orientation renegotiates now'); }
assert.deepEqual(shownSize(1280,846,1280,756),{width:1280,height:756},'fullscreen picture fills the normal page without bars');
assert.deepEqual(shownSize(1280,756,1280,846),{width:1280,height:846},'and the other way round');
assert.deepEqual(shownSize(1280,846,1082,1280),{width:1082,height:1280},'no black bars even before a portrait renegotiation');
assert.deepEqual(shownSize(0,0,1280,756),{width:0,height:0},'no picture yet');
for(const [w,h] of [[1920,1080],[2560,1440],[1920,720],[720,1280],[800,480],[320,700]]){
 assert.deepEqual(shownSize(1280,720,w,h),{width:w,height:h},'always fills the view');
 const target=suggestedResolution(w,h);assert.ok(Object.values(target).every(v=>v>=480&&v<=1920&&v%2===0));
 assert.ok(!aspectChanged(target,target));
}
assert.equal(aspectChanged({width:1280,height:720},{width:1920,height:1080}),false);
assert.equal(aspectChanged({width:1280,height:720},{width:1920,height:720}),true);
{ // Hiccups for the viewer log: a gap in a flowing stream (network/box) apart from frames the car's decoder held long.
  let clock=0;const realNow=performance.now;Object.defineProperty(performance,'now',{value:()=>clock,configurable:true,writable:true});
  globalThis.EncodedVideoChunk=class {constructor(v){Object.assign(this,v);}};
  const {VideoPlayer}=await load('video',s=>s.replace(/^import .*?;$/gm,''));
  const player=new VideoPlayer({getContext(){return null;}},()=>{},()=>{},()=>{});
  player.state={usesDescription:false,timestampUs:0,frameIntervalUs:16667,decoder:{decode(){},decodeQueueSize:0}};
  for(const t of [0,20,40,400,420,1400,2400]){clock=t;player.pushFrame({data:new Uint8Array([1]),keyframe:false});}
  assert.deepEqual(player.takeStalls(),{stalls:1,stallMaxMs:360,slowFrames:0,paintMaxMs:0,skipped:0,caughtUp:0},'Only a gap with frames flowing on both sides counts; motion ending into an idle screen (1 frame/s) does not');
  assert.deepEqual(player.takeStalls(),{stalls:0,stallMaxMs:0,slowFrames:0,paintMaxMs:0,skipped:0,caughtUp:0},'Counters restart for each report');
  Object.defineProperty(performance,'now',{value:realNow,configurable:true,writable:true}); }
{ // A decoder slower than the stream (Zeekr 7X, 2026-10-19: 60 fps asked, 504 to 1689 frames queued, seconds behind):
  // the page skips picture frames up to the next keyframe and shows that one at once.
  let clock=0;const realNow=performance.now;Object.defineProperty(performance,'now',{value:()=>clock,configurable:true,writable:true});
  globalThis.EncodedVideoChunk=class {constructor(v){Object.assign(this,v);}};
  globalThis.document={hidden:false};
  const {VideoPlayer}=await load('video',s=>s.replace(/^import .*?;$/gm,''));
  let asks=0;const canvas={getContext(){return {drawImage(){}};},width:1280,height:720};
  const player=new VideoPlayer(canvas,()=>{},()=>{},()=>{asks++;});
  const decoded=[];let resets=0;
  const decoder={decodeQueueSize:0,decode(c){decoded.push(c);},reset(){resets++;decoded.length=0;},configure(){}};
  player.state={decoder,config:{codec:'avc1'},usesDescription:false,timestampUs:0,frameIntervalUs:16667,width:1280,height:720};
  const push=(t,keyframe=false)=>{clock=t;player.pushFrame({data:new Uint8Array([1]),keyframe});};
  const paint=chunk=>player.paint({timestamp:chunk.timestamp,displayWidth:1280,displayHeight:720});
  // Painted as fast as they come: never behind.
  for(let t=0;t<2000;t+=17){push(t,t===0);paint(decoded.at(-1));}
  assert.deepEqual([asks,player.takeStalls().skipped],[0,0],'a decoder that keeps up');
  // The decoder stops painting: once 8 frames wait, the oldest over 200 ms, frames are skipped and a keyframe asked.
  decoded.length=0;let t=2000;
  for(;t<2400;t+=17)push(t);
  const held=decoded.length;
  assert.ok(held>=8&&held<=14,`skips from the 8th waiting frame over 200 ms (${held} decoded)`);
  assert.equal(asks,1,'one keyframe asked');
  for(;t<3500;t+=17)push(t);
  assert.equal(decoded.length,held,'nothing more is decoded');
  assert.equal(asks,2,'asked again after a second, no more often');
  document.hidden=true;for(;t<5000;t+=17)push(t);
  assert.equal(asks,2,'not asked while the page is hidden');
  document.hidden=false;push(t+=17);
  assert.equal(asks,3,'asked once shown again');
  push(t+=17,true);
  assert.equal(resets,1,'the keyframe drops what the decoder held');
  assert.equal(decoded.length,1,'and is decoded at once');
  paint(decoded[0]);push(t+=17);
  assert.equal(decoded.length,2,'then frames are decoded again');
  const stalls=player.takeStalls();
  assert.equal(stalls.caughtUp,1);assert.ok(stalls.skipped>100,'the skipped frames are counted for the viewer log');
  // A still screen keeps a frame or two in the decoder for a second each: never behind.
  decoded.length=0;
  for(let i=0;i<10;i++){push(t+=1000);if(decoded.length>2)paint(decoded.at(-3));}
  assert.equal(decoded.length,10,'a still screen is never skipped');
  // A burst after a hiccup: many frames at once, none old.
  paint(decoded.at(-1));decoded.length=0;for(let i=0;i<12;i++)push(t+=1);
  assert.equal(decoded.length,12,'a burst is decoded');
  // A frame painted removes older ones the decoder let go, so they never count as waiting.
  paint(decoded.at(-1));assert.equal(player.arrivals.size,0,'nothing older stays listed');
  delete globalThis.document;
  Object.defineProperty(performance,'now',{value:realNow,configurable:true,writable:true}); }
{ // Each keyframe the box asks for comes with the same codec config again (twice, 110 times in a 42-minute drive):
  // tearing the decoder down and resizing the canvas blanked the picture until the car's slow decoder painted again.
  const decoders=[];let sizeWrites=0;
  globalThis.VideoDecoder=class {constructor(){this.state='unconfigured';this.decodeQueueSize=0;decoders.push(this);}configure(){this.state='configured';}decode(){}close(){this.state='closed';}};
  globalThis.window=globalThis.window??{};window.setTimeout=()=>1;window.clearTimeout=()=>{};
  const canvas={getContext(){return null;},set width(v){sizeWrites++;this.w=v;},get width(){return this.w;},set height(v){sizeWrites++;this.h=v;},get height(){return this.h;}};
  const {VideoPlayer}=await load('video',s=>s.replace(/^import .*?;$/gm,'')+'\nconst VideoCodec={H264:1,H265:2};function avcCodecString(){return "avc1.640028";}function annexBToAvcc(d){return d;}');
  const player=new VideoPlayer(canvas,()=>{},()=>{},()=>{});
  const config=(w=1280,h=846,last=0x40)=>({kind:'video-config',streamType:110,codec:1,width:w,height:h,codecData:new Uint8Array([1,0x64,0,0x28,last])});
  player.configure(config());await Promise.resolve();
  assert.equal(decoders.length,1);const writes=sizeWrites;
  player.configure(config());player.configure(config());await Promise.resolve();
  assert.equal(decoders.length,1,'The same config keeps the running decoder');
  assert.equal(decoders[0].state,'configured');
  assert.equal(sizeWrites,writes,'and leaves the canvas (and its picture) alone');
  player.configure(config(1280,846,0x41));await Promise.resolve();
  assert.equal(decoders.length,2,'A different config gets a new decoder');
  assert.equal(sizeWrites,writes,'but a canvas of the same size keeps showing the last picture');
  player.configure(config(1082,1280,0x41));await Promise.resolve();
  assert.equal(canvas.width,1082,'A new size resizes the canvas');assert.equal(canvas.height,1280); }
{ // The pong waits behind every queued frame, so its round trip is how far the picture lags behind.
  const {LagProbe}=await load('lag');const probe=new LagProbe();
  probe.sent(0);probe.sent(1000);probe.pong(120);probe.pong(1900);
  assert.deepEqual(probe.take(2000),{lagMs:900},'Worst round trip of the window');
  assert.deepEqual(probe.take(3000),{},'Nothing measured, nothing reported');
  probe.sent(3000);probe.sent(4000);
  assert.deepEqual(probe.take(14000),{lagMs:11000},'A pong still queued counts with its age, so a lag beyond the window shows');
  probe.reset();assert.deepEqual(probe.take(15000),{},'A new connection starts clean');
  for(let i=0;i<100;i++)probe.sent(i);assert.ok(probe.pending<=30,'No unbounded list when pongs never come'); }
const {isNight,parseNightMode}=await load('night');
const at=(h,m)=>new Date(2026,9,10,h,m);
assert.equal(parseNightMode(null),'schedule');assert.equal(parseNightMode('bogus'),'schedule');assert.equal(parseNightMode('system'),'system');
assert.equal(isNight('schedule',at(18,29),true),false);assert.equal(isNight('schedule',at(18,30),false),true);
assert.equal(isNight('schedule',at(0,0),false),true);assert.equal(isNight('schedule',at(6,29),false),true);assert.equal(isNight('schedule',at(6,30),true),false);
assert.equal(isNight('system',at(12,0),true),true);assert.equal(isNight('system',at(23,0),false),false);
assert.equal(isNight('day',at(23,0),true),false);assert.equal(isNight('night',at(12,0),false),true);
console.log('Car checks passed: aspect fit, hiccups, decode backlog, night schedule.');
{ // View areas (2026-10-14): a window shape seen before is an area switch, never a reconnect.
  const windowed={width:1280,height:996}, full={width:1920,height:1080};
  const start={width:1280,height:996,hevc:true,fps:30};
  const first=areaPlan(start,windowed,true,[]);
  assert.equal(first,null,'the shape in use: nothing to do');
  const learn=areaPlan(start,full,true,[windowed]);
  assert.deepEqual([learn.display.width,learn.display.height],[1920,1080],'the stream covers both shapes');
  assert.deepEqual(learn.display.areas,[windowed,full],'both shapes declared as areas');
  assert.equal(learn.display.area,1,'and the fullscreen one in use');
  const back=areaPlan(learn.display,windowed,true,learn.shapes);
  assert.deepEqual(back.display,{...learn.display,area:0},'back to the window: only the area changes');
  assert.equal(areaPlan(back.display,{width:1282,height:998},true,back.shapes),null,'a shape within 2.5% is the same area');
  const sharper=areaPlan(back.display,{width:1280,height:996},false,back.shapes);
  assert.equal(sharper.display.hevc,false,'another codec declares again');
  const s=areaSize(1920,1080,windowed,773,601);
  assert.ok(Math.abs(s.width-773*1920/1280)<1e-6 && Math.abs(s.height-601*1080/996)<1e-6,'the area fills the view');
  assert.deepEqual(areaSize(1280,996,undefined,773,601),{width:773,height:601},'without areas as before');
  const many=Array.from({length:MAX_AREAS},(_,i)=>({width:1280,height:400+60*i}));
  const capped=areaPlan(start,{width:1280,height:300},true,many);
  assert.equal(capped.display.areas.length,MAX_AREAS,'at most MAX_AREAS areas');
  assert.ok(!capped.display.areas.some(a=>a.height===400),'the least recently used shape gives way');
  assert.equal(capped.shapes.length,MAX_AREAS,'and is no longer kept');
  // Turning the window (xcertplay 1836c27): only the window's orientation is declared, so the stream is never the
  // near-square envelope of a landscape and a portrait shape; the other orientation's shapes stay remembered.
  const portrait={width:1082,height:1280};
  const turned=areaPlan(learn.display,portrait,true,learn.shapes);
  assert.deepEqual([turned.display.width,turned.display.height,turned.display.areas.length],[1082,1280,0],'portrait alone, not 1920x1280');
  assert.deepEqual(turned.shapes,[windowed,full,portrait],'the landscape shapes are kept');
  const again=areaPlan(turned.display,full,true,turned.shapes);
  assert.deepEqual([again.display.width,again.display.height],[1920,1080],'turning back is landscape only');
  assert.deepEqual(again.display.areas,[windowed,full],'with the shapes learned before');
  assert.equal(again.display.area,1);
  assert.deepEqual(again.shapes,[windowed,portrait,full],'and the portrait one is kept, the most recent last');
  // A split screen (XPeng with fnOS beside CarPlay, 2026-10-19): the window turns portrait and back as the panel opens
  // and closes. The two orientations together hardly grow the stream: declared once, then only switched.
  const page={width:1280,height:756},tall={width:1280,height:1260},side={width:1162,height:1280};
  const xp={width:1372,height:1260,fps:30,uiScale:100,hevc:true,areas:[page,tall],area:0};
  const split=areaPlan(xp,side,true,[page,tall]);
  assert.deepEqual([split.display.width,split.display.height,split.display.areas.length],[1280,1280,3],'portrait joins: 1280x1280');
  let d=split.display,k=split.shapes;
  for (const shape of [page,side,tall,side,page]) {
    const p=areaPlan(d,shape,true,k);
    if (p) { assert.deepEqual({...p.display,area:0},{...d,area:0},'opening and closing the panel only switches area'); d=p.display; k=p.shapes; }
    const index=d.areas.findIndex(a=>!aspectChanged(a,shape));
    assert.equal(d.area,index,'the area in use is the window\'s'); }
  // The F50 in the XPeng (2026-10-21) had four landscape shapes declared; the split screen's portrait joins them.
  const narrow={width:1372,height:686},fullDock={width:1280,height:846};
  const xp4={width:1372,height:1260,fps:30,uiScale:100,hevc:true,areas:[page,fullDock,narrow,tall],area:1};
  const mixed=areaPlan(xp4,side,true,[narrow,fullDock,tall,page]);
  assert.deepEqual(mixed.display.areas,[side,page,fullDock,tall,narrow],'all five, by size');
  assert.deepEqual([mixed.display.width,mixed.display.height],[1372,1280]);
  for (const shape of [page,side,narrow,side,fullDock]) {
    const p=areaPlan(mixed.display,shape,true,mixed.shapes);
    assert.ok(!p||sameStream(mixed.display,p.display),'opening and closing the panel only switches area'); }
  assert.equal(areaFor(xp4,fullDock),1,'a declared shape is found');
  assert.equal(areaFor(xp4,side),-1,'a new one is not');
  assert.equal(areaFor({width:1280,height:720,hevc:false},page),-1,'nor without areas');
}
{ // A clearly portrait 1/3 window gets its own portrait stream (2026-10-23): inside a landscape stream the phone
  // keeps its landscape layout and squeezes it into the area, so the page looked landscape in a portrait window.
  const third=windowShape(490,580,1), two=windowShape(876,580,1), whole=windowShape(1372,686,1);
  const p=areaPlan({width:1372,height:686,hevc:false},third,false,[two,whole]);
  assert.deepEqual([p.display.width,p.display.height,p.display.areas],[490,580,[]],'portrait stream, its own size');
  const back=areaPlan(p.display,two,false,p.shapes);
  assert.deepEqual([back.display.width,back.display.height],[1372,686],'back to the landscape stream');
  assert.ok(back.display.areas.some(a=>a.width===876&&a.height===580),'the 2/3 area keeps its size');
}
{ // A screen split in thirds (2026-10-22): the areas keep the windows' proportions, the set fitted to the stream at once
  // (each shape fitted on its own made a third as wide as the full screen, and CarPlay showed both the same).
  const full=windowShape(1280,720,1), two=windowShape(853,720,1), third=windowShape(427,720,1);
  assert.deepEqual([two,third],[{width:854,height:720},{width:428,height:720}]);
  let p=areaPlan({width:1280,height:720,hevc:true},two,true,[full]);
  assert.deepEqual(p.display.areas,[two,full],'two thirds of the screen, two thirds of the stream');
  p=areaPlan(p.display,third,true,p.shapes);
  assert.deepEqual([p.display.width,p.display.height,p.display.areas],[480,808,[]],'the portrait third gets its own stream (480 short side)');
  // A Mac at 2x with a fast decoder: 1728x1000 CSS px is 3456x2000, fitted to 2560 together with its half.
  const big=windowShape(1728,1000,2), half=windowShape(864,1000,2);
  const m=areaPlan({width:1280,height:720,hevc:true},big,true,[half],2560);
  assert.deepEqual([m.display.width,m.display.height,m.display.areas],[2560,1482,[{width:1280,height:1482},{width:2560,height:1482}]]);
  assert.equal(m.display.area,1,'the large window in use');
  // A small car page alone keeps its true size (2026-10-23): forcing 1280 made a 2/3 window as wide as the full one.
  assert.deepEqual(areaPlan({width:1280,height:720,hevc:false},windowShape(876,518,1),false,[]).display,
    {width:876,height:518,hevc:false,areas:[],area:0});
  // A 2/3 window keeps its size before and after the full screen joins: 876x580 stays 876x580, so returning to it is
  // the same area of the same stream, not a resolution change (2026-10-22/23).
  {
    const two=windowShape(876,580,1), whole=windowShape(1372,686,1);
    let p=areaPlan({width:1280,height:720,hevc:false},two,false,[]);
    assert.deepEqual([p.display.width,p.display.height,p.display.areas],[876,580,[]],'the 2/3 window keeps its size');
    p=areaPlan(p.display,whole,false,p.shapes);
    assert.deepEqual([p.display.width,p.display.height,p.display.areas],[1372,686,[two,whole]],'the full shape joins');
    const back=areaPlan(p.display,two,false,p.shapes);
    assert.deepEqual([back.display.width,back.display.height,back.display.area],[1372,686,0],'back to its area, same stream');
    assert.deepEqual(back.display.areas,[two,whole],'the 2/3 area does not shrink'); }
}
console.log('View areas: shapes learned once, switched without reconnecting.');
{ // Tesla fullscreen leaves the page only when its video sites answer (offline Tesla, simulated 2026-10-14).
  const {reachable,TESLA_HOPS}=await load('tesla-fullscreen');
  assert.ok(TESLA_HOPS.length===2&&TESLA_HOPS.every(u=>u.startsWith('https://')));
  const seen=[];
  assert.equal(await reachable(TESLA_HOPS,(u,init)=>{seen.push([u,init.mode]);return Promise.resolve({});}),true,'both answer');
  assert.deepEqual(seen.map(s=>s[1]),['no-cors','no-cors'],'any answer counts, no CORS needed');
  assert.equal(await reachable(TESLA_HOPS,u=>u.includes('1905')?Promise.reject(new TypeError('Failed to fetch')):Promise.resolve({})),false,'one unreachable');
  const hang=(u,init)=>new Promise((_,reject)=>init.signal.addEventListener('abort',()=>reject(init.signal.reason)));
  const started=Date.now(), alive=setTimeout(()=>{},5000);   // AbortSignal.timeout alone does not keep Node running
  assert.equal(await reachable(TESLA_HOPS,hang,50),false,'no answer within the timeout');
  clearTimeout(alive);
  assert.ok(Date.now()-started<1000,'gives up at the timeout');
}
console.log('Tesla fullscreen: only with its video sites reachable.');

{ // Refresh timing must survive reconnects and never confuse connection time with the first painted frame.
  const {StartupTiming}=await load('startup'); let clock=12;
  const timing=new StartupTiming(()=>clock); timing.mark('bootMs');
  clock=10010;timing.mark('wsNewMs');clock=10030;timing.mark('wsOpenMs');
  clock=10040;timing.mark('wsFirstMs');clock=11600;timing.mark('firstFrameMs');
  clock=20000;timing.mark('wsNewMs');
  assert.deepEqual(timing.snapshot(),{navStartMs:0,bootMs:12,wsNewMs:10010,wsOpenMs:10030,wsFirstMs:10040,firstFrameMs:11600});
  const copy=timing.snapshot();copy.wsOpenMs=0;assert.equal(timing.snapshot().wsOpenMs,10030);
}

{ // Tesla-only build (flags.ts): the box's carMusic/tesla fields are constants now; boot reads the token and the
  // settings port only, and a stale receiver-access.json with the old fields (or 1.1.0-1.2.0's audioRouteNavigation,
  // gone with the page's sound in 1.3.0) changes nothing.
  const flags=await load('flags');
  assert.deepEqual(Object.keys(flags),['TESLA'],'the sound flags went with audio.ts');assert.equal(flags.TESLA,true);
  const savedWindow=globalThis.window, savedFetch=globalThis.fetch, savedStorage=globalThis.localStorage;
  const stored={};globalThis.window={};globalThis.localStorage={setItem(k,v){stored[k]=v;}};
  const {access}=await load('boot',s=>s.replace(/^import .*?;$/gm,'const startup={mark(){}};').replace('async function access()', 'export async function access()'));
  globalThis.fetch=async()=>({ok:true,json:async()=>({token:'0123456789abcdef0123456789abcdef',settingsPort:18080,tesla:false,carMusic:false,audioRouteNavigation:'carplay'})});await access();
  assert.equal(stored['playport-token'],'0123456789abcdef0123456789abcdef');assert.equal(window.playportBoxSettingsPort,18080);
  assert.deepEqual(Object.keys(window),['playportBoxSettingsPort'],'no runtime car or sound flags any more');
  globalThis.window=savedWindow;globalThis.fetch=savedFetch;globalThis.localStorage=savedStorage;
}

{ // The hint follows the state (viewer audit V3): the box is the question while the link is down, the iPhone only
  // while the box answers; the box's own page link hides while the box is unreachable.
  const {statusHint,SLOW_LINK_S}=await load('status');
  assert.deepEqual(statusHint('waiting',0),{key:'waitingHint',seconds:null,boxLink:true},'the one good state as before');
  assert.deepEqual(statusHint('starting',0),{key:'startingHint',seconds:null,boxLink:true},'iPhone connected: no first-run hint');
  assert.deepEqual(statusHint('renegotiating',0),{key:'renegotiatingHint',seconds:null,boxLink:true},'a display change is not "waiting for iPhone"');
  assert.deepEqual(statusHint('connecting',1),{key:null,seconds:null,boxLink:false},'the first seconds of a connect say nothing');
  assert.deepEqual(statusHint('connecting',SLOW_LINK_S+4.7),{key:'reconnectingHint',seconds:7,boxLink:false},'then the box is not answering, with the time');
  assert.deepEqual(statusHint('reconnecting',0.5),{key:'reconnectingHint',seconds:null,boxLink:false},'a dropped link names the box at once, the time after 3 s');
  assert.equal(statusHint('reconnecting',12.2).seconds,12);
  assert.equal(statusHint('access',0).key,'accessHint');
}
{ // Debug overlay (2026-10-16; two lines since 1.3.0, the page plays no sound): nothing for no picture yet.
  const {hudLines}=await load('debug-hud');
  const sample={width:1280,height:846,fps:29.6,hevc:false,videoKbps:2412,decodeMs:63.4,queue:1,rttMs:41.2};
  assert.deepEqual(hudLines(sample,true),['1280×846 · 30 fps · H.264 · 2.4 Mbps','解码 63 ms · 队列 1 · 往返 41 ms']);
  assert.deepEqual(hudLines({...sample,width:0,hevc:null,rttMs:-1},false),['No picture yet','Decode 63 ms · Queue 1 · RTT –']);
}

{ // Compatible display (2026-10-17): a Tesla on Chrome 113 decoded at full rate and showed nothing with the
  // low-latency canvas and the hardware preference, and neither fell back without an error.
  const {compatDisplayOn}=await load('compat-display');
  const ua=v=>`Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${v}.0.0.0 Safari/537.36`;
  assert.deepEqual([113,119,120,148].map(v=>compatDisplayOn('',ua(v))),[true,true,false,false],'automatic: on below Chrome 120');
  assert.equal(compatDisplayOn('','Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15'),false,'not Chrome: as before');
  assert.equal(compatDisplayOn('0',ua(113)),false,'the switch wins either way');assert.equal(compatDisplayOn('1',ua(148)),true);
  const configs=[];
  globalThis.VideoDecoder=class {constructor(){this.state='unconfigured';this.decodeQueueSize=0;}configure(c){configs.push(c);this.state='configured';}decode(){}close(){this.state='closed';}};
  VideoDecoder.isConfigSupported=async()=>({supported:true});
  globalThis.window=globalThis.window??{};window.setTimeout=()=>1;window.clearTimeout=()=>{};
  globalThis.document={hidden:false};   // requestKeyframe() after adoption reads document.hidden (until 1.0.1 a leftover of the music block)
  const {VideoPlayer}=await load('video',s=>s.replace(/^import .*?;$/gm,'')+'\nconst VideoCodec={H264:1,H265:2};function avcCodecString(){return "avc1.640028";}function annexBToAvcc(d){return d;}');
  const hvcC=new Uint8Array([1,1,0x60,0,0,0,0x90,0,0,0,0,0,0x5d]);
  for (const compat of [false,true]) {
    const contexts=[];const canvas={getContext(kind,options){contexts.push(options??null);return {getContextAttributes:()=>({alpha:false,desynchronized:!compat})};},width:0,height:0};
    const player=new VideoPlayer(canvas,()=>{},()=>{},()=>{},()=>{},compat);
    assert.equal(player.desynchronized,compat?0:1,'what the browser gave is read back for the viewer log');
    player.configure({codec:1,width:1280,height:846,codecData:new Uint8Array([1,0x64,0,0x28,0x40])});await Promise.resolve();
    player.configure({codec:2,width:1280,height:846,codecData:hvcC});for(let i=0;i<5;i++)await Promise.resolve();
    assert.deepEqual(contexts,compat?[{alpha:false}]:[{alpha:false,desynchronized:true}],compat?'compatible: an opaque canvas, not the low-latency one':'default: the opaque low-latency canvas');
    assert.deepEqual(configs.splice(0).map(c=>c.hardwareAcceleration),compat?['no-preference','no-preference']:['prefer-hardware','prefer-hardware'],
      'H.264 and the first H.265 candidate');
  }
}
console.log('Compatible display: automatic below Chrome 120, neither low-latency canvas nor hardware preference.');
{ // Option sheet (1.2.0, picker.ts): a car browser draws a native <select> list at the OS size, so the rows open an
  // in-page sheet; the hidden <select> keeps the value and its change event, which main.ts listens to.
  class Node {
    constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.listeners={};this.textContent='';this.hidden=false;this.disabled=false;this.open=false;}
    setAttribute(k,v){this.attrs[k]=String(v);} getAttribute(k){return this.attrs[k]??null;}
    addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
    dispatchEvent(ev){for(const fn of this.listeners[ev.type]??[])fn(ev);if(this['on'+ev.type])this['on'+ev.type](ev);return true;}
    replaceChildren(...kids){this.children=kids;} append(...kids){this.children.push(...kids);}
    querySelector(sel){const all=this.all();if(sel==='.main b')return all.find(n=>n.tag==='b')??null;if(sel==='b')return all.find(n=>n.tag==='b')??null;
      if(sel==='[aria-selected=true]')return all.find(n=>n.attrs['aria-selected']==='true')??null;if(sel.startsWith('#'))return all.find(n=>n.id===sel.slice(1))??null;if(sel==='.value')return all.find(n=>n.className==='value')??null;return null;}
    querySelectorAll(sel){return this.all().filter(n=>sel==='[data-picker]'?n.dataset?.picker:false);}
    all(){const out=[];const walk=n=>{for(const k of n.children){out.push(k);walk(k);}};walk(this);return out;}
    getBoundingClientRect(){return{top:0,bottom:0,height:0};} focus(){focused=this;}
    set innerHTML(html){this.children=[];if(html.includes('<b>')){const b=new Node('b');const main=new Node('span');main.children=[b];this.children.push(main);}if(html.includes('check'))this.children.push(new Node('svg'));}
    get className(){return this.attrs.class??'';} set className(v){this.attrs.class=v;}
    get selectedOptions(){return this.options.filter(o=>o.selected);}
    get value(){return (this.options??[]).find(o=>o.selected)?.value??'';} set value(v){for(const o of this.options??[])o.selected=o.value===v;}
  }
  let focused=null;
  const option=(value,text,selected=false)=>({tag:'option',value,textContent:text,selected});
  const select=new Node('select');select.id='fps';select.options=[option('30','30 fps',true),option('60','60 fps')];
  const trigger=new Node('button');trigger.dataset={picker:'fps'};const main=new Node('span');const b=new Node('b');b.textContent='帧率';main.children=[b];const value=new Node('span');value.className='value';trigger.children=[main,value];
  const root=new Node('section');root.children=[trigger,select];
  const sheet=new Node('dialog');const title=new Node('h2');title.id='picker-title';const list=new Node('div');list.id='picker-options';const cancel=new Node('button');cancel.id='picker-cancel';sheet.children=[title,list,cancel];
  let shown=0;sheet.showModal=()=>{shown++;sheet.open=true;};sheet.close=()=>{sheet.open=false;sheet.dispatchEvent({type:'close'});};
  globalThis.document={getElementById:id=>id==='fps'?select:null,createElement:tag=>new Node(tag)};
  globalThis.MutationObserver=class{constructor(fn){this.fn=fn;}observe(){observers.push(this);}};const observers=[];
  const {attachPickers,refreshPickers}=await load('picker');
  attachPickers(root,sheet);
  assert.equal(value.textContent,'30 fps','the row shows the current option');
  let changes=0;select.onchange=()=>changes++;
  trigger.onclick();
  assert.equal(shown,1);assert.equal(title.textContent,'帧率','the sheet is titled after the row');
  assert.deepEqual(list.children.map(r=>[r.querySelector('b').textContent,r.attrs['aria-selected']]),[['30 fps','true'],['60 fps','false']]);
  assert.equal(focused,list.children[0],'the current option takes focus');
  list.children[1].onclick();
  assert.deepEqual([select.value,value.textContent,changes,sheet.open],['60','60 fps',1,false],'a tap sets the select, fires change once, closes the sheet');
  assert.equal(list.children.length,0,'closing empties the list');
  trigger.onclick();list.children[1].onclick();
  assert.equal(changes,1,'re-choosing the current option fires no change');
  select.value='30';refreshPickers();assert.equal(value.textContent,'30 fps','a value set in code is mirrored on request');
  select.disabled=true;observers[0].fn();assert.equal(trigger.disabled,true,'a disabled select greys its row');
  delete globalThis.document;delete globalThis.MutationObserver;
}
console.log('Option sheet: rows mirror and set their hidden select, one change event per real change, the current option focused.');
