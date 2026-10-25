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
const actions={},sent=[],positions=[];
Object.defineProperty(globalThis,'navigator',{value:{mediaSession:{setActionHandler:(a,h)=>actions[a]=h,setPositionState:p=>positions.push(p)}},configurable:true});
globalThis.MediaMetadata=class {constructor(value){Object.assign(this,value);}};
const {SystemMedia}=await load('media-session');
const media=new SystemMedia(m=>sent.push(m),()=>{});
actions.nexttrack();assert.equal(sent.length,0,'No commands before phone connection');
media.report();
media.setActive(true);actions.play();actions.pause();actions.previoustrack();actions.nexttrack();actions.pause();
assert.deepEqual(sent.map(x=>x.media),[1,2,5,4,2],'Use distinct play and pause HID commands, not toggle');
assert.deepEqual(media.report(),{positionState:1,keyPlay:1,keyPause:2,keyPrev:1,keyNext:1},'The car media keys that reached the page, for the viewer log');
assert.deepEqual(media.report(),{positionState:1},'counted afresh each report');
media.setPlaying(true);assert.equal(navigator.mediaSession.playbackState,'playing');
media.setMetadata({title:'Test song',artist:'Test artist',album:'Test album'});
media.setPlaying(false);assert.equal(navigator.mediaSession.metadata.title,'Test song');assert.equal(navigator.mediaSession.playbackState,'paused');
media.setMetadata({title:'Next',artist:'Artist',album:'Album',durationMs:200000,positionMs:50000,revision:1});
assert.equal(positions.at(-1).duration,200);assert.equal(positions.at(-1).position,50);
assert.ok(positions.at(-1).playbackRate>0&&positions.at(-1).playbackRate<1e-3,'The card is told the position, not left to run it on by its own clock (XPeng: the bar stood full)');
{ const before=positions.length;media.tick();assert.equal(positions.length,before+1,'and is told it again on every tick'); }
media.setArtwork(0,'data:image/jpeg;base64,/9j/');assert.equal(navigator.mediaSession.metadata.artwork.length,0,'Reject old-track cover');
media.setArtwork(1,'data:image/jpeg;base64,/9j/');assert.equal(navigator.mediaSession.metadata.artwork.length,1);
media.setMetadata({title:'Another',artist:'',album:'',revision:2});assert.equal(navigator.mediaSession.metadata.artwork.length,0,'Clear old cover on track change');
assert.equal(positions.at(-1),undefined,'Missing duration must clear old timeline');
{ let clock=0;const realNow=performance.now;Object.defineProperty(performance,'now',{value:()=>clock,configurable:true,writable:true});
  media.setPlaying(false);   // the browser hears nothing yet, e.g. sound not unlocked
  media.setMetadata({title:'Run',artist:'',album:'',durationMs:200000,positionMs:50000,playing:true,revision:3});
  clock=10000;media.setPlaying(true);assert.equal(positions.at(-1).position,60,"The iPhone's playing state moves the clock, not what the browser hears");
  clock=12000;media.setMetadata({title:'Run',artist:'',album:'',durationMs:200000,positionMs:62000,playing:false,revision:3});
  clock=20000;media.setPlaying(false);assert.equal(positions.at(-1).position,62,'Paused on the iPhone: the clock stands');
  media.setPlaying(true);assert.equal(navigator.mediaSession.playbackState,'paused','Paused on the iPhone: the card offers play, even while the page plays its silence');
  sent.length=0;actions.pause();assert.deepEqual(sent.map(x=>x.media),[1],"The car's pause key while the iPhone is paused plays (the car toggles by the page)");
  assert.equal(media.report().keyPauseAsPlay,1,'counted for the viewer log');
  media.setMetadata({title:'Run',artist:'',album:'',durationMs:200000,positionMs:62000,playing:true,revision:3});
  assert.equal(navigator.mediaSession.playbackState,'playing','and pause once it plays again');
  media.setMetadata({title:'Run',artist:'',album:'',durationMs:200000,positionMs:62000,playing:false,revision:3});
  Object.defineProperty(performance,'now',{value:realNow,configurable:true,writable:true}); }
