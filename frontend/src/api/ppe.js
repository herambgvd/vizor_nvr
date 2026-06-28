// PPE scenario API — video-upload compliance helpers. Everything proxies through the
// NVR (license + enable gated) via proxyScenario, except the binary frame/output fetches
// which need the Bearer token on a raw fetch (returned as object-URLs the caller revokes).
import apiClient, { BACKEND_URL, getAccessToken } from "./client";
import { proxyScenario } from "./ai";

const SLUG = "ppe";

// Start a job. `file` = File, `cfg` = { required_items[], roi, emit_compliant, ... }.
export const uploadPpeVideo = async (file, cfg = {}) => {
  const form = new FormData();
  form.append("video", file);
  form.append("required_items", JSON.stringify(cfg.required_items || ["helmet", "vest"]));
  if (cfg.roi != null) form.append("roi", JSON.stringify(cfg.roi));
  form.append("emit_compliant", cfg.emit_compliant ? "true" : "false");
  if (cfg.missing_grace != null) form.append("missing_grace", String(cfg.missing_grace));
  if (cfg.cooldown != null) form.append("cooldown", String(cfg.cooldown));
  return proxyScenario(SLUG, "/video/upload", { method: "POST", data: form });
};

export const getPpeVideoStatus = (jobId) =>
  proxyScenario(SLUG, `/video/status/${jobId}`);

export const cancelPpeVideo = (jobId) =>
  proxyScenario(SLUG, `/video/cancel/${jobId}`, { method: "POST" });

export const getPpeVideoResult = (jobId) =>
  proxyScenario(SLUG, `/video/result/${jobId}`);

// Latest annotated frame as an object-URL (caller must URL.revokeObjectURL it).
export const fetchPpeVideoFrame = async (jobId) => {
  const token = getAccessToken();
  let resp;
  try {
    resp = await fetch(
      `${BACKEND_URL}/api/ai/scenarios/${SLUG}/proxy/video/frame/${jobId}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
  } catch (_e) {
    return null;
  }
  if (!resp.ok) return null;
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
};

// Direct URL to the result MP4 (auth via query token fallback handled by the proxy;
// for the <video> tag we fetch a blob so the Bearer header applies).
export const fetchPpeVideoOutput = async (jobId) => {
  const token = getAccessToken();
  let resp;
  try {
    resp = await fetch(
      `${BACKEND_URL}/api/ai/scenarios/${SLUG}/proxy/video/output/${jobId}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
  } catch (_e) {
    return null;
  }
  if (!resp.ok) return null;
  const blob = await resp.blob();
  return URL.createObjectURL(blob);
};

export { apiClient };
