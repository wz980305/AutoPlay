import { AudioEngine } from './audio';
import { InputController } from './input';
import { MicrophoneUplink } from './mic';
import { VideoPlayer } from './video';
import { Connection } from './ws';
import { SystemMedia } from './media-session';
import { LagProbe } from './lag';
import { shownSize, suggestedResolution, renegotiate } from './display-fit';
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
function error(message: string) {
  // This browser said it decodes H.265 but cannot: auto goes back to H.264 for good (on this browser).
  if (message.includes('H.265/HEVC')) { saveFlag('f50-hevc-failed', '1'); lastAutoTarget = ''; scheduleAuto(); }
  el('error-text').textContent = message; el('error-banner').hidden = !message;
}
/** Auto quality (2026-10-14; a Tesla decodes a frame in ~1 ms, the XPeng in 60-100 ms): once this browser has
 *  shown it decodes fast (f50-fast-decoder, from the 10 s reports), auto picks the resolution from the screen's real
 *  pixels (CSS size x device pixel ratio, long side 1280-1920) and H.265 when the browser decodes it; a slow decoder
 *  keeps the CSS-size choice and H.264. The codec list (auto / H.264 / H.265) overrides. */
function readFlag(key: string) { try { return localStorage.getItem(key) ?? ''; } catch { return ''; } }
function saveFlag(key: string, value: string) { try { localStorage.setItem(key, value); } catch { /* Then auto stays as it was. */ } }
let hevcDecodes = false;
if (typeof VideoDecoder !== 'undefined') void VideoDecoder.isConfigSupported({codec:'hvc1.1.6.L120.B0',codedWidth:1920,codedHeight:1080})
  .then(support => { hevcDecodes = support.supported === true; scheduleAuto(); }).catch(() => {});
const fastDecoder = () => readFlag('f50-fast-decoder') === '1';
function wantHevc() {
  const codec = el<HTMLSelectElement>('codec').value;
  return codec === 'h265' || (codec === 'auto' && fastDecoder() && hevcDecodes && readFlag('f50-hevc-failed') !== '1');
}
let fastReports = 0, slowReports = 0;
/** Called with each 10 s report: three fast ones in a row mark this browser fast, three slow ones unmark it. */
function judgeDecoder(decodeMs: number, fps: number) {
  if (!(decodeMs > 0) || fps < 5) return;
  fastReports = decodeMs < 12 ? fastReports + 1 : 0;
  slowReports = decodeMs > 40 ? slowReports + 1 : 0;
  if (fastReports >= 3 && !fastDecoder()) { saveFlag('f50-fast-decoder', '1'); lastAutoTarget = ''; scheduleAuto(); }
  if (slowReports >= 3 && fastDecoder()) { saveFlag('f50-fast-decoder', '0'); lastAutoTarget = ''; scheduleAuto(); }
}
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
// Tesla mode, turned on by the person on the box (2026-10-14): the music goes to the car over Bluetooth, so the
// steering wheel, media card and volume are the car's own; this page plays only prompts and calls, prompts boosted.
// ?promptgain=1..8 overrides the boost.
const teslaMode = (window as unknown as { playportTeslaMode?: boolean }).playportTeslaMode === true;
const promptGain = Number(new URLSearchParams(location.search).get('promptgain')) || (teslaMode ? 3 : 1);
// Music the iPhone still sends here is played: it sends music to one place at a time, and after Siri from the
// CarPlay screen it sent it here for ~27 s before going back to the car's Bluetooth, silent while it was dropped.
const audio = new AudioEngine(error, { promptBoost: promptGain, idleClose: teslaMode });
/** Tesla mode: the car's media card shows the page's title and address whenever the page sounds (Siri, prompts,
 *  calls); name it instead (2026-10-14). The last voice stream to start wins; the title goes back when none is left. */
