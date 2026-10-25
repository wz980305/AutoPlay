/**
 * Compatible display (2026-10-17). A tester's Tesla on Chrome 113 decoded every frame (fps full, no error) and showed
 * nothing: the low-latency canvas (desynchronized) and the hardware-decoder preference failed there without an error,
 * and both fall back only on one. Compatible display uses neither (about one frame later, the browser picks the
 * decoder). On by default below Chrome 120, the oldest car browser seen working (XPeng G6); the switch in Display
 * overrides that either way for this browser.
 */
export const COMPAT_BELOW_CHROME = 120;

/** saved: '1' or '0' from the switch, anything else for automatic. */
export function compatDisplayOn(saved: string, userAgent: string): boolean {
  if (saved === '1' || saved === '0') return saved === '1';
  const chrome = Number(/Chrome\/(\d+)/.exec(userAgent)?.[1] ?? 0);
  return chrome > 0 && chrome < COMPAT_BELOW_CHROME;
}
