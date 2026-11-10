import { startup, startupStats } from './startup';
import { InputController } from './input';
import { VideoPlayer } from './video';
import { Connection } from './ws';
import { LagProbe } from './lag';
import { suggestedResolution, windowResolution, areaSize, sameStream, frameRateCheck, type Area } from './display-fit';
import { TESLA } from './flags';
import { statusHint } from './status';
import { t, language, setLanguage, type Key } from './i18n';
import { boxPageUrl, isNight, parseNightMode } from './night';
import { reachable, TESLA_HOPS } from './tesla-fullscreen';
import { hudLines } from './debug-hud';
import { compatDisplayOn } from './compat-display';
import { askBox, READ_MS, WRITE_MS } from './ask-box';
import { LocationFeed, askLocation, autoDatum, browserZone, compassText, gcjToWgs, inChina, type Fix } from './location';
import { attachPickers, refreshPickers } from './picker';
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
// The same, per second, for the debug overlay (debug-hud.ts).
let hudFrames = 0, hudBytes = 0, hudStart = performance.now();
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
interface Display { width: number; height: number; fps: number; uiScale: number; hevc: boolean; areas?: Area[]; area?: number; pending?: boolean;
  /** The car-location switch and the datum of the browser's coordinates (1.4.0; absent from an older box). */
  carLocation?: boolean; carLocationDatum?: string; }
let display: Display | null = null;
/** Performance mode: upsize each window to the sharpest size (long side at least 1280), then shrink it into the
 *  window. Off (the Tesla default, 2026-10-26: the F50 and the iPhone run cooler, and a Tesla's panel is dense enough
 *  at the window's own pixels): the window's own size (minimum width 720). 2026-10-23, in Advanced. */
const performanceMode = el<HTMLInputElement>('performance-mode');
performanceMode.checked = readFlag('f50-performance-mode') === '1';
/** The long side is capped at 1920 (1.3.2). The "Allow 2560" switch of 1.0-1.3.1 is gone: it only raised the cap for a
 *  2.5K screen, a Tesla's widest page (borderless, 1256 CSS px at 1.53) is 1922 px and came out 2 px wider with it, and
 *  an MCU2 (Atom) Tesla must never be sent 2560 (hardware review H1). The flag a browser may still hold is dropped. */
try { localStorage.removeItem('f50-allow-2560'); } catch { /* Nothing to drop. */ }
const performanceOn = () => performanceMode.checked;
const nightSelect = el<HTMLSelectElement>('night-mode');
nightSelect.value = parseNightMode(localStorage.getItem('f50-night-mode'));
const darkQuery = matchMedia('(prefers-color-scheme: dark)');
let sentNight: boolean | null = null;

/** Box page (pairing, network, update), when the device startup announced one: same host, plain HTTP. The link
 *  carries the day/night this page asks CarPlay for, read again at the tap (a schedule may have turned since the page
 *  was drawn), so the box page shows the colours CarPlay does (1.5.0). */
