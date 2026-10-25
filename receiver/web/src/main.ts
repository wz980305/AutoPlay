import { AudioEngine } from './audio';
import { InputController } from './input';
import { MicrophoneUplink } from './mic';
import { VideoPlayer } from './video';
import { Connection } from './ws';
import { SystemMedia } from './media-session';
import { LagProbe } from './lag';
import { suggestedResolution, areaPlan, areaSize, type Area } from './display-fit';
import { t, language, setLanguage, type Key } from './i18n';
import { isNight, parseNightMode } from './night';
import { reachable, TESLA_HOPS } from './tesla-fullscreen';
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
interface Display { width: number; height: number; fps: number; uiScale: number; hevc: boolean; areas?: Area[]; area?: number; }
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
  el('overlay').hidden = painted || holding;
  el('app').dataset.live = String(painted || holding);
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
  // With view areas the stream is larger than the area in use: the area fills the view from the top left and the
  // rest of the picture lies outside it (areaSize, display-fit.ts).
  const areas = display?.areas ?? [], area = areas.length > 1 ? areas[display?.area ?? 0] : undefined;
  const size = areaSize(canvas.width, canvas.height, area, screen.clientWidth, screen.clientHeight);
  surface.style.width = `${size.width}px`; surface.style.height = `${size.height}px`;
  screen.classList.toggle('area', !!area);
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
  frames++; reportFrames++; painted = true; shownOnce = true; el('overlay').hidden = true; el('app').dataset.live = 'true';
  if (holding) { holding = false; el('toast').hidden = true; }
  if (wokeAt) { lifeEvent(14, { pictureMs: Math.round(performance.now() - wokeAt) }); wokeAt = 0; }
  const now = performance.now();
  if (input.lastDownAt > handledDownAt) {
    handledDownAt = input.lastDownAt;
    if (input.lastDownAt - lastPaintAt >= 150) { touchSum += now - input.lastDownAt; touchCount++; }
  }
  lastPaintAt = now;
}, () => send({ type:'keyframe' }), fit);
// Music over the car's Bluetooth, turned on by the person on the box (found in a Tesla, 2026-10-14; any car paired
// with the iPhone): the steering wheel, media card and volume are the car's own; this page plays prompts (boosted)
// and whatever else the iPhone still sends. ?promptgain=1..8 overrides the boost. Tesla mode sets it too, and adds
// the Tesla browser's ways (fullscreen below, microphone gain in mic.ts).
const boxFlags = window as unknown as { playportCarMusic?: boolean; playportTeslaMode?: boolean };
const carMusic = boxFlags.playportCarMusic === true;
const teslaMode = boxFlags.playportTeslaMode === true;
const promptGain = Number(new URLSearchParams(location.search).get('promptgain')) || (carMusic ? 3 : 1);
// Music the iPhone still sends here is played: it sends music to one place at a time, and after Siri from the
// CarPlay screen it sent it here for ~27 s before going back to the car's Bluetooth, silent while it was dropped.
const audio = new AudioEngine(error, { promptBoost: promptGain, idleClose: carMusic });
/** Music over the car's Bluetooth: the car's media card shows the page's title and address whenever the page sounds
 *  (Siri, prompts, calls; a Tesla, 2026-10-14); name it instead. The last voice stream to start wins; the title goes back when none is left. */
