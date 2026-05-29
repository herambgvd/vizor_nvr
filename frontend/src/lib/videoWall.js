// Pure helpers for the live video wall layout. No React, no I/O.

export const LAYOUTS = [1, 4, 6, 8, 9, 16, 25, 36, 49, 64];

export function slotCount(layout) {
  return LAYOUTS.includes(layout) ? layout : 4;
}

// Smallest supported layout that can hold `n` cameras (capped at the max).
export function fitLayout(n) {
  if (!n || n < 1) return 1;
  return LAYOUTS.find((l) => l >= n) || LAYOUTS[LAYOUTS.length - 1];
}

// Split camera ids into auto-cycling tour pages of `layout` slots each.
// Every page is padded to exactly slotCount(layout) entries (null fill) so
// the grid keeps a stable shape while cycling. Falsy ids are dropped.
// Returns [] when there are no cameras to show.
export function tourPages(cameraIds, layout) {
  const ids = Array.isArray(cameraIds) ? cameraIds.filter(Boolean) : [];
  if (ids.length === 0) return [];
  const size = slotCount(layout);
  const pages = [];
  for (let i = 0; i < ids.length; i += size) {
    const page = ids.slice(i, i + size);
    while (page.length < size) page.push(null);
    pages.push(page);
  }
  return pages;
}

// Square-ish grid: columns = ceil(sqrt(n)).
export function gridStyle(layout) {
  const n = slotCount(layout);
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  return {
    gridTemplateColumns: `repeat(${cols}, 1fr)`,
    gridTemplateRows: `repeat(${rows}, 1fr)`,
  };
}
