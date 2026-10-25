import { aacInit, aacFragment } from './aac-mp4';
import { FLAC_BLOCK, FLAC_MIME, flacFragment, flacFrame, flacInit } from './flac-mp4';
import type { AudioConfigMessage } from './protocol';
/** aac: stream 102's AAC as sent. flac: the wired iPhone's LPCM, losslessly framed (flac-mp4.ts). */
export type MusicKind = 'aac' | 'flac';
const MIMES: Record<MusicKind,string> = { aac: 'audio/mp4; codecs="mp4a.40.2"', flac: FLAC_MIME };
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
  private readonly rate:number;
  private readonly channels:number;
  readonly configKey: string;
  constructor(config:AudioConfigMessage,private readonly onError:(message:string)=>void,private readonly kind:MusicKind='aac') {
    this.configKey=MusicOutput.key(config,kind);this.rate=config.sampleRate;this.channels=config.channels;
    this.element.id='carplay-music';this.element.hidden=true;this.element.setAttribute('playsinline','');this.element.src=this.url;
    document.body.append(this.element);
    this.element.addEventListener('playing',()=>{this.running=true;});
    this.element.addEventListener('waiting',()=>{this.running=false;});
    this.element.addEventListener('pause',()=>{this.running=false;});
    this.element.addEventListener('error',()=>{if(!this.closed)this.onError('Music playback: '+(this.element.error?.message||'media error'));});
    this.pending.push(kind==='flac'?flacInit(config.sampleRate,config.channels):aacInit(config.sampleRate,config.channels,config.description));
    this.source.addEventListener('sourceopen',()=>{
      if(this.closed)return;
      try { this.buffer=this.source.addSourceBuffer(MIMES[this.kind]);this.buffer.addEventListener('updateend',()=>this.pump());this.buffer.addEventListener('error',()=>this.onError('Music buffer decode error'));this.pump(); }
      catch(error){this.onError(String(error));}
    },{once:true});
  }
  get unlocked(){return !this.element.paused;}
  get playing(){return this.running&&!this.element.paused&&performance.now()-this.lastPacket<1800;}
  pause(){this.element.pause();this.running=false;this.frames=[];this.pcm=[];this.pcmBytes=0;}
  unlock(){
    if(this.element.paused && this.buffer?.buffered.length) this.element.currentTime=this.buffer.buffered.end(this.buffer.buffered.length-1);
    return this.element.play();
  }
  volume(value:number){this.element.volume=Math.max(0,Math.min(1,value));}
  packet(data:Uint8Array){
    if(this.closed)return;
    if(this.kind==='flac'){this.pcmPacket(data);return;}
    this.lastPacket=performance.now();this.frames.push(data.slice());
    if(this.frames.length<20)return;
    this.pending.push(aacFragment(this.sequence++,this.samples,this.frames));this.samples+=1024*this.frames.length;this.frames=[];
    if(this.pending.length>12){this.onError('Music buffer is not advancing');this.close();return;}
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
      this.pending.push(flacFragment(this.sequence++,this.samples,flacFrame(this.block++,this.rate,this.channels,block),FLAC_BLOCK));this.samples+=FLAC_BLOCK;
    }
    if(this.pending.length>12){this.onError('Music buffer is not advancing');this.close();return;}
    this.pump();
  }
  private pump(){
    const b=this.buffer;if(this.closed||!b||b.updating||this.source.readyState!=='open')return;
    try {
      if(b.buffered.length){
        const end=b.buffered.end(b.buffered.length-1),now=this.element.currentTime;
        if(end-now>2)this.element.currentTime=Math.max(b.buffered.start(0),end-.65);
        if(now-b.buffered.start(0)>15){b.remove(0,now-10);return;}
      }
      const next=this.pending.shift();if(next)b.appendBuffer(next as Uint8Array<ArrayBuffer>);
    }catch(error){this.onError(String(error));}
  }
  close(){
    if(this.closed)return;this.closed=true;this.element.pause();this.element.removeAttribute('src');this.element.load();this.element.remove();URL.revokeObjectURL(this.url);this.pending=[];this.frames=[];this.pcm=[];this.pcmBytes=0;
  }
}