const voiceLabels: Record<string, string> = { speechrecognition: 'Siri', telephony: '通话', default: '导航播报' };
const voices = new Map<number, string>();
function showVoice() {
  const label = Array.from(voices.values()).pop() ?? null;
  document.title = label ? `${label} · DashPlay` : 'DashPlay';
  media.announce(label);
}
function voiceStarted(streamType: number, name: string) {
  if (!carMusic) return;
  voices.delete(streamType);
  if (voiceLabels[name]) voices.set(streamType, voiceLabels[name]);
  showVoice();
}
function voiceStopped(streamType: number) { if (carMusic && voices.delete(streamType)) showVoice(); }
const lag = new LagProbe();
const media = new SystemMedia(send, () => { void audio.unlock().catch(error); }, () => audio.pauseMusic(), carMusic);
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
  onServer(message) { lastHeard = performance.now(); server(message); },
  onBytes(count) { reportBytes += count; lastHeard = performance.now(); },
  onState(value) {
    if (value === 'open' && closedAt) { lifeEvent(11, { downMs: Math.round(performance.now() - closedAt), failures: connection.failures }); closedAt = 0; }
    if (value === 'closed') { if (!closedAt) closedAt = performance.now(); if (!wokeAt) wokeAt = closedAt; reset(shownOnce); state = 'reconnecting'; }
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
/** hold: the link dropped after a picture was shown (the car froze the browser, 2026-10-14). The last picture stays
 *  up with a small notice while the link comes back, instead of the full "connecting" screen. Only time the page is
 *  awake counts towards HOLD_MS (the one-second tick adds it): a wall-clock timer ran on while a Tesla had the page
 *  frozen and cleared the picture the moment it came back, just before the new one arrived. */
const HOLD_MS = 8000;
let holding = false, holdAwakeMs = 0, shownOnce = false;
function reset(hold = false) {
  sentNight = null; lag.reset();
  active = painted = false; input.reset(); canvas.inert = true;
  video.close(); audio.stopAll(); media.setActive(false); void microphone.stop();
  holding = hold; holdAwakeMs = 0;
  if (hold) toast(t('reconnecting'));
  else clearPicture();
}
function clearPicture() { canvas.getContext('2d')?.clearRect(0,0,canvas.width,canvas.height); }
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
let teslaChecking = false;
async function toggleFullscreen() {
  if (teslaMode && !teslaBorderless) {
    if (teslaChecking) return;
    teslaChecking = true;
    try {
      if (await reachable(TESLA_HOPS)) location.href = teslaFullscreenUrl();
      else toast(t('teslaFullscreenOffline'));
    } finally { teslaChecking = false; }
    return;
  }
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
  const plan=areaPlan(display,autoTarget(),wantHevc(),storedShapes());
  if (!plan) return;
  const next=plan.display,key=`${next.width}x${next.height}${next.hevc?'-h265':''}/${(next.areas??[]).map(a=>`${a.width}x${a.height}`).join(',')}/${next.area??0}`;
  if (key===lastAutoTarget) return;
  // Avoid a reconnect loop even when another viewer has a different screen shape.
  lastAutoTarget=key;
  if (!(await saveDisplay(next))) { error(t('autoFail')); return; }
  saveFlag('f50-view-areas', JSON.stringify(plan.shapes));
  fit();
}
/** The window shapes this browser has shown, kept as CarPlay view areas (areaPlan, display-fit.ts): switching
 *  between them (fullscreen in and out, the car's dock, a Tesla's own fullscreen) moves CarPlay to another area
 *  without reconnecting; only a shape seen the first time reconnects, once (2026-10-14, replacing the earlier
 *  "renegotiate a close shape in fullscreen only, once per browser"). */
function storedShapes(): Area[] {
  try { const value = JSON.parse(readFlag('f50-view-areas') || '[]'); return Array.isArray(value) ? value.filter(a => Number.isInteger(a?.width) && Number.isInteger(a?.height)) : []; }
  catch { return []; }
}
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
  connection.send({type:'stats',stats:{ev,hidden:document.hidden?1:0,fullscreen:document.fullscreenElement?1:0,width:screen.clientWidth,height:screen.clientHeight,want:wantFullscreen?1:0,...viewport()}});
}
/** Which page build runs (raised with each build tried in the car). */
const BUILD = 202610142250;
/** What the browser says of the space it gives the page, to find the car's bar over a fullscreen page (2026-10-13):
 *  window, visual viewport (and its offset), screen, available screen, outer window, pixel ratio. */
function viewport(): Record<string, number> {
  const v = window.visualViewport, d = window.screen;
  return { build:BUILD, iw:window.innerWidth, ih:window.innerHeight, vw:Math.round(v?.width ?? -1), vh:Math.round(v?.height ?? -1),
    vt:Math.round(v?.offsetTop ?? -1), sw:d.width, sh:d.height, sah:d.availHeight, oh:window.outerHeight,
    dpr:Math.round(window.devicePixelRatio*100) };
}
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
/** Coming back after the car froze the browser (a Tesla away from it: reverse gear, another app; 2026-10-14). The
 *  iPhone's CarPlay never stopped; only this page's link to the box may have. On a sign of coming back (a one-second
 *  tick over 2.5 s late, the page shown again, "resume", the network back) the page asks on its link first: the box
 *  keeps a silent page's link for 10 minutes with its sound held back, and an answer within PROBE_MS means a
 *  keyframe and the picture go on over it (21 ms to the first picture in the car). Without an answer a new link
 *  replaces it (the box drops the old one by this page's id). A reload, which loses the sound's unlock, only as the
 *  last resort: no link for RELOAD_AFTER_MS while the box answers. The last picture stays up meanwhile (reset, hold).
 *  A Tesla also leaves its Wi-Fi out of Park unless "Remain connected in Drive" is on: then the link comes back on
 *  "online". Viewer log: ev 8 frozen (gapMs), 11 link open again (downMs), 12 reloading, 13 back (how: 1 same link,
 *  2 new link, 3 network back), 14 first picture (pictureMs since waking). */