const boxPort = Number((window as unknown as { playportBoxSettingsPort?: number }).playportBoxSettingsPort) || 0;
const nightNow = () => isNight(parseNightMode(nightSelect.value), new Date(), darkQuery.matches);
if (boxPort) for (const id of ['box-link', 'box-link-panel']) {
  const link = el<HTMLAnchorElement>(id);
  const aim = () => { link.href = boxPageUrl(location.hostname, boxPort, nightNow()); };
  aim(); link.addEventListener('click', aim);
  link.hidden = false;
}
function render() {
  setLanguage(language);
  updateFullscreen();
  el<HTMLSelectElement>('language').value = language;
  refreshPickers();
  el('app').dataset.state = state;
  el('connection-text').textContent = t(state);
  el('connection-hint').textContent = hintFor();
  // The box's own page is no help while the box itself does not answer.
  if (boxPort) el('box-link').hidden = !statusHint(state, 0).boxLink;
  el('overlay').hidden = painted || holding;
  el('app').dataset.live = String(painted || holding);
  el('capabilities').textContent = !isSecureContext ? t('insecure') : typeof VideoDecoder === 'undefined' ? t('unsupported') : t('compatible');
  syncApply();
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
// This page is silent (1.3.0, docs/AUDIO.md): the receiver offers the iPhone no audio at all, so music, navigation
// prompts, calls and Siri all play on the Tesla's Bluetooth. Audio frames a receiver built before 1.3.0 might still
// relay (wire types 3/4/6) are parsed by protocol.ts and dropped here.
const lag = new LagProbe();
const connection = new Connection(token, {
  onTiming(stats) { connection.send({type:'stats', stats:{ev:16,...stats}}); },
  onWire(message) {
    switch (message.kind) {
      case 'video-config': video.configure(message); break;
      case 'video-frame': video.pushFrame(message); break;
      default: break;
    }
  },
  onServer(message) { lastHeard = performance.now(); server(message); },
  onBytes(count) { reportBytes += count; hudBytes += count; lastHeard = performance.now(); },
  onState(value) {
    if (value === 'open' && closedAt) { lifeEvent(11, { downMs: Math.round(performance.now() - closedAt), failures: connection.failures }); closedAt = 0; }
    if (value === 'closed') { if (!closedAt) { closedAt = performance.now(); linkDownAt = closedAt; } if (!wokeAt) wokeAt = closedAt; reset(shownOnce); state = 'reconnecting'; }
    else if (value === 'connecting') { if (state !== 'reconnecting') state = 'connecting'; }
    else { state = 'waiting'; void loadDisplay(); }
    render();
  },
});
const input = new InputController(canvas, send); input.attach();
/** Sends CarPlay day/night only on change; a new session (sentNight reset) always gets the current value. */
function syncNight() {
  if (!active) return;
  const night = nightNow();
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
  video.close();
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
  // "duck" (the iPhone lowering music under a prompt): nothing to lower on a silent page; a pre-1.3.0 box may still send it.
  if (message.type === 'duck') return;
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
/** The car's on-screen keyboard (1.3.0): a Tesla sometimes raised its keyboard when the browser was brought back to
 *  this page. The keyboard follows the browser's focused element, so nothing in the live view may hold focus: the
 *  canvas lost its tabindex and the focus() on every tap (input.ts; the keys are read on window anyway), and whatever
 *  the browser restores focus to when the page is shown again is blurred, unless a dialog of this page is open (the
 *  settings panel and the option sheet manage their own focus). A keyboard that still appears must not resize the
 *  page: a smaller window would renegotiate CarPlay (the meta viewport's interactive-widget=overlays-content, and
 *  the VirtualKeyboard API where the browser has it). */
function dropStrayFocus() {
  if (document.querySelector('dialog[open]')) return;
  const focused = document.activeElement;
  if (focused instanceof HTMLElement && focused !== document.body) focused.blur();
}
for (const event of ['pageshow', 'focus']) window.addEventListener(event, dropStrayFocus);
document.addEventListener('visibilitychange', () => { if (!document.hidden) dropStrayFocus(); });
{
  const keyboard = (navigator as unknown as { virtualKeyboard?: { overlaysContent: boolean } }).virtualKeyboard;
  if (keyboard) try { keyboard.overlaysContent = true; } catch { /* Then the meta viewport alone decides. */ }
}
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
  // The waiting screen's row explains the hop (a first-run screen); the settings row is a bare iOS-style row (1.3.0).
  const hint = t(borderless ? 'borderlessOnHint' : teslaChecking ? 'checkingNetworkHint' : 'fullscreenRowHint');
  el('fullscreen-text').textContent = label; el('welcome-fullscreen-text').textContent = label;
  el('welcome-fullscreen-hint').textContent = hint;
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
/** The box's display as it is now: another page may have changed it (it sent back that page's fps, 2026-10-16). */
async function fetchDisplay(): Promise<Display | null> {
  try { const { ok, body } = await askBox<Display>('/api/display', { cache: 'no-store' }, READ_MS); return ok ? body : null; }
  catch { return null; }
}
async function loadDisplay() {
  if (displayBusy || !token) return;
  setDisplayStatus('loading');
  const loaded = await fetchDisplay();
  if (!loaded) { setDisplayStatus('loadFail'); return; }
  display = loaded; showDisplay(); showLocation(loaded); fit(); scheduleAuto();
}
let statusTimer = 0;
function setDisplayStatus(key: Key) {
  const status = el('display-status');
  window.clearTimeout(statusTimer);
  status.dataset.i18n = key; status.textContent = t(key);
  // "Saved, reconnecting" has said its piece once CarPlay is back (about 5 s): the footer goes quiet again, as in iOS.
  if (key === 'applied') statusTimer = window.setTimeout(() => {
    if (status.dataset.i18n === 'applied') { delete status.dataset.i18n; status.textContent = ''; }
  }, 6000);
}
/** The rows show the box's values; the status line under the button speaks only while something is happening (or a
 *  change waits for the next session). The resolution, codec and frame rate in use are on the debug overlay and under
 *  Connection (1.3.0; the permanent "1920 × 998 / 30 fps / H.265" line said the same thing a third time). */
function showDisplay() {
  if (!display) return;
  el<HTMLSelectElement>('fps').value = String(display.fps); el<HTMLSelectElement>('ui-scale').value = String(display.uiScale);
  refreshPickers();
  if (display.pending) setDisplayStatus('nextSession');
  else { delete el('display-status').dataset.i18n; el('display-status').textContent = ''; }
  syncApply();
}
/** The apply row (1.4.0) is there only while the picked content size or frame rate differs from the box's, as an iOS
 *  "Set" appears with a change: "Apply and reconnect" while CarPlay runs, "Apply" when there is nothing to cut. */
function syncApply() {
  const row = el<HTMLButtonElement>('apply'), text = el('apply-text');
  const changed = display !== null && (Number(el<HTMLSelectElement>('fps').value) !== display.fps
    || Number(el<HTMLSelectElement>('ui-scale').value) !== display.uiScale);
  row.hidden = !changed;   // while a save is out the row stays, disabled (saveDisplay), until the box answers
  const key: Key = active ? 'apply' : 'applyNow';
  text.dataset.i18n = key; text.textContent = t(key);
}
for (const id of ['fps', 'ui-scale']) el<HTMLSelectElement>(id).addEventListener('change', syncApply);
function endExpectRestart() { expectRestart = false; window.clearTimeout(expectTimer); }
/** defer: a sharper picture or another codec for shapes the phone already has; the box keeps it for the next session. */
async function saveDisplay(target: Display, how: { defer?: boolean; reason: string }): Promise<boolean> {
  if (displayBusy || !token) return false;
  displayBusy = true; el<HTMLButtonElement>('apply').disabled = true; el<HTMLFieldSetElement>('display-fields').disabled = true;
  for (const id of ['codec', 'performance-mode']) el<HTMLInputElement | HTMLSelectElement>(id).disabled = true;
  setDisplayStatus('applying');
  // A renegotiation is coming: hold the layout from now, the session's end may arrive before this answer.
  const restart = active && !how.defer && (!display || !sameStream(display, target));
  if (restart) { expectRestart = true; window.clearTimeout(expectTimer); expectTimer = window.setTimeout(() => { endExpectRestart(); fit(); }, DISPLAY_HOLD_MS); }
  try {
    const { ok, body } = await askBox<{ ok?: boolean; deferred?: boolean }>(`/api/display?token=${encodeURIComponent(token)}`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ ...target, defer: how.defer === true, reason: how.reason }) },
      WRITE_MS);
    if (!ok || !body?.ok) throw new Error();
    if (body.deferred) { if (display) display.pending = true; setDisplayStatus('deferred'); return true; }
    display = { ...target, pending: false }; setDisplayStatus('applied'); return true;
  } catch { if (restart) { endExpectRestart(); fit(); } setDisplayStatus('applyFail'); return false; }
  finally { displayBusy=false; el<HTMLButtonElement>('apply').disabled=false; el<HTMLFieldSetElement>('display-fields').disabled=false;
    for (const id of ['codec', 'performance-mode']) el<HTMLInputElement | HTMLSelectElement>(id).disabled = false;
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
  if (current && !expectRestart && !holding) { display = current; showDisplay(); showLocation(current); }
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
 *  with a fast decoder), long side 1280 to 1920. Each window size
 *  is its own CarPlay session (2026-10-23: one stream shared by several window shapes made small windows soft and
 *  cramped). */
