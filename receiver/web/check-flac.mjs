// FLAC-in-MP4 framing of the wired iPhone's LPCM must be lossless and decodable: wrap 300 blocks of
// random stereo PCM (frame numbers beyond one byte), decode with ffmpeg, compare byte for byte.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import ts from 'typescript';
const source = readFileSync(new URL('./src/flac-mp4.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { flacInit, flacFrame, flacFragment, FLAC_BLOCK } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const rate = 48000, channels = 2, blocks = 300;
const pcm = new Uint8Array(blocks * FLAC_BLOCK * channels * 2);
let seed = 12345;
for (let i = 0; i < pcm.length; i++) { seed = (seed * 1103515245 + 12345) >>> 0; pcm[i] = seed >>> 24; }
const parts = [flacInit(rate, channels)];
const step = FLAC_BLOCK * channels * 2;
for (let n = 0; n < blocks; n++) {
  parts.push(flacFragment(n + 1, n * FLAC_BLOCK, flacFrame(n, rate, channels, pcm.subarray(n * step, (n + 1) * step)), FLAC_BLOCK));
}
const dir = mkdtempSync(join(tmpdir(), 'flac-check-'));
const file = join(dir, 'lpcm.mp4');
writeFileSync(file, Buffer.concat(parts));
let decoded;
try {
  decoded = execFileSync('ffmpeg', ['-v', 'error', '-i', file, '-f', 's16le', '-acodec', 'pcm_s16le', '-'], { maxBuffer: 1 << 26 });
} catch (error) {
  if (error.code === 'ENOENT') { console.log('FLAC check skipped: ffmpeg not installed'); process.exit(0); }
  throw error;
}
assert.equal(decoded.length, pcm.length, 'every sample comes back');
assert.ok(Buffer.from(pcm).equals(decoded), 'samples are bit-exact');
console.log(`FLAC framing: ${blocks} blocks (${(blocks * FLAC_BLOCK / rate).toFixed(1)} s) decoded bit-exact by ffmpeg`);
