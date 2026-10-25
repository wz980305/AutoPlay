import { startup, startupStats } from './startup';
import { AudioEngine } from './audio';
import { InputController } from './input';
import { MicrophoneUplink } from './mic';
import { VideoPlayer } from './video';
import { Connection } from './ws';
import { SystemMedia } from './media-session';
import { LagProbe } from './lag';
import { suggestedResolution, windowShape, areaPlan, areaSize, areaFor, sameStream, showsShape, frameRateCheck, type Area } from './display-fit';
import { t, language, setLanguage, type Key } from './i18n';
import { isNight, parseNightMode } from './night';
import { reachable, TESLA_HOPS } from './tesla-fullscreen';
import { hudLines } from './debug-hud';
import { compatDisplayOn } from './compat-display';
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
// The same, per second, for the debug overlay (debug-hud.ts).
let hudFrames = 0, hudBytes = 0, hudMusicBytes = 0, hudStart = performance.now();
let state: Key = token ? 'connecting' : 'access';
let hint: Key = token ? 'waitingHint' : 'accessHint';
let lastAutoTarget = '', autoTimer = 0, displayBusy = false;
/** A change that cannot wait for the next session (codec failed, a setting changed by hand): why, for the box's log. */
let urgentChange = '';
/** This page asked for a renegotiation: keep the layout of the picture on screen until the new one comes. */
let expectRestart = false, expectTimer = 0;
interface Display { width: number; height: number; fps: number; uiScale: number; hevc: boolean; areas?: Area[]; area?: number; pending?: boolean; }
let display: Display | null = null;
const customSize = el<HTMLInputElement>('custom-size');
// Off (the default) follows the window; on keeps the typed width and height.
customSize.checked = localStorage.getItem('f50-auto-fit') === 'false';
const autoFitOn = () => !customSize.checked;
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
  el<HTMLInputElement>('width').disabled = !customSize.checked;
  el<HTMLInputElement>('height').disabled = !customSize.checked;
  el('size-row').hidden = !customSize.checked;
  document.querySelectorAll<HTMLButtonElement>('[data-command]').forEach(b => { b.disabled = !active; });
  const night = isNight(parseNightMode(nightSelect.value), new Date(), darkQuery.matches);
  el('night-status').textContent = `${t('nightNow')}${t(night ? 'nightOn' : 'nightOff')}`;
  el('night-status').title = t(darkQuery.matches ? 'browserDark' : 'browserLight');
}
function fit() {
  // While CarPlay renegotiates, the last picture stays laid out as it was (the new areas belong to the next stream).
  if (expectRestart || (holding && holdForDisplay)) return;
  // With view areas the stream is larger than the area in use: the area fills the view from the top left and the
  // rest of the picture lies outside it (areaSize, display-fit.ts).
  // The area's share of the stream as declared: a stream decoded at another size than declared (a canvas scaled for
  // the old UI size, 2026-10-22) cut the area's right and bottom off when measured against the decoded size.
  const areas = display?.areas ?? [], area = areas.length > 1 ? areas[display?.area ?? 0] : undefined;
  const size = area && display ? areaSize(display.width, display.height, area, screen.clientWidth, screen.clientHeight)
    : areaSize(canvas.width, canvas.height, undefined, screen.clientWidth, screen.clientHeight);
  surface.style.width = `${size.width}px`; surface.style.height = `${size.height}px`;
  screen.classList.toggle('area', !!area);
}
function error(message: string) {
  // This browser said it decodes H.265 but cannot: auto goes back to H.264 for good (on this browser).
  if (message.includes('H.265/HEVC')) { saveFlag('f50-hevc-failed', '1'); lastAutoTarget = ''; urgentChange = 'codec'; scheduleAuto(); }
  el('error-text').textContent = message; el('error-banner').hidden = !message;
}
/** Auto quality (2026-10-14; a Tesla decodes a frame in ~1 ms, the XPeng in 60-100 ms): once this browser has
 *  shown it decodes fast (f50-fast-decoder, from the 10 s reports), auto picks the resolution from the screen's real
 *  pixels (CSS size x device pixel ratio, long side 1280-2560) and H.265 when the browser decodes it; a slow decoder
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
/** Automatic display only, once per browser: 60 fps chosen again by hand afterwards stays. */
let behindRun = 0;
function judgeFrameRate(caughtUp: number) {
  const check = frameRateCheck(behindRun, caughtUp, display?.fps ?? 0); behindRun = check.run;
  if (!check.lower || !display || !autoFitOn() || displayBusy || readFlag('f50-fps-lowered') === '1') return;
  saveFlag('f50-fps-lowered', '1'); toast(t('fpsLowered'));
  void saveDisplay({ ...display, fps: 30 }, { reason: 'decoder' });
}
function send(message: ClientMessage) { if (active) connection.send(message); }
// Compatible display (compat-display.ts): automatic by the browser's version, or the switch in Display; chosen once
// per page, since a canvas keeps the kind it was made with (the switch reloads the page).
const compatDisplay = compatDisplayOn(readFlag('f50-compat-display'), navigator.userAgent);
const video = new VideoPlayer(canvas, error, () => {
  if (!active) return;
  if (!shownOnce) { startup.mark('firstFrameMs'); connection.send({type:'stats', stats:{ev:16,...startupStats()}}); }
  frames++; reportFrames++; hudFrames++; painted = true; shownOnce = true; el('overlay').hidden = true; el('app').dataset.live = 'true';
  if (holding) { holding = false; el('toast').hidden = true; fit(); }
  if (wokeAt) { lifeEvent(14, { pictureMs: Math.round(performance.now() - wokeAt) }); wokeAt = 0; }
  const now = performance.now();
  if (input.lastDownAt > handledDownAt) {
    handledDownAt = input.lastDownAt;
    if (input.lastDownAt - lastPaintAt >= 150) { touchSum += now - input.lastDownAt; touchCount++; }
  }
  lastPaintAt = now;
}, () => send({ type:'keyframe' }), fit, compatDisplay);
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
  onTiming(stats) { connection.send({type:'stats', stats:{ev:16,...stats}}); },
  onWire(message) {
    switch (message.kind) {
      case 'video-config': video.configure(message); break;
      case 'video-frame': video.pushFrame(message); break;
      case 'audio-config': audio.handleConfig(message); voiceStarted(message.streamType, message.name); break;
      case 'audio-packet': if (message.streamType === 102) { musicBytes += message.data.length; hudMusicBytes += message.data.length; } audio.handlePacket(message); break;
      case 'audio-stopped': audio.stopStream(message.streamType); voiceStopped(message.streamType); break;
    }
  },
  onServer(message) { lastHeard = performance.now(); server(message); },
  onBytes(count) { reportBytes += count; hudBytes += count; lastHeard = performance.now(); },
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
/** A renegotiation for a new display (2026-10-21): the iPhone comes back in 5-6 s on Wi-Fi, ~10 s on the cable; the
 *  last picture stays up with a notice instead of the black "waiting for iPhone" screen. */
