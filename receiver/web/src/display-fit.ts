/** Keep the full CarPlay picture visible. Never stretch or crop input coordinates. */
export function fittedSize(width: number, height: number, viewWidth: number, viewHeight: number) {
  const scale = Math.min(viewWidth / Math.max(1, width), viewHeight / Math.max(1, height));
  return { width: Math.max(0, width * scale), height: Math.max(0, height * scale) };
}
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
