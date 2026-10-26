import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Exercise the real controller with just the DOM surface it uses; no browser or phone needed.
const source = readFileSync(new URL('./src/input.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { InputController, MIN_PRESS_MS } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const listeners = new Map();
const frames = [];
const messages = [];
let modalOpen = false;
let rect = { left: 100, top: 50, width: 400, height: 225 };
class Element {
  constructor(tag = 'canvas') { this.tag = tag; }
  closest(selector) { return selector.split(',').map((s) => s.trim()).includes(this.tag) ? this : null; }
}
globalThis.Element = Element;
globalThis.document = { querySelector: () => modalOpen ? {} : null };
const timers = [];
let clock = 0;
globalThis.performance = { now: () => clock };
globalThis.window = {
  addEventListener: (name, handler) => listeners.set(name, handler),
  removeEventListener: (name) => listeners.delete(name),
  requestAnimationFrame: (handler) => { frames.push(handler); return frames.length; },
  cancelAnimationFrame: (id) => { frames[id - 1] = () => {}; },
  setTimeout: (handler, ms) => { timers.push({ handler, ms }); return timers.length; },
  clearTimeout: (id) => { if (id) timers[id - 1] = null; },
};
const fireTimers = () => { for (const timer of timers.splice(0)) timer?.handler(); };
const surface = Object.assign(new Element(), {
  inert: false, style: {}, focus() {}, setPointerCapture() {},
  addEventListener: window.addEventListener, removeEventListener: window.removeEventListener,
  getBoundingClientRect: () => rect,
});
const controller = new InputController(surface, (message) => messages.push(message));
controller.attach();
const key = (value, target = surface, extra = {}) => listeners.get('keydown')({ key: value, target, preventDefault() {}, ...extra });
const flush = () => { for (const frame of frames.splice(0)) frame(); };

key('ArrowRight');
assert.equal(messages.pop().knob.x, 127);
key('Enter');
assert.equal(messages.pop().knob.select, true);
key(' ');
assert.deepEqual(messages.pop(), { type: 'media', media: 3 });
surface.inert = true;
key('s');
surface.inert = false;
modalOpen = true;
key('Escape');
modalOpen = false;
for (const tag of ['input', 'select', 'textarea', '[contenteditable="true"]']) key('ArrowUp', new Element(tag));
key('Enter', new Element('button'));
key(' ', new Element('a'));
key('s', surface, { ctrlKey: true });
key('s', surface, { defaultPrevented: true });
assert.equal(messages.length, 0, 'Settings, native controls, browser shortcuts, and disconnected screens must not send CarPlay commands');
key('ArrowLeft', new Element('button'));
assert.equal(messages.pop().knob.x, -127, 'Navigation still works after clicking a toolbar button');

const pointer = (id, x, y, type = 'pointerup') => ({ pointerId: id, clientX: x, clientY: y, type, preventDefault() {} });
listeners.get('pointerdown')(pointer(1, 300, 162.5));
flush();
assert.deepEqual(messages.pop().contacts, [{ id: 0, x: .5, y: .5, down: true }]);
rect = { left: 100, top: 50, width: 225, height: 400 };
listeners.get('pointermove')(pointer(1, 212.5, 250));
listeners.get('pointerdown')(pointer(2, 500, 0));
listeners.get('pointerdown')(pointer(3, 200, 100));
flush();
assert.deepEqual(messages.pop().contacts, [{ id: 0, x: .5, y: .5, down: true }, { id: 1, x: 1, y: 0, down: true }]);
clock += 100;
listeners.get('pointerup')(pointer(1, 0, 0));
listeners.get('pointercancel')(pointer(2, 0, 0, 'pointercancel'));
flush();
assert.ok(messages.pop().contacts.every(c => !c.down), 'Release every contact, including cancelled touches');
messages.length = 0;
// A complete quick click may happen before the next animation frame; a lift within MIN_PRESS_MS of the down is
// reported MIN_PRESS_MS after the down (a down and an up in the same instant read as nothing on the phone).
messages.length = 0;
listeners.get('pointerdown')(pointer(7, 212.5, 250));
clock += 5;
listeners.get('pointerup')(pointer(7, 212.5, 250));
flush();
assert.ok(messages.some(m => m.contacts?.some(c => c.down)), 'A quick tap must deliver a down report');
assert.ok(messages.at(-1).contacts[0].down, 'the up waits for the minimum press');
assert.equal(timers.filter(Boolean).at(-1).ms, MIN_PRESS_MS - 5, 'for the rest of the 30 ms');
fireTimers(); flush();
assert.deepEqual(messages.at(-1).contacts, [{ id: 0, x: .5, y: .5, down: false }], 'Lift preserves the hit target');
messages.length = 0;
listeners.get('pointerdown')(pointer(8, 212.5, 250));
listeners.get('pointerdown')(pointer(9, 212.5, 250));
clock += 100;
listeners.get('pointerup')(pointer(8, 212.5, 250));
listeners.get('pointermove')(pointer(9, 212.5, 250));
flush();
assert.equal(messages.at(-1).contacts[1].id, 1, 'Second finger retains its HID slot');
assert.equal(messages.at(-1).contacts[0].down, false);
// The page goes away or is frozen with a finger down: every contact is lifted at its last position, at once.
listeners.get('pointerup')(pointer(9, 212.5, 250)); fireTimers(); flush(); messages.length = 0;
listeners.get('pointerdown')(pointer(10, 212.5, 250));
controller.releaseAll();
assert.deepEqual(messages.at(-1).contacts, [{ id: 0, x: .5, y: .5, down: false }], 'releaseAll lifts the finger where it was');
assert.equal(timers.filter(Boolean).length, 0, 'and leaves no lift pending');
controller.releaseAll();
assert.equal(messages.at(-1).contacts[0].down, false, 'nothing more to lift sends nothing new');
controller.reset();
controller.detach();
assert.equal(listeners.size, 0);
console.log('Viewer input check passed: keyboard isolation, native controls, portrait/landscape coordinates, multi-touch, minimum press, and release.');
