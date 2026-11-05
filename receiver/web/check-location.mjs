// Car location (1.4.0, docs/LOCATION.md): what the page takes from the Tesla browser and sends to the box.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
async function load(name) {
  const source = readFileSync(new URL(`./src/${name}.ts`, import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
}
let intervals = 0;
globalThis.window = { setInterval: () => ++intervals, clearInterval: () => {} };
const { toFix, askLocation, LocationFeed, wgsToGcj, gcjToWgs, inChina, compassText } = await load('location');

const position = (coords, timestamp = 4242424) => ({ coords: { accuracy: 9999.99, altitude: null, speed: null, heading: null, ...coords }, timestamp });
const meters = (a, b, c, d) => {
  const r = Math.PI / 180, h = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.sqrt(h));
};

{ // A 2026 Tesla browser (tesla-pi, Chromium 148): placeholder accuracy and a constant non-epoch timestamp pass through
  // untouched (the box decides); speed, heading and altitude are kept, rounded.
  const fix = toFix(position({ latitude: 22.5431, longitude: 114.0579, speed: 0, heading: 203.77, altitude: 51.35 }));
  assert.deepEqual(fix, { lat: 22.5431, lon: 114.0579, time: 4242424, acc: 9999.99, alt: 51.4, speed: 0, heading: 203.8 });
  const still = toFix(position({ latitude: 31.2304, longitude: 121.4737, speed: null, heading: NaN }));
  assert.equal('speed' in still || 'heading' in still || 'alt' in still, false, 'unknown fields are left out, never sent as 0');
  assert.equal(toFix(position({ latitude: NaN, longitude: 121 })), null);
  assert.equal(toFix(position({ latitude: 95, longitude: 121 })), null);
}
{ // GCJ-02 (Shenzhen Civic Center): ~600 m south-east of WGS-84 there (the formula matched a Tesla's own GCJ-02 for a
  // car in Shenzhen to about a metre, fleet-telemetry #392), the same as the box's ChinaDatum, inverting to well under
  // a centimetre, and nothing moves outside mainland China.
  const [gLat, gLon] = wgsToGcj(22.5431, 114.0579);
  assert.ok(meters(gLat, gLon, 22.54038281, 114.06301400) < 0.01, 'the box computes the same');
  assert.ok(gLat < 22.5431 && gLon > 114.0579 && meters(22.5431, 114.0579, gLat, gLon) > 400 && meters(22.5431, 114.0579, gLat, gLon) < 800);
  const [wLat, wLon] = gcjToWgs(gLat, gLon);
  assert.ok(meters(wLat, wLon, 22.5431, 114.0579) < 0.01, 'inverts');
  assert.deepEqual(wgsToGcj(-33.8688, 151.2093), [-33.8688, 151.2093]);
  assert.equal(inChina(22.54, 113.95), true); assert.equal(inChina(-33.87, 151.21), false);
}
{ // Written as the iPhone's Compass app writes it.
  assert.equal(compassText(22.5431, 114.0579, true), '22°32′35″ 北纬  114°3′28″ 东经');
  assert.equal(compassText(-33.8688, 151.2093, false), '33°52′8″ S  151°12′33″ E');
  assert.equal(compassText(0.99999999, 10, false), '1°0′0″ N  10°0′0″ E', 'seconds round up into minutes and degrees');
}
{ // Turning the switch on asks the browser once; its answer decides.
  assert.equal(await askLocation(undefined), 'unavailable');
  assert.equal(await askLocation({ getCurrentPosition: (ok, fail) => fail({ code: 1 }) }), 'denied');
  assert.equal(await askLocation({ getCurrentPosition: (ok, fail) => fail({ code: 3 }) }), 'unavailable');
  assert.equal(await askLocation({ getCurrentPosition: ok => ok(position({ latitude: 1, longitude: 2 })) }), 'granted');
}
{ // One read at a time, only in view, a hung read given up after 5 s, a refusal reported once.
  let now = 0, visible = true, calls = [], denied = 0;
  const geo = { getCurrentPosition: (ok, fail, options) => { calls.push({ ok, fail, options }); } };
  const sent = [];
  const feed = new LocationFeed(fix => sent.push(fix), geo, () => visible, () => denied++, 1000, () => now);
  feed.setEnabled(true);
  assert.equal(calls.length, 1, 'reads at once');
  assert.deepEqual(calls[0].options, { enableHighAccuracy: true, maximumAge: 0, timeout: 3000 });
  now = 1000; feed.read(); assert.equal(calls.length, 1, 'not while a read is out');
  calls[0].ok(position({ latitude: 22.5, longitude: 113.9, speed: 12 }));
  assert.equal(sent.length, 1);
  now = 2000; feed.read(); assert.equal(calls.length, 2);
  now = 8000; feed.read(); assert.equal(calls.length, 3, 'a read unanswered for 5 s is given up');
  visible = false; now = 9000; calls[2].ok(position({ latitude: 22.5, longitude: 113.9 })); now = 10000; feed.read();
  assert.equal(calls.length, 3, 'nothing while hidden');
  visible = true; feed.read(); calls[3].fail({ code: 1 }); feed.read(); calls[4].fail({ code: 1 });
  assert.equal(denied, 1, 'a refusal is reported once');
  assert.deepEqual(feed.take(), { locSent: 2, locFailed: 2, locAcc: 9999.99, locDenied: 1 });
  assert.deepEqual(feed.take(), { locSent: 0, locFailed: 0, locAcc: 9999.99, locDenied: 1 }, 'counts start over');
  feed.setEnabled(false);
  calls[1].ok(position({ latitude: 22.6, longitude: 113.9 }));
  assert.equal(sent.length, 2, 'a read answered after the switch went off is not sent');
  assert.deepEqual(feed.take(), {});
}
console.log('Car location: Tesla browser quirks passed through, GCJ-02 both ways, Compass format, one read at a time, only in view.');
