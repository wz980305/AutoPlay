/**
 * How far the picture lags behind: the box answers a ping with a pong queued behind every frame it has not
 * sent yet (its send queue, then the TCP buffers), so the round trip grows with any backlog on the way.
 */
export class LagProbe {
  private readonly queue: number[] = [];
  private worst = -1;
  get pending() { return this.queue.length; }
  sent(now: number) {
    this.queue.push(now);
    if (this.queue.length > 30) this.queue.shift();
  }
  pong(now: number) {
    const at = this.queue.shift();
    if (at !== undefined) this.worst = Math.max(this.worst, now - at);
  }
  /** The window's worst round trip, counting a pong still on its way by its age; then a new window. */
  take(now: number): Record<string, number> {
    const waiting = this.queue.length ? now - this.queue[0] : -1;
    const lag = Math.max(this.worst, waiting);
    this.worst = -1;
    return lag >= 0 ? { lagMs: Math.round(lag) } : {};
  }
  reset() { this.queue.length = 0; this.worst = -1; }
}
