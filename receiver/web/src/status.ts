/** The hint under the status line as a function of the page's state (viewer audit V3). Pure, so check-car.mjs can
 *  assert it: `key` is the i18n string to show (null for none), `seconds` the elapsed time to append, when any. */
export type StatusHint = { key: string | null; seconds: number | null; boxLink: boolean };

/** Elapsed seconds without a link before the hint names the box as the problem (a normal connect takes well under 1 s). */
export const SLOW_LINK_S = 3;

export function statusHint(state: string, linkDownSeconds: number): StatusHint {
  switch (state) {
    case 'access': return { key: 'accessHint', seconds: null, boxLink: true };
    // Waiting and starting say nothing under their title (1.5.4, as the settings panel says nothing standing): the
    // way to pair is the box page's 「添加 iPhone」, one row below; starting said its title again.
    case 'waiting': return { key: null, seconds: null, boxLink: true };
    case 'starting': return { key: null, seconds: null, boxLink: true };
    case 'renegotiating': return { key: 'renegotiatingHint', seconds: null, boxLink: true };
    case 'connecting':
      // The first seconds of a connect say nothing; past them it is the box that is not answering.
      return linkDownSeconds < SLOW_LINK_S ? { key: null, seconds: null, boxLink: false }
        : { key: 'reconnectingHint', seconds: Math.floor(linkDownSeconds), boxLink: false };
    case 'reconnecting':
      // A link that was up and dropped: the box, not the iPhone, is the question, and its own page is no help now.
      return { key: 'reconnectingHint', seconds: linkDownSeconds >= SLOW_LINK_S ? Math.floor(linkDownSeconds) : null, boxLink: false };
    default: return { key: null, seconds: null, boxLink: true };
  }
}
