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

/**
 * Extract a human-readable string from an axios/FastAPI error.
 *
 * FastAPI validation failures (422) return `detail` as an ARRAY of objects
 * ({type, loc, msg, input}). Passing that array/object straight to a renderer
 * (e.g. toast.error / JSX) triggers React error #31 ("Objects are not valid
 * as a React child"). This always returns a plain string.
 */
export function getErrorMessage(error, fallback = "Something went wrong") {
  const detail = error?.response?.data?.detail;

  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (typeof d === "string" ? d : d?.msg))
      .filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }

  if (detail && typeof detail === "object") {
    if (typeof detail.msg === "string") return detail.msg;
  }

  if (typeof error?.message === "string") return error.message;

  return fallback;
}
