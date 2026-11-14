/** Option menu in place of native <select> popups (1.2.0, docs/UI-1.2.0.md; a menu since 1.5.4).
 *
 *  A car browser draws a <select>'s list itself, at the OS size and outside this page's type scale: small rows, a
 *  thin scrollbar, nothing the car's own scale setting reaches, and on some builds the list opens where a finger
 *  cannot see it. This menu lists the options as the page's own rows (the primary touch target, the body size, a
 *  check mark on the current one). Since 1.5.4 it opens from the row the way Apple's pop-up button does - under the
 *  row's value (above it when there is no room), no title and no Cancel: a tap outside or Esc closes it. Until then
 *  it was a sheet in the middle of the dimmed page with a Cancel row, opened from a row that showed a push chevron.
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

/** Under the row's trailing end, or above the row when the room under it is too short for the list and above is
 *  roomier; the list scrolls inside what is left. */
function place(menu: HTMLElement, row: HTMLElement): void {
  if (typeof innerHeight !== 'number' || !menu.style) return;
  const gap = 12, r = row.getBoundingClientRect();
  menu.style.maxHeight = '';
  const width = menu.offsetWidth, height = menu.offsetHeight;
  const below = innerHeight - r.bottom - gap, above = r.top - gap;
  const down = height <= below || below >= above;
  menu.style.maxHeight = `${Math.max(120, down ? below : above) - 4}px`;
  const shown = Math.min(height, Math.max(120, down ? below : above) - 4);
  menu.style.left = `${Math.max(gap, Math.min(r.right - width, innerWidth - width - gap))}px`;
  menu.style.top = `${down ? r.bottom + 4 : Math.max(gap, r.top - 4 - shown)}px`;
  menu.style.transformOrigin = down ? 'top right' : 'bottom right';
}

function open(p: Picker): void {
  if (!sheet) return;
  const list = sheet.querySelector<HTMLElement>('#picker-options')!;
  sheet.setAttribute('aria-label', p.trigger.querySelector('.main b')?.textContent ?? '');
  list.replaceChildren(...Array.from(p.select.options).map(option => {
    const row = document.createElement('button');
    row.type = 'button'; row.className = 'cell option'; row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(option.selected));
    row.innerHTML = `<span class="main"><b></b></span>${CHECK}`;
    row.querySelector('b')!.textContent = option.textContent;
    // A second, grey line under an option (data-detail): the car's position under each datum, for example.
    const text = option.dataset?.detail;
    if (text) {
      const detail = document.createElement('span');
      detail.textContent = text;
      row.querySelector('.main')!.append(detail);
    }
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
  place(sheet, p.trigger);
  list.querySelector<HTMLElement>('[aria-selected=true]')?.focus();
}

/** Wire every [data-picker] row under root to its hidden <select>, and the shared menu dialog. */
export function attachPickers(root: ParentNode, dialog: HTMLDialogElement): void {
  sheet = dialog;
  const close = () => { if (dialog.open) dialog.close(); };
  dialog.addEventListener('click', event => { if (event.target === dialog) close(); });   // a tap outside the menu
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