function autoTarget() {
  const pixels=fastDecoder()?Math.min(2,Math.max(1,window.devicePixelRatio||1)):1;
  const max=1920, width=screen.clientWidth*pixels, height=screen.clientHeight*pixels;
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
  // The picture at once instead of the phone's next keyframe.
  send({ type:'keyframe' }); fit(); scheduleAuto();
});
/** Straight into the viewer log, not only every 10 s: ev 1 hidden, 2 shown, 5 resized (3/4, DOM fullscreen, are gone). */
function pageEvent(ev: number) {
  connection.send({type:'stats',stats:{ev,hidden:document.hidden?1:0,borderless:teslaBorderless()?1:0,width:screen.clientWidth,height:screen.clientHeight,...viewport()}});
}
/** Which page build runs (raised with each build tried in the car). */
const BUILD = 202611101900;
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
  el('stats').textContent=painted?`${canvas.width} × ${canvas.height} / ${fps.toFixed(0)} fps / ${display?.hevc ? 'H.265' : 'H.264'} / ${t('latency')} ${video.decodeLatencyMs.toFixed(0)} ms`:t('noStream');
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
    width:canvas.width,height:canvas.height,...(touchCount?{touchMs:touchSum/touchCount,touches:touchCount}:{}),
    ...startupStats(),chrome:chromeMajor,compat:compatDisplay?1:0,desync:video.desynchronized,build:BUILD,webView,teslaMode:TESLA?1:0,...(revived?{revived}:{}),fastDecoder:fastDecoder()?1:0,hevcDecodes:hevcDecodes?1:0,hevc:display?.hevc?1:0,...stalls,...lag.take(performance.now()),...locationFeed.take(),...(locationFeed.enabled?{locGcj:datumInUse()==='gcj02'?1:0,locAuto:datumSelect.value==='auto'?1:0}:{})}});
  judgeDecoder(video.decodeLatencyMs, reportFrames/seconds);
  if (active) judgeFrameRate(stalls.caughtUp);
  reportFrames=0;reportBytes=0;reportStart=now;touchSum=0;touchCount=0;
},10000);
// Debug overlay: off unless turned on in Display (kept in this browser); nothing is counted differently while it is off.
const hud = el('debug-hud'), hudSwitch = el<HTMLInputElement>('debug-hud-on');
hudSwitch.checked = readFlag('f50-debug-hud') === '1';
hudSwitch.onchange = () => { saveFlag('f50-debug-hud', hudSwitch.checked ? '1' : '0'); hud.hidden = !hudSwitch.checked; updateHud(); };
hud.hidden = !hudSwitch.checked;
const compatSwitch = el<HTMLInputElement>('compat-display-on');
compatSwitch.checked = compatDisplay;
compatSwitch.onchange = () => { saveFlag('f50-compat-display', compatSwitch.checked ? '1' : '0'); location.reload(); };
// Car location (1.4.0, docs/LOCATION.md): the switch and datum live on the box (the iPhone learns of the location
// source when it identifies the accessory); the browser's permission is this page's. Off until switched on here.
const locationSwitch = el<HTMLInputElement>('car-location-on'), datumSelect = el<HTMLSelectElement>('car-location-datum');
const datumRow = el<HTMLButtonElement>('car-location-datum-row');
let lastFix: Fix | null = null, hudFixes = 0, locationBusy = false;
/** The car browser's time zone goes with each fix: the box's "auto" datum tells mainland China by it (1.5.0). */
const zone = browserZone();
const DATUM_NAME: Record<string, string> = { wgs84: 'WGS-84', gcj02: 'GCJ-02' };
/** The datum the box applies to the last fix: the chosen one, or what "auto" comes to here. */
function datumInUse(): string {
  return datumSelect.value !== 'auto' ? datumSelect.value : lastFix ? autoDatum(lastFix.lat, lastFix.lon, zone) : 'wgs84';
}
const locationFeed = new LocationFeed(fix => {
  lastFix = fix; hudFixes++; showDatumChoices();
  send({ type: 'location', location: zone ? { ...fix, zone } : fix });
}, navigator.geolocation, () => !document.hidden, () => toast(t('locationDenied')));
/** The datum row shows inside China's rectangle only (or once GCJ-02 is chosen). Each choice carries the position it
 *  would give the iPhone, written as the iPhone's Compass app writes it: the one that matches Compass is right.
 *  "Automatic" also says which of the two it comes to here. */
