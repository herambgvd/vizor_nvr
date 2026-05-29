import { clsx } from "clsx";
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

/**
 * Mask credentials embedded in a stream URL for safe display.
 * rtsp://user:pass@host:554/path  ->  rtsp://••••:••••@host:554/path
 * Leaves URLs without embedded credentials untouched.
 */
export function maskStreamUrl(url) {
  if (!url || typeof url !== "string") return url;
  // Match scheme://<authority-before-path>@host — greedy up to the LAST '@'
  // before the path so multi-'@' credential segments are fully masked.
  return url.replace(
    /(^[a-zA-Z][a-zA-Z0-9+.-]*:\/\/)([^/\s]+)@/,
    (_m, scheme) => `${scheme}••••:••••@`,
  );
}
