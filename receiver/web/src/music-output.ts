import { aacInit, aacFragment } from './aac-mp4';
import { FLAC_BLOCK, FLAC_MIME, flacFragment, flacFrame, flacInit } from './flac-mp4';
import type { AudioConfigMessage } from './protocol';
/** aac: stream 102's AAC as sent. flac: the wired iPhone's LPCM, losslessly framed (flac-mp4.ts). */
export type MusicKind = 'aac' | 'flac';
/** The song as the iPhone reports it: position and duration in seconds, and what identifies the song. */
export interface SongTimeline { position: number; duration: number; key: string; playing: boolean; }
const MIMES: Record<MusicKind,string> = { aac: 'audio/mp4; codecs="mp4a.40.2"', flac: FLAC_MIME };
/** How far behind the newest audio the element plays. Over Wi-Fi (AAC) the iPhone's packets come with gaps of
 *  about 400 ms every few seconds (F50, 2026-10-12): 0.65 s ran dry and the music stuttered. */
const CUSHION: Record<MusicKind,number> = { aac: 1, flac: .65 };
/** AAC frames (1024 samples, 21 ms) per MP4 fragment: small, so audio reaches the element as it arrives. */
const AAC_FRAGMENT = 4;
/** Fragments (85 ms each, AAC and FLAC alike) that may wait for the buffer: more than a realignment replays (5 s). */
const MAX_PENDING = 80;
/** A real HTML media timeline makes received music eligible for OS media controls. */
export class MusicOutput {
  static supported(kind: MusicKind = 'aac') { return typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(MIMES[kind]); }
  static key(config: AudioConfigMessage, kind: MusicKind) { return JSON.stringify([kind,config.sampleRate,config.channels,Array.from(config.description)]); }
  readonly element=document.createElement('audio');
  private readonly source=new MediaSource();
  private readonly url=URL.createObjectURL(this.source);
  private buffer:SourceBuffer|null=null;
  private pending:Uint8Array[]=[];
  private frames:Uint8Array[]=[];
  private sequence=1;
  private samples=0;
  private closed=false;
  private lastPacket=-Infinity;
  private running=false;
  private pcm:Uint8Array[]=[];
  private pcmBytes=0;
  private block=0;
  private song:(SongTimeline&{at:number})|null=null;
  private alignedKey='';
  private alignedAt=-Infinity;
  private started=false;
  /** Fragments of the last seconds, so a realignment replays what was not heard yet instead of dropping it. */
  private recent:{sample:number;length:number;data:Uint8Array}[]=[];
  private realign:{offset:number;from:number;duration:number}|null=null;
  /** For the viewer log: the element waited for audio, skipped ahead, moved onto the song's timeline. */
  private counts={musicWaits:0,musicSkips:0,musicAligns:0,musicSysPauses:0};
  private pausing=false;
  private readonly rate:number;
  private readonly channels:number;
  readonly configKey: string;
  constructor(config:AudioConfigMessage,private readonly onError:(message:string)=>void,private readonly kind:MusicKind='aac') {
    this.configKey=MusicOutput.key(config,kind);this.rate=config.sampleRate;this.channels=config.channels;
    this.element.id='carplay-music';this.element.hidden=true;this.element.setAttribute('playsinline','');this.element.src=this.url;
    document.body.append(this.element);
    this.element.addEventListener('playing',()=>{this.running=true;});
    this.element.addEventListener('waiting',()=>{this.running=false;if(this.started&&!this.element.paused)this.counts.musicWaits++;});
    // Paused by the car (another app took the sound), not by this page.
    this.element.addEventListener('pause',()=>{this.running=false;if(!this.pausing&&!this.closed)this.counts.musicSysPauses++;this.pausing=false;});
    this.element.addEventListener('error',()=>{if(!this.closed)this.onError('Music playback: '+(this.element.error?.message||'media error'));});
    this.pending.push(kind==='flac'?flacInit(config.sampleRate,config.channels):aacInit(config.sampleRate,config.channels,config.description));
    this.source.addEventListener('sourceopen',()=>{
      if(this.closed)return;
      try { this.buffer=this.source.addSourceBuffer(MIMES[this.kind]);this.buffer.addEventListener('updateend',()=>this.pump());this.buffer.addEventListener('error',()=>this.onError('Music buffer decode error'));this.pump(); }
      catch(error){this.onError(String(error));}
    },{once:true});
  }
  /** Waiting for a cushion before playing on (unlock). */
  private holding=false;
  get unlocked(){return !this.element.paused||this.holding;}
  get playing(){return this.running&&!this.element.paused&&performance.now()-this.lastPacket<1800;}
  pause(){this.holding=false;this.pausing=!this.element.paused;this.element.pause();this.running=false;this.frames=[];this.pcm=[];this.pcmBytes=0;}
  unlock(){
    // Not right at the end: playing from the last sample ran dry at once, a crackle on opening the page. Never
    // backwards either: after a pause the buffer may be played out, and going back replayed what was heard
    // (review 2026-10-12); then the music waits for its cushion and plays on (pump).
    const b=this.buffer;
    if(this.element.paused && b?.buffered.length){
      const target=b.buffered.end(b.buffered.length-1)-CUSHION[this.kind];
      if(target>this.element.currentTime)this.element.currentTime=Math.max(b.buffered.start(0),target);
      else{this.holding=true;this.pump();return Promise.resolve();}
    }
    return this.element.play();
  }
  volume(value:number){this.element.volume=Math.max(0,Math.min(1,value));}
  packet(data:Uint8Array){
    if(this.closed)return;
    if(this.kind==='flac'){this.pcmPacket(data);return;}
    this.lastPacket=performance.now();this.frames.push(data.slice());
    if(this.frames.length<AAC_FRAGMENT)return;
    this.queue(aacFragment(this.sequence++,this.samples,this.frames),1024*this.frames.length);this.frames=[];
    if(this.pending.length>MAX_PENDING){this.onError('Music buffer is not advancing');this.close();return;}
    this.pump();
  }
  /** LPCM packets (352 samples each) are cut into fixed FLAC_BLOCK blocks, one MP4 fragment each. */
  private pcmPacket(data:Uint8Array){
    this.lastPacket=performance.now();this.pcm.push(data.slice());this.pcmBytes+=data.length;
    const step=FLAC_BLOCK*this.channels*2;
    while(this.pcmBytes>=step){
      const block=new Uint8Array(step);let filled=0;
      while(filled<step){
        const head=this.pcm[0],take=Math.min(head.length,step-filled);
        block.set(head.subarray(0,take),filled);filled+=take;
        if(take===head.length)this.pcm.shift();else this.pcm[0]=head.subarray(take);
      }
      this.pcmBytes-=step;
      this.queue(flacFragment(this.sequence++,this.samples,flacFrame(this.block++,this.rate,this.channels,block),FLAC_BLOCK),FLAC_BLOCK);
    }
    if(this.pending.length>MAX_PENDING){this.onError('Music buffer is not advancing');this.close();return;}
    this.pump();
  }
  private queue(data:Uint8Array,length:number){
    this.pending.push(data);this.recent.push({sample:this.samples,length,data});this.samples+=length;
    while(this.recent.length&&this.recent[0].sample<this.samples-5*this.rate)this.recent.shift();
  }
  report():Record<string,number>{const counts=this.counts;this.counts={musicWaits:0,musicSkips:0,musicAligns:0,musicSysPauses:0};return counts;}
  /** A car's media card may show this element's own timeline instead of the song's (2026-10-12 drive: it ran on
   *  from the start of the music, 0 to 671 s, duration unknown, while the song was at 8 of 269 s). */
  follow(song:SongTimeline|null){
    this.song=song&&song.duration>0?{...song,at:performance.now()}:null;
    this.pump();
  }
  /** Moves the element onto the song's timeline: on a new song, or when it is more than 3 s off. The audio not
   *  heard yet is appended again on the new timeline, so the music goes on with its cushion (dropping it left a
   *  second of silence and then nothing in hand for the next Wi-Fi gap, F50 2026-10-12). */
  private align(b:SourceBuffer):boolean{
    if(this.realign){
      const {offset,from,duration}=this.realign;this.realign=null;
      b.timestampOffset=offset;
      this.pending=this.recent.filter(f=>f.sample+f.length>from).map(f=>f.data);
      this.source.duration=Math.max(duration,from/this.rate+offset);
      this.element.currentTime=from/this.rate+offset;
      return false;
    }
    // Paused (by the car for another app, or not unlocked yet): aligned when it plays again.
    const song=this.song;if(!song||!this.started||this.element.paused)return false;
    const position=Math.min(song.duration,song.position+(song.playing?(performance.now()-song.at)/1000:0));
    const now=performance.now();
    if(song.key===this.alignedKey&&(Math.abs(this.element.currentTime-position)<=3||now-this.alignedAt<5000))return false;
    this.alignedKey=song.key;this.alignedAt=now;this.counts.musicAligns++;
    if(!b.buffered.length){
      const queued=this.recent.find(f=>this.pending.includes(f.data));   // nothing appended yet: the next fragment starts the song
      b.timestampOffset=position-(queued?queued.sample:this.samples)/this.rate;
      this.source.duration=Math.max(song.duration,position);this.element.currentTime=position;
      return false;
    }
    // The sample being heard now becomes the song position.
    const from=Math.max(0,Math.round((this.element.currentTime-b.timestampOffset)*this.rate));
    this.realign={offset:position-from/this.rate,from,duration:song.duration};
    b.remove(0,Infinity);
    return true;
  }
  private pump(){
    const b=this.buffer;if(this.closed||!b||b.updating||this.source.readyState!=='open')return;
    try {
      if(this.align(b))return;
      if(b.buffered.length){
        const end=b.buffered.end(b.buffered.length-1),now=this.element.currentTime;
        if(end-now>CUSHION[this.kind]+1.35){this.element.currentTime=Math.max(b.buffered.start(0),end-CUSHION[this.kind]);this.counts.musicSkips++;}
        if(now-b.buffered.start(0)>15){b.remove(0,now-10);return;}
        if(this.holding&&end-now>=CUSHION[this.kind]){this.holding=false;void this.element.play().catch(()=>{});}
      }
      const next=this.pending.shift();if(next){b.appendBuffer(next as Uint8Array<ArrayBuffer>);this.started=true;}
    }catch(error){this.onError(String(error));}
  }
  close(){
    if(this.closed)return;this.closed=true;this.element.pause();this.element.removeAttribute('src');this.element.load();this.element.remove();URL.revokeObjectURL(this.url);this.pending=[];this.frames=[];this.pcm=[];this.pcmBytes=0;
  }
}
