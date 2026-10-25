import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
async function load(name, transform = s => s) {
  const source=transform(readFileSync(new URL(`./src/${name}.ts`,import.meta.url),'utf8'));
  const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}});
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
}
const {suggestedResolution,aspectChanged,shownSize,closeShape,renegotiate}=await load('display-fit');
{ // XPeng fullscreen is 876x579 or 876x641 CSS px (dock shown or not): 1280x846 or 1280x936 (F50 drive 2026-10-13).
  const s846=suggestedResolution(876,579),s936=suggestedResolution(876,641),page=suggestedResolution(876,518);
  assert.deepEqual([s846,s936],[{width:1280,height:846},{width:1280,height:936}]);
  assert.equal(renegotiate({width:1280,height:756},s846,true,''),true,'Fullscreen gets its own size once');
  assert.equal(renegotiate({width:1280,height:846},s936,true,'1280x846'),false,'then the other fullscreen height only stretches');
  assert.equal(renegotiate({width:1280,height:936},s846,true,'1280x936'),false,'either way round');
  assert.equal(renegotiate({width:1280,height:846},page,false,'1280x846'),false,'leaving fullscreen keeps it too');
  assert.equal(renegotiate({width:1280,height:602},s846,true,'1280x846'),true,'a size far off (a test window) is renegotiated');
  assert.equal(renegotiate({width:1280,height:846},{width:1372,height:686},false,'1280x846'),true,'split screen at once');
  assert.equal(renegotiate({width:1280,height:846},s846,true,''),false,'the same shape never'); }
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
