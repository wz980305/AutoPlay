/**
 * The car's position for the iPhone (docs/LOCATION.md). With the switch on (General → Navigation), the page reads the
 * Tesla browser's navigator.geolocation once a second while it is in view and sends each fix to the box, which hands
 * it to the iPhone as iAP2 LocationInformation (receiver CarLocation). Hidden, closed or without a fix, the page sends
 * nothing, and after 2.5 s the box stops too: the iPhone goes on with its own GNSS.
 *
 * getCurrentPosition every second, as Tesla Android has run in Teslas since 2023.32.1: on a 2020 build watchPosition
 * got no prompt and an error (Leaflet #7157), and a 2026 build calls a watcher only when the position changes. What
 * the browser returns is the car's own position with speed, heading and altitude; its accuracy can be the placeholder
 * 9999.99 and its timestamp a constant that is not epoch time (tesla-pi, Model 3 Highland, Chromium 148), so the box
 * judges freshness by the position and its own clock, not by these.
 */
export interface Fix {
  lat: number;
  lon: number;
  /** Horizontal accuracy in metres (coords.accuracy). */
  acc?: number;
  alt?: number;
  /** m/s. */
  speed?: number;
  /** Degrees clockwise from true north; absent when standing still. */
  heading?: number;
  /** position.timestamp: when the browser got the fix (ms since 1970). */
  time: number;
  /** The browser's IANA time zone, for the box's "auto" datum (1.5.0); absent when the browser names none. */
  zone?: string;
}

const finite = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isFinite(value);

/** The fields of a browser fix the box uses; null when it has no usable position. */
export function toFix(position: GeolocationPosition): Fix | null {
  const c = position.coords;
  if (!finite(c.latitude) || !finite(c.longitude) || Math.abs(c.latitude) > 90 || Math.abs(c.longitude) > 180) return null;
  const fix: Fix = { lat: c.latitude, lon: c.longitude, time: Math.round(finite(position.timestamp) ? position.timestamp : Date.now()) };
  if (finite(c.accuracy) && c.accuracy > 0) fix.acc = Math.round(c.accuracy * 100) / 100;
  if (finite(c.altitude)) fix.alt = Math.round(c.altitude * 10) / 10;
  if (finite(c.speed) && c.speed >= 0) fix.speed = Math.round(c.speed * 100) / 100;
  if (finite(c.heading) && c.heading >= 0) fix.heading = Math.round(c.heading * 10) / 10;
  return fix;
}

export type Permission = 'granted' | 'denied' | 'unavailable';

/** Turning the switch on asks the browser once (its prompt the first time); a refusal leaves the switch off. */
export function askLocation(geo: Geolocation | undefined, timeoutMs = 20_000): Promise<Permission> {
  if (!geo) return Promise.resolve('unavailable');
  return new Promise(resolve => {
    try {
      geo.getCurrentPosition(() => resolve('granted'), failure => resolve(failure.code === 1 ? 'denied' : 'unavailable'),
        { enableHighAccuracy: true, maximumAge: 0, timeout: timeoutMs });
    } catch { resolve('unavailable'); }
  });
}

/** China's GCJ-02 (the same formula as the box's ChinaDatum): the published offset of a few hundred metres. */
const A = 6378245.0, EE = 0.00669342162296594323;
export function inChina(lat: number, lon: number): boolean { return lon >= 72.004 && lon <= 137.8347 && lat >= 0.8293 && lat <= 55.8271; }
/** Mainland China's IANA time zones with their older names (the box's ChinaDatum.mainlandZone has the same list):
 *  Hong Kong, Macau and Taipei, inside the same rectangle, have their own. */
const MAINLAND_ZONES = new Set(['asia/shanghai', 'asia/urumqi', 'asia/chongqing', 'asia/chungking', 'asia/harbin', 'asia/kashgar', 'prc']);
export function mainlandZone(zone: string | null | undefined): boolean { return !!zone && MAINLAND_ZONES.has(zone.trim().toLowerCase()); }
/** The browser's time zone; '' when it will not say. */
export function browserZone(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch { return ''; }
}
/** What the "auto" datum comes to (1.5.0): GCJ-02 where the browser says mainland China - a China-market Model 3's
 *  browser gave GCJ-02 (owner's check against the iPhone's Compass, 2026-11-10) - and WGS-84 everywhere else. */
