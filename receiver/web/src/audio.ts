import { MusicOutput } from './music-output';
import { audioStartTime } from './audio-timing';
import { AudioCodec, type AudioConfigMessage, type AudioPacketMessage } from './protocol';

interface StreamState {
  codec: number;
  sampleRate: number;
  channels: number;
  name: string;
  music: MusicOutput | null;
  decoder: AudioDecoder | null;
  nextPlayTime: number;
  gain: GainNode;
}


/** Decodes and plays CarPlay audio streams (AAC-LC, Opus, LPCM) via Web Audio. */
export class AudioEngine {
  private readonly context: AudioContext;
  private readonly gain: GainNode;
  private readonly streams = new Map<number, StreamState>();
  private readonly streamGains = new Map<string, number>();
  private retainedMusic: MusicOutput | null = null;
  private retainedConfig = "";
  private unlocked = false;
  private masterVolume = 1;
  private lastAudioAt = -Infinity;

  get isPlaying(): boolean {
    return Array.from(this.streams.values()).some(s => s.music?.playing) ||
      (this.context.state === 'running' && performance.now() - this.lastAudioAt < 1800);
  }

  /** Navigation prompts and alerts (audioType "default") boosted by this much through a limiter: in a Tesla the
   *  music goes to the car over Bluetooth at the car's volume while prompts come through the browser, and they were
   *  hard to hear at 1 (2026-10-14). 1 leaves them as sent. */
  private readonly promptBoost: number;
  private promptLimiter: DynamicsCompressorNode | null = null;
  /** Music over the car's Bluetooth: a Tesla took a browser that has an audio output open, even a silent one, for a
   *  music source and switched its media card between it and the iPhone's Bluetooth over and over (2026-10-14). The output is closed
   *  (context suspended) a few seconds after the last stream ends and opened again for the next prompt or call. */
  private readonly idleClose: boolean;
  private idleTimer = 0;
  private sleeping = false;

  constructor(private readonly onError: (message: string) => void, options: { promptBoost?: number; idleClose?: boolean } = {}) {
    this.context = new AudioContext({ latencyHint: 'interactive' });
    this.gain = this.context.createGain();
    this.gain.connect(this.context.destination);
    this.promptBoost = Math.min(8, Math.max(1, options.promptBoost ?? 1));
    this.idleClose = options.idleClose ?? false;
  }

  /** idleClose: open the output for a stream, close it again when none is left. */
  private wake(): void {
    if (!this.idleClose) return;
    window.clearTimeout(this.idleTimer);
    if (this.context.state === 'suspended' && this.unlocked) void this.context.resume().then(() => { this.sleeping = false; }).catch(() => {});
  }
  private sleepWhenIdle(): void {
    if (!this.idleClose) return;
    window.clearTimeout(this.idleTimer);
    this.idleTimer = window.setTimeout(() => {
      if (this.streams.size === 0 && this.context.state === 'running') { this.sleeping = true; void this.context.suspend().catch(() => { this.sleeping = false; }); }
    }, 3000);
  }

  private streamGainValue(name: string): number {
    return (this.streamGains.get(name) ?? 1) * (name === 'default' ? this.promptBoost : 1);
  }

  private streamOutput(name: string): AudioNode {
    if (name !== 'default' || this.promptBoost === 1) return this.gain;
    if (!this.promptLimiter) {
      const limiter = this.context.createDynamicsCompressor();
      limiter.threshold.value = -6; limiter.knee.value = 0; limiter.ratio.value = 20;
      limiter.attack.value = 0.003; limiter.release.value = 0.1;
      limiter.connect(this.gain);
      this.promptLimiter = limiter;
    }
    return this.promptLimiter;
  }

  get isUnlocked(): boolean {
    return this.unlocked && (this.context.state === 'running' || this.sleeping) && Array.from(this.streams.values()).every(s => !s.music || s.music.unlocked);
  }

  /** Must run inside a user gesture so the browser allows audio playback. */
  async unlock(): Promise<void> {
    await Promise.all([this.context.resume(), ...Array.from(this.streams.values()).flatMap(s => s.music ? [s.music.unlock()] : [])]);
    this.unlocked = this.context.state === 'running';
    this.sleeping = false;
    if (this.streams.size === 0) this.sleepWhenIdle();
  }

