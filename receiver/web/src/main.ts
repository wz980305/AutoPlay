import { startup, startupStats } from './startup';
import { AudioEngine } from './audio';
import { InputController } from './input';
import { VideoPlayer } from './video';
import { Connection } from './ws';
import { LagProbe } from './lag';
import { suggestedResolution, windowResolution, areaSize, sameStream, frameRateCheck, type Area } from './display-fit';
import { CAR_MUSIC, TESLA, PROMPT_BOOST } from './flags';
import { statusHint } from './status';
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
/** A stream this page plays (type 100/101/102) arrived since the page loaded: only then is a locked AudioContext worth
 *  the "tap anywhere" bar (V7): a car that routes every sound over its Bluetooth never sees one. A reload starts over. */
let audioSeen = false;
// The same, per second, for the debug overlay (debug-hud.ts).
let hudFrames = 0, hudBytes = 0, hudMusicBytes = 0, hudStart = performance.now();
/** The page's state (viewer audit V3): the status line is t(state) and the hint under it is hintFor(), a function of
 *  the state (the old one was chosen once at load and said "add your iPhone" under "the box is not answering"). */
let state: Key = token ? 'connecting' : 'access';
/** When the link to the box went down (or the page started without one), for the elapsed time in the hint. */
let linkDownAt = performance.now();
function hintFor(): string {
  const hint = statusHint(state, (performance.now() - linkDownAt) / 1000);
  if (!hint.key) return '';
  return t(hint.key as Key) + (hint.seconds === null ? '' : ` · ${t('waited')}${hint.seconds}${t('secondsUnit')}`);
}
let lastAutoTarget = '', autoTimer = 0, displayBusy = false;
/** A change that cannot wait for the next session (codec failed, a setting changed by hand): why, for the box's log. */
let urgentChange = '';
/** This page asked for a renegotiation: keep the layout of the picture on screen until the new one comes. */
let expectRestart = false, expectTimer = 0;
interface Display { width: number; height: number; fps: number; uiScale: number; hevc: boolean; areas?: Area[]; area?: number; pending?: boolean; }
let display: Display | null = null;
/** Performance mode: upsize each window to the sharpest size (long side at least 1280), then shrink it into the
 *  window. Off (the Tesla default, 2026-10-26: the F50 and the iPhone run cooler, and a Tesla's panel is dense enough
 *  at the window's own pixels): the window's own size (minimum width 720). 2026-10-23, in Advanced. */
const performanceMode = el<HTMLInputElement>('performance-mode');
performanceMode.checked = readFlag('f50-performance-mode') === '1';
/** The 2560 long side (a 2.5K screen's own pixels) only when this browser proved fast AND the owner allowed it in
 *  Advanced (f50-allow-2560): a Tesla's borderless page at 1.53 is 1922 px wide anyway, and an MCU2 (Atom) Tesla
 *  must never be sent 2560 (hardware review H1). */
const allow2560 = el<HTMLInputElement>('allow-2560');
allow2560.checked = readFlag('f50-allow-2560') === '1';
allow2560.onchange = () => { saveFlag('f50-allow-2560', allow2560.checked ? '1' : '0'); lastAutoTarget = ''; urgentChange = 'manual'; scheduleAuto(); };
const performanceOn = () => performanceMode.checked;
const nightSelect = el<HTMLSelectElement>('night-mode');
nightSelect.value = parseNightMode(localStorage.getItem('f50-night-mode'));
const darkQuery = matchMedia('(prefers-color-scheme: dark)');
let sentNight: boolean | null = null;
const volume = el<HTMLInputElement>('volume');
volume.value = String(Math.min(100, Math.max(0, Number(localStorage.getItem('playport-master') ?? 100) || 0)));

/** Box settings page (pairing, hotspot), when the device startup announced one: same host, plain HTTP. */
const boxPort = Number((window as unknown as { playportBoxSettingsPort?: number }).playportBoxSettingsPort) || 0;
/** audio_route_navigation (boot.ts): false = the receiver offers the iPhone no audio, every sound is on the Tesla's
 *  Bluetooth and this page keeps its audio output closed and its sound controls hidden (docs/AUDIO.md). */
