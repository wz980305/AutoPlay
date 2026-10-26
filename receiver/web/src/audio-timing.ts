import { MUSIC_ELEMENT } from './flags';
/** Preserve queued samples across packet bursts; never rewind scheduled audio. Music through Web Audio (no media
 *  element) gets a 1.0 s target: the iPhone's packets over Wi-Fi come with ~400 ms gaps every few seconds (F50,
 *  2026-10-12), which the element's own 1 s cushion absorbs when it is in use (music-output.ts). */
export function audioStartTime(now: number, next: number, media: boolean): number | null {
  const target = media ? (MUSIC_ELEMENT ? 0.6 : 1.0) : 0.12;
  // Bound backlog without overlapping buffers already submitted to Web Audio.
  if (next > now + 2) return null;
  return next <= now + 0.005 ? now + target : next;
}