  setVolume(volume: number): void {
    this.masterVolume = Math.min(1, Math.max(0, volume));
    this.gain.gain.value = this.masterVolume;
    for (const state of this.streams.values()) state.music?.volume(this.masterVolume * (this.streamGains.get(state.name) ?? 1));
  }

  setStreamGain(name: string, value: number): void {
    const gain = Math.min(1, Math.max(0, value));
    this.streamGains.set(name, gain);
    for (const state of this.streams.values()) {
      if (state.name === name) state.gain.gain.value = this.streamGainValue(name);
    }
  }

  activeStreamNames(): string[] {
    return Array.from(new Set(Array.from(this.streams.values(), (state) => state.name))).sort();
  }

  handleConfig(message: AudioConfigMessage): void {
    this.closeStream(message.streamType);
    this.wake();
    const streamGain = this.context.createGain();
    streamGain.gain.value = this.streamGainValue(message.name);
    streamGain.connect(this.streamOutput(message.name));
    const state: StreamState = {
      codec: message.codec,
      sampleRate: message.sampleRate,
      channels: message.channels,
      name: message.name,
      music: null,
      decoder: null,
      nextPlayTime: 0,
      gain: streamGain,
    };
    // Music through a media element: AAC (stream 102) as sent. LPCM (prompts, alerts, "media" PCM) stays on Web
    // Audio for low latency (the wired iPhone's LPCM-as-FLAC element went with wired CarPlay).
    const kind = message.name === 'media' && message.codec === AudioCodec.AacLc ? 'aac' : null;
    if (kind && MusicOutput.supported(kind)) {
      try {
        state.music = (this.retainedMusic && this.retainedConfig === MusicOutput.key(message, kind) ? this.retainedMusic : new MusicOutput(message, this.onError, kind));
        if (this.retainedMusic && this.retainedMusic !== state.music) this.retainedMusic.close();
        this.retainedMusic = null;
        state.music.volume(this.masterVolume * (this.streamGains.get(state.name) ?? 1));
        this.streams.set(message.streamType, state);
        void state.music.unlock().catch(() => {});
        return;
      } catch (error) { this.onError(`Music output configuration: ${describeError(error)}`); }
    }
    if (message.codec === AudioCodec.AacLc || message.codec === AudioCodec.Opus) {
      if (typeof AudioDecoder === 'undefined') {
        this.onError(
          'WebCodecs audio decoding needs a secure context. Open the https:// URL printed by the server.',
        );
        this.streams.set(message.streamType, state);
        return;
      }
      let decoder: AudioDecoder;
      try {
        decoder = new AudioDecoder({
          output: (data) => {
            try {
              this.playAudioData(state, data);
            } finally {
              data.close();
            }
          },
          error: (error) => this.onError(`Audio decoder error: ${error.message}`),
        });
        const config: AudioDecoderConfig =
          message.codec === AudioCodec.AacLc
            ? {
                codec: 'mp4a.40.2',
                sampleRate: message.sampleRate,
                numberOfChannels: message.channels,
                description: message.description.length > 0 ? message.description : undefined,
              }
            : {
                codec: 'opus',
                sampleRate: message.sampleRate,
                numberOfChannels: message.channels,
              };
        decoder.configure(config);
        state.decoder = decoder;
      } catch (error) {
        this.onError(`Audio decoder rejected ${message.codec === AudioCodec.AacLc ? 'AAC' : 'Opus'}: ${describeError(error)}`);
      }
    }
    this.streams.set(message.streamType, state);
  }

  handlePacket(message: AudioPacketMessage): void {
    const state = this.streams.get(message.streamType);
    if (!state) return;
    if (state.music) { state.music.packet(message.data); return; }
    if (state.decoder) {
      try {
        state.decoder.decode(
          new EncodedAudioChunk({
            type: 'key',
            timestamp: message.timestampUs,
            data: message.data,
          }),
        );
      } catch (error) {
        this.onError(`Audio decode failed: ${describeError(error)}`);
      }
      return;
    }
    if (state.codec === AudioCodec.Lpcm) {
      this.playPcm(state, message.data);
    }
  }

  stopStream(streamType: number): void {
    const state = this.streams.get(streamType);
    if (state?.music) {
      this.retainedMusic?.close();
      this.retainedMusic = state.music;
      this.retainedConfig = state.music.configKey;
      state.music.pause();
      state.music = null;
    }
    this.closeStream(streamType);
    this.sleepWhenIdle();
  }

