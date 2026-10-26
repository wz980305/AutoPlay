import type { ClientMessage, KnobState, TouchContact } from './protocol';

const MAX_CONTACTS = 2;
const KNOB_FLICK = 127;
/** A finger lifted sooner than this after it came down is reported up this long after the down: a down and an up in
 *  the same instant (a light tap on a slow car panel) read as nothing on the phone (media_performance_audit #16;
 *  xcertplay uses the same 30 ms). */
export const MIN_PRESS_MS = 30;

interface ActivePointer {
  slot: number;
  x: number;
  y: number;
  down: boolean;
  startX: number;
  startY: number;
  downAt: number;
  liftTimer: number;
}

const emptyKnob = (overrides: Partial<KnobState> = {}): KnobState => ({
  select: false,
  home: false,
  back: false,
  x: 0,
  y: 0,
  wheel: 0,
  ...overrides,
});

/** Maps browser pointer/keyboard input to CarPlay touch and knob HID messages. */
export class InputController {
  private readonly pointers = new Map<number, ActivePointer>();
  private pendingFlush = 0;
  /** performance.now() of the latest finger down, for the touch-to-picture measurement. */
  lastDownAt = 0;

  constructor(
    private readonly surface: HTMLElement,
    private readonly send: (message: ClientMessage) => void,
  ) {}

  attach(): void {
    const surface = this.surface;
    surface.style.touchAction = 'none';
    surface.addEventListener('pointerdown', this.onPointerDown, { passive: false });
    surface.addEventListener('pointermove', this.onPointerMove, { passive: false });
    surface.addEventListener('pointerup', this.onPointerUp, { passive: false });
    surface.addEventListener('pointercancel', this.onPointerUp, { passive: false });
    window.addEventListener('keydown', this.onKeyDown);
  }

  detach(): void {
    const surface = this.surface;
    surface.removeEventListener('pointerdown', this.onPointerDown);
    surface.removeEventListener('pointermove', this.onPointerMove);
    surface.removeEventListener('pointerup', this.onPointerUp);
    surface.removeEventListener('pointercancel', this.onPointerUp);
    this.reset();
    window.removeEventListener('keydown', this.onKeyDown);
  }

  private readonly onPointerDown = (event: PointerEvent): void => {
    event.preventDefault();
    if (this.surface.inert || (event.button !== undefined && event.button !== 0) || this.pointers.size >= MAX_CONTACTS) return;
    this.surface.focus({ preventScroll: true });
    this.surface.setPointerCapture(event.pointerId);
    const x = this.normalizeX(event.clientX), y = this.normalizeY(event.clientY);
    const now = performance.now();
    this.pointers.set(event.pointerId, { slot: this.nextSlot(), x, y, down: true, startX: x, startY: y, downAt: now, liftTimer: 0 });
    this.flush();
    this.lastDownAt = now;
  };

  private readonly onPointerMove = (event: PointerEvent): void => {
    const pointer = this.pointers.get(event.pointerId);
    if (!pointer) return;
    event.preventDefault();
    pointer.x = this.normalizeX(event.clientX);
    pointer.y = this.normalizeY(event.clientY);
    this.scheduleFlush();
  };

  private readonly onPointerUp = (event: PointerEvent): void => {
    const pointer = this.pointers.get(event.pointerId);
    if (!pointer || pointer.liftTimer) return;
    event.preventDefault();
    // Release at the last real position; (0,0) can cancel an iPhone button tap.
    if (event.type === 'pointerup') {
      pointer.x = this.normalizeX(event.clientX);
      pointer.y = this.normalizeY(event.clientY);
      // A swipe that moved sends its final point as a move before the up: the animation-frame flush can be
      // starved while the page decodes, and an up alone at the end reads as a tap on the phone (2026-10-23).
      if (Math.abs(pointer.x - pointer.startX) > 0.01 || Math.abs(pointer.y - pointer.startY) > 0.01) this.flush();
      // The minimum press: a finger up within MIN_PRESS_MS of its down stays down until then (a cancel lifts at once).
      const held = performance.now() - pointer.downAt;
      if (held < MIN_PRESS_MS) { pointer.liftTimer = window.setTimeout(() => this.lift(event.pointerId), MIN_PRESS_MS - held); return; }
    }
    this.lift(event.pointerId);
  };