const DISPLAY_HOLD_MS = 20000;
let holding = false, holdAwakeMs = 0, holdForDisplay = false, shownOnce = false;
function reset(hold = false, forDisplay = false) {
  sentNight = null; lag.reset();
  active = painted = false; input.reset(); canvas.inert = true;
  video.close(); audio.stopAll(); media.setActive(false); void microphone.stop();
  holding = hold; holdAwakeMs = 0; holdForDisplay = forDisplay;
  if (hold) toast(t(forDisplay ? 'adjusting' : 'reconnecting'));
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
  if (!message.sessionActive) {
    // Ended to apply a new display (by this page or another): the phone comes straight back, keep the picture.
    const forDisplay = message.restarting === true || expectRestart;
    endExpectRestart(); reset(forDisplay && (painted || holding), forDisplay); state = 'waiting';
  }
  else { endExpectRestart(); void loadDisplay(); active = true; canvas.inert = false; state = 'starting'; media.setActive(true); syncNight(); if(message.nowPlaying) media.setMetadata(message.nowPlaying); if(message.artwork) media.setArtwork(message.revision ?? 0,message.artwork); }
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
/** Where the button over the live picture sits, or none: it may cover a CarPlay button (a music app's search,
 *  2026-10-19). Kept in this browser; fullscreen stays in Settings either way. */
const fullscreenPlace = el<HTMLSelectElement>('fullscreen-button');
fullscreenPlace.value = ['bottom', 'off'].includes(readFlag('f50-fullscreen-button')) ? readFlag('f50-fullscreen-button') : 'top';
el('btn-fullscreen').dataset.place = fullscreenPlace.value;
fullscreenPlace.onchange = () => { saveFlag('f50-fullscreen-button', fullscreenPlace.value); el('btn-fullscreen').dataset.place = fullscreenPlace.value; };
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
/** The box's display as it is now: another page may have changed it (it sent back that page's fps, 2026-10-16). */
async function fetchDisplay(): Promise<Display | null> {
  try { const r = await fetch('/api/display', { cache: 'no-store' }); return r.ok ? await r.json() as Display : null; }
  catch { return null; }
}
async function loadDisplay() {
  if (displayBusy || !token) return;
  el('display-status').textContent = t('loading');
  const loaded = await fetchDisplay();
  if (!loaded) { el('display-status').textContent = t('loadFail'); return; }
  display = loaded; showDisplay(); fit(); scheduleAuto();
}
function showDisplay() {
  if (!display) return;
  el<HTMLInputElement>('width').value = String(display.width); el<HTMLInputElement>('height').value = String(display.height);
  el<HTMLSelectElement>('fps').value = String(display.fps); el<HTMLSelectElement>('ui-scale').value = String(display.uiScale);
  el('display-status').dataset.codec = display.hevc ? 'H.265' : 'H.264';
  el('display-status').textContent = `${display.width} × ${display.height} / ${display.fps} fps / ${display.hevc ? 'H.265' : 'H.264'}${display.pending ? ` · ${t('nextSession')}` : ''}`;
}
function endExpectRestart() { expectRestart = false; window.clearTimeout(expectTimer); }
/** defer: a sharper picture or another codec for shapes the phone already has; the box keeps it for the next session. */
async function saveDisplay(target: Display, how: { defer?: boolean; reason: string }): Promise<boolean> {
  if (displayBusy || !token) return false;
  displayBusy = true; el<HTMLButtonElement>('apply').disabled = true; el<HTMLFieldSetElement>('display-fields').disabled = true;
  el('display-status').textContent = t('applying');
  // A renegotiation is coming: hold the layout from now, the session's end may arrive before this answer.
  const restart = active && !how.defer && (!display || !sameStream(display, target));
  if (restart) { expectRestart = true; window.clearTimeout(expectTimer); expectTimer = window.setTimeout(() => { endExpectRestart(); fit(); }, DISPLAY_HOLD_MS); }
  try {
    const r = await fetch(`/api/display?token=${encodeURIComponent(token)}`, { method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ ...target, defer: how.defer === true, reason: how.reason }) });
    const body = await r.json() as {ok?:boolean; deferred?:boolean}; if (!r.ok || !body.ok) throw new Error();
    if (body.deferred) { if (display) display.pending = true; el('display-status').textContent = t('deferred'); return true; }
    display = { ...target, pending: false }; el('display-status').textContent = t('applied'); return true;
  } catch { if (restart) { endExpectRestart(); fit(); } el('display-status').textContent = t('applyFail'); return false; }
  finally { displayBusy=false; el<HTMLButtonElement>('apply').disabled=false; el<HTMLFieldSetElement>('display-fields').disabled=false; render(); }
}
function scheduleAuto() {
  window.clearTimeout(autoTimer);
  if (!autoFitOn() || !display || displayBusy || document.hidden || typeof VideoDecoder === 'undefined') return;
  autoTimer=window.setTimeout(() => { void adapt(); },1500);
}
async function adapt() {
  // Not for a hidden page (a covered page reports a small window) nor while fullscreen waits for its tap; a timer
  // set just before the car covered the page fired anyway and renegotiated to 800x400 (Chrome, 2026-10-12).
  const busy = () => !display || !autoFitOn() || displayBusy || document.hidden || (wantFullscreen && !document.fullscreenElement);
  if (busy()) return;
  // From the box's own, not what this page last saw: fps and size set by another page are kept, not sent back.
  const current = await fetchDisplay();
  if (current && !expectRestart && !holding) { display = current; showDisplay(); }
  if (busy() || !display) return;
  const urgent = urgentChange; urgentChange = '';
  const target=autoTarget(), plan=areaPlan(display,target,wantHevc(),storedShapes(),fastDecoder()?2560:1920);
  if (!plan) return;
  const next=plan.display,key=`${next.width}x${next.height}${next.hevc?'-h265':''}/${(next.areas??[]).map(a=>`${a.width}x${a.height}`).join(',')}/${next.area??0}`;
  if (key===lastAutoTarget) return;
  // Avoid a reconnect loop even when another viewer has a different screen shape.
  lastAutoTarget=key;
  // A shape the phone has (only sharper, or another codec as this browser proved fast or slow) waits for the session to
  // end; a new shape, the other orientation, a codec that failed or a change by hand renegotiates now.
  const waits = !urgent && showsShape(display, target);
  const reason = urgent || (waits ? 'quality' : 'shape');
  // What waits is for the next session; the window's shape is shown now, by switching to its declared area.
  const now = waits ? areaFor(display, target) : -1;
  if (now >= 0 && now !== (display.area ?? 0) && !(await saveDisplay({ ...display, area: now }, { reason: 'area' }))) { error(t('autoFail')); return; }
  if (!(await saveDisplay(next, { defer: waits, reason }))) { error(t('autoFail')); return; }
  saveFlag(SHAPES_KEY, JSON.stringify(plan.shapes));
  fit();
}
/** The window shapes this browser has shown, kept as CarPlay view areas (areaPlan, display-fit.ts): switching
 *  between them (fullscreen in and out, the car's dock, a Tesla's own fullscreen) moves CarPlay to another area
 *  without reconnecting; only a shape seen the first time reconnects, once (2026-10-14, replacing the earlier
 *  "renegotiate a close shape in fullscreen only, once per browser"). */