const pageAudio = (window as unknown as { playportPageAudio?: boolean }).playportPageAudio !== false;
if (boxPort) for (const id of ['box-link', 'box-link-panel']) {
  const link = el<HTMLAnchorElement>(id);
  link.href = `http://${location.hostname}${boxPort === 80 ? '' : `:${boxPort}`}/`;
  link.hidden = false;
}
function render() {
  setLanguage(language);
  showVoice();
  updateFullscreen();
  el<HTMLSelectElement>('language').value = language;
  el('app').dataset.state = state;
  volume.setAttribute('aria-label', t('volume'));
  el('audio-status').textContent = t(audio.isPlaying ? 'playing' : 'paused');
  el('connection-text').textContent = t(state);
  el('connection-hint').textContent = hintFor();
  // The box's own page is no help while the box itself does not answer.
  if (boxPort) el('box-link').hidden = !statusHint(state, 0).boxLink;
  el('overlay').hidden = painted || holding;
  el('app').dataset.live = String(painted || holding);
  el('capabilities').textContent = !isSecureContext ? t('insecure') : typeof VideoDecoder === 'undefined' || typeof AudioDecoder === 'undefined' ? t('unsupported') : t('compatible');
  document.querySelectorAll<HTMLButtonElement>('[data-command]').forEach(b => { b.disabled = !active; });
  const night = isNight(parseNightMode(nightSelect.value), new Date(), darkQuery.matches);
  el('night-status').textContent = `${t('nightNow')}${t(night ? 'nightOn' : 'nightOff')}`;
  el('night-schedule-hint').hidden = nightSelect.value !== 'schedule';
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
  if (!check.lower || !display || displayBusy || readFlag('f50-fps-lowered') === '1') return;
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
  if (holding) { holding = false; hideRecovering(); fit(); }
  if (wokeAt) { lifeEvent(14, { pictureMs: Math.round(performance.now() - wokeAt) }); wokeAt = 0; }
  const now = performance.now();
  if (input.lastDownAt > handledDownAt) {
    handledDownAt = input.lastDownAt;
    if (input.lastDownAt - lastPaintAt >= 150) { touchSum += now - input.lastDownAt; touchCount++; }
  }
  lastPaintAt = now;
}, () => send({ type:'keyframe' }), fit, compatDisplay);
// Music over the car's Bluetooth (CAR_MUSIC, flags.ts; found in a Tesla, 2026-10-14): the steering wheel, media card
// and volume are the car's own; this page plays prompts (boosted). ?promptgain=1..8 overrides the boost. Music the
// iPhone still sends here (~27 s after Siri) is dropped and the driver told once (1.1.0; a moving Tesla answers a
// page playing music with its "video is audio-only" banner, whose resize renegotiated CarPlay every ~10 s upstream).
const carMusic = CAR_MUSIC;
const promptGain = Math.min(8, Math.max(1, Number(new URLSearchParams(location.search).get('promptgain')) || PROMPT_BOOST));
const audio = new AudioEngine(error, { promptBoost: promptGain, idleClose: carMusic, onDroppedMusic: () => toast(t('musicDropped')) });
/** Music over the car's Bluetooth: the car's media card shows the page's title and address whenever the page sounds
 *  (Siri, prompts; a Tesla, 2026-10-14); name it instead. The last voice stream to start wins; the title goes back when none is left. */
