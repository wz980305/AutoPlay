/** Match aspect rather than blindly multiplying by DPR (a 4K car panel need not decode 4K): the long side 1280 to
 *  `max` (1920; auto with a fast decoder asks for up to 2560, as owners of 2.5K screens set by hand, 2026-10-19). */
export function suggestedResolution(width: number, height: number, max = 1920) {
  const ratio = Math.min(4, Math.max(0.25, width / Math.max(1, height)));
  const long = Math.max(1280, Math.min(max, Math.max(width, height)));
  let w = ratio >= 1 ? long : long * ratio;
  let h = ratio >= 1 ? long / ratio : long;
  const grow = Math.max(1, 480 / Math.min(w, h));
  w *= grow; h *= grow;
  return { width: Math.round(w / 2) * 2, height: Math.round(h / 2) * 2 };
}
/** The window's own size for the normal mode (no upsize to 1280): the CSS size times the pixels used, a minimum
 *  width of 720 (CarPlay's UI is cramped below that in the 1/3 split) and the same maximum (1920; 2560 with a fast
 *  decoder). A larger window keeps its true size; clarity may drop. */
export function windowResolution(width: number, height: number, max = 1920, minWidth = 720) {
  const long = Math.max(width, height);
  let factor = Math.max(1, minWidth / Math.max(1, width));
  if (long * factor > max) factor = max / Math.max(1, long);
  return { width: Math.round(width * factor / 2) * 2, height: Math.round(height * factor / 2) * 2 };
}
export function aspectChanged(a: {width: number; height: number}, b: {width: number; height: number}) {
  return Math.abs((a.width / a.height) / (b.width / b.height) - 1) > 0.025;
}
/** The picture always fills the view, stretched per axis: no black bars (user 2026-10-12). A close shape
 *  stays stretched; a clearly different one is shown stretched only until CarPlay is renegotiated.
 *  Touch input is normalized per axis, so it stays exact. */
export function shownSize(width: number, height: number, viewWidth: number, viewHeight: number) {
  if (width <= 0 || height <= 0) return { width: 0, height: 0 };
  return { width: viewWidth, height: viewHeight };
}

export interface Area { width: number; height: number }
export interface AreaDisplay { width: number; height: number; hevc: boolean; areas?: Area[]; area?: number }
/** Window shapes declared as CarPlay view areas, and kept per browser and orientation. 4 at first (2026-10-14, chosen,
 *  not a protocol limit: DiPlay sets none); 8 since a car with a split screen shows more (user 2026-10-21). The
 *  receiver's DisplayState.MAX_AREAS must allow as many. */
export const MAX_AREAS = 8;
/** 60 fps the browser's decoder cannot keep up with: the page catches up at a keyframe now and then (video.ts), each a
 *  visible jump. This many 10 s reports in a row with at least two catch-ups each take automatic display to 30 fps
 *  (a Zeekr 7X decodes about 50 a second, 2026-10-19). Returns the new run of such reports and whether to lower now. */
export const BEHIND_REPORTS = 2;
export function frameRateCheck(run: number, caughtUp: number, fps: number): { run: number; lower: boolean } {
  const next = caughtUp >= 2 && fps === 60 ? run + 1 : 0;
  return next >= BEHIND_REPORTS ? { run: 0, lower: true } : { run: next, lower: false };
}
/** Both orientations are declared together only while the stream grows by at most this much over one orientation's. */
export const MIXED_GROWTH = 1.1;
/** A window's shape as remembered for view areas: its CSS size times the pixels used (1, or the device pixel ratio with
 *  a fast decoder), not yet fitted to the stream's limits: areaPlan fits the whole set at once, so the shapes keep their
 *  true proportions (2026-10-22: each fitted on its own, a split screen's third grew to 1280 like the full screen, and
 *  CarPlay, which lays out by physical width, showed both the same). */
export function windowShape(cssWidth: number, cssHeight: number, pixels: number): Area {
  return { width: Math.max(2, Math.round(cssWidth * pixels / 2) * 2), height: Math.max(2, Math.round(cssHeight * pixels / 2) * 2) };
}
/** The factor that brings a stream of `width` x `height` (the envelope of the shapes) within the auto limits:
 *  the long side at most `max`, the short side at least 480. A window smaller than 1280 keeps its true size: forcing
 *  1280 made a 2/3 window as wide as the full one, and it then changed size when the full shape joined (2026-10-23). */
function fitFactor(width: number, height: number, max: number) {
  const long = Math.max(width, height), short = Math.min(width, height);
  const factor = long > max ? max / long : 1;
  return Math.max(factor, 480 / Math.max(1, short));
}
/** View areas (2026-10-14): each window shape the browser has shown (normal, fullscreen, the car's dock shown or not)
 *  becomes an area at the stream's top left, the stream as large as all of them. A shape seen before is reached by
 *  switching area, without reconnecting CarPlay; a new shape, or one that wants a clearly sharper size, declares the
 *  areas again (one reconnect). Returns what to send and the shapes to keep, or null when nothing changes.
 *  The shapes are kept most recently used last; the areas declared are the most recent ones, ordered by size, so the
 *  same shapes always make the same areas whichever of them the window has now (2026-10-21). */