assert.deepEqual(media.report(),{positionState:1,songPos:62,songDur:200,art:0},'The viewer log tells whether the OS card can take our song position, and whether a cover is shown');
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
{ // The music element keeps its own timeline: nothing moves it onto the song (F50 drive 2026-10-13: moving it seeked
  // on every song change, threw appendBuffer errors on Chrome 120 and pulled the music back while the iPhone's
  // position reports stalled). The song position reaches the car's card through the Media Session position state.
  let clock=0;const realNow=performance.now;Object.defineProperty(performance,'now',{value:()=>clock,configurable:true,writable:true});
  const log=[];
  class Ranges {constructor(r){this.r=r;}get length(){return this.r.length;}start(i){return this.r[i][0];}end(i){return this.r[i][1];}}
  const buffer={updating:false,ranges:[],timestampOffset:0,listeners:{},addEventListener(n,h){this.listeners[n]=h;},
    get buffered(){return new Ranges(this.ranges);},appendBuffer(){if(this.updating)throw new Error('InvalidStateError: still processing');log.push('append');},remove(a,b){log.push(`remove ${a}-${b}`);this.ranges=[];}};
  const source={readyState:'open',get duration(){return Infinity;},set duration(v){log.push(`duration ${v}`);},addEventListener(n,h){h();},addSourceBuffer(){return buffer;}};
  globalThis.MediaSource=class {constructor(){return source;}};globalThis.URL.createObjectURL=()=>'blob:x';
  const element={currentTime:0,paused:true,plays:0,setAttribute(){},removeAttribute(){},load(){},remove(){},addEventListener(){},play(){this.plays++;this.paused=false;return Promise.resolve();},pause(){this.paused=true;}};
  globalThis.document={createElement:()=>element,body:{append(){}}};
  const {MusicOutput}=await load('music-output',s=>'const FLAC_BLOCK=4096,FLAC_MIME="audio/mp4";function flacInit(){return new Uint8Array(1);}function aacInit(){return new Uint8Array(1);}function flacFrame(){return new Uint8Array(1);}function flacFragment(){return new Uint8Array(1);}\n'+s.replace(/^import .*?;$/gm,''));
  const errors=[];const music=new MusicOutput({sampleRate:48000,channels:2,description:new Uint8Array()},m=>errors.push(m),'flac');
  assert.deepEqual(log,['append'],'init segment');
  assert.equal(music.follow,undefined,'No song timeline to follow');
  element.paused=false;element.currentTime=600;buffer.ranges=[[599,600.6]];
  for(let i=0;i<20;i++){clock+=85;music.packet(new Uint8Array(4096*4));}
  assert.ok(!log.some(x=>x.startsWith('remove 0-')||x.startsWith('duration')),'Playing on moves neither the timeline nor the duration');
  assert.equal(element.currentTime,600,'and seeks nothing');assert.deepEqual(errors,[]);
  // Behind the cushion: no faster playback (it crackled at song changes), only measured for the viewer log.
  element.playbackRate=1;music.report();buffer.ranges=[[590,601.5]];music.packet(new Uint8Array(4096*4));
  assert.equal(element.playbackRate,1,'1.5 s behind: still normal speed');assert.equal(element.currentTime,600,'and no jump');
  assert.deepEqual([music.report().musicLeadMaxMs,music.report().musicLeadMaxMs],[1500,undefined],'How far behind it played, for the viewer log');
  element.plays=0;element.play=function(){this.plays++;return Promise.reject(Object.assign(new Error('blocked'),{name:'NotAllowedError'}));};
  element.paused=true;element.currentTime=599;await music.unlock().catch(()=>{});
  assert.equal(music.report().musicBlocked,1,'A play() the browser refused (no gesture) is counted for the viewer log');
  element.play=function(){this.plays++;this.paused=false;return Promise.resolve();};
  // A buffer busy for a few seconds is not a stuck one.
  const stuck=[];const flac=new MusicOutput({sampleRate:48000,channels:2,description:new Uint8Array()},m=>stuck.push(m),'flac');
  buffer.updating=true;for(let i=0;i<40;i++)flac.packet(new Uint8Array(4096*4));
  assert.deepEqual(stuck,[],'Forty fragments (3.4 s) waiting on a busy buffer close nothing');
  for(let i=0;i<60;i++)flac.packet(new Uint8Array(4096*4));
  assert.deepEqual(stuck,['Music buffer is not advancing'],'but a buffer stuck for good still does');buffer.updating=false;
  // Resuming after a pause whose buffer was played out: no step back (that replayed a second already heard).
  const resumed=new MusicOutput({sampleRate:48000,channels:2,description:new Uint8Array()},()=>{},'aac');
  element.paused=true;element.plays=0;element.currentTime=10;buffer.ranges=[[5,10]];
  await resumed.unlock();
  assert.equal(element.currentTime,10,'No step back');assert.equal(element.plays,0,'it waits for a cushion');assert.equal(resumed.unlocked,true);
  buffer.ranges=[[5,11.2]];buffer.listeners.updateend();
  assert.equal(element.plays,1,'and plays on once a second of new audio is in');
  element.paused=true;element.currentTime=6;buffer.ranges=[[5,12]];await resumed.unlock();
  assert.equal(element.currentTime,11,'A stale buffer still jumps forward to 1 s before its end');
  Object.defineProperty(performance,'now',{value:realNow,configurable:true,writable:true}); }
