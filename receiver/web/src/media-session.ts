import type { ClientMessage, NowPlaying } from './protocol';
/** The position state's rate: the card is told the position, not left to work it out. */
const STILL_RATE = 1e-6;
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
  /** For the viewer log: the car's media buttons (card, steering wheel) as they reach this page. */
  private actions: Record<string, number> = {};
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
    this.update(); this.updatePosition();
  }
  setArtwork(revision: number, src: string) {
    if(revision !== this.revision || !src.startsWith('data:image/jpeg;base64,')) return;
    this.info = {...this.info, artwork:[{src,type:'image/jpeg'}]};this.refreshMetadata();
  }
  /** The position goes out on every tick with a near-zero rate (0 is refused): an OS card that runs the position on
   *  by its own clock showed the XPeng's bar always full (F50 drive 2026-10-13); with this it follows the song. The
   *  card reads only this, not the music element: without a position state it showed no bar at all. */
  /** Called by the page's 750 ms tick: the card gets the running position at least once a second. */
  tick() { if (this.active && this.duration > 0) this.updatePosition(); }
  private updatePosition() {
    if(!this.supported || !navigator.mediaSession.setPositionState) return;
    try { navigator.mediaSession.setPositionState(this.active && this.duration > 0 ? { duration:this.duration, position:this.positionNow(), playbackRate:STILL_RATE } : undefined); } catch { /* Older browsers may not support a position state. */ }
  }
  private refreshMetadata() {
    if (this.supported) navigator.mediaSession.metadata = this.active && typeof MediaMetadata !== "undefined" ? new MediaMetadata(this.info) : null;
  }
  /** Off with the music over the car's Bluetooth: a Tesla took the page for a second music source beside the
   *  iPhone, paused one for the other (its pause reached the page and went on to the iPhone) and the two kept
   *  fighting (2026-10-14).
   *  There the music is the car's own; the page names no song and passes on no media key. */
  readonly supported: boolean;
  /** Whether the iPhone says it plays; undefined while it has not said. */
  get phoneState() { return this.phonePlaying; }
  /** For the box's viewer log: can the OS media card take our song position at all, and which one we give it. */
  report(): Record<string, number> {
    const positionState = this.supported && typeof navigator.mediaSession.setPositionState === 'function' ? 1 : 0;
    const art = this.info.artwork && (this.info.artwork as MediaImage[]).length ? 1 : 0;
    const actions = this.actions; this.actions = {};
    return this.duration > 0 ? { positionState, songPos: Math.round(this.positionNow()), songDur: Math.round(this.duration), art, ...actions } : { positionState, ...actions };
  }
  constructor(private readonly send: (message: ClientMessage) => void, unlock: () => void, pause: () => void = () => {}, passive = false) {
    this.supported = !passive && 'mediaSession' in navigator;
    if (!this.supported) return;
    const handlers: Partial<Record<MediaSessionAction, () => void>> = {
      play: () => { unlock(); this.command(1); },
      // The car turns its play/pause key into pause while the page plays, also when the car itself paused the
      // iPhone for its own video app and the page goes on with the iPhone's silence: then it means play (F50 drive
      // 2026-10-13: the first press paused again; pausing the page instead silenced the car's video app).
      pause: () => { if (this.phonePlaying === false) { this.actions.keyPauseAsPlay = (this.actions.keyPauseAsPlay ?? 0) + 1; unlock(); this.command(1); return; }
        pause(); this.setPlaying(false); this.command(2); },
      previoustrack: () => this.command(5),
      nexttrack: () => this.command(4),
    };
    const counted: Record<string, string> = { play: 'keyPlay', pause: 'keyPause', previoustrack: 'keyPrev', nexttrack: 'keyNext' };
    for (const [name, handler] of Object.entries(handlers)) {
      const count = () => { this.actions[counted[name]] = (this.actions[counted[name]] ?? 0) + 1; handler(); };
      try { navigator.mediaSession.setActionHandler(name as MediaSessionAction, count); } catch { /* Partial browser support. */ }
    }
  }
  private command(index: number) { if (this.active) this.send({ type: 'media', media: index }); }
  /** While Siri, a call or a prompt sounds from this page and no music does (music over the car's Bluetooth): what
   *  the card shows instead of the page address (a Tesla showed the page and its address during Siri, 2026-10-14). null
   *  puts the song back. */
  announce(label: string | null) {
    if (!this.supported || typeof MediaMetadata === 'undefined') return;
    if (label) navigator.mediaSession.metadata = new MediaMetadata({ title: label, artist: 'DashPlay' });
    else this.refreshMetadata();
  }
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
  /** The iPhone's own state when it reports one: the car paused the iPhone (over its Bluetooth) for its own video
   *  app while the page went on playing the iPhone's silence, so the card showed "pause" and its first press paused
   *  again (F50 drive 2026-10-13: media key 2, then 1). */
  private update() {
    if (this.supported) navigator.mediaSession.playbackState = this.active ? ((this.phonePlaying ?? this.playing) ? 'playing' : 'paused') : 'none';
  }
}
