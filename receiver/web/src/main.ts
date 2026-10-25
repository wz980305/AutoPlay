import { AudioEngine } from './audio';
import { InputController } from './input';
import { MicrophoneUplink } from './mic';
import { VideoPlayer } from './video';
import { Connection } from './ws';
import { SystemMedia } from './media-session';
import { shownSize, suggestedResolution, aspectChanged, closeShape } from './display-fit';
import { t, language, setLanguage, type Key } from './i18n';
import { isNight, parseNightMode } from './night';
import type { ServerMessage, ClientMessage } from './protocol';

function el<T extends HTMLElement = HTMLElement>(id: string): T { return document.getElementById(id) as T; }
const canvas = el<HTMLCanvasElement>('screen');
const surface = el('surface');
const screen = el('screen-container');
const panel = el<HTMLDialogElement>('settings');
const url = new URL(location.href);
const fromUrl = url.searchParams.get('token');
if (fromUrl) { localStorage.setItem('playport-token', fromUrl); url.searchParams.delete('token'); history.replaceState(null, '', url); }
const token = fromUrl || localStorage.getItem('playport-token') || '';
let active = false, painted = false, frames = 0, lastStats = performance.now();
// Reported to the box every 10 s for its persistent drive diagnostics (no personal data).
let reportFrames = 0, reportBytes = 0, reportStart = performance.now();
// Touch-to-picture: from a finger down on a still picture to the next painted frame (network both ways,
// the iPhone's render and encode, our decode). An animating screen would answer with a frame it was
// sending anyway, so only taps after at least 150 ms without a frame count.
let lastPaintAt = 0, handledDownAt = 0, touchSum = 0, touchCount = 0;
// Music as the iPhone sends it (stream 102, AAC): its bitrate is the iPhone's choice.
let musicBytes = 0;
let state: Key = token ? 'connecting' : 'access';
let hint: Key = token ? 'waitingHint' : 'accessHint';
let lastAutoTarget = '', autoTimer = 0, displayBusy = false;
interface Display { width: number; height: number; fps: number; uiScale: number; hevc: boolean; }
let display: Display | null = null;
const autoFit = el<HTMLInputElement>('auto-fit');
autoFit.checked = localStorage.getItem('f50-auto-fit') !== 'false';
const nightSelect = el<HTMLSelectElement>('night-mode');
nightSelect.value = parseNightMode(localStorage.getItem('f50-night-mode'));
const darkQuery = matchMedia('(prefers-color-scheme: dark)');
let sentNight: boolean | null = null;
const volume = el<HTMLInputElement>('volume');
volume.value = String(Math.min(100, Math.max(0, Number(localStorage.getItem('playport-master') ?? 100) || 0)));

