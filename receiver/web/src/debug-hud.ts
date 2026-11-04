/** Debug overlay over the picture (2026-10-16, asked for in the car): a few numbers only, refreshed once a second
 *  while the switch in Display is on. It takes no touches (pointer-events: none), so CarPlay under it works as usual.
 *  Two lines since 1.3.0: the page plays no sound, so the sound line went with it. */
export interface HudSample {
  width: number; height: number; fps: number; hevc: boolean | null;
  videoKbps: number; decodeMs: number; queue: number;
  /** Last ping round trip to the box (the pong queues behind every frame not yet sent), -1 before the first. */
  rttMs: number;
}

function rate(kbps: number) { return kbps >= 1000 ? `${(kbps / 1000).toFixed(1)} Mbps` : `${Math.round(kbps)} kbps`; }

export function hudLines(s: HudSample, zh: boolean): string[] {
  const codec = s.hevc === null ? '' : s.hevc ? ' · H.265' : ' · H.264';
  return [
    s.width ? `${s.width}×${s.height} · ${Math.round(s.fps)} fps${codec} · ${rate(s.videoKbps)}` : (zh ? '尚无画面' : 'No picture yet'),
    `${zh ? '解码' : 'Decode'} ${Math.round(s.decodeMs)} ms · ${zh ? '队列' : 'Queue'} ${s.queue} · ${zh ? '往返' : 'RTT'} ${s.rttMs >= 0 ? `${Math.round(s.rttMs)} ms` : '–'}`,
  ];
}