export function areaPlan<T extends AreaDisplay>(display: T, target: Area, hevc: boolean, known: Area[], max = 1920): { display: T; shapes: Area[] } | null {
  const landscape = (s: Area) => s.width >= s.height, wide = landscape(target);
  const all = known.filter(s => s.width > 0 && s.height > 0).map(s => ({ width: s.width, height: s.height }));
  let found = all.findIndex(s => landscape(s) === wide && !aspectChanged(s, target));
  let entry = found >= 0 ? all.splice(found, 1)[0] : { ...target };
  if (target.width * target.height > entry.width * entry.height * 1.2) entry = { ...target };   // sharper (a fast decoder's real pixels): worth one reconnect
  all.push(entry);
  // At most MAX_AREAS of each orientation are remembered.
  const kept = all.filter((s, i) => all.slice(i + 1).filter(n => landscape(n) === landscape(s)).length < MAX_AREAS);
  // Shapes of the window's orientation are declared: a landscape and a portrait shape together make the stream as
  // large as both, a near-square frame the iPhone has to encode (xcertplay 1836c27; 1920x1080 with 1082x1280 would be
  // 1920x1280). The most recent shapes of both join when the stream hardly grows: a split screen turns the car's window
  // portrait and back (XPeng with fnOS beside CarPlay, 2026-10-19: 1372x1260 with 1162x1280 is 1372x1280, yet every
  // open and close of the panel renegotiated). Otherwise turning is one reconnect.
  let chosen = kept.filter(s => landscape(s) === wide).slice(-MAX_AREAS);
  const recent = kept.slice(-MAX_AREAS);
  const ofOrientation = (o: boolean) => recent.filter(s => landscape(s) === o);
  // A clearly portrait window must not share a landscape stream: the phone keeps the stream's landscape layout and
  // squeezes it into the portrait area (the 1/3 split, 2026-10-23). It gets its own portrait stream instead, one
  // reconnect when turning. A near-square portrait still joins, so a car's dock opening and closing does not.
  const mixedAspect = Math.max(...recent.map(s => s.width)) / Math.max(1, Math.max(...recent.map(s => s.height)));
  const targetAspect = target.width / Math.max(1, target.height);
  const portraitInLandscape = !wide && mixedAspect >= 1 && Math.abs(mixedAspect / targetAspect - 1) > 0.25;
  if (!portraitInLandscape && recent.some(s => landscape(s) !== wide) &&
      pixels(recent) <= MIXED_GROWTH * Math.max(pixels(ofOrientation(true)), pixels(ofOrientation(false)))) chosen = recent;
  chosen = [...chosen].sort((a, b) => a.width - b.width || a.height - b.height);
  const at = chosen.indexOf(entry);
  // One factor for all: the stream within its limits, every area the same share of it as its window of the screen.
  const factor = fitFactor(Math.max(...chosen.map(s => s.width)), Math.max(...chosen.map(s => s.height)), max);
  const fitted = chosen.map(s => ({ width: Math.round(s.width * factor / 2) * 2, height: Math.round(s.height * factor / 2) * 2 }));
  const width = Math.max(...fitted.map(s => s.width)), height = Math.max(...fitted.map(s => s.height));
  const areas = fitted.length > 1 ? fitted : [];
  const declared = display.areas ?? [];
  const same = display.width === width && display.height === height && display.hevc === hevc &&
    declared.length === areas.length && declared.every((a, i) => a.width === areas[i].width && a.height === areas[i].height);
  if (same) return areas.length && (display.area ?? 0) !== at ? { display: { ...display, area: at }, shapes: kept } : null;
  return { display: { ...display, width, height, hevc, areas, area: areas.length ? at : 0 }, shapes: kept };
}
/** The declared area with `target`'s shape, or -1 (none, or no areas declared). */
export function areaFor(display: AreaDisplay, target: Area) {
  return display.areas && display.areas.length > 1 ? display.areas.findIndex(s => !aspectChanged(s, target)) : -1;
}
function pixels(shapes: Area[]) {
  return shapes.length ? Math.max(...shapes.map(s => s.width)) * Math.max(...shapes.map(s => s.height)) : 0;
}
/** Whether `next` keeps the stream the phone was told, only the area in use differing: no reconnect. */
export function sameStream(display: AreaDisplay & { fps?: number; uiScale?: number }, next: AreaDisplay & { fps?: number; uiScale?: number }) {
  const a = display.areas ?? [], b = next.areas ?? [];
  return display.width === next.width && display.height === next.height && display.hevc === next.hevc &&
    display.fps === next.fps && display.uiScale === next.uiScale &&
    a.length === b.length && a.every((s, i) => s.width === b[i].width && s.height === b[i].height);
}
/** Whether the display the phone was told already has `target`'s shape (one of its areas, or the whole stream). Then a
 *  plan for it only makes the picture sharper or changes codec, and waits for the session to end (2026-10-21: each
 *  renegotiation cut the picture 5-10 s; a Tesla's page asked for four such within ten minutes, 2026-10-16). */
export function showsShape(display: AreaDisplay, target: Area) {
  const declared = display.areas && display.areas.length > 1 ? display.areas : [{ width: display.width, height: display.height }];
  return declared.some(s => s.width > 0 && s.height > 0 && !aspectChanged(s, target));
}
/** The picture element's size so that the area in use fills the view (the rest of the stream lies outside it, to the
 *  right and below; touches, normalized over the element, stay in stream coordinates). Without areas: shownSize. */
export function areaSize(streamWidth: number, streamHeight: number, area: Area | undefined, viewWidth: number, viewHeight: number) {
  if (!area || area.width <= 0 || area.height <= 0 || streamWidth <= 0 || streamHeight <= 0) return shownSize(streamWidth, streamHeight, viewWidth, viewHeight);
  return { width: viewWidth * streamWidth / area.width, height: viewHeight * streamHeight / area.height };
}