media.setActive(false);assert.equal(navigator.mediaSession.playbackState,'none');assert.equal(navigator.mediaSession.metadata,null);
// Music must take exactly one route; voice/navigation keep the existing Web Audio path.
const edges=[];let music;let packets=0;
class Node {gain={value:1};connect(to){edges.push(to);}disconnect(){}}
globalThis.AudioContext=class {state='running';destination={speaker:true};createGain(){return new Node();}resume(){return Promise.resolve();}};
globalThis.TestMusic=class {static supported(){return true;}static key(c){return JSON.stringify([c.sampleRate,c.channels,Array.from(c.description)]);}constructor(config){music=this;this.configKey=JSON.stringify([config.sampleRate,config.channels,Array.from(config.description)]);}unlocked=false;playing=false;configKey="";pause(){this.playing=false;this.paused=true;}volume(){}unlock(){this.unlocked=true;this.unlocks=(this.unlocks??0)+1;return Promise.resolve();}packet(){packets++;}close(){this.closed=true;}};
const {AudioEngine}=await load('audio',s=>s.replace(/^import .*?;$/gm,'')+'\nconst MusicOutput=globalThis.TestMusic;const AudioCodec={AacLc:1,Opus:2,Lpcm:3};\nfunction audioStartTime(){return 0;}');
const audio=new AudioEngine(()=>{});assert.equal(edges.length,1);assert.equal(edges[0].speaker,true);
audio.handleConfig({streamType:102,codec:1,name:'media',sampleRate:48000,channels:2,description:new Uint8Array([0x11,0x90])});
audio.handlePacket({streamType:102,timestampUs:0,data:new Uint8Array([1,2])});assert.equal(packets,1);
assert.equal(audio.isPlaying,false,'Do not claim playing before actual media playback');
await audio.unlock();assert.equal(audio.isUnlocked,true);music.playing=true;assert.equal(audio.isPlaying,true);
audio.stopStream(102);assert.equal(music.closed,undefined,"Pause retains native media element");assert.equal(music.paused,true);
const pausedMusic=music;
audio.handleConfig({streamType:102,codec:1,name:'media',sampleRate:48000,channels:2,description:new Uint8Array([0x11,0x90])});
assert.equal(music,pausedMusic,'Resume reuses the native media element');assert.equal(audio.streams.get(102).music,pausedMusic,'as the stream\'s music');
audio.stopAll();assert.equal(music.closed,true);assert.equal(audio.isPlaying,false);
const {aacInit,aacFragment}=await load('aac-mp4');
const init=aacInit(48000,2,new Uint8Array([0x11,0x90]));
function boxes(data){const result=[];for(let offset=0;offset<data.length;){const size=new DataView(data.buffer,data.byteOffset+offset,4).getUint32(0);assert.ok(size>=8&&offset+size<=data.length);result.push(new TextDecoder().decode(data.slice(offset+4,offset+8)));offset+=size;}return result;}
assert.deepEqual(boxes(init),['ftyp','moov']);
assert.deepEqual(boxes(aacFragment(1,0,[new Uint8Array([1,2,3])])),['moof','mdat']);
assert.throws(()=>aacInit(48000,2,new Uint8Array()));
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
console.log('Car checks passed: aspect fit, media keys, disconnect state, single music route, MP4 framing, night schedule.');
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

