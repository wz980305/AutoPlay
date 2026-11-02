/** Preserve queued samples across packet bursts; never rewind scheduled audio. A media stream would get a 1.0 s
 *  target (the iPhone's packets over Wi-Fi come with ~400 ms gaps every few seconds, F50 2026-10-12); since 1.1.0 the
 *  page drops music, so only the 0.12 s voice target is in use. */
export function audioStartTime(now: number, next: number, media: boolean): number | null {
  const target = media ? 1.0 : 0.12;
  // Bound backlog without overlapping buffers already submitted to Web Audio.
  if (next > now + 2) return null;
  return next <= now + 0.005 ? now + target : next;
}
