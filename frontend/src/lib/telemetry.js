// Pure display formatters for the status bar / tile overlays.

export function fmtPct(v, isFraction = false) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  let pct = isFraction ? Number(v) * 100 : Number(v);
  pct = Math.max(0, Math.min(100, pct));
  return `${Math.round(pct)}%`;
}

export function fmtBytes(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const bytes = Number(n);
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  let val = bytes / 1024;
  let i = 0;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i += 1;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

export function fmtBitrate(kbps) {
  if (kbps === null || kbps === undefined || Number.isNaN(Number(kbps))) return "—";
  const v = Number(kbps);
  if (v < 1000) return `${Math.round(v)} kbps`;
  return `${(v / 1000).toFixed(1)} Mbps`;
}
