// Microphone -> 16 kHz mono PCM16 WAV, entirely in the browser (Web Audio API).
// The backend's existing audio channel reads WAV with soundfile, so no server-side
// transcoding (ffmpeg) is needed.

const TARGET_RATE = 16000;

export class WavRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private chunks: Float32Array[] = [];
  private rate = 48000;
  onLevel: ((level: number) => void) | null = null;

  static supported(): boolean {
    return !!(typeof navigator.mediaDevices?.getUserMedia === "function" && (window.AudioContext || (window as unknown as { webkitAudioContext?: unknown }).webkitAudioContext));
  }

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctx();
    this.rate = this.ctx.sampleRate;
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    this.chunks = [];
    this.node.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(data));
      if (this.onLevel) {
        let peak = 0;
        for (let i = 0; i < data.length; i += 16) peak = Math.max(peak, Math.abs(data[i]));
        this.onLevel(Math.min(1, peak * 1.6));
      }
    };
    this.source.connect(this.node);
    this.node.connect(this.ctx.destination);
  }

  async stop(): Promise<{ blob: Blob; seconds: number }> {
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close();
    const total = this.chunks.reduce((n, c) => n + c.length, 0);
    const merged = new Float32Array(total);
    let off = 0;
    for (const c of this.chunks) {
      merged.set(c, off);
      off += c.length;
    }
    this.chunks = [];
    const pcm = downsample(merged, this.rate, TARGET_RATE);
    return { blob: encodeWav(pcm, TARGET_RATE), seconds: pcm.length / TARGET_RATE };
  }

  cancel(): void {
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.chunks = [];
  }
}

function downsample(input: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return input;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = sum / Math.max(1, end - start); // box filter = simple anti-aliasing
  }
  return out;
}

function encodeWav(samples: Float32Array, rate: number): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const w = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  w(8, "WAVE");
  w(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  w(36, "data");
  v.setUint32(40, samples.length * 2, true);
  let o = 44;
  for (let i = 0; i < samples.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}