function showDatumChoices() {
  const china = lastFix !== null && inChina(lastFix.lat, lastFix.lon);
  datumRow.hidden = !locationSwitch.checked || !(china || datumSelect.value === 'gcj02');
  if (!lastFix) return;
  const zh = language === 'zh', [gLat, gLon] = gcjToWgs(lastFix.lat, lastFix.lon);
  const wgs = compassText(lastFix.lat, lastFix.lon, zh), gcj = compassText(gLat, gLon, zh);
  const auto = autoDatum(lastFix.lat, lastFix.lon, zone);
  for (const option of Array.from(datumSelect.options)) {
    option.dataset.detail = option.value === 'auto' ? `${DATUM_NAME[auto]} · ${auto === 'gcj02' ? gcj : wgs}` : option.value === 'gcj02' ? gcj : wgs;
  }
}
function applyLocation(on: boolean, datum: string) {
  locationSwitch.checked = on; datumSelect.value = datum === 'gcj02' || datum === 'wgs84' ? datum : 'auto';
  locationFeed.setEnabled(on); showDatumChoices(); refreshPickers();
}
function showLocation(from: Display) { if (!locationBusy) applyLocation(from.carLocation === true, from.carLocationDatum ?? 'auto'); }
/** On asks the browser first (its prompt, the first time); a refusal leaves the switch off. On reconnects CarPlay
 *  once, for the iPhone to learn of the new location source; off and a new datum take effect at once. The datum goes
 *  to the box only when the owner picked one (picked): the switch alone leaves the box's as it is. */