{ // Tesla browser UI can keep sound in the webpage: explicit false wins over the legacy Tesla default.
  const savedWindow=globalThis.window, savedFetch=globalThis.fetch, savedStorage=globalThis.localStorage;
  globalThis.window={};globalThis.localStorage={setItem(){}};
  const {access}=await load('boot',s=>s.replace(/^import .*?;$/gm,'const startup={mark(){}};').replace('async function access()', 'export async function access()'));
  for(const [flags,want] of [[{tesla:true},true],[{tesla:true,carMusic:false},false],[{tesla:false,carMusic:true},true]]) {
    globalThis.fetch=async()=>({ok:true,json:async()=>flags});await access();
    assert.equal(window.playportCarMusic,want);assert.equal(window.playportTeslaMode,flags.tesla);
  }
  globalThis.window=savedWindow;globalThis.fetch=savedFetch;globalThis.localStorage=savedStorage;
}

{ // Debug overlay (2026-10-16): three short lines, the music bitrate on the music stream, nothing for no picture yet.
  const {hudLines}=await load('debug-hud');
  const sample={width:1280,height:846,fps:29.6,hevc:false,videoKbps:2412,decodeMs:63.4,queue:1,rttMs:41.2,
    audio:[{name:'media',codec:'AAC',sampleRate:44100,channels:2},{name:'default',codec:'PCM',sampleRate:16000,channels:1}],musicKbps:256.4,playing:true};
  assert.deepEqual(hudLines(sample,true),['1280×846 · 30 fps · H.264 · 2.4 Mbps','解码 63 ms · 队列 1 · 往返 41 ms','声音 音乐 AAC 44.1 kHz 256 kbps · 播报 PCM 16 kHz 单声道']);
  assert.deepEqual(hudLines({...sample,width:0,hevc:null,rttMs:-1,audio:[],musicKbps:0,playing:false},false),
    ['No picture yet','Decode 63 ms · Queue 1 · RTT –','Sound none']);
  assert.equal(hudLines({...sample,playing:false},true)[2].endsWith('（静音中）'),true);
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
  const {VideoPlayer}=await load('video',s=>s.replace(/^import .*?;$/gm,'')+'\nconst VideoCodec={H264:1,H265:2};function avcCodecString(){return "avc1.640028";}function annexBToAvcc(d){return d;}');
  const hvcC=new Uint8Array([1,1,0x60,0,0,0,0x90,0,0,0,0,0,0x5d]);
  for (const compat of [false,true]) {
    const contexts=[];const canvas={getContext(kind,options){contexts.push(options??null);return null;},width:0,height:0};
    const player=new VideoPlayer(canvas,()=>{},()=>{},()=>{},()=>{},compat);
    player.configure({codec:1,width:1280,height:846,codecData:new Uint8Array([1,0x64,0,0x28,0x40])});await Promise.resolve();
    player.configure({codec:2,width:1280,height:846,codecData:hvcC});for(let i=0;i<5;i++)await Promise.resolve();
    assert.deepEqual(contexts,compat?[]:[{desynchronized:true}],compat?'compatible: no low-latency canvas':'default: the low-latency canvas');
    assert.deepEqual(configs.splice(0).map(c=>c.hardwareAcceleration),compat?['no-preference','no-preference']:['prefer-hardware','prefer-hardware'],
      'H.264 and the first H.265 candidate');
  }
}
console.log('Compatible display: automatic below Chrome 120, neither low-latency canvas nor hardware preference.');
