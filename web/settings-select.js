// Keep settings menus inside the web page. Native <select> popups create
// another Qt window, outside the frameless host's layout and focus rules.
window.SettingsSelect = (() => {
  const controls = new Map();
  let active = null;

  function close(restoreFocus = false) {
    if (!active) return;
    const {button, menu} = active;
    active = null;
    menu.remove();
    button.setAttribute('aria-expanded', 'false');
    if (restoreFocus) button.focus();
  }

  function sync() {
    for (const [select, button] of controls) {
      const text = select.selectedOptions[0]?.textContent || '';
      button.textContent = text + ' ▾';
      const label = select.closest('label')?.querySelector('span')?.textContent || '';
      button.setAttribute('aria-label', `${label}：${text}`);
      button.disabled = select.disabled;
    }
  }

  function open(select, button) {
    if (active?.button === button) { close(true); return; }
    close();
    const options = Array.from(select.options).filter(o => !o.hidden && !o.disabled);
    if (!options.length) return;
    const menu = document.createElement('div');
    menu.id = select.id + '-menu';
    menu.className = 'settings-select-menu';
    menu.setAttribute('role', 'listbox');
    menu.setAttribute('aria-label', button.getAttribute('aria-label'));
    const items = options.map(option => {
      const item = document.createElement('button');
      item.type = 'button';
      item.tabIndex = -1;
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(option.selected));
      item.textContent = option.textContent;
      item.addEventListener('click', () => {
        const changed = select.value !== option.value;
        select.value = option.value;
        sync();
        close(true);
        if (changed) select.dispatchEvent(new Event('change', {bubbles: true}));
      });
      menu.appendChild(item);
      return item;
    });
    document.body.appendChild(menu); // Never participates in #stage measurement.
    active = {button, menu};
    button.setAttribute('aria-expanded', 'true');
    const rect = button.getBoundingClientRect();
    const margin = 8;
    const width = Math.min(Math.max(rect.width, menu.offsetWidth), window.innerWidth - margin * 2);
    menu.style.width = width + 'px';
    menu.style.left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin)) + 'px';
    const below = window.innerHeight - rect.bottom - margin;
    const above = rect.top - margin;
    const upwards = below < menu.offsetHeight && above > below;
    menu.style.maxHeight = Math.max(1, upwards ? above : below) + 'px';
    menu.style.top = (upwards ? rect.top - menu.offsetHeight : rect.bottom) + 'px';
    const selected = Math.max(0, options.findIndex(o => o.selected));
    items[selected].focus({preventScroll: true});
    items[selected].scrollIntoView({block: 'nearest'});
    menu.addEventListener('keydown', e => {
      const index = items.indexOf(document.activeElement);
      let next;
      if (e.key === 'ArrowDown') next = (index + 1) % items.length;
      if (e.key === 'ArrowUp') next = (index - 1 + items.length) % items.length;
      if (e.key === 'Home') next = 0;
      if (e.key === 'End') next = items.length - 1;
      if (next !== undefined) {
        e.preventDefault();
        items[next].focus();
      }
    });
  }

  function install() {
    for (const select of document.querySelectorAll('#view-settings select')) {
      const button = document.createElement('button');
      button.id = select.id + '-button';
      button.type = 'button';
      button.className = 'settings-select ' + select.className;
      button.setAttribute('aria-haspopup', 'listbox');
      button.setAttribute('aria-expanded', 'false');
      button.setAttribute('aria-controls', select.id + '-menu');
      select.hidden = true;
      select.after(button);
      controls.set(select, button);
      button.addEventListener('click', () => open(select, button));
      button.addEventListener('keydown', e => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          open(select, button);
        }
      });
      select.addEventListener('change', sync);
    }
    document.addEventListener('pointerdown', e => {
      if (active && !active.menu.contains(e.target) && !active.button.contains(e.target)) close();
    });
    document.addEventListener('keydown', e => {
      if (!active) return;
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopImmediatePropagation();
        close(true);
      } else if (e.key === 'Tab') close(true);
    }, true);
    document.addEventListener('scroll', e => {
      if (active && !active.menu.contains(e.target)) close();
    }, true);
    window.addEventListener('resize', () => close());
    window.addEventListener('blur', () => close());
    sync();
  }
  return {install, sync, close};
})();
