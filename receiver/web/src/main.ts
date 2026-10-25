import { AudioEngine } from './audio';
import { InputController } from './input';
import { MicrophoneUplink } from './mic';
import { VideoPlayer } from './video';
import { Connection } from './ws';
import { SystemMedia } from './media-session';
import { fittedSize, suggestedResolution, aspectChanged } from './display-fit';
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

function render() {
  setLanguage(language);
  updateFullscreen();
  el<HTMLSelectElement>('language').value = language;
  el('btn-settings').setAttribute('aria-label', t('settings'));
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
  el('night-status').textContent = `${t('nightNow')}${t(night ? 'nightOn' : 'nightOff')}；${t(darkQuery.matches ? 'browserDark' : 'browserLight')}`;
}
function fit() {
  const size = fittedSize(canvas.width, canvas.height, screen.clientWidth, screen.clientHeight);
  surface.style.width = `${size.width}px`; surface.style.height = `${size.height}px`;
}
function error(message: string) { el('error-text').textContent = message; el('error-banner').hidden = !message; }
function send(message: ClientMessage) { if (active) connection.send(message); }
const video = new VideoPlayer(canvas, error, () => {
  if (!active) return;
  frames++; painted = true; el('overlay').hidden = true; el('app').dataset.live = 'true';
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
      case 'audio-packet': audio.handlePacket(message); break;
      case 'audio-stopped': audio.stopStream(message.streamType); break;
    }
  },
  onServer: server,
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
    panel.showModal(); void loadDisplay(); return;
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
el('btn-settings').onclick = () => { panel.showModal(); void loadDisplay(); };
el('btn-close').onclick = () => panel.close();
el('dismiss-error').onclick = () => error('');
el<HTMLSelectElement>('language').onchange = event => { setLanguage((event.target as HTMLSelectElement).value); render(); };
panel.addEventListener('click', event => { if (event.target !== panel) return; const r=panel.getBoundingClientRect(); if(event.clientX<r.left || event.clientX>r.right) panel.close(); });
function updateFullscreen() {
  const full = !!document.fullscreenElement;
  const label = t(full ? 'exitFullscreen' : 'fullscreen');
  el('fullscreen-label').textContent = label;
  el('fullscreen-text').textContent = label;
  for (const id of ['btn-fullscreen', 'fullscreen']) {
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
  const target=suggestedResolution(screen.clientWidth,screen.clientHeight);
  const key=`${target.width}x${target.height}`;
  if (!aspectChanged(display,target) || key===lastAutoTarget) return;
  // Avoid a reconnect loop even when another viewer has a different screen shape.
  lastAutoTarget=key;
  if (!(await saveDisplay({...display,...target,hevc:false}))) error(t('autoFail'));
}
autoFit.onchange=() => { localStorage.setItem('f50-auto-fit',String(autoFit.checked)); lastAutoTarget=''; render(); scheduleAuto(); };
el<HTMLFormElement>('display-form').onsubmit=event => {
  event.preventDefault();
  const size=autoFit.checked?suggestedResolution(screen.clientWidth,screen.clientHeight):{width:Number(el<HTMLInputElement>('width').value),height:Number(el<HTMLInputElement>('height').value)};
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
render();fit();if(token) connection.connect();

nightSelect.onchange = () => { localStorage.setItem('f50-night-mode', nightSelect.value); syncNight(); render(); };
darkQuery.addEventListener('change', () => { syncNight(); render(); });
window.setInterval(() => { syncNight(); if (panel.open) render(); }, 30000);

el('browser-check-show').onclick = () => (window as unknown as { F50BrowserCheck: { show(): void } }).F50BrowserCheck.show();