  /** The streams now open, for the debug overlay (debug-hud.ts). */
  describe(): { name: string; codec: string; sampleRate: number; channels: number }[] {
    const codecs: Record<number, string> = { [AudioCodec.AacLc]: 'AAC', [AudioCodec.Opus]: 'Opus', [AudioCodec.Lpcm]: 'PCM' };
    return Array.from(this.streams.values(), s => ({ name: s.name, codec: codecs[s.codec] ?? String(s.codec), sampleRate: s.sampleRate, channels: s.channels }));
  }

  /** Music element counters for the viewer log (music-output.ts). */
  musicReport(): Record<string, number> {
    const total: Record<string, number> = {};
    for (const state of this.streams.values()) for (const [k, v] of Object.entries(state.music?.report() ?? {})) total[k] = (total[k] ?? 0) + v;
    return total;
  }

  pauseMusic(): void {
    for (const state of this.streams.values()) state.music?.pause();
  }

  stopAll(): void {
    for (const streamType of this.streams.keys()) this.closeStream(streamType);
    this.retainedMusic?.close(); this.retainedMusic = null;
    this.lastAudioAt = -Infinity;
  }

  private closeStream(streamType: number): void {
    const state = this.streams.get(streamType);
    if (!state) return;
    this.streams.delete(streamType);
    state.music?.close();
    runCatchingDisconnect(state.gain);
    if (state.decoder) {
      try {
        state.decoder.close();
      } catch {
        // Already closed.
      }
    }
  }

  /** For the viewer log: how far ahead the far end (a call, Siri) is queued, and the reported output latency
   *  (F50 drive 2026-10-13: about 160 ms and 200 ms, so the car's speakers play a call about 0.4 s late). */
  private farQueueMaxMs = 0;
  farReport(): Record<string, number> {
    if (!this.farQueueMaxMs) return {};
    const out = { farQueueMaxMs: Math.round(this.farQueueMaxMs), outLatMs: Math.round(((this.context as AudioContext & {outputLatency?: number}).outputLatency ?? this.context.baseLatency ?? 0) * 1000) };
    this.farQueueMaxMs = 0; return out;
  }

  private playAudioData(state: StreamState, data: AudioData): void {
    if (!this.unlocked) return;
    const numberOfChannels = Math.max(1, data.numberOfChannels);
    const buffer = this.context.createBuffer(numberOfChannels, data.numberOfFrames, data.sampleRate);
    for (let channel = 0; channel < numberOfChannels; channel += 1) {
      const plane = new Float32Array(data.numberOfFrames);
      data.copyTo(plane, { planeIndex: channel, format: 'f32-planar' });
      buffer.copyToChannel(plane, channel);
    }
    const start = this.schedule(state, buffer);
    if (start === null || state.name === 'media') return;
    this.farQueueMaxMs = Math.max(this.farQueueMaxMs, (start - this.context.currentTime) * 1000);
  }

  private playPcm(state: StreamState, payload: Uint8Array): void {
    if (!this.unlocked || payload.length < 2) return;
    const sampleCount = Math.floor(payload.length / 2);
    const channels = Math.max(1, state.channels);
    const frames = Math.max(1, Math.floor(sampleCount / channels));
    const view = new DataView(payload.buffer, payload.byteOffset, payload.byteLength);
    const buffer = this.context.createBuffer(channels, frames, state.sampleRate);
    for (let channel = 0; channel < channels; channel += 1) {
      const plane = new Float32Array(frames);
      for (let frame = 0; frame < frames; frame += 1) {
        const offset = (frame * channels + channel) * 2;
        plane[frame] = view.getInt16(offset, true) / 32768;
      }
      buffer.copyToChannel(plane, channel);
    }
    this.schedule(state, buffer);
  }

  private schedule(state: StreamState, buffer: AudioBuffer): number | null {
    const now = this.context.currentTime;
    const start = audioStartTime(now, state.nextPlayTime, state.name === 'media');
    if (start === null) return null;
    state.nextPlayTime = start;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(state.gain);
    source.onended = () => source.disconnect();
    source.start(state.nextPlayTime);
    this.lastAudioAt = performance.now();
    state.nextPlayTime += buffer.duration;
    return start;
  }
}

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function runCatchingDisconnect(node: AudioNode): void {
  try {
    node.disconnect();
  } catch {
    // Already disconnected.
  }
}
