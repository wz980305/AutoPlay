/** CarPlay day/night appearance requested by this display. CarPlay itself switches maps and UI. */
export type NightMode = 'schedule' | 'system' | 'day' | 'night';
export const NIGHT_START = 18 * 60 + 30;
export const NIGHT_END = 6 * 60 + 30;

export function parseNightMode(value: string | null): NightMode {
  return value === 'system' || value === 'day' || value === 'night' ? value : 'schedule';
}

/** schedule: 18:30–06:30 local time; system: the car browser's dark/light preference. */
export function isNight(mode: NightMode, now: Date, prefersDark: boolean): boolean {
  if (mode === 'day') return false;
  if (mode === 'night') return true;
  if (mode === 'system') return prefersDark;
  const minutes = now.getHours() * 60 + now.getMinutes();
  return minutes >= NIGHT_START || minutes < NIGHT_END;
}