async function setLocation(on: boolean, datum: string, picked = false) {
  if (!token || locationBusy) return;
  const was = { on: locationFeed.enabled, datum: datumSelect.value };
  locationBusy = true; locationSwitch.disabled = true;
  try {
    if (on && !was.on) {
      const permission = await askLocation(navigator.geolocation);
      if (permission !== 'granted') { applyLocation(false, was.datum); toast(t(permission === 'denied' ? 'locationDenied' : 'locationUnavailable')); return; }
    }
    const { ok, body } = await askBox<{ ok?: boolean; restarting?: boolean }>(`/api/location?token=${encodeURIComponent(token)}`,
      { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(picked ? { enabled: on, datum } : { enabled: on }) }, WRITE_MS);
    if (!ok || !body?.ok) throw new Error();
    applyLocation(on, datum);
    if (body.restarting) toast(t('locationReconnecting'));
  } catch { applyLocation(was.on, was.datum); toast(t('locationFail')); }
  finally { locationBusy = false; locationSwitch.disabled = false; }
}
locationSwitch.onchange = () => { void setLocation(locationSwitch.checked, datumSelect.value); };
datumSelect.onchange = () => { void setLocation(true, datumSelect.value, true); };
function updateHud() {
  const now = performance.now(), seconds = Math.max(0.25, (now - hudStart) / 1000);
  if (!hud.hidden) hud.textContent = hudLines({ width: painted ? canvas.width : 0, height: canvas.height, fps: hudFrames / seconds,
    hevc: display ? display.hevc : null, videoKbps: hudBytes * 8 / 1000 / seconds, decodeMs: video.decodeLatencyMs,
    queue: video.decodeQueueSize, rttMs: lag.last,
    ...(locationFeed.enabled ? { location: { perSecond: hudFixes / seconds, kmh: lastFix?.speed === undefined ? null : lastFix.speed * 3.6,
      datum: `${DATUM_NAME[datumInUse()]}${datumSelect.value === 'auto' ? (language === 'zh' ? '（自动）' : ' (auto)') : ''}` } } : {}) },
    language === 'zh').join('\n');
  hudFrames = 0; hudBytes = 0; hudStart = now; hudFixes = 0;
}
window.setInterval(updateHud, 1000);
render();fit();if(token) connection.connect();

nightSelect.onchange = () => { localStorage.setItem('f50-night-mode', nightSelect.value); syncNight(); render(); };
darkQuery.addEventListener('change', () => { syncNight(); render(); });
window.setInterval(() => { syncNight(); if (panel.open) render(); }, 30000);

// Native <select> lists are drawn by the car browser at the OS size; the rows open the page's own option sheet instead.
attachPickers(panel, el<HTMLDialogElement>('picker'));
// A second-level section (details) opened near the bottom of a short window unfolds below the fold: scroll it into
// view, whole when it fits, else from its title (the 773×601 Tesla window shows about five rows).
const settingsBody = panel.querySelector<HTMLElement>('.settings-body')!;
panel.querySelectorAll<HTMLDetailsElement>('details').forEach(details => {
  details.addEventListener('toggle', () => {
    if (!details.open) return;
    const own = details.getBoundingClientRect(), view = settingsBody.getBoundingClientRect();
    if (own.bottom <= view.bottom) return;
    details.scrollIntoView({ block: own.height > view.height ? 'start' : 'end', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  });
});
el('browser-check-show').onclick = () => {
  panel.close();
  (window as unknown as { F50BrowserCheck: { show(): void } }).F50BrowserCheck.show();
};
