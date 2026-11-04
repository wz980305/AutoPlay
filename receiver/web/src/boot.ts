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
    // Only the token and the settings port are read. The carMusic/tesla fields of older boxes are constants since the
    // Tesla-only build (flags.ts); audioRouteNavigation (1.1.0–1.2.0) is gone with the page's sound (1.3.0).
    const value = await response.json() as { token?: string; settingsPort?: number };
    if (typeof value.token === 'string' && /^[0-9a-f]{32}$/.test(value.token)) localStorage.setItem('playport-token', value.token);
    const flags = window as unknown as { playportBoxSettingsPort?: number };
    if (Number.isInteger(value.settingsPort)) flags.playportBoxSettingsPort = value.settingsPort;
  } catch { /* No box behind this page, or storage blocked: the page asks for a token as before. */ }
}
start();
