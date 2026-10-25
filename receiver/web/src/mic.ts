/** Browser microphone uplink: captures PCM and sends it to the CarPlay speech/telephony stream. */

export interface MicRequest {
  sampleRate: number;
  channels: number;
  codec: string;
  samplesPerPacket: number;
  bitrate: number | null;
}

const WORKLET_SOURCE = `
class CarplayMic extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const configured = options && options.processorOptions && options.processorOptions.packetSamples;
    this.packetSamples = configured && configured > 0 ? configured : 320;
    this.buffer = new Float32Array(this.packetSamples);
    this.offset = 0;
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    for (let index = 0; index < channel.length; index += 1) {
      this.buffer[this.offset] = channel[index];
      this.offset += 1;
      if (this.offset === this.packetSamples) {
        const packet = new Float32Array(this.buffer);
        this.port.postMessage(packet, [packet.buffer]);
        this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor('carplay-mic', CarplayMic);
`;

export class MicrophoneUplink {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private encoder: AudioEncoder | null = null;
  private encoderTimestampUs = 0;
  private active = false;
  private workletUrl: string | null = null;
  /** For the viewer log (a call on the F50 drive of 2026-10-13: the other side heard nothing, nothing told why):
   *  how the last start ended (1 live, 2 refused, 3 no microphone, 4 busy, 5 no API, 6 other) and packets sent. */
  private micState = 0;
  private micPackets = 0;
  /** Blocks of samples from the microphone, encoder errors: where a live microphone that sends nothing stops. */
  private micFrames = 0;
  private micEncErrors = 0;
  /** Loudest sample from the microphone in this report, in thousandths of full scale (0: silence). */
  private micPeak = 0;
  report(): Record<string, number> {
    if (!this.micState && !this.micPackets) return {};
    const track = this.stream?.getAudioTracks()[0];
    const out: Record<string, number> = { micState: this.micState, micPackets: this.micPackets, micFrames: this.micFrames, micEncErrors: this.micEncErrors, micPeak: this.micPeak, micGain: micGain(),
      micContext: !this.context ? 0 : this.context.state === 'running' ? 1 : this.context.state === 'suspended' ? 2 : 3,
      micTrack: !track ? 0 : track.readyState === 'ended' ? 3 : track.muted ? 2 : 1, micEncoder: this.encoder ? 1 : 0 };
    this.micPackets = 0; this.micFrames = 0; this.micEncErrors = 0; this.micPeak = 0; return out;
  }

  constructor(
    private readonly send: (payload: Uint8Array, opus: boolean) => void,
    private readonly onStatus: (message: string) => void,
  ) {}

  get isActive(): boolean {
    return this.active;
  }

