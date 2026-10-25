import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
async function load(name, transform = s => s) {
  const source=transform(readFileSync(new URL(`./src/${name}.ts`,import.meta.url),'utf8'));
  const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}});
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
}
const {suggestedResolution,aspectChanged,shownSize,closeShape}=await load('display-fit');
assert.equal(closeShape({width:1280,height:846},{width:1280,height:756}),true,'page vs fullscreen: no renegotiation outside fullscreen');
assert.equal(closeShape({width:1280,height:846},{width:1082,height:1280}),false,'portrait renegotiates at once');
assert.equal(closeShape({width:1280,height:846},{width:1372,height:686}),false,'split screen renegotiates at once');
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
media.setActive(true);actions.play();actions.pause();actions.previoustrack();actions.nexttrack();
assert.deepEqual(sent.map(x=>x.media),[1,2,5,4],'Use distinct play and pause HID commands, not toggle');
media.setPlaying(true);assert.equal(navigator.mediaSession.playbackState,'playing');
media.setMetadata({title:'Test song',artist:'Test artist',album:'Test album'});
media.setPlaying(false);assert.equal(navigator.mediaSession.metadata.title,'Test song');assert.equal(navigator.mediaSession.playbackState,'paused');
media.setMetadata({title:'Next',artist:'Artist',album:'Album',durationMs:200000,positionMs:50000,revision:1});
assert.equal(positions.at(-1).duration,200);assert.equal(positions.at(-1).position,50);
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
  Object.defineProperty(performance,'now',{value:realNow,configurable:true,writable:true}); }
