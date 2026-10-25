import type { ClientMessage, NowPlaying } from './protocol';
/** Real receiver audio owns the media element. No silent loop or invented song metadata. */
export class SystemMedia {
  private active = false;
  private playing = false;
  private info: MediaMetadataInit = { title: "CarPlay" };
  private revision = 0;
  private duration = 0;
  private position = 0;
  private speed = 1;
  private at = 0;
  /** The iPhone's own playing state; what the browser hears (navigation prompts, locked sound) only stands in when it is unknown. */
  private phonePlaying: boolean | undefined;
  private positionNow() { return Math.min(this.duration, this.position + ((this.phonePlaying ?? this.playing) ? (performance.now()-this.at)/1000*this.speed : 0)); }
  setMetadata(value: NowPlaying) {
    const revision = value.revision ?? 0;
    const changed = revision !== this.revision || value.title !== this.info.title || value.artist !== this.info.artist || value.album !== this.info.album;
    this.info = { title: value.title, artist: value.artist, album: value.album, artwork: revision === this.revision ? this.info.artwork : [] };
    this.revision = revision;
    this.duration = Math.max(0,(value.durationMs ?? 0)/1000);
    this.position = Math.max(0,Math.min(this.duration,(value.positionMs ?? 0)/1000));
    this.speed = (value.speed ?? 1) > 0 ? value.speed! : 1;
    this.phonePlaying = value.playing ?? undefined;
    if (!Number.isFinite(this.speed)) this.speed = 1;
    this.at = performance.now();
    if(changed) this.refreshMetadata();
    this.updatePosition();
  }
  setArtwork(revision: number, src: string) {
    if(revision !== this.revision || !src.startsWith('data:image/jpeg;base64,')) return;
    this.info = {...this.info, artwork:[{src,type:'image/jpeg'}]};this.refreshMetadata();
  }
  private updatePosition() {
    if(!this.supported || !navigator.mediaSession.setPositionState) return;
    try { navigator.mediaSession.setPositionState(this.active && this.duration > 0 ? { duration:this.duration, position:this.positionNow(), playbackRate:this.speed } : undefined); } catch { /* Older browsers may not support a position state. */ }
  }
  private refreshMetadata() {
    if (this.supported) navigator.mediaSession.metadata = this.active && typeof MediaMetadata !== "undefined" ? new MediaMetadata(this.info) : null;
  }
  readonly supported = 'mediaSession' in navigator;
  /** For the box's viewer log: can the OS media card take our song position at all, and which one we give it. */
  report(): Record<string, number> {
    const positionState = this.supported && typeof navigator.mediaSession.setPositionState === 'function' ? 1 : 0;
    return this.duration > 0 ? { positionState, songPos: Math.round(this.positionNow()), songDur: Math.round(this.duration) } : { positionState };
  }
  constructor(private readonly send: (message: ClientMessage) => void, unlock: () => void, pause: () => void = () => {}) {
    if (!this.supported) return;
    const handlers: Partial<Record<MediaSessionAction, () => void>> = {
      play: () => { unlock(); this.command(1); },
      pause: () => { pause(); this.setPlaying(false); this.command(2); },
      previoustrack: () => this.command(5),
      nexttrack: () => this.command(4),
    };
    for (const [name, handler] of Object.entries(handlers)) {
      try { navigator.mediaSession.setActionHandler(name as MediaSessionAction, handler); } catch { /* Partial browser support. */ }
    }
  }
  private command(index: number) { if (this.active) this.send({ type: 'media', media: index }); }
  setActive(active: boolean) {
    this.active = active;
    if (!this.supported) return;
    if (!active) { this.info = { title: "CarPlay" }; this.duration=0; this.revision=0; this.phonePlaying=undefined; }
    this.refreshMetadata();
    if (!active) this.playing = false;
    this.update(); this.updatePosition();
  }
  setPlaying(playing: boolean) {
    if(playing === this.playing) return;
    this.position=this.positionNow();this.at=performance.now();this.playing=playing;this.update();this.updatePosition();
  }
  private update() {
    if (this.supported) navigator.mediaSession.playbackState = this.active ? (this.playing ? 'playing' : 'paused') : 'none';
  }
}
