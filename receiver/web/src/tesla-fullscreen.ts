/** The Tesla way to fullscreen leaves this page for v.qq.com and 1905.com. A Tesla on the box hotspot without its
 *  own LTE has no internet and would land on an error page instead (simulated 2026-10-14), so the page looks first. */
export const TESLA_HOPS = ['https://v.qq.com/favicon.ico', 'https://www.1905.com/favicon.ico'];

type Fetcher = (url: string, init: RequestInit) => Promise<unknown>;

/** Every url answers within timeoutMs. no-cors: any HTTP answer counts; only DNS, connection or TLS failures fail. */
export async function reachable(urls: string[], fetcher: Fetcher = fetch, timeoutMs = 3000): Promise<boolean> {
  try {
    await Promise.all(urls.map(url => fetcher(url, { mode: 'no-cors', cache: 'no-store', signal: AbortSignal.timeout(timeoutMs) })));
    return true;
  } catch {
    return false;
  }
}
