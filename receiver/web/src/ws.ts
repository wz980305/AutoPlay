import { startup, startupStats } from './startup';
import { parseWireMessage, type ClientMessage, type ServerMessage, type WireMessage } from './protocol';

export type ConnectionState = 'connecting' | 'open' | 'closed';

/** This page load's id (letters and digits). */
const PAGE_ID = Array.from(crypto.getRandomValues(new Uint8Array(8)), b => b.toString(16).padStart(2, '0')).join('');

/** A socket not open by then is given up for a new one: in the car a link opens in tens of milliseconds, and the
 *  first one tried right after a Tesla unfroze the page sometimes hung (2026-10-14). */
const OPEN_TIMEOUT_MS = 1500;

export interface ConnectionHandlers {
  onWire: (message: WireMessage) => void;
  onServer: (message: ServerMessage) => void;
  onState: (state: ConnectionState) => void;
  onBytes?: (count: number) => void;
  onTiming?: (stats: Record<string, number>) => void;
}

/** Reconnecting WebSocket client for the playport server. */
export class Connection {
  private socket: WebSocket | null = null;
  private retryTimer: number | null = null;
  private retryDelayMs = 500;
  private stopped = false;
  /** Sockets in a row that did not open (closed first, or not open within OPEN_TIMEOUT_MS); 0 once one opens. */
  failures = 0;

  constructor(
    private readonly token: string,
    private readonly handlers: ConnectionHandlers,
  ) {}

  connect(): void {
    this.stopped = false;
    this.open();
  }

  private open(): void {
    this.handlers.onState('connecting');
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    // page: this page's id, so the box replaces this page's old link at once when it connects again.
    const url = `${scheme}://${location.host}/ws?token=${encodeURIComponent(this.token)}&page=${PAGE_ID}`;
    startup.mark('wsNewMs');
    const socket = new WebSocket(url);
    socket.binaryType = 'arraybuffer';
    this.socket = socket;
    let opened = false, openedAt = 0, firstMessage = true;
    // After a Tesla unfroze its browser (reverse gear, 2026-10-14) a new socket hung half-open, neither open nor
    // closed, and the page said "connecting" until refreshed: one that is not open in time is left for another.
    // A timer that runs late means the page was frozen meanwhile: the socket may have opened with its "open" not
    // handled yet (a test froze the page 0.3 s after connecting, 2026-10-14), so it gets another OPEN_TIMEOUT_MS.
    let openTimer = 0;
    const checkOpen = (armedAt: number) => {
      if (this.socket !== socket || socket.readyState === WebSocket.OPEN) return;
      if (performance.now() - armedAt > OPEN_TIMEOUT_MS + 1000) { const now = performance.now(); openTimer = window.setTimeout(() => checkOpen(now), OPEN_TIMEOUT_MS); return; }
      this.failures++; this.restart();
    };
    const armedAt = performance.now();
    openTimer = window.setTimeout(() => checkOpen(armedAt), OPEN_TIMEOUT_MS);

    socket.addEventListener('open', () => {
      window.clearTimeout(openTimer);
      if (this.socket !== socket) return;
      opened = true; openedAt = performance.now();
      this.retryDelayMs = 500;
      this.failures = 0;
      startup.mark('wsOpenMs');
      this.handlers.onState('open');
      this.handlers.onTiming?.(startupStats());
    });
    socket.addEventListener('message', (event: MessageEvent<string | ArrayBuffer>) => {
      if (this.socket !== socket) return;   // a socket left by restart()
      if (firstMessage) { firstMessage = false; startup.mark('wsFirstMs'); this.handlers.onTiming?.(startupStats()); }
      if (typeof event.data === 'string') {
        try {
          this.handlers.onServer(JSON.parse(event.data) as ServerMessage);
        } catch {
          // Ignore malformed control messages.
        }
        return;
      }
      this.handlers.onBytes?.(event.data.byteLength);
      const message = parseWireMessage(event.data);
      if (message) this.handlers.onWire(message);
    });
    socket.addEventListener('close', () => {
      window.clearTimeout(openTimer);
      if (this.socket !== socket) return;   // left by restart(), which already moved on
      if (!opened) this.failures++;
      // A link that had been up a while (the box closed it while the page was frozen): again at once, no back-off.
      if (opened && performance.now() - openedAt > 5000) this.retryDelayMs = 0;
      this.socket = null;
      this.handlers.onState('closed');
      this.scheduleReconnect();
    });
    socket.addEventListener('error', () => {
      socket.close();
    });
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.retryTimer !== null) return;
    this.retryTimer = window.setTimeout(() => {
      this.retryTimer = null;
      this.open();
    }, this.retryDelayMs);
    this.retryDelayMs = Math.min(Math.max(this.retryDelayMs * 2, 500), 5000);
  }

  get isOpen(): boolean { return this.socket?.readyState === WebSocket.OPEN; }

  /** false when the link is not open (nothing sent). */
  send(message: ClientMessage): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(message));
    return true;
  }

  sendBinary(payload: Uint8Array): void {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(payload);
  }

  /** Leaves the current socket at once, without waiting for it to close (after the browser was frozen it may be
   *  dead with no close to come), and opens a new one. */
  restart(): void {
    if (this.stopped) return;
    const old = this.socket;
    this.socket = null;
    if (this.retryTimer !== null) { window.clearTimeout(this.retryTimer); this.retryTimer = null; }
    try { old?.close(); } catch { /* Already gone. */ }
    this.handlers.onState('closed');
    this.retryDelayMs = 500;
    this.open();
  }

  close(): void {
    this.stopped = true;
    if (this.retryTimer !== null) {
      window.clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }
}
