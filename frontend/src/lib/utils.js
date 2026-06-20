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

/**
 * Operator-safe error message.
 *
 * Unlike getErrorMessage(), this NEVER surfaces raw backend strings — those can
 * leak ffmpeg stderr, RTSP URLs with passwords, SOAP faults, internal IPs, or
 * stack traces. It maps the HTTP status (and a few well-known structured cases)
 * to clean, non-technical text suitable for a commercial NVR operator UI.
 *
 * Pass a `fallback` describing the action ("Couldn't add the camera") so the
 * default message reads naturally for the specific operation.
 */
export function friendlyError(error, fallback = "Operation failed, please try again") {
  // Validation errors (422) are user-fixable and safe to surface as a short,
  // generic hint — but never the raw `loc`/`input` internals.
  const detail = error?.response?.data?.detail;
  if (Array.isArray(detail)) {
    return "Please check the values entered and try again.";
  }

  const status = error?.response?.status;
  switch (status) {
    case 400:
      return "That request couldn't be completed. Please review and try again.";
    case 401:
    case 403:
      return "You don't have permission to do that.";
    case 404:
      return "That item could not be found.";
    case 409:
      return "That conflicts with an existing item.";
    case 422:
      return "Please check the values entered and try again.";
    case 429:
      return "Too many requests — please wait a moment and try again.";
    case 502:
    case 503:
    case 504:
      return "Couldn't reach the camera. Please check it's online and try again.";
    default:
      break;
  }

  if (status && status >= 500) {
    return fallback;
  }

  // No response → network/transport failure (offline, CORS, timeout).
  if (!error?.response) {
    return "Network problem — please check your connection and try again.";
  }

  return fallback;
}