const voiceLabels: Record<string, Key> = { speechrecognition: 'voiceSiri', telephony: 'voiceCall', default: 'voicePrompt' };
const voices = new Map<number, Key>();
function showVoice() {
  const label = Array.from(voices.values()).pop() ?? null;
  document.title = label ? `${t(label)} · ${t('brand')}` : t('brand');
}
function voiceStarted(streamType: number, name: string) {
  if (!carMusic) return;
  voices.delete(streamType);
  if (voiceLabels[name]) voices.set(streamType, voiceLabels[name]);
  showVoice();
}
function voiceStopped(streamType: number) { if (carMusic && voices.delete(streamType)) showVoice(); }
const lag = new LagProbe();
const connection = new Connection(token, {
  onTiming(stats) { connection.send({type:'stats', stats:{ev:16,...stats}}); },
  onWire(message) {
    switch (message.kind) {
      case 'video-config': video.configure(message); break;
      case 'video-frame': video.pushFrame(message); break;
      case 'audio-config': audioSeen = true; audio.handleConfig(message); voiceStarted(message.streamType, message.name); break;
      case 'audio-packet': if (message.streamType === 102) { musicBytes += message.data.length; hudMusicBytes += message.data.length; } audio.handlePacket(message); break;
      case 'audio-stopped': audio.stopStream(message.streamType); voiceStopped(message.streamType); break;
    }
  },
  onServer(message) { lastHeard = performance.now(); server(message); },
  onBytes(count) { reportBytes += count; hudBytes += count; lastHeard = performance.now(); },
  onState(value) {
    if (value === 'open' && closedAt) { lifeEvent(11, { downMs: Math.round(performance.now() - closedAt), failures: connection.failures }); closedAt = 0; }
    if (value === 'closed') { if (!closedAt) { closedAt = performance.now(); linkDownAt = closedAt; } if (!wokeAt) wokeAt = closedAt; reset(shownOnce); state = 'reconnecting'; }
    else if (value === 'connecting') { if (state !== 'reconnecting') state = 'connecting'; }
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
 *  up, veiled and with one persistent notice (#recovering: "link lost, reconnecting, touch paused"), while the link
 *  comes back, instead of the full "connecting" screen; the notice goes with a cross-fade on the first new frame. Only
 *  time the page is awake counts towards HOLD_MS (the one-second tick adds it): a wall-clock timer ran on while a
 *  Tesla had the page frozen and cleared the picture the moment it came back, just before the new one arrived. */
const HOLD_MS = 8000;
/** A renegotiation for a new display (2026-10-21): the iPhone comes back in 5-6 s on Wi-Fi, ~10 s on the cable; the
 *  last picture stays up with a notice instead of the black "waiting for iPhone" screen. */
const DISPLAY_HOLD_MS = 20000;
let holding = false, holdAwakeMs = 0, holdForDisplay = false, shownOnce = false;
function reset(hold = false, forDisplay = false) {
  sentNight = null; lag.reset();
  active = painted = false; input.reset(); canvas.inert = true;
  video.close(); audio.stopAll();
  holding = hold; holdAwakeMs = 0; holdForDisplay = forDisplay;
  if (hold) showRecovering(t(forDisplay ? 'adjusting' : 'recoveringNotice'));
  else { clearPicture(); hideRecovering(); }
}
function clearPicture() { canvas.getContext('2d')?.clearRect(0,0,canvas.width,canvas.height); }
/** The veil and notice over a held picture (recovering, V1): shown at once, faded out over 250 ms. */
const recovering = el('recovering');
let recoverFade = 0;
function showRecovering(text: string) {
  window.clearTimeout(recoverFade);
  el('recovering-text').textContent = text; recovering.hidden = false;
  requestAnimationFrame(() => { if (!recovering.hidden) recovering.classList.add('on'); });
}
function hideRecovering() {
  if (recovering.hidden) return;
  recovering.classList.remove('on');
  window.clearTimeout(recoverFade); recoverFade = window.setTimeout(() => { recovering.hidden = true; }, 300);
}
function server(message: ServerMessage) {
  if (message.type === 'pong') { lag.pong(performance.now()); return; }
  // Straight back, also before CarPlay starts: the box pauses the picture while this page lags behind.
  if (message.type === 'mark') { connection.send({ type: 'ack', mark: message.mark ?? 0 }); return; }
  // The iPhone lowers the music under a prompt or Siri and brings it back (duckAudio/unduckAudio via the box).
  if (message.type === 'duck') { audio.duck(message.level ?? 1, message.ms ?? 0); return; }
  if (message.type === 'host-ui' && active) {
    openPanel(); return;
  }
  if (message.type !== 'session' && message.type !== 'hello') return;
  if (!message.sessionActive) {
    // Ended to apply a new display (by this page or another): the phone comes straight back, keep the picture.
    const forDisplay = message.restarting === true || expectRestart;
    endExpectRestart(); reset(forDisplay && (painted || holding), forDisplay); state = forDisplay ? 'renegotiating' : 'waiting';
  }
  else { endExpectRestart(); void loadDisplay(); active = true; canvas.inert = false; state = 'starting'; syncNight(); }
  render();
}
async function unlock() {
  if (!pageAudio || audio.isUnlocked) return;   // Bluetooth route: never open an audio output the Tesla could take for a media source
  try { await audio.unlock(); } catch { /* Keep a truthful gesture hint; retry on next gesture. */ }
}
window.addEventListener('pointerdown', () => { void unlock(); });
window.addEventListener('click', () => { void unlock(); });
window.addEventListener('keydown', () => { void unlock(); });
el('audio-unlock').onclick = () => { void unlock(); };
function setVolume() { audio.setVolume(Number(volume.value) / 100); el('volume-value').textContent = `${volume.value}%`; localStorage.setItem('playport-master',volume.value); }
volume.oninput = setVolume; setVolume();
function openPanel() {
  if (!panel.open) {
    for (const id of ['toast', 'error-banner']) el('settings-notices').append(el(id));
    panel.classList.remove('closing'); panel.showModal();
  }
  void loadDisplay();
}
/** Leave along the path it came in (to the right), unless motion is reduced. */
function closePanel() {
  if (!panel.open || panel.classList.contains('closing')) return;
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { panel.close(); return; }
  panel.classList.add('closing');
  window.setTimeout(() => { panel.classList.remove('closing'); panel.close(); }, 200);
}
// Page navigation changes only host controls; it never changes the video viewport or display settings.
const settingsPages = panel.querySelectorAll<HTMLElement>('[data-settings-content]');
panel.querySelectorAll<HTMLButtonElement>('[data-settings-page]').forEach(button => {
  button.onclick = () => {
    for (const page of settingsPages) page.hidden = page.dataset.settingsContent !== button.dataset.settingsPage;
    panel.querySelectorAll<HTMLButtonElement>('[data-settings-page]').forEach(item => {
      item.setAttribute('aria-current', item === button ? 'page' : 'false');
    });
    panel.querySelector<HTMLElement>('.settings-body')!.scrollTop = 0;
  };
});
el('btn-settings').onclick = openPanel;
el('btn-close').onclick = closePanel;
// Native modal dialogs are in the top layer: keep notices with the controls that triggered them.
panel.addEventListener('close', () => {
  for (const id of ['toast', 'error-banner']) el('app').append(el(id));
});
panel.addEventListener('cancel', event => { event.preventDefault(); closePanel(); });
el('dismiss-error').onclick = () => error('');
el<HTMLSelectElement>('language').onchange = event => { setLanguage((event.target as HTMLSelectElement).value); render(); };
panel.addEventListener('click', event => { if (event.target !== panel) return; const r=panel.getBoundingClientRect(); if(event.clientX<r.left || event.clientX>r.right) closePanel(); });
/** A Tesla's browser ignores a page's fullscreen request (so the DOM requestFullscreen path and an Xpeng's
 *  reverse-camera restore are gone, TESLA in flags.ts); it shows a page without its address bar when it comes through
 *  a video site it lists (in China v.qq.com and 1905.com, as tesla-kit.com does; elsewhere youtube.com/redirect). The
 *  "borderless" rows on the welcome screen and in Settings take that way back to this page (2026-10-14). The
 *  "?www.1905.com" the hop ends with marks a page shown that way; so does a window as wide as the screen (95 %: the
 *  3/Y page is 773 of 1254 CSS px windowed, 1256 borderless), which still holds after the marker is gone. */
function teslaBorderless() { return location.search.includes('www.1905.com') || window.innerWidth >= 0.95 * window.screen.width; }
function teslaFullscreenUrl() {
  // 1905.com goes on only when the text between "//" and the first "/" ends in "1905.com": no "/" before the "?"
  // (with "/?" it went to its own home page, 2026-10-14); this page is the site's root anyway.
  return 'https://v.qq.com/search_redirect.html?url=https://www.1905.com/api/redirec.html?redirect_url='
    + `${location.origin}?www.1905.com`;
}
let teslaChecking = false;
function updateFullscreen() {
  const borderless = teslaBorderless();
  const label = t(borderless ? 'borderlessOn' : teslaChecking ? 'checkingNetwork' : 'fullscreen');
  const hint = t(borderless ? 'borderlessOnHint' : teslaChecking ? 'checkingNetworkHint' : 'fullscreenRowHint');
  el('fullscreen-text').textContent = label; el('welcome-fullscreen-text').textContent = label;
  el('fullscreen-hint').textContent = hint; el('welcome-fullscreen-hint').textContent = hint;
  for (const id of ['fullscreen', 'welcome-fullscreen']) {
    el(id).setAttribute('aria-label', label);
    el<HTMLButtonElement>(id).disabled = borderless || teslaChecking;
  }
}
/** The hop leaves this page for the video sites, which need the car's own internet (the box answers the Tesla's
 *  connectivity checks but gives the browser no internet without a SIM): the page looks first, and says so inline. */
async function toggleFullscreen() {
  if (!TESLA || teslaBorderless() || teslaChecking) return;
  teslaChecking = true; updateFullscreen();
  try {
    if (await reachable(TESLA_HOPS)) { location.href = teslaFullscreenUrl(); return; }
    toast(t('teslaFullscreenOffline'));
  } finally { teslaChecking = false; updateFullscreen(); }
}
el('fullscreen').onclick = () => { void toggleFullscreen(); };
el('welcome-fullscreen').onclick = () => { void toggleFullscreen(); };
let toastTimer = 0;
function toast(message: string) {
  el('toast').textContent = message; el('toast').hidden = false;
  window.clearTimeout(toastTimer); toastTimer = window.setTimeout(() => { el('toast').hidden = true; }, 6000);
}
// Fallback controls: home, back and a fresh keyframe only; previous/play/next are the car's own keys over Bluetooth.
document.querySelectorAll<HTMLButtonElement>('[data-command]').forEach(button => button.onclick = () => {
  const cmd = button.dataset.command;
  if (cmd === 'home' || cmd === 'back') send({ type:'knob', knob:{ select:false, home:cmd==='home', back:cmd==='back', x:0,y:0,wheel:0 } });
  else if (cmd === 'refresh') send({ type:'keyframe' });
});
/** The box's display as it is now: another page may have changed it (it sent back that page's fps, 2026-10-16). */
async function fetchDisplay(): Promise<Display | null> {
  try { const r = await fetch('/api/display', { cache: 'no-store' }); return r.ok ? await r.json() as Display : null; }
  catch { return null; }
}
async function loadDisplay() {
  if (displayBusy || !token) return;
  setDisplayStatus('loading');
  const loaded = await fetchDisplay();
  if (!loaded) { setDisplayStatus('loadFail'); return; }
  display = loaded; showDisplay(); fit(); scheduleAuto();
}
function setDisplayStatus(key: Key) {
  const status = el('display-status');
  status.dataset.i18n = key; status.textContent = t(key);
}
function showDisplay() {
  if (!display) return;
  el<HTMLSelectElement>('fps').value = String(display.fps); el<HTMLSelectElement>('ui-scale').value = String(display.uiScale);
  delete el('display-status').dataset.i18n;
  el('display-status').dataset.codec = display.hevc ? 'H.265' : 'H.264';
  el('display-status').textContent = `${display.width} × ${display.height} / ${display.fps} fps / ${display.hevc ? 'H.265' : 'H.264'}${display.pending ? ` · ${t('nextSession')}` : ''}`;
}
function endExpectRestart() { expectRestart = false; window.clearTimeout(expectTimer); }
/** defer: a sharper picture or another codec for shapes the phone already has; the box keeps it for the next session. */
async function saveDisplay(target: Display, how: { defer?: boolean; reason: string }): Promise<boolean> {
  if (displayBusy || !token) return false;
  displayBusy = true; el<HTMLButtonElement>('apply').disabled = true; el<HTMLFieldSetElement>('display-fields').disabled = true;
  for (const id of ['codec', 'performance-mode', 'allow-2560']) el<HTMLInputElement | HTMLSelectElement>(id).disabled = true;
  setDisplayStatus('applying');
  // A renegotiation is coming: hold the layout from now, the session's end may arrive before this answer.
  const restart = active && !how.defer && (!display || !sameStream(display, target));
  if (restart) { expectRestart = true; window.clearTimeout(expectTimer); expectTimer = window.setTimeout(() => { endExpectRestart(); fit(); }, DISPLAY_HOLD_MS); }
  try {
    const r = await fetch(`/api/display?token=${encodeURIComponent(token)}`, { method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({ ...target, defer: how.defer === true, reason: how.reason }) });
    const body = await r.json() as {ok?:boolean; deferred?:boolean}; if (!r.ok || !body.ok) throw new Error();
    if (body.deferred) { if (display) display.pending = true; setDisplayStatus('deferred'); return true; }
    display = { ...target, pending: false }; setDisplayStatus('applied'); return true;
  } catch { if (restart) { endExpectRestart(); fit(); } setDisplayStatus('applyFail'); return false; }
  finally { displayBusy=false; el<HTMLButtonElement>('apply').disabled=false; el<HTMLFieldSetElement>('display-fields').disabled=false;
    for (const id of ['codec', 'performance-mode', 'allow-2560']) el<HTMLInputElement | HTMLSelectElement>(id).disabled = false;
    render(); }
}
function scheduleAuto() {
  window.clearTimeout(autoTimer);
  if (!display || displayBusy || document.hidden || typeof VideoDecoder === 'undefined') return;
  autoTimer=window.setTimeout(() => { void adapt(); },1500);
}
async function adapt() {
  // Not for a hidden page (a covered page reports a small window): a timer set just before the car covered the page
  // fired anyway and renegotiated to 800x400 (Chrome, 2026-10-12).
  const busy = () => !display || displayBusy || document.hidden;
  if (busy()) return;
  // From the box's own, not what this page last saw: fps and size set by another page are kept, not sent back.
  const current = await fetchDisplay();
  if (current && !expectRestart && !holding) { display = current; showDisplay(); }
  if (busy() || !display) return;
  const urgent = urgentChange; urgentChange = '';
  const target=autoTarget();
  const next={...display,width:target.width,height:target.height,areas:[],area:0,hevc:wantHevc()};
  const key=`${next.width}x${next.height}${next.hevc?'-h265':''}`;
  if (key===lastAutoTarget) return;
  // Avoid a reconnect loop even when another viewer has a different screen shape.
  lastAutoTarget=key;
  if (sameStream(display,next)) return;
  // Every window size (and a codec this browser proved it can or cannot handle) renegotiates now: each size is its
  // own CarPlay session at its sharpest resolution (2026-10-23).
  if (!(await saveDisplay(next, { reason: urgent || 'shape' }))) { error(t('autoFail')); return; }
  fit();
}
/** The window's own size, at the sharpest the box offers: the CSS size times the pixels used (the device pixel ratio
 *  with a fast decoder), long side 1280 to 1920 (2560 only with a fast decoder and f50-allow-2560). Each window size
 *  is its own CarPlay session (2026-10-23: one stream shared by several window shapes made small windows soft and
 *  cramped). */
function autoTarget() {
  const pixels=fastDecoder()?Math.min(2,Math.max(1,window.devicePixelRatio||1)):1;
  const max=fastDecoder()&&allow2560.checked?2560:1920, width=screen.clientWidth*pixels, height=screen.clientHeight*pixels;
  return performanceOn() ? suggestedResolution(width,height,max) : windowResolution(width,height,max);
}
el<HTMLSelectElement>('codec').value = readFlag('f50-codec') || 'auto';
el<HTMLSelectElement>('codec').onchange=() => { saveFlag('f50-codec', el<HTMLSelectElement>('codec').value); lastAutoTarget=''; urgentChange='manual'; scheduleAuto(); };
performanceMode.onchange=() => { saveFlag('f50-performance-mode',performanceMode.checked?'1':'0'); lastAutoTarget=''; urgentChange='manual'; scheduleAuto(); };
el<HTMLFormElement>('display-form').onsubmit=event => {
  event.preventDefault();
  // The size is always the window's own (autoTarget; the typed width/height of the custom mode are gone): the form
  // changes frame rate, UI size or codec; the areas are empty now that each window size is its own stream (2026-10-23).
  const size:Pick<Display,'width'|'height'|'areas'|'area'>=display?{width:display.width,height:display.height,areas:[],area:0}:{...autoTarget(),areas:[],area:0};
  void saveDisplay({...size,fps:Number(el<HTMLSelectElement>('fps').value),uiScale:Number(el<HTMLSelectElement>('ui-scale').value),hevc:wantHevc()},{reason:'manual'});
};
new ResizeObserver(()=>{ fit(); scheduleAuto(); }).observe(screen);
// A finger left down when the page goes away or is frozen stays down on the phone: lift every contact first.
window.addEventListener('pagehide', () => input.releaseAll());
document.addEventListener('visibilitychange',()=>{
  pageEvent(document.hidden ? 1 : 2);
  if (document.hidden) { input.releaseAll(); return; }
  // The picture at once instead of the phone's next keyframe; then the sound.
  send({ type:'keyframe' }); fit(); scheduleAuto(); void unlock();
});
/** Straight into the viewer log, not only every 10 s: ev 1 hidden, 2 shown, 5 resized (3/4, DOM fullscreen, are gone). */
function pageEvent(ev: number) {
  connection.send({type:'stats',stats:{ev,hidden:document.hidden?1:0,borderless:teslaBorderless()?1:0,width:screen.clientWidth,height:screen.clientHeight,...viewport()}});
}
/** Which page build runs (raised with each build tried in the car). */
const BUILD = 202610310112;
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
  el('audio-unlock').hidden=!pageAudio||!active||!audioSeen||audio.isUnlocked;
  el('audio-status').textContent=t(audio.isPlaying?'playing':'paused');
},750);
// Which browser the car runs.
const chromeMajor=Number(/Chrome\/(\d+)/.exec(navigator.userAgent)?.[1] ?? 0),webView=/; wv\)/.test(navigator.userAgent)?1:0;
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
  if (holding && !late) { holdAwakeMs += Math.min(gap, 1000); if (holdAwakeMs > (holdForDisplay ? DISPLAY_HOLD_MS : HOLD_MS)) { holding = false; hideRecovering(); clearPicture(); fit(); render(); } }
  if (!painted && (state === 'connecting' || state === 'reconnecting')) el('connection-hint').textContent = hintFor();   // the elapsed time
  if (late) { lifeEvent(8, { gapMs: Math.round(gap) }); wake(1); }
  else if (active && !document.hidden && now - lastHeard > 8000) revive();   // the link died while in view
  else if (!document.hidden && closedAt && now - closedAt > RELOAD_AFTER_MS) reloadWhenBoxAnswers();
}, 1000);
window.setInterval(()=>{
  const now=performance.now(),seconds=Math.max(1,(now-reportStart)/1000),stalls=video.takeStalls();
  send({type:'stats',stats:{fps:reportFrames/seconds,decodeMs:video.decodeLatencyMs,queue:video.decodeQueueSize,
    kbps:reportBytes*8/1000/seconds,hidden:document.hidden?1:0,borderless:teslaBorderless()?1:0,
    width:canvas.width,height:canvas.height,...(touchCount?{touchMs:touchSum/touchCount,touches:touchCount}:{}),...(musicBytes?{musicKbps:musicBytes*8/1000/seconds}:{}),
    ...startupStats(),chrome:chromeMajor,compat:compatDisplay?1:0,desync:video.desynchronized,build:BUILD,webView,carMusic:carMusic?1:0,teslaMode:TESLA?1:0,promptGain,...(revived?{revived}:{}),fastDecoder:fastDecoder()?1:0,hevcDecodes:hevcDecodes?1:0,hevc:display?.hevc?1:0,...audio.farReport(),...audio.duckReport(),...audio.musicReport(),pageAudio:pageAudio?1:0,...stalls,...lag.take(performance.now())}});
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

// Bluetooth route (audio_route_navigation=bluetooth): the page has no sound of its own; say so where the slider was.
if (!pageAudio) {
  el('sound-settings').querySelectorAll<HTMLElement>(':scope > :not(#sound-on-car)').forEach(node => { node.hidden = true; });
  el('sound-on-car').hidden = false;
  document.querySelectorAll<HTMLElement>('[data-i18n="privacy"]').forEach(node => { node.hidden = true; });   // "tap for sound" does not apply
}
el('browser-check-show').onclick = () => {
  panel.close();
  (window as unknown as { F50BrowserCheck: { show(): void } }).F50BrowserCheck.show();
};
