import { aacInit, aacFragment } from './aac-mp4';
import type { AudioConfigMessage } from './protocol';
/** aac: stream 102's AAC as sent (the wired iPhone's LPCM-as-FLAC kind went with wired CarPlay). */
export type MusicKind = 'aac';
const MIMES: Record<MusicKind,string> = { aac: 'audio/mp4; codecs="mp4a.40.2"' };
/** How far behind the newest audio the element plays. Over Wi-Fi (AAC) the iPhone's packets come with gaps of
 *  about 400 ms every few seconds (F50, 2026-10-12): 0.65 s ran dry and the music stuttered. */
const CUSHION: Record<MusicKind,number> = { aac: 1 };
/** AAC frames (1024 samples, 21 ms) per MP4 fragment: small, so audio reaches the element as it arrives. */
const AAC_FRAGMENT = 4;
/** Fragments (85 ms each) that may wait for a busy buffer before it counts as stuck (6.8 s). */
const MAX_PENDING = 80;
/** An HTML media element plays the AAC the iPhone still sends here (after Siri, ~27 s). Its timeline is its own and
 *  is never moved onto the song (the Media Session that once carried the song position went with the car-Bluetooth
 *  media card): moving it (2026-10-13) seeked on every song change, a hiccup and on Chrome 120 an appendBuffer error
 *  (a shorter duration removes buffered audio), and pulled the music back every 5 s while the iPhone's position
 *  reports stalled over Bluetooth (F50 drive 2026-10-13, 93 s without one). */
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
  private started=false;
  /** For the viewer log: the element waited for audio, skipped ahead, was paused by the car, or the browser refused
   *  to play it (no user gesture). */
  private counts={musicWaits:0,musicSkips:0,musicSysPauses:0,musicBlocked:0};
  /** For the viewer log: how far behind the newest audio the element played, most and least in this report. */
  private lead={max:0,min:Infinity};
  private pausing=false;
  readonly configKey: string;
  constructor(config:AudioConfigMessage,private readonly onError:(message:string)=>void,private readonly kind:MusicKind='aac') {
    this.configKey=MusicOutput.key(config,kind);
    this.element.id='carplay-music';this.element.hidden=true;this.element.setAttribute('playsinline','');this.element.src=this.url;
    document.body.append(this.element);
    this.element.addEventListener('playing',()=>{this.running=true;});
    this.element.addEventListener('waiting',()=>{this.running=false;if(this.started&&!this.element.paused)this.counts.musicWaits++;});
    // Paused by the car (another app took the sound), not by this page.
    this.element.addEventListener('pause',()=>{this.running=false;if(!this.pausing&&!this.closed)this.counts.musicSysPauses++;this.pausing=false;});
    this.element.addEventListener('error',()=>{if(!this.closed)this.onError('Music playback: '+(this.element.error?.message||'media error'));});
    this.pending.push(aacInit(config.sampleRate,config.channels,config.description));
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
  pause(){this.holding=false;this.pausing=!this.element.paused;this.element.pause();this.running=false;this.frames=[];}
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
    return this.element.play().catch(error=>{if((error as Error)?.name==='NotAllowedError')this.counts.musicBlocked++;throw error;});
  }
  volume(value:number){this.element.volume=Math.max(0,Math.min(1,value));}
  get currentVolume(){return this.element.volume;}
  packet(data:Uint8Array){
    if(this.closed)return;
    this.lastPacket=performance.now();this.frames.push(data.slice());
    if(this.frames.length<AAC_FRAGMENT)return;
    this.queue(aacFragment(this.sequence++,this.samples,this.frames),1024*this.frames.length);this.frames=[];
    if(this.pending.length>MAX_PENDING){this.onError('Music buffer is not advancing');this.close();return;}
    this.pump();
  }
  private queue(data:Uint8Array,length:number){
    this.pending.push(data);this.samples+=length;
  }
  report():Record<string,number>{
    const counts:Record<string,number>=this.counts;this.counts={musicWaits:0,musicSkips:0,musicSysPauses:0,musicBlocked:0};
    if(this.lead.max>0)Object.assign(counts,{musicLeadMaxMs:Math.round(this.lead.max*1000),musicLeadMinMs:Math.round(this.lead.min*1000)});
    this.lead={max:0,min:Infinity};return counts;
  }
  private pump(){
    const b=this.buffer;if(this.closed||!b||b.updating||this.source.readyState!=='open')return;
    try {
      if(b.buffered.length){
        const end=b.buffered.end(b.buffered.length-1),now=this.element.currentTime;
        if(end-now>CUSHION[this.kind]+1.35){this.element.currentTime=Math.max(b.buffered.start(0),end-CUSHION[this.kind]);this.counts.musicSkips++;}
        else if(!this.element.paused){
          // Not drained by playing faster: switching to 1.03 at song changes (the iPhone sends the new song in a
          // burst) crackled in the XPeng's Chrome (F50 drive 2026-10-13).
          const lead=end-now;this.lead.max=Math.max(this.lead.max,lead);this.lead.min=Math.min(this.lead.min,lead);
        }
        if(now-b.buffered.start(0)>15){b.remove(0,now-10);return;}
        if(this.holding&&end-now>=CUSHION[this.kind]){this.holding=false;void this.element.play().catch(error=>{if((error as Error)?.name==='NotAllowedError')this.counts.musicBlocked++;});}
      }
      const next=this.pending.shift();if(next){b.appendBuffer(next as Uint8Array<ArrayBuffer>);this.started=true;}
    }catch(error){this.onError(String(error));}
  }
  close(){
    if(this.closed)return;this.closed=true;this.element.pause();this.element.removeAttribute('src');this.element.load();this.element.remove();URL.revokeObjectURL(this.url);this.pending=[];this.frames=[];
  }
}
