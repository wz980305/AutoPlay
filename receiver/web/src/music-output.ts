import { aacInit, aacFragment } from './aac-mp4';
import type { AudioConfigMessage } from './protocol';
const mime='audio/mp4; codecs="mp4a.40.2"';
/** A real HTML media timeline makes received music eligible for OS media controls. */
export class MusicOutput {
  static supported() { return typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(mime); }
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
  readonly configKey: string;
  constructor(config:AudioConfigMessage,private readonly onError:(message:string)=>void) {
    this.configKey=JSON.stringify([config.sampleRate,config.channels,Array.from(config.description)]);
    this.element.id='carplay-music';this.element.hidden=true;this.element.setAttribute('playsinline','');this.element.src=this.url;
    document.body.append(this.element);
    this.element.addEventListener('playing',()=>{this.running=true;});
    this.element.addEventListener('waiting',()=>{this.running=false;});
    this.element.addEventListener('pause',()=>{this.running=false;});
    this.element.addEventListener('error',()=>{if(!this.closed)this.onError('Music playback: '+(this.element.error?.message||'media error'));});
    this.pending.push(aacInit(config.sampleRate,config.channels,config.description));
    this.source.addEventListener('sourceopen',()=>{
      if(this.closed)return;
      try { this.buffer=this.source.addSourceBuffer(mime);this.buffer.addEventListener('updateend',()=>this.pump());this.buffer.addEventListener('error',()=>this.onError('Music buffer decode error'));this.pump(); }
      catch(error){this.onError(String(error));}
    },{once:true});
  }
  get unlocked(){return !this.element.paused;}
  get playing(){return this.running&&!this.element.paused&&performance.now()-this.lastPacket<1800;}
  pause(){this.element.pause();this.running=false;this.frames=[];}
  unlock(){
    if(this.element.paused && this.buffer?.buffered.length) this.element.currentTime=this.buffer.buffered.end(this.buffer.buffered.length-1);
    return this.element.play();
  }
  volume(value:number){this.element.volume=Math.max(0,Math.min(1,value));}
  packet(data:Uint8Array){
    if(this.closed)return;
    this.lastPacket=performance.now();this.frames.push(data.slice());
    if(this.frames.length<20)return;
    this.pending.push(aacFragment(this.sequence++,this.samples,this.frames));this.samples+=1024*this.frames.length;this.frames=[];
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
    if(this.closed)return;this.closed=true;this.element.pause();this.element.removeAttribute('src');this.element.load();this.element.remove();URL.revokeObjectURL(this.url);this.pending=[];this.frames=[];
  }
}
