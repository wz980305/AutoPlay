/** CarPlay day/night appearance requested by this display. CarPlay itself switches maps and UI. */
import type { SunTimes } from './sun';
export type NightMode = 'schedule' | 'system' | 'day' | 'night';
/** schedule without a sunset and sunrise to go by (1.0-1.6.4 always): 18:30-06:30. */
export const NIGHT_START = 18 * 60 + 30;
export const NIGHT_END = 6 * 60 + 30;

export function parseNightMode(value: string | null): NightMode {
  return value === 'system' || value === 'day' || value === 'night' ? value : 'schedule';
}

/** schedule: from sunset to sunrise (sun.ts, 1.6.5: when an iPhone on Automatic appearance switches), or 18:30-06:30
 *  local time without them; system: the car browser's dark/light preference. */
export function isNight(mode: NightMode, now: Date, prefersDark: boolean, sun: SunTimes | null = null): boolean {
  if (mode === 'day') return false;
  if (mode === 'night') return true;
  if (mode === 'system') return prefersDark;
  const minutes = now.getHours() * 60 + now.getMinutes();
  return minutes >= (sun ? sun.set : NIGHT_START) || minutes < (sun ? sun.rise : NIGHT_END);
}

/** When the schedule next turns day into night or back (epoch ms), for the box page to turn with it while it is open
 *  (1.6.5); null for the other modes, which have no time to turn at. sunOn gives a local day's sunset and sunrise. */
export function nextTurn(mode: NightMode, now: Date, sunOn: (day: Date) => SunTimes | null): number | null {
  if (mode !== 'schedule') return null;
  const nightAt = (at: Date) => isNight('schedule', at, false, sunOn(at));
  const was = nightAt(now);
  for (let offset = 0; offset < 3; offset++) {
    const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() + offset);
    const sun = sunOn(day);
    const marks = [sun ? sun.rise : NIGHT_END, sun ? sun.set : NIGHT_START].filter(m => m > 0 && m < 1440).sort((a, b) => a - b);
    for (const minute of marks) {
      const at = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, minute);
      if (at.getTime() > now.getTime() && nightAt(at) !== was) return at.getTime();
    }
  }
  return null;
}

/** The box page's address as this page links to it (1.5.0): same host, plain HTTP, with two things the box page
 *  cannot know by itself. night: the day/night this page asks CarPlay for at that moment, so the box page comes up in
 *  the colours CarPlay is showing. from: where the link was - the settings panel or the page itself (the waiting
 *  screen) - so the box page's 返回 leads back there. */
export type BoxLinkFrom = 'panel' | 'page';
/** turn (1.6.5): when the schedule next changes day and night (nextTurn), so the box page changes with it. */
export function boxPageUrl(hostname: string, port: number, night: boolean, from: BoxLinkFrom, turn: number | null = null): string {
  return `http://${hostname}${port === 80 ? '' : `:${port}`}/?night=${night ? 1 : 0}&from=${from}${turn ? `&turn=${Math.round(turn / 1000)}` : ''}`;
}

/** The way back (1.5.0): the box page's 返回 opens this page with #settings=<category> when the visit began in the
 *  settings panel. The category to open the panel at, or null for any other fragment. */
export type SettingsCategory = 'general' | 'display' | 'connection';
export function panelFromHash(hash: string): SettingsCategory | null {
  const match = /^#settings=(general|display|connection)$/.exec(hash);
  return match ? match[1] as SettingsCategory : null;
}
