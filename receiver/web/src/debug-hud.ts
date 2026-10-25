/** Debug overlay over the picture (2026-10-16, asked for in the car): a few numbers only, refreshed once a second
 *  while the switch in Display is on. It takes no touches (pointer-events: none), so CarPlay under it works as usual. */
export interface HudSample {
  width: number; height: number; fps: number; hevc: boolean | null;
  videoKbps: number; decodeMs: number; queue: number;
  /** Last ping round trip to the box (the pong queues behind every frame not yet sent), -1 before the first. */
  rttMs: number;
  /** Each audio stream now open (audio.ts describe()), and the music bitrate as the iPhone sends it. */
  audio: { name: string; codec: string; sampleRate: number; channels: number }[];
  musicKbps: number; playing: boolean;
}

const NAMES: Record<string, [string, string]> = {
  media: ['音乐', 'Music'], default: ['播报', 'Prompts'], telephony: ['通话', 'Call'],
  speechrecognition: ['Siri', 'Siri'], alert: ['提示音', 'Alert'],
};

function rate(kbps: number) { return kbps >= 1000 ? `${(kbps / 1000).toFixed(1)} Mbps` : `${Math.round(kbps)} kbps`; }

export function hudLines(s: HudSample, zh: boolean): string[] {
  const i = zh ? 0 : 1;
  const codec = s.hevc === null ? '' : s.hevc ? ' · H.265' : ' · H.264';
  const lines = [
    s.width ? `${s.width}×${s.height} · ${Math.round(s.fps)} fps${codec} · ${rate(s.videoKbps)}` : (zh ? '尚无画面' : 'No picture yet'),
    `${zh ? '解码' : 'Decode'} ${Math.round(s.decodeMs)} ms · ${zh ? '队列' : 'Queue'} ${s.queue} · ${zh ? '往返' : 'RTT'} ${s.rttMs >= 0 ? `${Math.round(s.rttMs)} ms` : '–'}`,
  ];
  const audio = s.audio.map(a => {
    const name = NAMES[a.name]?.[i] ?? a.name;
    const music = a.name === 'media' && s.musicKbps > 0 ? ` ${rate(s.musicKbps)}` : '';
    return `${name} ${a.codec} ${(a.sampleRate / 1000).toFixed(a.sampleRate % 1000 ? 1 : 0)} kHz${a.channels === 1 ? ' ' + (zh ? '单声道' : 'mono') : ''}${music}`;
  });
  lines.push(`${zh ? '声音' : 'Sound'} ${audio.length ? audio.join(' · ') : (zh ? '无' : 'none')}${audio.length && !s.playing ? (zh ? '（静音中）' : ' (silent)') : ''}`);
  return lines;
}
