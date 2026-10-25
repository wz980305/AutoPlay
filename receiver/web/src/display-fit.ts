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
/** The picture always fills the view, stretched per axis: no black bars (user 2026-10-12). A close shape
 *  stays stretched; a clearly different one is shown stretched only until CarPlay is renegotiated.
 *  Touch input is normalized per axis, so it stays exact. */
export function shownSize(width: number, height: number, viewWidth: number, viewHeight: number) {
  if (width <= 0 || height <= 0) return { width: 0, height: 0 };
  return { width: viewWidth, height: viewHeight };
}

export interface Area { width: number; height: number }
export interface AreaDisplay { width: number; height: number; hevc: boolean; areas?: Area[]; area?: number }
/** Window shapes kept per browser and orientation as CarPlay view areas (protocol: at most 4). */
export const MAX_AREAS = 4;
/** View areas (2026-10-14): each window shape of this orientation the browser has shown (normal, fullscreen, the car's dock shown or not)
 *  becomes an area at the stream's top left, the stream as large as all of them. A shape seen before is reached by
 *  switching area, without reconnecting CarPlay; a new shape, or one that wants a clearly sharper size, declares the
 *  areas again (one reconnect). Returns what to send and the shapes to keep, or null when nothing changes. */
export function areaPlan<T extends AreaDisplay>(display: T, target: Area, hevc: boolean, known: Area[]): { display: T; shapes: Area[] } | null {
  // Only shapes of the target's orientation are declared: a landscape and a portrait shape together make the stream
  // as large as both, a near-square frame the iPhone has to encode (xcertplay 1836c27). Shapes of the other
  // orientation stay remembered for when the window turns back; turning is one reconnect.
  const landscape = (s: Area) => s.width >= s.height, wide = landscape(target);
  const valid = known.filter(s => s.width > 0 && s.height > 0).map(s => ({ width: s.width, height: s.height }));
  const other = valid.filter(s => landscape(s) !== wide).slice(-MAX_AREAS);
  const shapes = valid.filter(s => landscape(s) === wide).slice(-MAX_AREAS);
  let at = shapes.findIndex(s => !aspectChanged(s, target));
  if (at < 0) {
    shapes.push({ ...target });
    if (shapes.length > MAX_AREAS) shapes.shift();
    at = shapes.length - 1;
  } else if (target.width * target.height > shapes[at].width * shapes[at].height * 1.2) {
    shapes[at] = { ...target };   // sharper (a fast decoder's real pixels): worth one reconnect
  }
  const width = Math.max(...shapes.map(s => s.width)), height = Math.max(...shapes.map(s => s.height));
  const areas = shapes.length > 1 ? shapes : [];
  const declared = display.areas ?? [];
  const same = display.width === width && display.height === height && display.hevc === hevc &&
    declared.length === areas.length && declared.every((a, i) => a.width === areas[i].width && a.height === areas[i].height);
  const kept = [...other, ...shapes];
  if (same) return areas.length && (display.area ?? 0) !== at ? { display: { ...display, area: at }, shapes: kept } : null;
  return { display: { ...display, width, height, hevc, areas, area: areas.length ? at : 0 }, shapes: kept };
}
/** The picture element's size so that the area in use fills the view (the rest of the stream lies outside it, to the
 *  right and below; touches, normalized over the element, stay in stream coordinates). Without areas: shownSize. */
export function areaSize(streamWidth: number, streamHeight: number, area: Area | undefined, viewWidth: number, viewHeight: number) {
  if (!area || area.width <= 0 || area.height <= 0 || streamWidth <= 0 || streamHeight <= 0) return shownSize(streamWidth, streamHeight, viewWidth, viewHeight);
  return { width: viewWidth * streamWidth / area.width, height: viewHeight * streamHeight / area.height };
}