export function autoDatum(lat: number, lon: number, zone: string | null | undefined): 'gcj02' | 'wgs84' {
  return mainlandZone(zone) && inChina(lat, lon) ? 'gcj02' : 'wgs84';
}
export function wgsToGcj(lat: number, lon: number): [number, number] {
  if (!inChina(lat, lon)) return [lat, lon];
  const x = lon - 105, y = lat - 35, PI = Math.PI;
  let dLat = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
  dLat += (20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2 / 3;
  dLat += (20 * Math.sin(y * PI) + 40 * Math.sin(y / 3 * PI)) * 2 / 3;
  dLat += (160 * Math.sin(y / 12 * PI) + 320 * Math.sin(y * PI / 30)) * 2 / 3;
  let dLon = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
  dLon += (20 * Math.sin(6 * x * PI) + 20 * Math.sin(2 * x * PI)) * 2 / 3;
  dLon += (20 * Math.sin(x * PI) + 40 * Math.sin(x / 3 * PI)) * 2 / 3;
  dLon += (150 * Math.sin(x / 12 * PI) + 300 * Math.sin(x / 30 * PI)) * 2 / 3;
  const rad = lat / 180 * PI, magic = 1 - EE * Math.sin(rad) ** 2, sqrtMagic = Math.sqrt(magic);
  dLat = dLat * 180 / (A * (1 - EE) / (magic * sqrtMagic) * PI);
  dLon = dLon * 180 / (A / sqrtMagic * Math.cos(rad) * PI);
  return [lat + dLat, lon + dLon];
}
export function gcjToWgs(lat: number, lon: number): [number, number] {
  if (!inChina(lat, lon)) return [lat, lon];
  let wLat = lat, wLon = lon;
  for (let i = 0; i < 30; i++) {
    const [gLat, gLon] = wgsToGcj(wLat, wLon), eLat = gLat - lat, eLon = gLon - lon;
    wLat -= eLat; wLon -= eLon;
    if (Math.abs(eLat) < 1e-10 && Math.abs(eLon) < 1e-10) break;
  }
  return [wLat, wLon];
}

/** A position as the iPhone's Compass app writes it (whole seconds), to tell the two datums apart by eye. */
export function compassText(lat: number, lon: number, zh: boolean): string {
  const part = (value: number, positive: string, negative: string) => {
    let total = Math.round(Math.abs(value) * 3600);
    const d = Math.floor(total / 3600); total -= d * 3600;
    const m = Math.floor(total / 60), sec = total - m * 60;
    const side = value >= 0 ? positive : negative;
    return `${d}°${m}′${sec}″ ${side}`;
  };
  return zh ? `${part(lat, '北纬', '南纬')}  ${part(lon, '东经', '西经')}` : `${part(lat, 'N', 'S')}  ${part(lon, 'E', 'W')}`;
}

const READ: PositionOptions = { enableHighAccuracy: true, maximumAge: 0, timeout: 3000 };

/** Reads a fix every [interval] ms while on and in view, one read at a time. Counters go into the page's stats. */
export class LocationFeed {
  private on = false;
  private timer = 0;
  private readingSince: number | null = null;
  sent = 0;
  failed = 0;
  denied = false;
  lastAccuracy = 0;

  constructor(
    private readonly deliver: (fix: Fix) => void,
    private readonly geo: Geolocation | undefined,
    private readonly visible: () => boolean,
    private readonly onDenied: () => void = () => {},
    private readonly interval = 1000,
    private readonly now: () => number = () => performance.now(),
  ) {}

  get enabled(): boolean { return this.on; }

  setEnabled(on: boolean): void {
    if (on === this.on) return;
    this.on = on;
    window.clearInterval(this.timer);
    this.timer = 0;
    this.readingSince = null;
    if (on && this.geo) { this.denied = false; this.timer = window.setInterval(() => this.read(), this.interval); this.read(); }
  }

  /** The counters since the last call, for the stats message (numbers only). */
  take(): Record<string, number> {
    if (!this.on) return {};
    const out: Record<string, number> = { locSent: this.sent, locFailed: this.failed, locAcc: this.lastAccuracy };
    if (this.denied) out.locDenied = 1;
    this.sent = 0; this.failed = 0;
    return out;
  }

  private read(): void {
    if (!this.on || !this.geo || !this.visible()) return;
    // A read the browser never answered (seen with location providers that hang) is given up after 5 s.
    if (this.readingSince !== null && this.now() - this.readingSince < 5000) return;
    const started = this.readingSince = this.now();
    try {
      this.geo.getCurrentPosition(position => {
        if (this.readingSince === started) this.readingSince = null;
        const fix = toFix(position);
        if (!fix || !this.on) return;
        this.sent++; this.lastAccuracy = fix.acc ?? 0;
        this.deliver(fix);
      }, failure => {
        if (this.readingSince === started) this.readingSince = null;
        this.failed++;
        if (failure.code === 1 && !this.denied) { this.denied = true; this.onDenied(); }
      }, READ);
    } catch { this.readingSince = null; this.failed++; }
  }
}
