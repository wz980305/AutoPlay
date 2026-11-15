/** Is the page this tab runs still the one the box serves? (1.6.7)
 *
 *  The drive record of 2026-11-15 began with the Tesla running a page from 1.4.x or earlier against a 1.6.5 box: the
 *  car keeps its tab for days, and nothing told an open page that the box had been upgraded. Each time the link to
 *  the box opens (main.ts), the page reads index.html again, never from the cache, and reloads once when that is not
 *  the page it runs: the text no longer names this tab's entry script (a release build's script names carry a hash,
 *  and a page the browser brought back from its cache is caught on its first reading), or it differs from the first
 *  reading (markup alone changed). */
export class PageWatch {
  private first: string | null = null;
  /** entry: the file name of this tab's entry script (boot.ts), '' when unknown. */
  constructor(private readonly entry: string) {}
  /** served: index.html as the box serves it now; null or '' when it could not be read (nothing is concluded). */
  changed(served: string | null): boolean {
    if (!served) return false;
    if (this.entry && !served.includes(this.entry)) return true;
    if (this.first === null) { this.first = served; return false; }
    return served !== this.first;
  }
}

/** Names one served page, for "reload once for this page": a page that still differs after its reload (a build whose
 *  index.html does not name its entry) must not reload in a loop. */
export function pageMark(text: string): string {
  let hash = 0;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  return `${text.length}.${hash}`;
}
