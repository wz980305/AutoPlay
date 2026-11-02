/** Option sheet in place of native <select> popups (1.2.0, docs/UI-1.2.0.md).
 *
 *  A car browser draws a <select>'s list itself, at the OS size and outside this page's type scale: small rows, a
 *  thin scrollbar, nothing the car's own scale setting reaches, and on some builds the list opens where a finger
 *  cannot see it. This sheet lists the options as the page's own rows (the primary touch target, the body size, a
 *  check mark on the current one) in the middle of the dimmed settings page, with a Cancel row under them.
 *
 *  The <select> stays in the DOM, hidden, as the value holder: main.ts keeps reading .value, setting it, disabling
 *  it and listening to its change event, which a chosen row dispatches. The visible row is a button carrying
 *  data-picker="<select id>" with a .value span that mirrors the selected option's text; refreshPickers() re-reads
 *  every value after a programmatic set (render() calls it, so a language change relabels the rows too). */
const CHECK = '<svg class="ico check" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';

type Picker = { trigger: HTMLButtonElement; select: HTMLSelectElement; value: HTMLElement };
const pickers: Picker[] = [];
let sheet: HTMLDialogElement | null = null;

function sync(p: Picker): void {
  p.value.textContent = p.select.selectedOptions[0]?.textContent ?? '';
  // A fieldset's disabled reaches the rows inside it on its own; a disabled select (codec while applying) is mirrored.
  p.trigger.disabled = p.select.disabled;
}

/** Mirror the current option of every picker row; call after setting a select's value in code. */
export function refreshPickers(): void { pickers.forEach(sync); }

function open(p: Picker): void {
  if (!sheet) return;
  const title = sheet.querySelector<HTMLElement>('#picker-title')!;
  const list = sheet.querySelector<HTMLElement>('#picker-options')!;
  title.textContent = p.trigger.querySelector('.main b')?.textContent ?? '';
  list.replaceChildren(...Array.from(p.select.options).map(option => {
    const row = document.createElement('button');
    row.type = 'button'; row.className = 'cell option'; row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(option.selected));
    row.innerHTML = `<span class="main"><b></b></span>${CHECK}`;
    row.querySelector('b')!.textContent = option.textContent;
    row.onclick = () => {
      if (p.select.value !== option.value) {
        p.select.value = option.value;
        p.select.dispatchEvent(new Event('change', { bubbles: true }));
      }
      sync(p);
      sheet!.close();
    };
    return row;
  }));
  if (typeof sheet.showModal === 'function') sheet.showModal(); else sheet.setAttribute('open', '');
  list.querySelector<HTMLElement>('[aria-selected=true]')?.focus();
}

/** Wire every [data-picker] row under root to its hidden <select>, and the shared sheet dialog. */
export function attachPickers(root: ParentNode, dialog: HTMLDialogElement): void {
  sheet = dialog;
  const close = () => { if (dialog.open) dialog.close(); };
  dialog.querySelector<HTMLButtonElement>('#picker-cancel')!.onclick = close;
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });   // the dimmed backdrop
  dialog.addEventListener('close', () => { dialog.querySelector('#picker-options')!.replaceChildren(); });
  for (const trigger of root.querySelectorAll<HTMLButtonElement>('[data-picker]')) {
    const select = document.getElementById(trigger.dataset.picker!) as HTMLSelectElement | null;
    const value = trigger.querySelector<HTMLElement>('.value');
    if (!select || !value) continue;
    const p: Picker = { trigger, select, value };
    pickers.push(p);
    sync(p);
    select.addEventListener('change', () => sync(p));
    // disabled is an attribute; option labels change with the language (setLanguage rewrites their text).
    new MutationObserver(() => sync(p)).observe(select, { attributes: true, childList: true, subtree: true, characterData: true });
    trigger.onclick = () => open(p);
  }
}
