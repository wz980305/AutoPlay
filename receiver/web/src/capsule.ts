/** The page's one kind of notice (1.6.2, owner's call: a browser that shows CarPlay is no place for a box that must be
 *  tapped away; 1.6.0-1.6.1 had Apple's alert). toast(): one line, gone by itself after 6 s - what the page handled
 *  itself, or a tap that did not take. stay(): a capsule that stays while there can be no picture until something
 *  changes; with a fix (action) it is a button with a chevron (.tap) that goes there. A passing toast shows over a
 *  staying one and gives it back. Where the capsule sits (the screen's foot, the open panel's top) is the page's
 *  business (main.ts moves the element). */
export type Capsule = { toast(text: string): void; stay(text: string, action?: (() => void) | null): void; unstay(): void };

type Timers = { set(fn: () => void, ms: number): number; clear(id: number): void };
const WINDOW_TIMERS: Timers = { set: (fn, ms) => window.setTimeout(fn, ms), clear: id => window.clearTimeout(id) };
export const TOAST_MS = 6000;

export function capsule(pill: HTMLElement, timers: Timers = WINDOW_TIMERS): Capsule {
  let staying: { text: string; action: (() => void) | null } | null = null;
  let timer = 0;
  const show = (text: string, action: (() => void) | null) => {
    pill.textContent = text; pill.hidden = false; pill.classList.toggle('tap', !!action);
    if (action) { pill.setAttribute('role', 'button'); pill.tabIndex = 0; } else { pill.setAttribute('role', 'status'); pill.removeAttribute('tabindex'); }
  };
  // Only the staying capsule is a button; a passing one over it is not.
  const go = () => { if (!timer) staying?.action?.(); };
  pill.addEventListener('click', go);
  pill.addEventListener('keydown', e => { const key = (e as KeyboardEvent).key; if ((key === 'Enter' || key === ' ') && !timer && staying?.action) { e.preventDefault(); go(); } });
  return {
    toast(text) {
      show(text, null); timers.clear(timer);
      timer = timers.set(() => { timer = 0; if (staying) show(staying.text, staying.action); else pill.hidden = true; }, TOAST_MS);
    },
    stay(text, action = null) { staying = { text, action }; timers.clear(timer); timer = 0; show(text, action); },
    unstay() { if (!staying) return; staying = null; if (!timer) pill.hidden = true; },
  };
}
