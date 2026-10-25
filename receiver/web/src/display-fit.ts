/** Match aspect rather than blindly multiplying by DPR (a 4K car panel need not decode 4K). */
export function suggestedResolution(width: number, height: number) {
  const ratio = Math.min(4, Math.max(0.25, width / Math.max(1, height)));
  const long = Math.max(1280, Math.min(1920, Math.max(width, height)));
  let w = ratio >= 1 ? long : long * ratio;
  let h = ratio >= 1 ? long / ratio : long;
  const grow = Math.max(1, 480 / Math.min(w, h));
  w *= grow; h *= grow;
  return { width: Math.round(w / 2) * 2, height: Math.round(h / 2) * 2 };
}
export function aspectChanged(a: {width: number; height: number}, b: {width: number; height: number}) {
  return Math.abs((a.width / a.height) / (b.width / b.height) - 1) > 0.025;
}
/** Shapes within 20% of each other (the car's page 1280x756 vs fullscreen 1280x846) are not renegotiated
 *  outside fullscreen; clearly different ones (portrait, split screen) are, at once. */
export function closeShape(a: {width: number; height: number}, b: {width: number; height: number}) {
  return a.width > 0 && a.height > 0 && b.width > 0 && b.height > 0 &&
    Math.abs((a.width / a.height) / (b.width / b.height) - 1) <= 0.2;
}
/** Whether to renegotiate CarPlay to `target`. A close shape is renegotiated in fullscreen only once: when the
 *  current size was not itself set for fullscreen on this browser (`fullscreenSize`). The car's fullscreen is not
 *  always the same height (XPeng, 2026-10-13: 876x579 or 876x641 CSS px, its dock shown or not), and switching
 *  between 1280x846 and 1280x936 reconnected CarPlay, a crackle and seconds without a picture, on most entries. */
export function renegotiate(display: {width: number; height: number}, target: {width: number; height: number}, fullscreen: boolean, fullscreenSize: string) {
  if (!aspectChanged(display, target)) return false;
  return !(closeShape(display, target) && (!fullscreen || fullscreenSize === `${display.width}x${display.height}`));
}
/** The picture always fills the view, stretched per axis: no black bars (user 2026-10-12). A close shape
 *  stays stretched; a clearly different one is shown stretched only until CarPlay is renegotiated.
 *  Touch input is normalized per axis, so it stays exact. */
export function shownSize(width: number, height: number, viewWidth: number, viewHeight: number) {
  if (width <= 0 || height <= 0) return { width: 0, height: 0 };
  return { width: viewWidth, height: viewHeight };
}
