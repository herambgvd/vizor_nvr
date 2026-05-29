// Pure helpers for the live video wall layout. No React, no I/O.

export const LAYOUTS = [1, 4, 6, 8, 9, 16, 25];

export function slotCount(layout) {
  return LAYOUTS.includes(layout) ? layout : 4;
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
