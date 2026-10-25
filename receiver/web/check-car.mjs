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
const {isNight,parseNightMode}=await load('night');
const at=(h,m)=>new Date(2026,9,10,h,m);
assert.equal(parseNightMode(null),'schedule');assert.equal(parseNightMode('bogus'),'schedule');assert.equal(parseNightMode('system'),'system');
assert.equal(isNight('schedule',at(18,29),true),false);assert.equal(isNight('schedule',at(18,30),false),true);
assert.equal(isNight('schedule',at(0,0),false),true);assert.equal(isNight('schedule',at(6,29),false),true);assert.equal(isNight('schedule',at(6,30),true),false);
assert.equal(isNight('system',at(12,0),true),true);assert.equal(isNight('system',at(23,0),false),false);
assert.equal(isNight('day',at(23,0),true),false);assert.equal(isNight('night',at(12,0),false),true);
console.log('Car checks passed: aspect fit, media keys, disconnect state, single music route, MP4 framing, night schedule.');
