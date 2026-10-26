import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('./src/audio-timing.ts', import.meta.url), 'utf8').replace(/^import .*?;$/gm, 'const MUSIC_ELEMENT = true;');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { audioStartTime } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
// Observed NAS delivery: ~400 ms bursts carrying 1024-sample / 48 kHz frames.
const duration = 1024 / 48000;
let next = 0, lastEnd = null;
for (let burst = 0; burst < 100; burst++) {
  const arrival = burst * duration * 19 + (burst % 3) * 0.01;
  for (let packet = 0; packet < 19; packet++) {
    const start = audioStartTime(arrival, next, true);
    assert.notEqual(start, null);
    if (lastEnd !== null) assert.ok(Math.abs(start - lastEnd) < 1e-8, 'burst delivery must not overlap or gap queued frames');
    next = start + duration;
    lastEnd = next;
  }
}
assert.equal(audioStartTime(10, 9, true), 10.6, 'underrun rebuilds music reserve');
assert.equal(audioStartTime(10, 10.04, true), 10.04, 'small remaining reserve is not an underrun');
assert.equal(audioStartTime(10, 0, false), 10.12, 'voice keeps lower initial latency');
assert.equal(audioStartTime(10, 13, true), null, 'excess backlog is bounded without rewinding');
console.log('Audio burst scheduling checks passed');
