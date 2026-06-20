// =============================================================================
// AI · Suspect Search tab — Eocortex-style visual "search engine" for people.
//
// Three columns:
//   LEFT   — the suspect BUILDER: a clickable person silhouette whose upper /
//            lower regions get painted from a quick colour palette, garment +
//            demographic + accessory filters, optional reference image, cameras,
//            time range, confidence, and the big SEARCH / Reset actions.
//   CENTER — the result CANVAS: empty / loading / responsive grid of matches.
//   RIGHT  — context: active filters, movement trajectory, and a tucked-away
//            "Index archive" background job (the only polled job left).
//
// SEARCH is synchronous: scenarioSearch(slug, FormData) → response.items.
// Find-similar is synchronous: createScenarioSimilarSearchJob → response.items.
// Only INDEX runs as a polled background job.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  Camera,
  ChevronDown,
  Database,
  Glasses,
  HardHat,
  Loader2,
  MapPinned,
  RefreshCw,
  RotateCcw,
  Search,
  ShoppingBag,
  Upload,
  XCircle,
} from "lucide-react";
import {
  cancelScenarioJob,
  createScenarioIndexJob,
  createScenarioSimilarSearchJob,
  getScenarioJob,
  getScenarioJobResults,
  listScenarioCameras,
  scenarioSearch,
  scenarioThumbnailUrl,
} from "../../../api/ai";
import { friendlyError } from "../../../lib/utils";

// ── Shared style tokens (every colour is a --console-* custom property) ───────
const inputClass = "h-8 w-full rounded border px-2.5 text-[12px] outline-none";
const inputStyle = {
  borderColor: "var(--console-border)",
  background: "var(--console-raised)",
  color: "var(--console-text)",
};
const labelClass =
  "block font-telemetry text-[9px] uppercase tracking-widest mb-1";
const labelStyle = { color: "var(--console-muted)" };

const objectTypes = [
  { key: "person", label: "Person" },
  { key: "bag", label: "Bag" },
];

// Garment vocabularies — mirror the backend top_type / bottom_type enums.
const TOP_TYPES = ["any", "shirt", "top", "sweater", "jacket", "coat", "dress"];
const BOTTOM_TYPES = ["any", "pants", "shorts", "skirt"];
const GENDERS = ["any", "male", "female"];
const AGE_BANDS = [
  "any",
  "0-2",
  "3-9",
  "10-19",
  "20-29",
  "30-39",
  "40-49",
  "50-59",
  "60-69",
  "70+",
];
const ACCESSORIES = [
  { key: "bag", label: "Bag", Icon: ShoppingBag },
  { key: "hat", label: "Hat", Icon: HardHat },
  { key: "glasses", label: "Glasses", Icon: Glasses },
];

// Quick palette of common clothing colours — the operator paints the silhouette.
const PALETTE = [
  { name: "black", hex: "#000000" },
  { name: "white", hex: "#ffffff" },
  { name: "gray", hex: "#808080" },
  { name: "red", hex: "#e11d48" },
  { name: "maroon", hex: "#800000" },
  { name: "orange", hex: "#f97316" },
  { name: "yellow", hex: "#eab308" },
  { name: "green", hex: "#16a34a" },
  { name: "olive", hex: "#808000" },
  { name: "teal", hex: "#0d9488" },
  { name: "blue", hex: "#2563eb" },
  { name: "navy", hex: "#1e3a5f" },
  { name: "purple", hex: "#7c3aed" },
  { name: "pink", hex: "#ec4899" },
  { name: "brown", hex: "#854d0e" },
  { name: "beige", hex: "#d9c5a0" },
];

const DEFAULT_TOP_RGB = "#3b82f6";
const DEFAULT_BOTTOM_RGB = "#1f2937";

// ── Result thumbnail (auth'd object URL via existing helper) ──────────────────
const ResultThumb = ({ scenarioSlug, resultId }) => {
  const [url, setUrl] = useState(null);

  useEffect(() => {
    let active = true;
    if (!resultId) return undefined;
    scenarioThumbnailUrl(scenarioSlug, resultId).then((next) => {
      if (active) setUrl(next);
      else if (next) URL.revokeObjectURL(next);
    });
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [scenarioSlug, resultId]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      className="aspect-[4/3] rounded overflow-hidden flex items-center justify-center border"
      style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}
    >
      {url ? (
        <img src={url} alt="" className="h-full w-full object-cover" />
      ) : (
        <Camera className="h-5 w-5" style={{ color: "var(--console-muted)" }} />
      )}
    </div>
  );
};

