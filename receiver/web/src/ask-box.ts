/** A request to the box with a deadline (1.4.1, after DashPlay 2026.11.04): a box that does not answer (Wi-Fi gone,
 *  receiver restarting) used to leave the settings panel on "Applying…" with its controls locked. The deadline covers
 *  the answer's body too; on expiry the request is aborted and rejects, and the caller's catch reports the failure. */
export const READ_MS = 2500, WRITE_MS = 6000;

export async function askBox<T>(url: string, init: RequestInit, ms: number,
  fetcher: typeof fetch = (...args) => fetch(...args)): Promise<{ ok: boolean; body: T | null }> {
  const abort = new AbortController(), timer = setTimeout(() => abort.abort(), ms);
  try {
    const r = await fetcher(url, { ...init, signal: abort.signal });
    return { ok: r.ok, body: await r.json().catch(() => null) as T | null };
  } finally { clearTimeout(timer); }
}
