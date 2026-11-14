/** Sunset and sunrise, for 「日落到日出」 night mode (1.6.5). The owner (2026-11-14): AutoPlay's day and night should
 *  switch when the iPhone's does, and an iPhone on Automatic appearance switches at the local sunset and sunrise, while
 *  AutoPlay's schedule was a fixed 18:30-06:30 (an hour off in a Sydney November, more in winter). AutoPlay cannot read
 *  the iPhone's appearance - CarPlay takes day and night from the car - so it works out the same moments itself.
 *
 *  The sunrise equation (as on Wikipedia, "Sunrise equation"; the sun's upper edge at -0.833°): within a minute or two
 *  of published tables outside the polar circles, which is as close as the switch needs. Written for this project. */

export interface Place { lat: number; lon: number }
/** Minutes after local midnight. A polar day is {rise: 0, set: 1440} (never night); a polar night {rise: 1440, set: 0}. */
export interface SunTimes { rise: number; set: number }

const RAD = Math.PI / 180, DAY_MS = 86_400_000, J1970 = 2440587.5, J2000 = 2451545;

/** Sunrise and sunset (epoch ms) of the local calendar day of `day`, or 'day' / 'night' when the sun does not cross the
 *  horizon that day. */
export function sunEvents(day: Date, place: Place): { rise: number; set: number } | 'day' | 'night' {
  const noon = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 12).getTime();
  const d = noon / DAY_MS + J1970 - J2000;
  const west = -place.lon;
  const n = Math.round(d - 0.0009 - west / 360);
  const approx = 0.0009 + west / 360 + n;
  const m = (357.5291 + 0.98560028 * approx) * RAD;
  const centre = (1.9148 * Math.sin(m) + 0.02 * Math.sin(2 * m) + 0.0003 * Math.sin(3 * m)) * RAD;
  const ecliptic = m + centre + (180 + 102.9372) * RAD;
  const transit = approx + 0.0053 * Math.sin(m) - 0.0069 * Math.sin(2 * ecliptic);
  const sinDec = Math.sin(ecliptic) * Math.sin(23.4397 * RAD), cosDec = Math.sqrt(1 - sinDec * sinDec);
  const lat = place.lat * RAD;
  const cosHour = (Math.sin(-0.833 * RAD) - Math.sin(lat) * sinDec) / (Math.cos(lat) * cosDec);
  if (cosHour > 1) return 'night';
  if (cosHour < -1) return 'day';
  const half = Math.acos(cosHour) / (2 * Math.PI);
  const ms = (j: number) => Math.round((j + J2000 - J1970) * DAY_MS);
  return { rise: ms(transit - half), set: ms(transit + half) };
}

/** Today's sunrise and sunset as minutes after local midnight (what isNight() and index.html's head take). */
export function sunTimes(day: Date, place: Place): SunTimes {
  const events = sunEvents(day, place);
  if (events === 'day') return { rise: 0, set: 1440 };
  if (events === 'night') return { rise: 1440, set: 0 };
  const minutes = (ms: number) => { const at = new Date(ms); return at.getHours() * 60 + at.getMinutes(); };
  return { rise: minutes(events.rise), set: minutes(events.set) };
}

/** Where the sun is reckoned from when the car's position is not known: the main city of the browser's time zone.
 *  Mainland China is one zone (Shanghai stands for it: Beijing is minutes off, Chengdu about an hour); the
 *  hemisphere is what matters most (a Sydney summer evening is a Shanghai winter one). Unknown zones: none. */
const ZONES: Record<string, [number, number]> = {
  'Asia/Shanghai': [31.2, 121.5], 'Asia/Chongqing': [29.6, 106.5], 'Asia/Chungking': [29.6, 106.5], 'Asia/Harbin': [45.8, 126.5],
  'Asia/Urumqi': [43.8, 87.6], 'Asia/Kashgar': [39.5, 76.0], 'PRC': [31.2, 121.5], 'Asia/Hong_Kong': [22.3, 114.2],
  'Asia/Macau': [22.2, 113.5], 'Asia/Taipei': [25.0, 121.6], 'Asia/Tokyo': [35.7, 139.7], 'Asia/Seoul': [37.6, 127.0],
  'Asia/Singapore': [1.4, 103.8], 'Asia/Kuala_Lumpur': [3.1, 101.7], 'Asia/Bangkok': [13.8, 100.5], 'Asia/Dubai': [25.2, 55.3],
  'Asia/Kolkata': [21.1, 79.1], 'Asia/Jerusalem': [31.8, 35.2], 'Asia/Riyadh': [24.7, 46.7], 'Europe/Istanbul': [41.0, 29.0],
  'Australia/Sydney': [-33.9, 151.2], 'Australia/Melbourne': [-37.8, 145.0], 'Australia/Brisbane': [-27.5, 153.0],
  'Australia/Adelaide': [-34.9, 138.6], 'Australia/Perth': [-32.0, 115.9], 'Australia/Hobart': [-42.9, 147.3],
  'Australia/Darwin': [-12.5, 130.8], 'Australia/Canberra': [-35.3, 149.1], 'Pacific/Auckland': [-36.8, 174.8],
  'Europe/London': [51.5, -0.1], 'Europe/Dublin': [53.3, -6.3], 'Europe/Paris': [48.9, 2.4], 'Europe/Berlin': [52.5, 13.4],
  'Europe/Amsterdam': [52.4, 4.9], 'Europe/Brussels': [50.8, 4.4], 'Europe/Zurich': [47.4, 8.5], 'Europe/Vienna': [48.2, 16.4],
  'Europe/Madrid': [40.4, -3.7], 'Europe/Lisbon': [38.7, -9.1], 'Europe/Rome': [41.9, 12.5], 'Europe/Oslo': [59.9, 10.8],
  'Europe/Stockholm': [59.3, 18.1], 'Europe/Copenhagen': [55.7, 12.6], 'Europe/Helsinki': [60.2, 24.9], 'Europe/Warsaw': [52.2, 21.0],
  'Europe/Prague': [50.1, 14.4], 'America/New_York': [40.7, -74.0], 'America/Chicago': [41.9, -87.6],
  'America/Denver': [39.7, -105.0], 'America/Phoenix': [33.4, -112.1], 'America/Los_Angeles': [34.1, -118.2],
  'America/Toronto': [43.7, -79.4], 'America/Vancouver': [49.3, -123.1], 'America/Mexico_City': [19.4, -99.1],
  'America/Sao_Paulo': [-23.6, -46.6],
};
export function zonePlace(zone: string): Place | null {
  const at = ZONES[zone];
  return at ? { lat: at[0], lon: at[1] } : null;
}

/** A position kept for the sun: rounded to 0.1° (about 10 km), which moves sunset by well under a minute, so the
 *  browser keeps no more than it needs. */
export function roughPlace(lat: number, lon: number): Place {
  return { lat: Math.round(lat * 10) / 10, lon: Math.round(lon * 10) / 10 };
}