// ── Person silhouette — click upper / lower to select, fill shows chosen colour.
const SuspectSilhouette = ({ region, onRegion, topFill, bottomFill }) => {
  const ringFor = (r) => (region === r ? "var(--console-accent)" : "var(--console-border)");
  const baseFill = "var(--console-raised)";
  return (
    <svg viewBox="0 0 120 220" className="h-full w-auto" role="img" aria-label="Suspect silhouette">
      {/* head — neutral, not selectable */}
      <circle cx="60" cy="26" r="18" fill={baseFill} stroke="var(--console-border)" strokeWidth="2" />
      {/* UPPER BODY (torso + arms) — selectable "top" */}
      <g
        onClick={() => onRegion("top")}
        style={{ cursor: "pointer" }}
      >
        <path
          d="M60 46
             C44 46 36 52 32 62
             L22 104 L34 110 L42 86
             L42 132 L78 132 L78 86
             L86 110 L98 104 L88 62
             C84 52 76 46 60 46 Z"
          fill={topFill || baseFill}
          stroke={ringFor("top")}
          strokeWidth={region === "top" ? 3 : 2}
        />
      </g>
      {/* LOWER BODY (legs) — selectable "bottom" */}
      <g
        onClick={() => onRegion("bottom")}
        style={{ cursor: "pointer" }}
      >
        <path
          d="M42 132 L42 206 L56 206 L60 150 L64 206 L78 206 L78 132 Z"
          fill={bottomFill || baseFill}
          stroke={ringFor("bottom")}
          strokeWidth={region === "bottom" ? 3 : 2}
        />
      </g>
    </svg>
  );
};

// ── Visible badge: bordered, muted text, never white-on-white ─────────────────
const Badge = ({ children, swatch }) => (
  <span
    className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] font-telemetry uppercase tracking-wider"
    style={{
      borderColor: "var(--console-border)",
      background: "var(--console-raised)",
      color: "var(--console-muted)",
    }}
  >
    {swatch ? (
      <span
        className="h-2.5 w-2.5 rounded-full"
        style={{ backgroundColor: swatch, border: "1px solid var(--console-border)" }}
      />
    ) : null}
    {children}
  </span>
);

const SectionLabel = ({ children, Icon }) => (
  <div className="flex items-center gap-1.5 font-telemetry text-[9px] uppercase tracking-widest mb-2" style={labelStyle}>
    {Icon ? <Icon className="h-3.5 w-3.5" /> : null}
    {children}
  </div>
);