/** Box settings page (pairing, hotspot), when the device startup announced one: same host, plain HTTP. */
const boxPort = Number((window as unknown as { playportBoxSettingsPort?: number }).playportBoxSettingsPort) || 0;
if (boxPort) for (const id of ['box-link', 'box-link-panel']) {
  const link = el<HTMLAnchorElement>(id);
  link.href = `http://${location.hostname}${boxPort === 80 ? '' : `:${boxPort}`}/`;
  link.hidden = false;
}
function render() {
  setLanguage(language);
  updateFullscreen();
  el<HTMLSelectElement>('language').value = language;
  el('app').dataset.state = state;
  volume.setAttribute('aria-label', t('volume'));
  el('connection-text').textContent = t(state);
  el('connection-hint').textContent = t(hint);
  el('overlay').hidden = painted;
  el('app').dataset.live = String(painted);
  el('capabilities').textContent = !isSecureContext ? t('insecure') : typeof VideoDecoder === 'undefined' || typeof AudioDecoder === 'undefined' ? t('unsupported') : t('compatible');
  el('media-support').textContent = t(media.supported ? 'mediaYes' : 'mediaNo');
  el<HTMLInputElement>('width').disabled = autoFit.checked;
  el<HTMLInputElement>('height').disabled = autoFit.checked;
  document.querySelectorAll<HTMLButtonElement>('[data-command]').forEach(b => { b.disabled = !active; });
  const night = isNight(parseNightMode(nightSelect.value), new Date(), darkQuery.matches);
  el('night-status').textContent = `${t('nightNow')}${t(night ? 'nightOn' : 'nightOff')}`;
  el('night-status').title = t(darkQuery.matches ? 'browserDark' : 'browserLight');
}
function fit() {
  const size = shownSize(canvas.width, canvas.height, screen.clientWidth, screen.clientHeight);
  surface.style.width = `${size.width}px`; surface.style.height = `${size.height}px`;
}
function error(message: string) { el('error-text').textContent = message; el('error-banner').hidden = !message; }
function send(message: ClientMessage) { if (active) connection.send(message); }
const video = new VideoPlayer(canvas, error, () => {
  if (!active) return;
  frames++; reportFrames++; painted = true; el('overlay').hidden = true; el('app').dataset.live = 'true';
  const now = performance.now();
  if (input.lastDownAt > handledDownAt) {
    handledDownAt = input.lastDownAt;
    if (input.lastDownAt - lastPaintAt >= 150) { touchSum += now - input.lastDownAt; touchCount++; }
  }
  lastPaintAt = now;
}, () => send({ type:'keyframe' }), fit);
const audio = new AudioEngine(error);
const media = new SystemMedia(send, () => { void audio.unlock().catch(error); }, () => audio.pauseMusic());
const microphone = new MicrophoneUplink((payload, opus) => {
  const frame = new Uint8Array(payload.length + 1); frame[0] = opus ? 0x11 : 0x10; frame.set(payload, 1); connection.sendBinary(frame);
}, message => { el('mic-status').textContent = message; });
const connection = new Connection(token, {
  onWire(message) {
    switch (message.kind) {
      case 'video-config': video.configure(message); break;
      case 'video-frame': video.pushFrame(message); break;
      case 'audio-config': audio.handleConfig(message); break;
      case 'audio-packet': if (message.streamType === 102) musicBytes += message.data.length; audio.handlePacket(message); break;
      case 'audio-stopped': audio.stopStream(message.streamType); break;
    }
  },
  onServer: server,
  onBytes(count) { reportBytes += count; },
  onState(value) {
    if (value === 'closed') { reset(); state = 'reconnecting'; }
    else if (value === 'connecting') state = 'connecting';
    else { state = 'waiting'; void loadDisplay(); void unlock(); }
    render();
  },
});
const input = new InputController(canvas, send); input.attach();
/** Sends CarPlay day/night only on change; a new session (sentNight reset) always gets the current value. */
function syncNight() {
  if (!active) return;
  const night = isNight(parseNightMode(nightSelect.value), new Date(), darkQuery.matches);
  if (night === sentNight) return;
  sentNight = night; send({ type:'night', night });
}
function reset() {
  sentNight = null;
  active = painted = false; input.reset(); canvas.inert = true;
  video.close(); audio.stopAll(); media.setActive(false); void microphone.stop();
  canvas.getContext('2d')?.clearRect(0,0,canvas.width,canvas.height);
}
function server(message: ServerMessage) {
  if(message.type === 'artwork' && message.artwork) { media.setArtwork(message.revision ?? 0,message.artwork); return; }
  if (message.type === 'now-playing' && message.nowPlaying) { media.setMetadata(message.nowPlaying); return; }
  if (message.type === 'host-ui' && active) {
    openPanel(); return;
  }
  if (message.type === 'mic') {
    if (message.micActive) void microphone.start({ sampleRate:message.micRate ?? 16000, channels:message.micChannels ?? 1, codec:message.micCodec ?? 'lpcm', samplesPerPacket:message.micSamplesPerPacket ?? 320, bitrate:message.micBitrate ?? null });
    else void microphone.stop();
  }
  if (message.type !== 'session' && message.type !== 'hello') return;
  if (!message.sessionActive) { reset(); state = 'waiting'; }
  else { active = true; canvas.inert = false; state = 'starting'; media.setActive(true); syncNight(); if(message.nowPlaying) media.setMetadata(message.nowPlaying); if(message.artwork) media.setArtwork(message.revision ?? 0,message.artwork); }
  render();
}
async function unlock() {
  if (audio.isUnlocked) return;
  try { await audio.unlock(); } catch { /* Keep a truthful gesture hint; retry on next gesture. */ }
}
window.addEventListener('pointerdown', () => { void unlock(); });
window.addEventListener('click', () => { void unlock(); });
window.addEventListener('keydown', () => { void unlock(); });
el('audio-unlock').onclick = () => { void unlock(); };
function setVolume() { audio.setVolume(Number(volume.value) / 100); el('volume-value').textContent = `${volume.value}%`; localStorage.setItem('playport-master',volume.value); }
volume.oninput = setVolume; setVolume();
function openPanel() {
  if (!panel.open) { panel.classList.remove('closing'); panel.showModal(); }
  void loadDisplay();
}
/** Leave along the path it came in (to the right), unless motion is reduced. */
function closePanel() {
  if (!panel.open || panel.classList.contains('closing')) return;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { panel.close(); return; }
  panel.classList.add('closing');
  window.setTimeout(() => { panel.classList.remove('closing'); panel.close(); }, 200);
}
el('btn-settings').onclick = openPanel;
el('btn-close').onclick = closePanel;
panel.addEventListener('cancel', event => { event.preventDefault(); closePanel(); });
el('dismiss-error').onclick = () => error('');
el<HTMLSelectElement>('language').onchange = event => { setLanguage((event.target as HTMLSelectElement).value); render(); };
panel.addEventListener('click', event => { if (event.target !== panel) return; const r=panel.getBoundingClientRect(); if(event.clientX<r.left || event.clientX>r.right) closePanel(); });
function updateFullscreen() {
  const full = !!document.fullscreenElement;
  const label = t(full ? 'exitFullscreen' : 'fullscreen');
  el('fullscreen-label').textContent = label;
  el('fullscreen-text').textContent = label;
  el('welcome-fullscreen-text').textContent = label;
  for (const id of ['btn-fullscreen', 'fullscreen', 'welcome-fullscreen']) {
    el(id).setAttribute('aria-label', label);
    el(id).setAttribute('title', label);
    el(id).dataset.fullscreen = String(full);
  }
}
async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
    if (panel.open) panel.close();
  } catch { error(t('fullscreenFail')); }
  updateFullscreen();
}
el('fullscreen').onclick = toggleFullscreen;
el('btn-fullscreen').onclick = toggleFullscreen;
el('welcome-fullscreen').onclick = toggleFullscreen;
let toastTimer = 0;
function toast(message: string) {
  el('toast').textContent = message; el('toast').hidden = false;
  window.clearTimeout(toastTimer); toastTimer = window.setTimeout(() => { el('toast').hidden = true; }, 6000);
}
document.addEventListener('fullscreenchange', () => {
  updateFullscreen(); fit();
  if (document.fullscreenElement) toast(t('fullscreenHint')); else el('toast').hidden = true;
});
document.querySelectorAll<HTMLButtonElement>('[data-command]').forEach(button => button.onclick = () => {
  const cmd = button.dataset.command;
  if (cmd === 'home' || cmd === 'back') send({ type:'knob', knob:{ select:false, home:cmd==='home', back:cmd==='back', x:0,y:0,wheel:0 } });
  else if (cmd === 'refresh') send({ type:'keyframe' });
  else send({ type:'media', media:cmd==='previous'?5:cmd==='next'?4:3 });
});
async function loadDisplay() {
  if (displayBusy || !token) return;
  el('display-status').textContent = t('loading');
  try {
    const r = await fetch('/api/display'); if (!r.ok) throw new Error();
    display = await r.json() as Display;
    el<HTMLInputElement>('width').value = String(display.width); el<HTMLInputElement>('height').value = String(display.height);
    el<HTMLSelectElement>('fps').value = String(display.fps); el<HTMLSelectElement>('ui-scale').value = String(display.uiScale);
    el('display-status').textContent = `${display.width} × ${display.height} / ${display.fps} fps`;
    scheduleAuto();
  } catch { el('display-status').textContent = t('loadFail'); }
}
async function saveDisplay(target: Display): Promise<boolean> {
  if (displayBusy || !token) return false;
  displayBusy = true; el<HTMLButtonElement>('apply').disabled = true; el<HTMLFieldSetElement>('display-fields').disabled = true;
  el('display-status').textContent = t('applying');
  try {
    const r = await fetch(`/api/display?token=${encodeURIComponent(token)}`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(target) });
    const body = await r.json() as {ok?:boolean}; if (!r.ok || !body.ok) throw new Error();
    display = target; el('display-status').textContent = t('applied'); return true;
  } catch { el('display-status').textContent = t('applyFail'); return false; }
  finally { displayBusy=false; el<HTMLButtonElement>('apply').disabled=false; el<HTMLFieldSetElement>('display-fields').disabled=false; render(); }
}
function scheduleAuto() {
  window.clearTimeout(autoTimer);
  if (!autoFit.checked || !display || displayBusy || document.hidden || typeof VideoDecoder === 'undefined') return;
  autoTimer=window.setTimeout(() => { void adapt(); },1500);
}
async function adapt() {
  if (!display || !autoFit.checked || displayBusy) return;
  const target=autoTarget();
  if (!document.fullscreenElement && closeShape(display,target)) return;
  const key=`${target.width}x${target.height}`;
  if (!aspectChanged(display,target) || key===lastAutoTarget) return;
  // Avoid a reconnect loop even when another viewer has a different screen shape.
  lastAutoTarget=key;
  if (!(await saveDisplay({...display,...target,hevc:false}))) error(t('autoFail'));
}
/** A close shape is renegotiated only in fullscreen: opening the page or leaving fullscreen shows the
 *  current picture stretched (shownSize, never black bars) instead of a black reconnect right after
 *  opening. A clearly different shape (portrait, split screen) is renegotiated at once, as before
 *  (user 2026-10-12, replacing 2026-10-11's reconnect on every window change). */