const voiceLabels: Record<string, string> = { speechrecognition: 'Siri', telephony: '通话', default: '导航播报' };
const voices = new Map<number, string>();
function showVoice() {
  const label = Array.from(voices.values()).pop() ?? null;
  document.title = label ? `${label} · DashPlay` : 'DashPlay';
  media.announce(label);
}
function voiceStarted(streamType: number, name: string) {
  if (!teslaMode) return;
  voices.delete(streamType);
  if (voiceLabels[name]) voices.set(streamType, voiceLabels[name]);
  showVoice();
}
function voiceStopped(streamType: number) { if (teslaMode && voices.delete(streamType)) showVoice(); }
const lag = new LagProbe();
const media = new SystemMedia(send, () => { void audio.unlock().catch(error); }, () => audio.pauseMusic(), teslaMode);
const microphone = new MicrophoneUplink((payload, opus) => {
  const frame = new Uint8Array(payload.length + 1); frame[0] = opus ? 0x11 : 0x10; frame.set(payload, 1); connection.sendBinary(frame);
}, message => { el('mic-status').textContent = message; });
const connection = new Connection(token, {
  onWire(message) {
    switch (message.kind) {
      case 'video-config': video.configure(message); break;
      case 'video-frame': video.pushFrame(message); break;
      case 'audio-config': audio.handleConfig(message); voiceStarted(message.streamType, message.name); break;
      case 'audio-packet': if (message.streamType === 102) musicBytes += message.data.length; audio.handlePacket(message); break;
      case 'audio-stopped': audio.stopStream(message.streamType); voiceStopped(message.streamType); break;
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
  sentNight = null; lag.reset();
  active = painted = false; input.reset(); canvas.inert = true;
  video.close(); audio.stopAll(); media.setActive(false); void microphone.stop();
  canvas.getContext('2d')?.clearRect(0,0,canvas.width,canvas.height);
}
function server(message: ServerMessage) {
  if (message.type === 'pong') { lag.pong(performance.now()); return; }
  // Straight back, also before CarPlay starts: the box pauses the picture while this page lags behind.
  if (message.type === 'mark') { connection.send({ type: 'ack', mark: message.mark ?? 0 }); return; }
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
/** The car shows something else over the page (reverse camera): the page is hidden and comes back out of
 *  fullscreen (Xpeng G6, 2026-10-12). Such an exit keeps the picture as negotiated, and the next tap on the
 *  picture goes back to fullscreen; a browser enters fullscreen only on a tap, never by itself. */
let wantFullscreen = false, hiddenAt = -Infinity, shownAt = -Infinity, coveredInFullscreen = false, fullscreenSeq = 0;
/** A tap goes back to fullscreen only when the car covered the page (reverse camera), not after leaving fullscreen on
 *  purpose (the car's back button or gesture): in the 2 s that tells the two apart, a tap went back to fullscreen
 *  and never reached CarPlay (2026-10-13). */
let restoreArmed = false;
const restoring = () => restoreArmed && wantFullscreen && !document.fullscreenElement && !document.hidden;
/** A Tesla's browser ignores a page's fullscreen request; it shows a page without its address bar when it comes
 *  through a video site it lists (in China v.qq.com and 1905.com, as tesla-kit.com does; elsewhere
 *  youtube.com/redirect). In Tesla mode the fullscreen button takes that way back to this page (2026-10-14); the
 *  "?www.1905.com" it ends with marks a page already shown that way. */
const teslaBorderless = location.search.includes('www.1905.com');
function teslaFullscreenUrl() {
  // 1905.com goes on only when the text between "//" and the first "/" ends in "1905.com": no "/" before the "?"
  // (with "/?" it went to its own home page, 2026-10-14); this page is the site's root anyway.
  return 'https://v.qq.com/search_redirect.html?url=https://www.1905.com/api/redirec.html?redirect_url='
    + `${location.origin}?www.1905.com`;
}
async function toggleFullscreen() {
  if (teslaMode && !teslaBorderless) { location.href = teslaFullscreenUrl(); return; }
  try {
    if (document.fullscreenElement) { wantFullscreen = false; await document.exitFullscreen(); }
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
  updateFullscreen(); fit(); pageEvent(document.fullscreenElement ? 3 : 4);
  const seq = ++fullscreenSeq;
  if (document.fullscreenElement) { wantFullscreen = true; coveredInFullscreen = false; restoreArmed = false; toast(t('fullscreenHint')); return; }
  el('toast').hidden = true;
  // The car covered the page: the browser leaves fullscreen while it is hidden, and may tell the page only once it
  // is shown again (Chrome, 2026-10-12: hidden, shown, then out of fullscreen). Fullscreen comes back on a tap.
  if (wantFullscreen && (document.hidden || (coveredInFullscreen && performance.now() - shownAt < 2000))) { restoreArmed = true; showRestoreHint(); return; }
  // Left while shown: on purpose, unless the page is hidden within 2 s; then fit the window as usual.
  const exitedAt = performance.now();
  window.setTimeout(() => { if (seq !== fullscreenSeq || hiddenAt >= exitedAt) return; wantFullscreen = false; scheduleAuto(); }, 2000);
});
function showRestoreHint() {
  if (!restoring()) return;
  window.clearTimeout(toastTimer); el('toast').textContent = t('tapFullscreen'); el('toast').hidden = false;
}
// Capture phase, ahead of the CarPlay input: this tap only goes back to fullscreen.
for (const name of ['pointerdown', 'pointerup'] as const) window.addEventListener(name, event => {
  if (!restoring() || !surface.contains(event.target as Node)) return;
  event.stopPropagation(); event.preventDefault();
  if (name === 'pointerup') void document.documentElement.requestFullscreen().catch(() => { wantFullscreen = false; el('toast').hidden = true; });
}, { capture: true });
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
    el('display-status').dataset.codec = display.hevc ? 'H.265' : 'H.264';
    el('display-status').textContent = `${display.width} × ${display.height} / ${display.fps} fps / ${display.hevc ? 'H.265' : 'H.264'}`;
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
  // Not for a hidden page (a covered page reports a small window) nor while fullscreen waits for its tap; a timer
  // set just before the car covered the page fired anyway and renegotiated to 800x400 (Chrome, 2026-10-12).
  if (!display || !autoFit.checked || displayBusy || document.hidden || (wantFullscreen && !document.fullscreenElement)) return;
  const target=autoTarget(),fullscreen=!!document.fullscreenElement,hevc=wantHevc();
  // Sharper than now (a fast decoder's real pixels, or the codec changed): once; else the shape rules below.
  const sharper=target.width*target.height>display.width*display.height*1.2||hevc!==display.hevc;
  if (!sharper && !renegotiate(display,target,fullscreen,storedFullscreenSize())) return;
  const key=`${target.width}x${target.height}${hevc?'-h265':''}`;
  if (key===lastAutoTarget) return;
  // Avoid a reconnect loop even when another viewer has a different screen shape.
  lastAutoTarget=key;
  if (!(await saveDisplay({...display,...target,hevc}))) { error(t('autoFail')); return; }
  if (fullscreen) try { localStorage.setItem('f50-fullscreen-shape',key); } catch { /* Then fullscreen may renegotiate once more. */ }
}
function storedFullscreenSize() { try { return localStorage.getItem('f50-fullscreen-shape') ?? ''; } catch { return ''; } }
/** A close shape is renegotiated only in fullscreen, and there only once (renegotiate, display-fit.ts): opening
 *  the page or leaving fullscreen shows the current picture stretched (shownSize, never black bars) instead of a
 *  black reconnect right after opening. A clearly different shape (portrait, split screen) is renegotiated at
 *  once, as before (user 2026-10-12, replacing 2026-10-11's reconnect on every window change). */
function autoTarget() {
  const pixels=fastDecoder()?Math.min(2,Math.max(1,window.devicePixelRatio||1)):1;
  return suggestedResolution(screen.clientWidth*pixels,screen.clientHeight*pixels);
}
el<HTMLSelectElement>('codec').value = readFlag('f50-codec') || 'auto';
el<HTMLSelectElement>('codec').onchange=() => { saveFlag('f50-codec', el<HTMLSelectElement>('codec').value); lastAutoTarget=''; scheduleAuto(); };
autoFit.onchange=() => { localStorage.setItem('f50-auto-fit',String(autoFit.checked)); lastAutoTarget=''; render(); scheduleAuto(); };
el<HTMLFormElement>('display-form').onsubmit=event => {
  event.preventDefault();
  const size=autoFit.checked?autoTarget():{width:Number(el<HTMLInputElement>('width').value),height:Number(el<HTMLInputElement>('height').value)};
  if (![size.width,size.height].every(v=>Number.isInteger(v)&&v>=480&&v<=3840&&v%2===0)) { error(t('range')); return; }
  void saveDisplay({...size,fps:Number(el<HTMLSelectElement>('fps').value),uiScale:Number(el<HTMLSelectElement>('ui-scale').value),hevc:wantHevc()});
};
new ResizeObserver(()=>{ fit(); scheduleAuto(); }).observe(screen);
document.addEventListener('visibilitychange',()=>{
  pageEvent(document.hidden ? 1 : 2);
  if (document.hidden) { hiddenAt = performance.now(); if (document.fullscreenElement || wantFullscreen) coveredInFullscreen = true; return; }
  shownAt = performance.now();
  // The picture at once instead of the phone's next keyframe; then the sound.
  if (wantFullscreen && !document.fullscreenElement) restoreArmed = true;   // covered: left fullscreen while hidden
  send({ type:'keyframe' }); fit(); scheduleAuto(); void unlock(); showRestoreHint();
});
/** Straight into the viewer log, not only every 10 s: ev 1 hidden, 2 shown, 3 fullscreen, 4 out of fullscreen, 5 resized. */
function pageEvent(ev: number) {
  send({type:'stats',stats:{ev,hidden:document.hidden?1:0,fullscreen:document.fullscreenElement?1:0,width:screen.clientWidth,height:screen.clientHeight,want:wantFullscreen?1:0,...viewport()}});
}
/** Which page build runs (raised with each build tried in the car). */
const BUILD = 202610141550;
/** What the browser says of the space it gives the page, to find the car's bar over a fullscreen page (2026-10-13):
 *  window, visual viewport (and its offset), screen, available screen, outer window, pixel ratio. */
function viewport(): Record<string, number> {
  const v = window.visualViewport, d = window.screen;
  return { build:BUILD, iw:window.innerWidth, ih:window.innerHeight, vw:Math.round(v?.width ?? -1), vh:Math.round(v?.height ?? -1),
    vt:Math.round(v?.offsetTop ?? -1), sw:d.width, sh:d.height, sah:d.availHeight, oh:window.outerHeight,
    dpr:Math.round(window.devicePixelRatio*100) };
}
/** Every key, wheel and focus move the page receives, by name ("inK<code>", "inWheelUp", "inFocus"), sent within a
 *  second as ev 6: what a car's steering-wheel buttons and scroll wheels reach the browser as (Tesla, 2026-10-14). */
const inputSeen: Record<string, number> = {};
let inputTimer = 0;
function seenInput(name: string) {
  const key = ('in' + name.replace(/[^A-Za-z]/g, '')).slice(0, 24);
  inputSeen[key] = (inputSeen[key] ?? 0) + 1;
  window.clearTimeout(inputTimer);
  inputTimer = window.setTimeout(() => send({type:'stats',stats:{ev:6,...inputSeen}}), 1000);
}
window.addEventListener('keydown', e => seenInput('K' + (e.code || e.key || 'Unknown')), { capture: true });
window.addEventListener('wheel', e => seenInput(Math.abs(e.deltaY) >= Math.abs(e.deltaX)
  ? (e.deltaY < 0 ? 'WheelUp' : 'WheelDown') : (e.deltaX < 0 ? 'WheelLeft' : 'WheelRight')), { capture: true, passive: true });
document.addEventListener('focusin', () => seenInput('Focus'), true);
// ev 5: the window changed size (debounced), with what the browser says of it.
let resizeTimer = 0;
window.addEventListener('resize', () => { window.clearTimeout(resizeTimer); resizeTimer = window.setTimeout(() => pageEvent(5), 400); });
window.setInterval(()=>{
  const now=performance.now(),fps=frames*1000/Math.max(1,now-lastStats);frames=0;lastStats=now;
  el('stats').textContent=painted?`${canvas.width} × ${canvas.height} / ${fps.toFixed(0)} fps / ${t('latency')} ${video.decodeLatencyMs.toFixed(0)} ms`:t('noStream');
  el('audio-unlock').hidden=!active||audio.isUnlocked;
  el('audio-status').textContent=t(audio.isPlaying?'playing':'paused');media.setPlaying(audio.isPlaying);media.tick();
},750);
// Which browser the car runs and the music element's own timeline, which an OS media card may show instead of the song's.
const chromeMajor=Number(/Chrome\/(\d+)/.exec(navigator.userAgent)?.[1] ?? 0),webView=/; wv\)/.test(navigator.userAgent)?1:0;
function musicTimeline(): Record<string, number> {
  const element=document.getElementById('carplay-music') as HTMLAudioElement|null;
  if(!element) return {};
  return {elTime:Math.round(element.currentTime),elDur:Number.isFinite(element.duration)?Math.round(element.duration):-1};
}
// Once a second while CarPlay runs: the pong comes back behind every frame still queued for this page.
window.setInterval(()=>{ if (active) { lag.sent(performance.now()); connection.send({type:'ping'}); } },1000);
window.setInterval(()=>{
  const now=performance.now(),seconds=Math.max(1,(now-reportStart)/1000);
  send({type:'stats',stats:{fps:reportFrames/seconds,decodeMs:video.decodeLatencyMs,queue:video.decodeQueueSize,
    kbps:reportBytes*8/1000/seconds,hidden:document.hidden?1:0,fullscreen:document.fullscreenElement?1:0,
    width:canvas.width,height:canvas.height,...(touchCount?{touchMs:touchSum/touchCount,touches:touchCount}:{}),...(musicBytes?{musicKbps:musicBytes*8/1000/seconds}:{}),
    chrome:chromeMajor,build:BUILD,webView,teslaMode:teslaMode?1:0,promptGain,fastDecoder:fastDecoder()?1:0,hevcDecodes:hevcDecodes?1:0,hevc:display?.hevc?1:0,...microphone.report(),...audio.farReport(),...media.report(),...musicTimeline(),...audio.musicReport(),...video.takeStalls(),...lag.take(performance.now())}});
  judgeDecoder(video.decodeLatencyMs, reportFrames/seconds);
  reportFrames=0;reportBytes=0;reportStart=now;touchSum=0;touchCount=0;musicBytes=0;
},10000);
render();fit();if(token) connection.connect();

nightSelect.onchange = () => { localStorage.setItem('f50-night-mode', nightSelect.value); syncNight(); render(); };
darkQuery.addEventListener('change', () => { syncNight(); render(); });
window.setInterval(() => { syncNight(); if (panel.open) render(); }, 30000);

el('browser-check-show').onclick = () => (window as unknown as { F50BrowserCheck: { show(): void } }).F50BrowserCheck.show();
