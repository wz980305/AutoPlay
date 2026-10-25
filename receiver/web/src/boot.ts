import { startup } from './startup';
startup.mark('bootMs');
interface BrowserCheck { done: boolean; allowed: boolean; appReady(): void; appFailed(): void }
const check = (window as unknown as { F50BrowserCheck?: BrowserCheck }).F50BrowserCheck;
function start() {
  if (!check) return; // Keep the independent diagnostic visible if its script failed.
  if (!check.done) { setTimeout(start, 50); return; }
  if (check.allowed) void access().then(() => { startup.mark('accessMs'); return import('./main'); }).then(() => check.appReady()).catch(() => check.appFailed());
}
/** The viewer token the box hands to pages on its network, read from the box's own address only: a script any
 *  site could include gave it away (audit 2026-10-13). Without a box (development) the token comes from the URL. */
async function access() {
  try {
    const response = await fetch('./receiver-access.json', { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) return;
    const value = await response.json() as { token?: string; settingsPort?: number; carMusic?: boolean; tesla?: boolean };
    if (typeof value.token === 'string' && /^[0-9a-f]{32}$/.test(value.token)) localStorage.setItem('playport-token', value.token);
    if (Number.isInteger(value.settingsPort)) (window as unknown as { playportBoxSettingsPort?: number }).playportBoxSettingsPort = value.settingsPort;
    // Set on the box: carMusic, the music goes over the car's own Bluetooth (OpenWrt dashplay.main.car_music, settings
    // page); tesla, the Tesla browser's ways (fullscreen through a listed video site, a quieter microphone). Tesla
    // mode (dashplay.main.tesla_mode) sets both.
    const flags = window as unknown as { playportCarMusic?: boolean; playportTeslaMode?: boolean };
    flags.playportTeslaMode = value.tesla === true;
    flags.playportCarMusic = value.carMusic === true || (value.carMusic === undefined && value.tesla === true);
  } catch { /* No box behind this page, or storage blocked: the page asks for a token as before. */ }
}
start();