function autoTarget() {
  return suggestedResolution(screen.clientWidth,screen.clientHeight);
}
autoFit.onchange=() => { localStorage.setItem('f50-auto-fit',String(autoFit.checked)); lastAutoTarget=''; render(); scheduleAuto(); };
el<HTMLFormElement>('display-form').onsubmit=event => {
  event.preventDefault();
  const size=autoFit.checked?autoTarget():{width:Number(el<HTMLInputElement>('width').value),height:Number(el<HTMLInputElement>('height').value)};
  if (![size.width,size.height].every(v=>Number.isInteger(v)&&v>=480&&v<=3840&&v%2===0)) { error(t('range')); return; }
  void saveDisplay({...size,fps:Number(el<HTMLSelectElement>('fps').value),uiScale:Number(el<HTMLSelectElement>('ui-scale').value),hevc:false});
};
new ResizeObserver(()=>{ fit(); scheduleAuto(); }).observe(screen);
document.addEventListener('visibilitychange',()=>{if(!document.hidden){fit();scheduleAuto();void unlock();}});
window.setInterval(()=>{
  const now=performance.now(),fps=frames*1000/Math.max(1,now-lastStats);frames=0;lastStats=now;
  el('stats').textContent=painted?`${canvas.width} × ${canvas.height} / ${fps.toFixed(0)} fps / ${t('latency')} ${video.decodeLatencyMs.toFixed(0)} ms`:t('noStream');
  el('audio-unlock').hidden=!active||audio.isUnlocked;
  el('audio-status').textContent=t(audio.isPlaying?'playing':'paused');media.setPlaying(audio.isPlaying);
},750);
window.setInterval(()=>{
  const now=performance.now(),seconds=Math.max(1,(now-reportStart)/1000);
  send({type:'stats',stats:{fps:reportFrames/seconds,decodeMs:video.decodeLatencyMs,queue:video.decodeQueueSize,
    kbps:reportBytes*8/1000/seconds,hidden:document.hidden?1:0,fullscreen:document.fullscreenElement?1:0,
    width:canvas.width,height:canvas.height,...(touchCount?{touchMs:touchSum/touchCount,touches:touchCount}:{}),...(musicBytes?{musicKbps:musicBytes*8/1000/seconds}:{})}});
  reportFrames=0;reportBytes=0;reportStart=now;touchSum=0;touchCount=0;musicBytes=0;
},10000);
render();fit();if(token) connection.connect();

nightSelect.onchange = () => { localStorage.setItem('f50-night-mode', nightSelect.value); syncNight(); render(); };
darkQuery.addEventListener('change', () => { syncNight(); render(); });
window.setInterval(() => { syncNight(); if (panel.open) render(); }, 30000);

el('browser-check-show').onclick = () => (window as unknown as { F50BrowserCheck: { show(): void } }).F50BrowserCheck.show();
