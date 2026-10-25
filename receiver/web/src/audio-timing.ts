/** Preserve queued samples across packet bursts; never rewind scheduled audio. */
export function audioStartTime(now: number, next: number, media: boolean): number | null {
  const target = media ? 0.6 : 0.12;
  // Bound backlog without overlapping buffers already submitted to Web Audio.
  if (next > now + 2) return null;
  return next <= now + 0.005 ? now + target : next;
}