/** Shapes as windowShape gives them since 2026-10-22; the earlier key held each shape fitted on its own, learned anew. */
const SHAPES_KEY = 'f50-window-shapes';
function storedShapes(): Area[] {
  try { const value = JSON.parse(readFlag(SHAPES_KEY) || '[]'); return Array.isArray(value) ? value.filter(a => Number.isInteger(a?.width) && Number.isInteger(a?.height)) : []; }
  catch { return []; }
}
/** This window's shape (windowShape, display-fit.ts): areaPlan fits it, with the others remembered, to the stream. */
function autoTarget() {
  const pixels=fastDecoder()?Math.min(2,Math.max(1,window.devicePixelRatio||1)):1;
  return windowShape(screen.clientWidth,screen.clientHeight,pixels);
}
el<HTMLSelectElement>('codec').value = readFlag('f50-codec') || 'auto';
el<HTMLSelectElement>('codec').onchange=() => { saveFlag('f50-codec', el<HTMLSelectElement>('codec').value); lastAutoTarget=''; urgentChange='manual'; scheduleAuto(); };
customSize.onchange=() => { localStorage.setItem('f50-auto-fit',String(!customSize.checked)); lastAutoTarget=''; urgentChange='manual'; render(); scheduleAuto(); };
el<HTMLFormElement>('display-form').onsubmit=event => {
  event.preventDefault();
  // Automatic display keeps the box's stream and its areas, changing only frame rate, size or codec: sent without the
  // areas, the largest window then showed less (2026-10-22).
  const size:Pick<Display,'width'|'height'|'areas'|'area'>=autoFitOn()?(display?{width:display.width,height:display.height,areas:display.areas,area:display.area}:suggestedResolution(autoTarget().width,autoTarget().height,fastDecoder()?2560:1920))
    :{width:Number(el<HTMLInputElement>('width').value),height:Number(el<HTMLInputElement>('height').value)};
  if (![size.width,size.height].every(v=>Number.isInteger(v)&&v>=480&&v<=3840&&v%2===0)) { error(t('range')); return; }
  void saveDisplay({...size,fps:Number(el<HTMLSelectElement>('fps').value),uiScale:Number(el<HTMLSelectElement>('ui-scale').value),hevc:wantHevc()},{reason:'manual'});
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
const BUILD = 202610221200;
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
  if (holding && !late) { holdAwakeMs += Math.min(gap, 1000); if (holdAwakeMs > (holdForDisplay ? DISPLAY_HOLD_MS : HOLD_MS)) { holding = false; el('toast').hidden = true; clearPicture(); fit(); render(); } }
  if (late) { lifeEvent(8, { gapMs: Math.round(gap) }); wake(1); }
  else if (active && !document.hidden && now - lastHeard > 8000) revive();   // the link died while in view
  else if (!document.hidden && closedAt && now - closedAt > RELOAD_AFTER_MS) reloadWhenBoxAnswers();
}, 1000);
window.setInterval(()=>{
  const now=performance.now(),seconds=Math.max(1,(now-reportStart)/1000),stalls=video.takeStalls();
  send({type:'stats',stats:{fps:reportFrames/seconds,decodeMs:video.decodeLatencyMs,queue:video.decodeQueueSize,
    kbps:reportBytes*8/1000/seconds,hidden:document.hidden?1:0,fullscreen:document.fullscreenElement?1:0,
    width:canvas.width,height:canvas.height,...(touchCount?{touchMs:touchSum/touchCount,touches:touchCount}:{}),...(musicBytes?{musicKbps:musicBytes*8/1000/seconds}:{}),
    ...startupStats(),chrome:chromeMajor,compat:compatDisplay?1:0,build:BUILD,webView,carMusic:carMusic?1:0,teslaMode:teslaMode?1:0,promptGain,...(revived?{revived}:{}),fastDecoder:fastDecoder()?1:0,hevcDecodes:hevcDecodes?1:0,hevc:display?.hevc?1:0,...microphone.report(),...audio.farReport(),...media.report(),...musicTimeline(),...audio.musicReport(),...stalls,...lag.take(performance.now())}});
  judgeDecoder(video.decodeLatencyMs, reportFrames/seconds);
  if (active) judgeFrameRate(stalls.caughtUp);
  reportFrames=0;reportBytes=0;reportStart=now;touchSum=0;touchCount=0;musicBytes=0;
},10000);
// Debug overlay: off unless turned on in Display (kept in this browser); nothing is counted differently while it is off.
const hud = el('debug-hud'), hudSwitch = el<HTMLInputElement>('debug-hud-on');
hudSwitch.checked = readFlag('f50-debug-hud') === '1';
hudSwitch.onchange = () => { saveFlag('f50-debug-hud', hudSwitch.checked ? '1' : '0'); hud.hidden = !hudSwitch.checked; updateHud(); };
hud.hidden = !hudSwitch.checked;
const compatSwitch = el<HTMLInputElement>('compat-display-on');
compatSwitch.checked = compatDisplay;
compatSwitch.onchange = () => { saveFlag('f50-compat-display', compatSwitch.checked ? '1' : '0'); location.reload(); };
function updateHud() {
  const now = performance.now(), seconds = Math.max(0.25, (now - hudStart) / 1000);
  if (!hud.hidden) hud.textContent = hudLines({ width: painted ? canvas.width : 0, height: canvas.height, fps: hudFrames / seconds,
    hevc: display ? display.hevc : null, videoKbps: hudBytes * 8 / 1000 / seconds, decodeMs: video.decodeLatencyMs,
    queue: video.decodeQueueSize, rttMs: lag.last, audio: audio.describe(), musicKbps: hudMusicBytes * 8 / 1000 / seconds,
    playing: audio.isPlaying }, language === 'zh').join('\n');
  hudFrames = 0; hudBytes = 0; hudMusicBytes = 0; hudStart = now;
}
window.setInterval(updateHud, 1000);
render();fit();if(token) connection.connect();

nightSelect.onchange = () => { localStorage.setItem('f50-night-mode', nightSelect.value); syncNight(); render(); };
darkQuery.addEventListener('change', () => { syncNight(); render(); });
window.setInterval(() => { syncNight(); if (panel.open) render(); }, 30000);

el('browser-check-show').onclick = () => (window as unknown as { F50BrowserCheck: { show(): void } }).F50BrowserCheck.show();