  async start(request: MicRequest): Promise<void> {
    await this.stop();
    try {
      if (!navigator.mediaDevices?.getUserMedia) { this.micState = 5; throw new Error('getUserMedia is not available'); }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: Math.max(1, Math.min(2, request.channels)),
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const context = new AudioContext({ sampleRate: request.sampleRate });
      await context.resume();
      const url = this.workletSourceUrl();
      await context.audioWorklet.addModule(url);
      const node = new AudioWorkletNode(context, 'carplay-mic', {
        numberOfInputs: 1,
        numberOfOutputs: 0,
        processorOptions: { packetSamples: Math.max(1, request.samplesPerPacket) },
      });
      const source = context.createMediaStreamSource(stream);
      // The XPeng's microphone reaches the browser very quiet (speech peaking at 1% of full scale on the F50 drive of
      // 2026-10-13; the other side of a call heard it faint): raised (micGain), with a limiter against clipping.
      const gain = context.createGain();
      gain.gain.value = micGain();
      const limiter = context.createDynamicsCompressor();
      limiter.threshold.value = -6; limiter.knee.value = 0; limiter.ratio.value = 20; limiter.attack.value = 0.003; limiter.release.value = 0.1;
      source.connect(gain); gain.connect(limiter); limiter.connect(node);
      node.port.onmessage = (event: MessageEvent<Float32Array>) => {
        this.micFrames++;
        let peak = 0; for (const v of event.data) peak = Math.max(peak, Math.abs(v));
        this.micPeak = Math.max(this.micPeak, Math.round(peak * 1000));
        this.onSamples(event.data);
      };
      if (request.codec === 'opus' && typeof AudioEncoder !== 'undefined') {
        const encoder = new AudioEncoder({
          output: (chunk) => {
            const payload = new Uint8Array(chunk.byteLength);
            chunk.copyTo(payload);
            this.micPackets++; this.send(payload, true);
          },
          error: (error) => { this.micEncErrors++; this.onStatus(`Microphone encoder error: ${error.message}`); },
        });
        encoder.configure({
          codec: 'opus',
          sampleRate: request.sampleRate,
          numberOfChannels: 1,
          bitrate: request.bitrate ?? 32_000,
        });
        this.encoder = encoder;
        this.encoderTimestampUs = 0;
      }
      this.stream = stream;
      this.context = context;
      this.node = node;
      this.active = true; this.micState = 1;
      this.onStatus(`Microphone live (${request.sampleRate} Hz, ${request.codec})`);
    } catch (error) {
      const name = (error as Error)?.name;
      if (this.micState !== 5) this.micState = name === 'NotAllowedError' ? 2 : name === 'NotFoundError' ? 3 : name === 'NotReadableError' ? 4 : 6;
      this.onStatus(`Microphone unavailable: ${describeError(error)}`);
      await this.stop();
    }
  }

  async stop(): Promise<void> {
    this.active = false;
    const encoder = this.encoder;
    this.encoder = null;
    if (encoder) {
      try {
        encoder.close();
      } catch {
        // Already closed.
      }
    }
    const node = this.node;
    this.node = null;
    if (node) {
      node.port.onmessage = null;
      try {
        node.disconnect();
      } catch {
        // Already disconnected.
      }
    }
    const context = this.context;
    this.context = null;
    if (context) {
      try {
        await context.close();
      } catch {
        // Already closed.
      }
    }
    const stream = this.stream;
    this.stream = null;
    stream?.getTracks().forEach((track) => track.stop());
  }

  private onSamples(samples: Float32Array): void {
    if (this.encoder) {
      const context = this.context;
      if (!context) return;
      const data = new AudioData({
        format: 'f32-planar',
        sampleRate: context.sampleRate,
        numberOfFrames: samples.length,
        numberOfChannels: 1,
        timestamp: this.encoderTimestampUs,
        data: new Float32Array(samples),
      });
      this.encoderTimestampUs += Math.round((samples.length / context.sampleRate) * 1_000_000);
      try {
        this.encoder.encode(data);
      } catch { this.micEncErrors++; } finally {
        data.close();
      }
      return;
    }
    const pcm = new Uint8Array(samples.length * 2);
    const view = new DataView(pcm.buffer);
    for (let index = 0; index < samples.length; index += 1) {
      const clamped = Math.max(-1, Math.min(1, samples[index]));
      view.setInt16(index * 2, Math.round(clamped * 32767), true);
    }
    this.micPackets++; this.send(pcm, false);
  }

  private workletSourceUrl(): string {
    if (this.workletUrl) return this.workletUrl;
    const blob = new Blob([WORKLET_SOURCE], { type: 'application/javascript' });
    this.workletUrl = URL.createObjectURL(blob);
    return this.workletUrl;
  }
}

/** Microphone gain: 16 (24 dB) unless the page address sets ?micgain= (1 to 64). The owner's choice after the F50
 *  drive of 2026-10-13: at 16 the other side heard the voice best, though also the speakers' echo the browser had
 *  not cancelled (open); ducking the microphone while the far end played only made it rough; at 1 it was faint. */
function micGain(): number {
  const value = Number(new URLSearchParams(location.search).get('micgain'));
  return Number.isFinite(value) && value >= 1 && value <= 64 ? value : 16;
}

function describeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