  private lift(pointerId: number): void {
    const pointer = this.pointers.get(pointerId);
    if (!pointer) return;
    pointer.liftTimer = 0;
    pointer.down = false;
    this.flush();
    this.pointers.delete(pointerId);
    if (this.surface.hasPointerCapture?.(pointerId)) this.surface.releasePointerCapture(pointerId);
  }

  /** Every finger up at its last position, now: the page is going away or being frozen (the car's reverse camera,
   *  another app), and a finger left down on the phone would stay down (media_performance_audit #16). */
  releaseAll(): void {
    if (!this.pointers.size) return;
    for (const pointer of this.pointers.values()) { window.clearTimeout(pointer.liftTimer); pointer.liftTimer = 0; pointer.down = false; }
    this.flush();
    this.reset();
  }

  private readonly onKeyDown = (event: KeyboardEvent): void => {
    if (this.surface.inert || event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    if (document.querySelector('dialog[open]')) return;
    if (event.target instanceof Element && (event.target.closest('input, select, textarea, [contenteditable="true"]') || ((event.key === 'Enter' || event.key === ' ') && event.target.closest('button, a')))) return;
    const knob = (overrides: Partial<KnobState>) => {
      event.preventDefault();
      this.send({ type: 'knob', knob: emptyKnob(overrides) });
    };
    switch (event.key) {
      case 'ArrowUp':
        knob({ y: -KNOB_FLICK });
        break;
      case 'ArrowDown':
        knob({ y: KNOB_FLICK });
        break;
      case 'ArrowLeft':
        knob({ x: -KNOB_FLICK });
        break;
      case 'ArrowRight':
        knob({ x: KNOB_FLICK });
        break;
      case 'Enter':
        knob({ select: true });
        break;
      case 'Escape':
      case 'Backspace':
        knob({ back: true });
        break;
      case 'Home':
        knob({ home: true });
        break;
      case 's':
        event.preventDefault();
        this.send({ type: 'siri' });
        break;
      case ' ':
        event.preventDefault();
        this.send({ type: 'media', media: 3 });
        break;
      case 'MediaPlayPause':
        event.preventDefault();
        this.send({ type: 'media', media: 3 });
        break;
      case 'MediaTrackNext':
        event.preventDefault();
        this.send({ type: 'media', media: 4 });
        break;
      case 'MediaTrackPrevious':
        event.preventDefault();
        this.send({ type: 'media', media: 5 });
        break;
      default:
        break;
    }
  };

  private nextSlot(): number {
    const used = new Set(Array.from(this.pointers.values(), (pointer) => pointer.slot));
    for (let slot = 0; slot < MAX_CONTACTS; slot += 1) {
      if (!used.has(slot)) return slot;
    }
    return 0;
  }

  reset(): void {
    if (this.pendingFlush) window.cancelAnimationFrame(this.pendingFlush);
    this.pendingFlush = 0;
    for (const pointer of this.pointers.values()) window.clearTimeout(pointer.liftTimer);
    this.pointers.clear();
  }

  private flush(): void {
    if (this.pendingFlush) window.cancelAnimationFrame(this.pendingFlush);
    this.pendingFlush = 0;
    // The receiver's HID report uses list position as contact slot. Keep holes.
    const contacts: TouchContact[] = [];
    for (const pointer of this.pointers.values()) {
      while (contacts.length <= pointer.slot) {
        contacts.push({ id: contacts.length, x: 0, y: 0, down: false });
      }
      contacts[pointer.slot] = { id: pointer.slot, x: pointer.x, y: pointer.y, down: pointer.down };
    }
    this.send({ type: 'touch', contacts });
  }

  private scheduleFlush(): void {
    if (this.pendingFlush !== 0) return;
    this.pendingFlush = window.requestAnimationFrame(() => {
      this.pendingFlush = 0;
      this.flush();
    });
  }

  private normalizeX(clientX: number): number {
    const rect = this.surface.getBoundingClientRect();
    if (rect.width <= 0) return 0;
    return clamp01((clientX - rect.left) / rect.width);
  }

  private normalizeY(clientY: number): number {
    const rect = this.surface.getBoundingClientRect();
    if (rect.height <= 0) return 0;
    return clamp01((clientY - rect.top) / rect.height);
  }
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}