const PROBE_MS = 600, RELOAD_AFTER_MS = 15000;
let lastTick = performance.now(), lastHeard = performance.now(), revived = 0, hiddenMeanwhile = document.hidden;
let reloading = false, closedAt = 0, lifecycle: Record<string, number> = {}, probing = 0, wokeAt = 0;
/** Straight into the viewer log whenever the link is open (also before CarPlay runs), else with the next open. */
function lifeEvent(ev: number, data: Record<string, number> = {}) {
  lifecycle = { ...lifecycle, ev, ...data };
  if (connection.send({ type:'stats', stats: lifecycle })) lifecycle = {};
}
function revive() { revived++; lastHeard = performance.now(); connection.restart(); }
function wake(why: number) {
  if (!token || probing || reloading) return;
  const asked = performance.now();
  if (asked - lastHeard < 1500) return;   // the box was heard just now: nothing was frozen
  wokeAt = asked;
  if (!connection.isOpen) { revive(); lifeEvent(13, { how: 2, why }); return; }   // no link to ask on
  probing = window.setTimeout(() => {
    probing = 0;
    if (lastHeard > asked) { lifeEvent(13, { how: 1, why, ms: Math.round(lastHeard - asked) }); send({ type:'keyframe' }); return; }
    revive();
    lifeEvent(13, { how: 2, why });
  }, PROBE_MS);
  connection.send({ type:'ping' });
  connection.send({ type:'keyframe' });
}
/** The last resort: a reload, as a refresh by hand always came back, while the box answers (a reload while the box
 *  restarts would leave the browser's own error page). */
function reloadWhenBoxAnswers() {
  if (reloading) return;
  reloading = true;
  lifeEvent(12);
  void fetch('./receiver-access.json', { cache: 'no-store' }).then(r => { if (r.ok) location.reload(); else reloading = false; })
    .catch(() => { reloading = false; });
}
// A hidden page's timers are slowed on purpose (the XPeng's reverse camera hides the page, and its link lives on):
// lateness then is no freeze.
document.addEventListener('visibilitychange', () => { if (document.hidden) hiddenMeanwhile = true; else wake(4); });
document.addEventListener('resume', () => wake(6));
window.addEventListener('online', () => { if (token && !connection.isOpen) { lifeEvent(13, { how: 3 }); revive(); } });
window.setInterval(() => {
  const now = performance.now(), gap = now - lastTick, late = gap > 2500 && !hiddenMeanwhile;
  lastTick = now; hiddenMeanwhile = document.hidden;
  if (!token) return;
  if (holding && !late) { holdAwakeMs += Math.min(gap, 1000); if (holdAwakeMs > HOLD_MS) { holding = false; clearPicture(); render(); } }
  if (late) { lifeEvent(8, { gapMs: Math.round(gap) }); wake(1); }
  else if (active && !document.hidden && now - lastHeard > 8000) revive();   // the link died while in view
  else if (!document.hidden && closedAt && now - closedAt > RELOAD_AFTER_MS) reloadWhenBoxAnswers();
}, 1000);
window.setInterval(()=>{
  const now=performance.now(),seconds=Math.max(1,(now-reportStart)/1000);
  send({type:'stats',stats:{fps:reportFrames/seconds,decodeMs:video.decodeLatencyMs,queue:video.decodeQueueSize,
    kbps:reportBytes*8/1000/seconds,hidden:document.hidden?1:0,fullscreen:document.fullscreenElement?1:0,
    width:canvas.width,height:canvas.height,...(touchCount?{touchMs:touchSum/touchCount,touches:touchCount}:{}),...(musicBytes?{musicKbps:musicBytes*8/1000/seconds}:{}),
    chrome:chromeMajor,build:BUILD,webView,carMusic:carMusic?1:0,teslaMode:teslaMode?1:0,promptGain,...(revived?{revived}:{}),fastDecoder:fastDecoder()?1:0,hevcDecodes:hevcDecodes?1:0,hevc:display?.hevc?1:0,...microphone.report(),...audio.farReport(),...media.report(),...musicTimeline(),...audio.musicReport(),...video.takeStalls(),...lag.take(performance.now())}});
  judgeDecoder(video.decodeLatencyMs, reportFrames/seconds);
  reportFrames=0;reportBytes=0;reportStart=now;touchSum=0;touchCount=0;musicBytes=0;
},10000);
render();fit();if(token) connection.connect();

nightSelect.onchange = () => { localStorage.setItem('f50-night-mode', nightSelect.value); syncNight(); render(); };
darkQuery.addEventListener('change', () => { syncNight(); render(); });
window.setInterval(() => { syncNight(); if (panel.open) render(); }, 30000);

el('browser-check-show').onclick = () => (window as unknown as { F50BrowserCheck: { show(): void } }).F50BrowserCheck.show();