assert.deepEqual(media.report(),{positionState:1,songPos:62,songDur:200,art:0},'The viewer log tells whether the OS card can take our song position, and whether a cover is shown');
assert.equal(media.timeline().key,'Run|||200');assert.equal(media.timeline().position,62);
{ // Hiccups for the viewer log: a gap in a flowing stream (network/box) apart from frames the car's decoder held long.
  let clock=0;const realNow=performance.now;Object.defineProperty(performance,'now',{value:()=>clock,configurable:true,writable:true});
  globalThis.EncodedVideoChunk=class {constructor(v){Object.assign(this,v);}};
  const {VideoPlayer}=await load('video',s=>s.replace(/^import .*?;$/gm,''));
  const player=new VideoPlayer({getContext(){return null;}},()=>{},()=>{},()=>{});
  player.state={usesDescription:false,timestampUs:0,frameIntervalUs:16667,decoder:{decode(){},decodeQueueSize:0}};
  for(const t of [0,20,40,400,420,1400,2400]){clock=t;player.pushFrame({data:new Uint8Array([1]),keyframe:false});}
  assert.deepEqual(player.takeStalls(),{stalls:1,stallMaxMs:360,slowFrames:0,paintMaxMs:0},'Only a gap with frames flowing on both sides counts; motion ending into an idle screen (1 frame/s) does not');
  assert.deepEqual(player.takeStalls(),{stalls:0,stallMaxMs:0,slowFrames:0,paintMaxMs:0},'Counters restart for each report');
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
{ // The music element's own timeline follows the song, which a car's media card may show instead of ours.
  let clock=0;const realNow=performance.now;Object.defineProperty(performance,'now',{value:()=>clock,configurable:true,writable:true});
  const log=[];
  class Ranges {constructor(r){this.r=r;}get length(){return this.r.length;}start(i){return this.r[i][0];}end(i){return this.r[i][1];}}
  const buffer={updating:false,ranges:[],timestampOffset:0,listeners:{},addEventListener(n,h){this.listeners[n]=h;},
    get buffered(){return new Ranges(this.ranges);},appendBuffer(){log.push('append');},remove(a,b){log.push(`remove ${a}-${b}`);this.ranges=[];}};
  const source={readyState:'open',duration:Infinity,addEventListener(n,h){h();},addSourceBuffer(){return buffer;}};
  globalThis.MediaSource=class {constructor(){return source;}};globalThis.URL.createObjectURL=()=>'blob:x';
  const element={currentTime:0,paused:true,setAttribute(){},addEventListener(){},play(){return Promise.resolve();},pause(){}};
  globalThis.document={createElement:()=>element,body:{append(){}}};
  const {MusicOutput}=await load('music-output',s=>'const FLAC_BLOCK=4096,FLAC_MIME="audio/mp4";function flacInit(){return new Uint8Array(1);}function aacInit(){return new Uint8Array(1);}\n'+s.replace(/^import .*?;$/gm,''));
  const music=new MusicOutput({sampleRate:48000,channels:2,description:new Uint8Array()},()=>{},'flac');
  assert.deepEqual(log,['append'],'init segment');
  element.currentTime=600;buffer.ranges=[[599,600.6]];
  music.follow({position:8,duration:269,key:'A',playing:true});
  assert.deepEqual(log.slice(1),['remove 0-Infinity'],'A new song first drops the old timeline');
  clock=100;buffer.listeners.updateend();
  assert.equal(element.currentTime,8,'then what was being heard is the song position');assert.equal(source.duration,269,'with the song duration');
  assert.equal(buffer.timestampOffset,8-600,'and the audio not heard yet is replayed on that timeline');
  assert.deepEqual(music.report(),{musicWaits:0,musicSkips:0,musicAligns:1,musicSysPauses:0},'Counted for the viewer log');
  log.length=0;element.currentTime=9;buffer.ranges=[[8.1,9.6]];
  clock=1000;music.follow({position:9,duration:269,key:'A',playing:true});
  assert.ok(!log.some(x=>x.startsWith('remove')),'Following the same song moves nothing');
  clock=10000;music.follow({position:60,duration:269,key:'A',playing:true});
  assert.ok(log.includes('remove 0-Infinity'),'A seek on the iPhone (more than 3 s off) realigns');
  Object.defineProperty(performance,'now',{value:realNow,configurable:true,writable:true}); }
media.setActive(false);assert.equal(navigator.mediaSession.playbackState,'none');assert.equal(navigator.mediaSession.metadata,null);
// Music must take exactly one route; voice/navigation keep the existing Web Audio path.
const edges=[];let music;let packets=0;
class Node {gain={value:1};connect(to){edges.push(to);}disconnect(){}}
globalThis.AudioContext=class {state='running';destination={speaker:true};createGain(){return new Node();}resume(){return Promise.resolve();}};
globalThis.TestMusic=class {static supported(){return true;}constructor(config){music=this;this.configKey=JSON.stringify([config.sampleRate,config.channels,Array.from(config.description)]);}unlocked=false;playing=false;configKey="";pause(){this.playing=false;this.paused=true;}volume(){}unlock(){this.unlocked=true;return Promise.resolve();}packet(){packets++;}close(){this.closed=true;}};
const {AudioEngine}=await load('audio',s=>s.replace(/^import .*?;$/gm,'')+'\nconst MusicOutput=globalThis.TestMusic;const AudioCodec={AacLc:1,Opus:2,Lpcm:3};\nfunction audioStartTime(){return 0;}');
const audio=new AudioEngine(()=>{});assert.equal(edges.length,1);assert.equal(edges[0].speaker,true);
audio.handleConfig({streamType:102,codec:1,name:'media',sampleRate:48000,channels:2,description:new Uint8Array([0x11,0x90])});
audio.handlePacket({streamType:102,timestampUs:0,data:new Uint8Array([1,2])});assert.equal(packets,1);
assert.equal(audio.isPlaying,false,'Do not claim playing before actual media playback');
await audio.unlock();assert.equal(audio.isUnlocked,true);music.playing=true;assert.equal(audio.isPlaying,true);
audio.stopStream(102);assert.equal(music.closed,undefined,"Pause retains native media element");assert.equal(music.paused,true);
const pausedMusic=music;
audio.handleConfig({streamType:102,codec:1,name:'media',sampleRate:48000,channels:2,description:new Uint8Array([0x11,0x90])});
assert.equal(music,pausedMusic,'Resume reuses the native media element');
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