const SuspectSearchTab = ({ scenario }) => {
  const [file, setFile] = useState(null);
  const [objectType, setObjectType] = useState("person");

  // Which silhouette region the colour palette paints.
  const [region, setRegion] = useState("top");

  // Advanced filters (reference image, cameras, time range, confidence) collapse
  // by default so the core attribute builder stays short and Search stays reachable.
  const [showMoreFilters, setShowMoreFilters] = useState(false);

  // STAGE 1 attribute state.
  const [topType, setTopType] = useState("any");
  const [topUseColor, setTopUseColor] = useState(false);
  const [topRgb, setTopRgb] = useState(DEFAULT_TOP_RGB);
  const [bottomType, setBottomType] = useState("any");
  const [bottomUseColor, setBottomUseColor] = useState(false);
  const [bottomRgb, setBottomRgb] = useState(DEFAULT_BOTTOM_RGB);
  const [gender, setGender] = useState("any");
  const [ageBand, setAgeBand] = useState("any");
  const [accessories, setAccessories] = useState(() => new Set());

  const [confidence, setConfidence] = useState(0.72);
  const [cameraIds, setCameraIds] = useState("");
  const [assignedCameras, setAssignedCameras] = useState([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const [job, setJob] = useState(null);
  const [results, setResults] = useState([]);
  const [resultTotal, setResultTotal] = useState(0);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  useEffect(() => {
    if (!scenario?.id) return undefined;
    let alive = true;
    listScenarioCameras(scenario.id)
      .then((items) => {
        if (!alive) return;
        const assigned = items || [];
        setAssignedCameras(assigned);
        setCameraIds(assigned.map((item) => item.camera_id).join(","));
      })
      .catch(() => {
        if (alive) setAssignedCameras([]);
      });
    return () => {
      alive = false;
    };
  }, [scenario?.id]);

  const refreshJob = async (jobId = job?.job_id) => {
    if (!jobId) return;
    const next = await getScenarioJob(scenario.slug, jobId);
    setJob(next);
    const payload = await getScenarioJobResults(scenario.slug, jobId, { limit: 100 });
    setResults(payload.items || payload.results || []);
    setResultTotal(payload.total || payload.count || 0);
  };

  useEffect(() => {
    if (!job?.job_id || ["completed", "failed", "cancelled"].includes(job.status)) return undefined;
    const timer = setInterval(() => {
      setPolling(true);
      refreshJob(job.job_id).catch((err) => setError(friendlyError(err, "Something went wrong. Please try again."))).finally(() => setPolling(false));
    }, 2500);
    return () => clearInterval(timer);
  }, [job?.job_id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const isPerson = objectType === "person";
  const accessoryCsv = useMemo(() => Array.from(accessories).join(","), [accessories]);

  // True when the operator has set ANY filter that lets a no-image search run.
  const hasAttributeSearch = useMemo(() => {
    if (isPerson) {
      if (topType !== "any" || bottomType !== "any") return true;
      if (topUseColor || bottomUseColor) return true;
      if (gender !== "any" || ageBand !== "any") return true;
      if (accessories.size > 0) return true;
    }
    if (cameraIds.trim()) return true;
    if (from || to) return true;
    return false;
  }, [isPerson, topType, bottomType, topUseColor, bottomUseColor, gender, ageBand, accessories, cameraIds, from, to]);

  const appendFilters = (form) => {
    form.append("object_type", objectType);
    form.append("min_confidence", String(confidence));
    if (cameraIds.trim()) form.append("camera_ids", cameraIds.trim());
    if (from) form.append("start_time", from);
    if (to) form.append("end_time", to);
    if (isPerson) {
      if (topType !== "any") form.append("top_type", topType);
      if (bottomType !== "any") form.append("bottom_type", bottomType);
      if (topUseColor) form.append("top_rgb", topRgb);
      if (bottomUseColor) form.append("bottom_rgb", bottomRgb);
      if (gender !== "any") form.append("gender", gender);
      if (ageBand !== "any") form.append("age_band", ageBand);
      if (accessoryCsv) form.append("accessories", accessoryCsv);
    }
  };

  const toggleAccessory = (key) =>
    setAccessories((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  // Paint the currently-selected silhouette region from the quick palette.
  const paintRegion = (hex) => {
    if (region === "top") {
      setTopRgb(hex);
      setTopUseColor(true);
    } else {
      setBottomRgb(hex);
      setBottomUseColor(true);
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setJob(null);
    if (!file && !hasAttributeSearch) {
      setError("Set at least one attribute, camera or time filter — or upload a reference image.");
      return;
    }
    const form = new FormData();
    if (file) form.append("reference", file);
    appendFilters(form);
    try {
      setLoading(true);
      setSearched(true);
      // Synchronous search — results come back directly, no job + no polling.
      const response = await scenarioSearch(scenario.slug, form);
      setResults(response.items || []);
      setResultTotal(response.total || (response.items || []).length);
    } catch (err) {
      setError(friendlyError(err, "Search failed."));
    } finally {
      setLoading(false);
    }
  };

  const resetBuilder = () => {
    setFile(null);
    setRegion("top");
    setShowMoreFilters(false);
    setTopType("any");
    setTopUseColor(false);
    setTopRgb(DEFAULT_TOP_RGB);
    setBottomType("any");
    setBottomUseColor(false);
    setBottomRgb(DEFAULT_BOTTOM_RGB);
    setGender("any");
    setAgeBand("any");
    setAccessories(new Set());
    setConfidence(0.72);
    setError("");
    setResults([]);
    setResultTotal(0);
    setSearched(false);
    setJob(null);
  };

  const runIndex = async () => {
    setError("");
    try {
      setLoading(true);
      const created = await createScenarioIndexJob(scenario.slug, {
        object_types: "person,bag",
        camera_ids: cameraIds.trim(),
        start_time: from,
        end_time: to,
      });
      setJob(created);
      if (created?.job_id) await refreshJob(created.job_id);
    } catch (err) {
      setError(friendlyError(err, "Index job failed."));
    } finally {
      setLoading(false);
    }
  };

  const searchSimilar = async (result) => {
    const resultId = result.result_id || result.id;
    if (!resultId) return;
    setError("");
    try {
      setLoading(true);
      setSearched(true);
      // Search-similar is synchronous too — results returned directly, no polling.
      const response = await createScenarioSimilarSearchJob(scenario.slug, resultId, {
        object_type: result.object_type || objectType,
        min_confidence: confidence,
        camera_ids: cameraIds.trim(),
        start_time: from,
        end_time: to,
      });
      setResults(response.items || []);
      setResultTotal(response.total || (response.items || []).length);
    } catch (err) {
      setError(friendlyError(err, "Nested search failed."));
    } finally {
      setLoading(false);
    }
  };

  const blocked = !scenario.licensed || !scenario.enabled;
  const noAssignedCameras = assignedCameras.length === 0;
  const enabledCameraCount = assignedCameras.filter((item) => item.enabled).length;
  const noEnabledCameras = enabledCameraCount === 0;
  const selectedCameraIds = useMemo(
    () => new Set(cameraIds.split(",").map((x) => x.trim()).filter(Boolean)),
    [cameraIds],
  );
  const toggleCamera = (cameraId) => {
    const next = new Set(selectedCameraIds);
    if (next.has(cameraId)) next.delete(cameraId);
    else next.add(cameraId);
    setCameraIds(Array.from(next).join(","));
  };

  const playbackUrl = (result) => {
    const cameraId = result.camera_id || result.cameraId;
    const ts = result.timestamp || result.triggered_at || result.time;
    if (!cameraId || !ts) return null;
    const date = String(ts).slice(0, 10);
    return `/playback?camera=${encodeURIComponent(cameraId)}&date=${encodeURIComponent(date)}&t=${encodeURIComponent(ts)}`;
  };

  // Pull a usable hex from a result for the colour swatches.
  const hexOf = (result, ...keys) => {
    for (const k of keys) {
      const v = result[k];
      if (typeof v === "string" && /^#?[0-9a-fA-F]{6}$/.test(v)) {
        return v.startsWith("#") ? v : `#${v}`;
      }
    }
    return null;
  };

  const accList = (result) =>
    Array.isArray(result.accessories)
      ? result.accessories
      : typeof result.accessories === "string"
        ? result.accessories.split(",").map((x) => x.trim()).filter(Boolean)
        : [];

  const indexRunning = job && !["completed", "failed", "cancelled"].includes(job.status);
  const matchCount = resultTotal || results.length;

  // Color sent to the silhouette only when that region's colour is "on".
  const topFill = topUseColor ? topRgb : null;
  const bottomFill = bottomUseColor ? bottomRgb : null;

  return (
    <div className="console-root flex flex-col h-full min-h-0 overflow-hidden" style={{ color: "var(--console-text)" }}>
      {/* Warning banners — kept from original, visible on dark */}
      <div className="px-4 pt-3 space-y-2 shrink-0">
        {blocked && (
          <div className="rounded border p-3 flex gap-2 text-[12px]" style={{ borderColor: "var(--console-rec)", background: "var(--console-raised)", color: "var(--console-rec)" }}>
            <AlertCircle className="h-4 w-4 shrink-0" />
            Scenario must be licensed and enabled before search or index jobs can run.
          </div>
        )}
        {!blocked && !noAssignedCameras && noEnabledCameras && (
          <div className="rounded border p-3 flex gap-2 text-[12px]" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)", color: "var(--console-muted)" }}>
            <AlertCircle className="h-4 w-4 shrink-0" style={{ color: "var(--console-accent)" }} />
            All assigned cameras are disabled. Historical indexed data can still be searched; new indexing is paused.
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-[320px_1fr_300px] gap-3 p-4">

        {/* ════════════════ LEFT — SUSPECT BUILDER ════════════════ */}
        <form
          onSubmit={submit}
          className="rounded border flex flex-col min-h-0"
          style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
        >
          <div className="px-3 py-2.5 border-b flex items-center gap-2" style={{ borderColor: "var(--console-border)" }}>
            <Search className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
            <span className="font-telemetry text-[11px] font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>
              Build a suspect
            </span>
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-2.5">
            {/* Object type toggle */}
            <div>
              <span className={labelClass} style={labelStyle}>Object</span>
              <div className="grid grid-cols-2 gap-1.5">
                {objectTypes.map((item) => {
                  const on = objectType === item.key;
                  return (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setObjectType(item.key)}
                      className="h-7 rounded border text-[12px]"
                      style={{
                        borderColor: on ? "var(--console-accent)" : "var(--console-border)",
                        color: on ? "var(--console-text)" : "var(--console-muted)",
                        background: on ? "rgba(34,139,34,0.22)" : "var(--console-raised)",
                      }}
                    >
                      {item.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Silhouette + palette */}
            <div style={{ opacity: isPerson ? 1 : 0.45, pointerEvents: isPerson ? "auto" : "none" }}>
              <div className="flex items-center justify-between mb-1">
                <span className={labelClass} style={labelStyle}>Paint region</span>
                <div className="flex gap-1">
                  {["top", "bottom"].map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => setRegion(r)}
                      className="rounded border px-2 py-0.5 text-[10px] font-telemetry uppercase tracking-wider"
                      style={{
                        borderColor: region === r ? "var(--console-accent)" : "var(--console-border)",
                        background: region === r ? "rgba(34,139,34,0.22)" : "var(--console-raised)",
                        color: region === r ? "var(--console-text)" : "var(--console-muted)",
                      }}
                    >
                      {r}
                    </button>
                  ))}
                </div>
              </div>

              <div
                className="rounded border p-2 flex justify-center"
                style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}
              >
                <div style={{ maxHeight: 150 }} className="h-[150px]">
                  <SuspectSilhouette region={region} onRegion={setRegion} topFill={topFill} bottomFill={bottomFill} />
                </div>
              </div>

              {/* Quick colour swatches */}
              <div className="mt-1.5 grid grid-cols-8 gap-1">
                {PALETTE.map((c) => {
                  const activeHex = region === "top" ? (topUseColor ? topRgb : null) : (bottomUseColor ? bottomRgb : null);
                  const sel = activeHex && activeHex.toLowerCase() === c.hex.toLowerCase();
                  return (
                    <button
                      key={c.name}
                      type="button"
                      title={c.name}
                      onClick={() => paintRegion(c.hex)}
                      className="aspect-square rounded"
                      style={{
                        backgroundColor: c.hex,
                        border: sel ? "2px solid var(--console-accent)" : "1px solid var(--console-border)",
                      }}
                    />
                  );
                })}
              </div>

              {/* Precise pickers + clear, both regions */}
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                {[
                  { key: "top", use: topUseColor, setUse: setTopUseColor, rgb: topRgb, setRgb: setTopRgb },
                  { key: "bottom", use: bottomUseColor, setUse: setBottomUseColor, rgb: bottomRgb, setRgb: setBottomRgb },
                ].map((c) => (
                  <div
                    key={c.key}
                    className="rounded border px-2 py-1.5 flex items-center gap-2"
                    style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}
                  >
                    <input
                      type="color"
                      value={c.rgb}
                      onChange={(e) => { c.setRgb(e.target.value); c.setUse(true); }}
                      className="h-6 w-7 rounded border-0 bg-transparent p-0 cursor-pointer"
                      title={`${c.key} colour`}
                    />
                    <span className="font-telemetry text-[9px] uppercase tracking-wider flex-1" style={{ color: c.use ? "var(--console-text)" : "var(--console-muted)" }}>
                      {c.key}{c.use ? "" : " any"}
                    </span>
                    {c.use && (
                      <button
                        type="button"
                        onClick={() => c.setUse(false)}
                        className="font-telemetry text-[9px] uppercase tracking-wider"
                        style={{ color: "var(--console-muted)" }}
                        title="Clear colour"
                      >
                        clear
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Garment types */}
            <div className="grid grid-cols-2 gap-1.5" style={{ opacity: isPerson ? 1 : 0.45, pointerEvents: isPerson ? "auto" : "none" }}>
              <label className="block">
                <span className={labelClass} style={labelStyle}>Top type</span>
                <select className={inputClass} style={inputStyle} value={topType} onChange={(e) => setTopType(e.target.value)}>
                  {TOP_TYPES.map((t) => <option key={t} value={t}>{t === "any" ? "Any" : t}</option>)}
                </select>
              </label>
              <label className="block">
                <span className={labelClass} style={labelStyle}>Bottom type</span>
                <select className={inputClass} style={inputStyle} value={bottomType} onChange={(e) => setBottomType(e.target.value)}>
                  {BOTTOM_TYPES.map((t) => <option key={t} value={t}>{t === "any" ? "Any" : t}</option>)}
                </select>
              </label>
              <label className="block">
                <span className={labelClass} style={labelStyle}>Gender</span>
                <select className={inputClass} style={inputStyle} value={gender} onChange={(e) => setGender(e.target.value)}>
                  {GENDERS.map((g) => <option key={g} value={g}>{g === "any" ? "Any" : g}</option>)}
                </select>
              </label>
              <label className="block">
                <span className={labelClass} style={labelStyle}>Age band</span>
                <select className={inputClass} style={inputStyle} value={ageBand} onChange={(e) => setAgeBand(e.target.value)}>
                  {AGE_BANDS.map((a) => <option key={a} value={a}>{a === "any" ? "Any" : a}</option>)}
                </select>
              </label>
            </div>

            {/* Accessories */}
            <div style={{ opacity: isPerson ? 1 : 0.45, pointerEvents: isPerson ? "auto" : "none" }}>
              <span className={labelClass} style={labelStyle}>Accessories</span>
              <div className="flex flex-wrap gap-1.5">
                {ACCESSORIES.map(({ key, label, Icon }) => {
                  const on = accessories.has(key);
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => toggleAccessory(key)}
                      className="inline-flex h-7 items-center gap-1.5 rounded border px-2.5 text-[11px]"
                      style={{
                        borderColor: on ? "var(--console-accent)" : "var(--console-border)",
                        background: on ? "rgba(34,139,34,0.22)" : "var(--console-raised)",
                        color: on ? "var(--console-text)" : "var(--console-muted)",
                      }}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      {label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* More filters — reference image, cameras, time range, confidence.
                Collapsed by default to keep the core attribute builder short. */}
            <button
              type="button"
              onClick={() => setShowMoreFilters((v) => !v)}
              className="w-full flex items-center justify-between rounded border px-2.5 h-8 text-[10px] font-telemetry uppercase tracking-widest"
              style={{ borderColor: "var(--console-border)", background: "var(--console-raised)", color: "var(--console-muted)" }}
              aria-expanded={showMoreFilters}
            >
              <span>More filters{(file || selectedCameraIds.size > 0 || from || to) ? " · set" : ""}</span>
              <ChevronDown
                className="h-3.5 w-3.5 transition-transform"
                style={{ transform: showMoreFilters ? "rotate(180deg)" : "none" }}
              />
            </button>

            <div className="space-y-2.5" style={{ display: showMoreFilters ? "block" : "none" }}>
            {/* Optional reference image */}
            <div>
              <span className={labelClass} style={labelStyle}>Reference image (optional)</span>
              <div className="flex items-center gap-2">
                <label
                  className="inline-flex h-9 flex-1 items-center justify-center gap-2 rounded border px-3 text-[12px] cursor-pointer"
                  style={{ borderColor: "var(--console-border)", background: "var(--console-raised)", color: "var(--console-text)" }}
                >
                  <Upload className="h-4 w-4" />
                  {file ? "Replace" : "Choose"}
                  <input type="file" accept="image/*" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                </label>
                {file && (
                  <button
                    type="button"
                    onClick={() => setFile(null)}
                    className="h-9 rounded border px-2 text-[11px]"
                    style={{ borderColor: "var(--console-border)", background: "var(--console-raised)", color: "var(--console-muted)" }}
                  >
                    Remove
                  </button>
                )}
              </div>
              {previewUrl && (
                <div className="mt-2 h-20 rounded border overflow-hidden" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}>
                  <img src={previewUrl} alt="Reference" className="h-full w-full object-contain" />
                </div>
              )}
              <div className="mt-1 text-[11px] truncate" style={{ color: "var(--console-muted)" }}>
                {file?.name || "No file selected"}
              </div>
            </div>

            {/* Cameras */}
            <div>
              <span className={labelClass} style={labelStyle}>Cameras</span>
              <div
                className="min-h-9 rounded border p-1.5 flex flex-wrap gap-1.5"
                style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}
              >
                {assignedCameras.length === 0 ? (
                  <span className="text-[11px]" style={{ color: "var(--console-muted)" }}>No assigned cameras</span>
                ) : assignedCameras.map((cam) => {
                  const on = selectedCameraIds.has(cam.camera_id);
                  return (
                    <button
                      key={cam.camera_id}
                      type="button"
                      onClick={() => toggleCamera(cam.camera_id)}
                      className="rounded border px-2 py-1 text-[11px]"
                      style={{
                        borderColor: on ? "var(--console-accent)" : "var(--console-border)",
                        background: on ? "rgba(34,139,34,0.22)" : "var(--console-panel)",
                        color: on ? "var(--console-text)" : "var(--console-muted)",
                        opacity: cam.enabled ? 1 : 0.72,
                      }}
                    >
                      {cam.camera_name || cam.camera_id}
                      {!cam.enabled ? " · history" : ""}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Time + confidence */}
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className={labelClass} style={labelStyle}>From</span>
                <input className={inputClass} style={inputStyle} type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label className="block">
                <span className={labelClass} style={labelStyle}>To</span>
                <input className={inputClass} style={inputStyle} type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} />
              </label>
              <label className="block col-span-2">
                <span className={labelClass} style={labelStyle}>Min confidence</span>
                <input className={inputClass} style={inputStyle} type="number" min="0" max="1" step="0.01" value={confidence} onChange={(e) => setConfidence(e.target.value)} />
              </label>
            </div>
            </div>

            {error && (
              <div className="rounded border p-2 text-[11px]" style={{ borderColor: "var(--console-rec)", background: "var(--console-raised)", color: "var(--console-rec)" }}>
                {error}
              </div>
            )}
          </div>

          {/* Sticky action bar — prominent SEARCH, always reachable */}
          <div className="shrink-0 border-t p-2.5 flex gap-2" style={{ borderColor: "var(--console-border)" }}>
            <button
              type="submit"
              disabled={loading || blocked}
              className="flex-1 inline-flex items-center justify-center gap-2 rounded h-10 text-[13px] font-semibold uppercase tracking-widest disabled:opacity-50"
              style={{ background: "var(--console-accent)", color: "#ffffff" }}
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {loading ? "Searching" : "Search"}
            </button>
            <button
              type="button"
              onClick={resetBuilder}
              className="inline-flex items-center justify-center gap-2 rounded h-10 px-3 border text-[12px]"
              style={{ borderColor: "var(--console-border)", background: "var(--console-raised)", color: "var(--console-text)" }}
              title="Reset builder"
            >
              <RotateCcw className="h-4 w-4" />
              Reset
            </button>
          </div>
        </form>

        {/* ════════════════ CENTER — RESULT CANVAS ════════════════ */}
        <section
          className="rounded border flex flex-col min-h-0"
          style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
        >
          <div className="px-4 py-2.5 border-b flex items-center justify-between gap-3" style={{ borderColor: "var(--console-border)" }}>
            <span className="font-telemetry text-[12px] font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>
              {searched ? `${matchCount} match${matchCount === 1 ? "" : "es"}` : "Search results"}
            </span>
            {searched && !loading && (
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                Press “Find similar” on a result to refine
              </span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            {loading ? (
              <div className="h-full flex flex-col items-center justify-center gap-3">
                <Loader2 className="h-9 w-9 animate-spin" style={{ color: "var(--console-accent)" }} />
                <div className="font-telemetry text-[12px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>Searching…</div>
              </div>
            ) : !searched ? (
              <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-6">
                <Search className="h-14 w-14" style={{ color: "var(--console-border)" }} />
                <div className="font-telemetry text-[13px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  Build a suspect on the left and press Search
                </div>
                <div className="text-[12px] max-w-md" style={{ color: "var(--console-muted)" }}>
                  Match by garment type and colour, gender, age, accessories, cameras and time — no reference photo required.
                </div>
              </div>
            ) : results.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center gap-3 text-center">
                <Camera className="h-12 w-12" style={{ color: "var(--console-border)" }} />
                <div className="font-telemetry text-[12px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  No matches found
                </div>
                <div className="text-[12px]" style={{ color: "var(--console-muted)" }}>Try widening the colour, time range or confidence.</div>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-3">
                {results.map((result) => {
                  const url = playbackUrl(result);
                  const resultId = result.result_id || result.id;
                  const topHex = hexOf(result, "top_hex", "top_rgb");
                  const bottomHex = hexOf(result, "bottom_hex", "bottom_rgb");
                  const domHex = hexOf(result, "dominant_hex");
                  const accs = accList(result);
                  return (
                    <article
                      key={resultId}
                      className="rounded border p-3 space-y-3"
                      style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}
                    >
                      <ResultThumb scenarioSlug={scenario.slug} resultId={resultId} />
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-[12px] truncate" style={{ color: "var(--console-text)" }}>{result.camera_name || result.camera_id || "Camera"}</div>
                          <div className="text-[11px] truncate" style={{ color: "var(--console-muted)" }}>{result.timestamp || result.triggered_at || "-"}</div>
                        </div>
                        <div className="rounded px-2 py-1 text-[11px] shrink-0 border" style={{ borderColor: "var(--console-accent)", background: "rgba(34,139,34,0.2)", color: "var(--console-text)" }}>
                          {typeof result.confidence === "number" ? `${Math.round(result.confidence * 100)}%` : "-"}
                        </div>
                      </div>

                      <div className="flex flex-wrap gap-1">
                        <Badge>{result.object_type || objectType}</Badge>
                        {(result.top_type || topHex) && (
                          <Badge swatch={topHex || undefined}>{result.top_type || result.top_color || "top"}</Badge>
                        )}
                        {(result.bottom_type || bottomHex) && (
                          <Badge swatch={bottomHex || undefined}>{result.bottom_type || result.bottom_color || "bottom"}</Badge>
                        )}
                        {domHex && <Badge swatch={domHex}>colour</Badge>}
                        {result.gender && <Badge>{result.gender}</Badge>}
                        {result.age_band && <Badge>{result.age_band}</Badge>}
                        {accs.map((a) => {
                          const meta = ACCESSORIES.find((x) => x.key === a);
                          const Icon = meta?.Icon;
                          return (
                            <Badge key={a}>
                              {Icon ? <Icon className="h-3 w-3" /> : null}
                              {a}
                            </Badge>
                          );
                        })}
                      </div>

                      <div className="flex gap-2">
                        {url ? (
                          <Link
                            className="flex-1 rounded border px-3 py-2 text-center text-[12px]"
                            style={{ borderColor: "var(--console-border)", background: "var(--console-panel)", color: "var(--console-text)" }}
                            to={url}
                          >
                            Playback
                          </Link>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => searchSimilar(result)}
                          className="flex-1 rounded px-3 py-2 text-[12px] font-semibold"
                          style={{ background: "var(--console-accent)", color: "#050505" }}
                        >
                          Find similar
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        </section>

        {/* ════════════════ RIGHT — CONTEXT ════════════════ */}
        <aside
          className="rounded border flex flex-col min-h-0"
          style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
        >
          <div className="flex-1 overflow-y-auto p-3 space-y-4">
            {/* Active filters */}
            <div>
              <SectionLabel>Active filters</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {!isPerson && <Badge>{objectType}</Badge>}
                {isPerson && topType !== "any" && <Badge>top: {topType}</Badge>}
                {isPerson && topUseColor && <Badge swatch={topRgb}>top colour</Badge>}
                {isPerson && bottomType !== "any" && <Badge>bottom: {bottomType}</Badge>}
                {isPerson && bottomUseColor && <Badge swatch={bottomRgb}>bottom colour</Badge>}
                {isPerson && gender !== "any" && <Badge>{gender}</Badge>}
                {isPerson && ageBand !== "any" && <Badge>age {ageBand}</Badge>}
                {isPerson && Array.from(accessories).map((a) => <Badge key={a}>{a}</Badge>)}
                {(from || to) && <Badge>time range</Badge>}
                {selectedCameraIds.size > 0 && <Badge>{selectedCameraIds.size} cam</Badge>}
                {file && <Badge>reference image</Badge>}
                {!hasAttributeSearch && !file && (
                  <span className="text-[12px]" style={{ color: "var(--console-muted)" }}>
                    No filters set — choose attributes, cameras or a time range.
                  </span>
                )}
              </div>
            </div>

            {/* Movement trajectory */}
            <div className="rounded border p-3" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}>
              <SectionLabel Icon={MapPinned}>Movement trajectory</SectionLabel>
              {results.length === 0 ? (
                <div className="text-[12px]" style={{ color: "var(--console-muted)" }}>No route until matches are available.</div>
              ) : (
                <div className="space-y-3">
                  {results.slice(0, 12).map((result, index) => (
                    <div key={`${result.result_id || result.id}-route`} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <div className="h-6 w-6 rounded-full text-[11px] flex items-center justify-center" style={{ background: "var(--console-accent)", color: "#050505" }}>{index + 1}</div>
                        {index < Math.min(results.length, 12) - 1 && <div className="h-8 w-px" style={{ background: "var(--console-border)" }} />}
                      </div>
                      <div className="min-w-0">
                        <div className="text-[12px] truncate" style={{ color: "var(--console-text)" }}>{result.camera_name || result.camera_id || "Camera"}</div>
                        <div className="text-[11px] truncate" style={{ color: "var(--console-muted)" }}>{result.timestamp || result.triggered_at}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Index archive — minor, tucked at the bottom */}
          <div className="border-t p-3 space-y-2" style={{ borderColor: "var(--console-border)" }}>
            <SectionLabel Icon={Database}>Index archive</SectionLabel>
            <div className="text-[11px]" style={{ color: "var(--console-muted)" }}>
              Background pass that indexes the archive so attribute search has data.
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={loading || blocked || noEnabledCameras}
                onClick={runIndex}
                className="flex-1 inline-flex items-center justify-center gap-2 rounded h-8 border text-[11px] disabled:opacity-50"
                style={{ borderColor: "var(--console-border)", background: "var(--console-raised)", color: "var(--console-text)" }}
              >
                <Database className="h-3.5 w-3.5" />
                {indexRunning ? "Indexing…" : "Index"}
              </button>
              {job && (
                <button
                  type="button"
                  onClick={() => refreshJob().catch((err) => setError(friendlyError(err, "Something went wrong. Please try again.")))}
                  className="inline-flex items-center justify-center rounded h-8 w-8 border"
                  style={{ borderColor: "var(--console-border)", background: "var(--console-raised)", color: "var(--console-text)" }}
                  title="Refresh index status"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${polling ? "animate-spin" : ""}`} />
                </button>
              )}
              {indexRunning && (
                <button
                  type="button"
                  onClick={() => cancelScenarioJob(scenario.slug, job.job_id).then(setJob).catch((err) => setError(friendlyError(err, "Something went wrong. Please try again.")))}
                  className="inline-flex items-center justify-center rounded h-8 w-8 border"
                  style={{ borderColor: "var(--console-rec)", background: "var(--console-raised)", color: "var(--console-rec)" }}
                  title="Cancel index job"
                >
                  <XCircle className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            {job && (
              <div className="text-[10px] font-telemetry uppercase tracking-wider" style={{ color: "var(--console-muted)" }}>
                {job.status} · {Math.round((job.progress || 0) * 100)}%{job.message ? ` · ${job.message}` : ""}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
};

export default SuspectSearchTab;
