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
