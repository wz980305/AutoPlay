/** Milliseconds since this navigation, shared by boot and the viewer. No URLs or tokens. */
export class StartupTiming {
  private marks: Record<string, number> = {};
  constructor(private now: () => number = () => performance.now()) {}
  mark(name: string): void { if (!(name in this.marks)) this.marks[name] = Math.round(this.now()); }
  snapshot(): Record<string, number> { return { navStartMs: 0, ...this.marks }; }
}
export const startup = new StartupTiming();
export function startupStats(): Record<string, number> {
  const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined;
  return { ...startup.snapshot(), ...(nav ? { domMs: Math.round(nav.domContentLoadedEventStart),
    responseMs: Math.round(nav.responseStart), dnsMs: Math.round(nav.domainLookupEnd - nav.domainLookupStart),
    tcpMs: Math.round(nav.connectEnd - nav.connectStart) } : {}) };
}
