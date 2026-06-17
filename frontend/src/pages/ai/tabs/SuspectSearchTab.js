import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertCircle,
  Camera,
  Database,
  MapPinned,
  RefreshCw,
  Search,
  Upload,
  XCircle,
} from "lucide-react";
import {
  cancelScenarioJob,
  createScenarioIndexJob,
  createScenarioSearchJob,
  createScenarioSimilarSearchJob,
  getScenarioJob,
  getScenarioJobResults,
  listScenarioCameras,
  scenarioThumbnailUrl,
} from "../../../api/ai";

const inputClass =
  "h-10 rounded border border-white/10 bg-black px-3 text-[13px] text-zinc-100 outline-none focus:border-[#228B22]";

const colors = ["any", "black", "white", "gray", "red", "orange", "yellow", "green", "blue", "purple", "pink", "brown"];
const colorHex = {
  black: "#111827",
  white: "#f8fafc",
  gray: "#6b7280",
  red: "#dc2626",
  orange: "#f97316",
  yellow: "#eab308",
  green: "#228B22",
  blue: "#2563eb",
  purple: "#7c3aed",
  pink: "#db2777",
  brown: "#8b5a2b",
};

const objectTypes = [
  { key: "person", label: "Person" },
  { key: "bag", label: "Bag" },
  { key: "helmet", label: "Helmet" },
];

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
    <div className="aspect-[4/3] rounded bg-zinc-950 border border-white/10 overflow-hidden flex items-center justify-center">
      {url ? <img src={url} alt="" className="h-full w-full object-cover" /> : <Camera className="h-5 w-5 text-zinc-700" />}
    </div>
  );
};

const ColorSelect = ({ label, value, onChange, disabled = false }) => (
  <label className="block">
    <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">{label}</span>
    <select disabled={disabled} className={`${inputClass} w-full disabled:opacity-45`} value={value} onChange={(e) => onChange(e.target.value)}>
      {colors.map((name) => <option key={name} value={name}>{name === "any" ? "Any" : name}</option>)}
    </select>
  </label>
);

const SuspectSearchTab = ({ scenario }) => {
  const [file, setFile] = useState(null);
  const [sourceMode, setSourceMode] = useState("upload");
  const [objectType, setObjectType] = useState("person");
  const [upperColor, setUpperColor] = useState("any");
  const [lowerColor, setLowerColor] = useState("any");
  const [dominantColor, setDominantColor] = useState("any");
  const [sizeBucket, setSizeBucket] = useState("any");
  const [positionRegion, setPositionRegion] = useState("any");
  const [confidence, setConfidence] = useState(0.72);
  const [cameraIds, setCameraIds] = useState("");
  const [assignedCameras, setAssignedCameras] = useState([]);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [job, setJob] = useState(null);
  const [results, setResults] = useState([]);
  const [resultTotal, setResultTotal] = useState(0);
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
      refreshJob(job.job_id).catch((err) => setError(err?.response?.data?.detail || err.message)).finally(() => setPolling(false));
    }, 2500);
    return () => clearInterval(timer);
  }, [job?.job_id, job?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const appendFilters = (form) => {
    form.append("object_type", objectType);
    form.append("min_confidence", String(confidence));
    if (cameraIds.trim()) form.append("camera_ids", cameraIds.trim());
    if (from) form.append("start_time", from);
    if (to) form.append("end_time", to);
    if (upperColor !== "any") form.append("upper_color", upperColor);
    if (lowerColor !== "any") form.append("lower_color", lowerColor);
    if (dominantColor !== "any") form.append("dominant_color", dominantColor);
    if (sizeBucket !== "any") form.append("size_bucket", sizeBucket);
    if (positionRegion !== "any") form.append("position_region", positionRegion);
  };

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    setJob(null);
    const hasAttributeSearch = objectType !== "person" ? dominantColor !== "any" : upperColor !== "any" || lowerColor !== "any";
    if (!file && !hasAttributeSearch) {
      setError("Reference image or color attributes required.");
      return;
    }
    const form = new FormData();
    if (file) form.append("reference", file);
    appendFilters(form);
    try {
      setLoading(true);
      const created = await createScenarioSearchJob(scenario.slug, form);
      setJob(created);
      setResults([]);
      setResultTotal(0);
      if (created?.job_id) await refreshJob(created.job_id);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Search job failed.");
    } finally {
      setLoading(false);
    }
  };

  const runIndex = async () => {
    setError("");
    try {
      setLoading(true);
      const created = await createScenarioIndexJob(scenario.slug, {
        object_types: "person,bag,helmet",
        camera_ids: cameraIds.trim(),
        start_time: from,
        end_time: to,
      });
      setJob(created);
      setResults([]);
      if (created?.job_id) await refreshJob(created.job_id);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Index job failed.");
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
      const created = await createScenarioSimilarSearchJob(scenario.slug, resultId, {
        object_type: result.object_type || objectType,
        min_confidence: confidence,
        camera_ids: cameraIds.trim(),
        start_time: from,
        end_time: to,
      });
      setJob(created);
      setResults([]);
      if (created?.job_id) await refreshJob(created.job_id);
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || "Nested search failed.");
    } finally {
      setLoading(false);
    }
  };

  const blocked = !scenario.licensed || !scenario.enabled;
  const noAssignedCameras = assignedCameras.length === 0;
  const enabledCameraCount = assignedCameras.filter((item) => item.enabled).length;
  const noEnabledCameras = enabledCameraCount === 0;
  const isPerson = objectType === "person";
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

  return (
    <div className="p-5 max-w-[1440px]">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-telemetry text-[14px] font-semibold uppercase tracking-wide text-zinc-100">
            Archive Object Search
          </h2>
          <p className="font-telemetry text-[11px] text-zinc-500 mt-1">
            Eocortex-style archive search for person, bag and helmet by photo, color, size, position and nested result matching.
          </p>
        </div>
        <button
          type="button"
          disabled={loading || blocked || noEnabledCameras}
          onClick={runIndex}
          className="inline-flex h-10 items-center gap-2 rounded bg-[#228B22] px-4 text-sm text-white disabled:opacity-50"
        >
          <Database className="h-4 w-4" />
          Index Archive
        </button>
      </div>

      {blocked && (
        <div className="mb-4 rounded border border-red-500/30 bg-red-950/20 p-3 flex gap-2 text-red-200 text-[12px]">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Scenario must be licensed and enabled before proxy search jobs can run.
        </div>
      )}
      {!blocked && noAssignedCameras && (
        <div className="mb-4 rounded border border-yellow-500/30 bg-yellow-950/20 p-3 flex gap-2 text-yellow-100 text-[12px]">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Enable Suspect Search on at least one camera from the Cameras tab before indexing or searching.
        </div>
      )}
      {!blocked && !noAssignedCameras && noEnabledCameras && (
        <div className="mb-4 rounded border border-yellow-500/30 bg-yellow-950/20 p-3 flex gap-2 text-yellow-100 text-[12px]">
          <AlertCircle className="h-4 w-4 shrink-0" />
          All assigned cameras are currently disabled. Historical indexed data can be searched, but new indexing is paused.
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[1fr_360px] gap-5">
        <main className="space-y-5">
          <form
            onSubmit={submit}
            className="rounded p-5"
            style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
          >
            <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-5">
              <section className="rounded border border-white/10 bg-black p-4 space-y-4">
                <div>
                  <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">Object</span>
                  <div className="grid grid-cols-3 gap-2">
                    {objectTypes.map((item) => (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => setObjectType(item.key)}
                        className="h-9 rounded border text-[12px]"
                        style={{
                          borderColor: objectType === item.key ? "#228B22" : "rgba(255,255,255,0.1)",
                          color: objectType === item.key ? "#fff" : "var(--console-muted)",
                          background: objectType === item.key ? "rgba(34,139,34,0.22)" : "transparent",
                        }}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="aspect-[4/3] rounded border border-white/10 bg-zinc-950 flex items-center justify-center overflow-hidden">
                  {previewUrl ? (
                    <img src={previewUrl} alt="Reference" className="h-full w-full object-contain" />
                  ) : (
                    <div className="text-center text-zinc-600 text-[12px] px-5">
                      Add photo/crop, or search using attributes only after archive indexing.
                    </div>
                  )}
                </div>

                <label className="inline-flex h-10 w-full items-center justify-center gap-2 rounded bg-[#228B22] px-4 text-sm text-white cursor-pointer">
                  <Upload className="h-4 w-4" />
                  Choose Sample
                  <input type="file" accept="image/*" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                </label>
                <div className="text-[12px] text-zinc-400 truncate">{file?.name || "No file selected"}</div>
              </section>

              <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 content-start">
                <label className="block">
                  <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">Sample Source</span>
                  <select className={`${inputClass} w-full`} value={sourceMode} onChange={(e) => setSourceMode(e.target.value)}>
                    <option value="upload">Upload image</option>
                    <option value="snapshot" disabled>Snapshot from recording</option>
                    <option value="crop" disabled>Crop from frame</option>
                  </select>
                </label>
                <label className="block">
                  <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">Minimum Confidence</span>
                  <input className={`${inputClass} w-full`} type="number" min="0" max="1" step="0.01" value={confidence} onChange={(e) => setConfidence(e.target.value)} />
                </label>
                <label className="block">
                  <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">Cameras</span>
                  <div className="min-h-10 rounded border border-white/10 bg-black p-2 flex flex-wrap gap-1.5">
                    {assignedCameras.length === 0 ? (
                      <span className="text-[12px] text-zinc-600">No enabled cameras</span>
                    ) : assignedCameras.map((cam) => {
                      const on = selectedCameraIds.has(cam.camera_id);
                      return (
                        <button
                          key={cam.camera_id}
                          type="button"
                          onClick={() => toggleCamera(cam.camera_id)}
                          className="rounded border px-2 py-1 text-[11px]"
                          style={{
                            borderColor: on ? "#228B22" : "rgba(255,255,255,0.12)",
                            background: on ? "rgba(34,139,34,0.22)" : "transparent",
                            color: on ? "#fff" : "var(--console-muted)",
                            opacity: cam.enabled ? 1 : 0.72,
                          }}
                        >
                          {cam.camera_name || cam.camera_id}
                          {!cam.enabled ? " · history" : ""}
                        </button>
                      );
                    })}
                  </div>
                </label>
                <ColorSelect label="Upper Wear" value={upperColor} onChange={setUpperColor} disabled={!isPerson} />
                <ColorSelect label="Lower Wear" value={lowerColor} onChange={setLowerColor} disabled={!isPerson} />
                <ColorSelect label={isPerson ? "Any Object Color" : "Object Color"} value={dominantColor} onChange={setDominantColor} />
                <label className="block">
                  <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">Size</span>
                  <select className={`${inputClass} w-full`} value={sizeBucket} onChange={(e) => setSizeBucket(e.target.value)}>
                    {["any", "small", "medium", "large"].map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </label>
                <label className="block">
                  <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">Position</span>
                  <select className={`${inputClass} w-full`} value={positionRegion} onChange={(e) => setPositionRegion(e.target.value)}>
                    {["any", "left", "center", "right", "top", "bottom"].map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </label>
                <div className="hidden xl:block" />
                <label className="block">
                  <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">From</span>
                  <input className={`${inputClass} w-full`} type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
                </label>
                <label className="block">
                  <span className="block text-[11px] uppercase tracking-wide text-zinc-400 mb-2">To</span>
                  <input className={`${inputClass} w-full`} type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} />
                </label>
                <div className="md:col-span-2 xl:col-span-3 rounded border border-white/10 bg-black p-3">
                  <div className="text-[11px] uppercase tracking-wide text-zinc-400">Engine</div>
                  <div className="text-[12px] text-zinc-500 mt-1">
                    Qdrant vector index with ONNX-ready detector/ReID runtime. Current fallback indexes sampled archive frames until YOLO26/ReID model files are mounted.
                  </div>
                </div>
              </section>
            </div>

            {error && <div className="mt-4 text-[12px] text-red-300">{error}</div>}

            <div className="mt-5 flex flex-wrap gap-2">
              <button type="submit" disabled={loading || blocked || noAssignedCameras} className="inline-flex items-center gap-2 rounded px-4 h-10 text-sm text-white disabled:opacity-50" style={{ background: "#228B22" }}>
                <Search className="h-4 w-4" />
                {loading ? "Working..." : "Search Archive"}
              </button>
              {job && !["completed", "failed", "cancelled"].includes(job.status) && (
                <button
                  type="button"
                  onClick={() => cancelScenarioJob(scenario.slug, job.job_id).then(setJob).catch((err) => setError(err?.response?.data?.detail || err.message))}
                  className="inline-flex items-center gap-2 rounded border border-red-500/40 px-3 h-10 text-[12px] text-red-200"
                >
                  <XCircle className="h-4 w-4" />
                  Cancel
                </button>
              )}
            </div>
          </form>

          {job && (
            <section className="rounded p-4 space-y-3" style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[12px] text-zinc-300">Job: {job.job_id}</div>
                  <div className="text-[12px] text-zinc-500 mt-1">
                    Status: {job.status} · Results: {resultTotal || job.result_count || 0} · Progress: {Math.round((job.progress || 0) * 100)}%
                  </div>
                  {job.message && <div className="text-[12px] text-zinc-400 mt-1">{job.message}</div>}
                </div>
                <button type="button" onClick={() => refreshJob().catch((err) => setError(err?.response?.data?.detail || err.message))} className="inline-flex items-center gap-2 rounded border border-white/10 px-3 h-9 text-[12px] text-zinc-200">
                  <RefreshCw className={`h-4 w-4 ${polling ? "animate-spin" : ""}`} />
                  Refresh
                </button>
              </div>

              {results.length === 0 ? (
                <div className="rounded border border-white/10 bg-black p-8 text-center text-[12px] text-zinc-600">
                  No matching objects returned yet.
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                  {results.map((result) => {
                    const url = playbackUrl(result);
                    const resultId = result.result_id || result.id;
                    return (
                      <article key={resultId} className="rounded border border-white/10 bg-black p-3 space-y-3">
                        <ResultThumb scenarioSlug={scenario.slug} resultId={resultId} />
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <div className="text-[12px] text-zinc-200">{result.camera_name || result.camera_id || "Camera"}</div>
                            <div className="text-[11px] text-zinc-500">{result.timestamp || result.triggered_at || "-"}</div>
                          </div>
                          <div className="rounded bg-[#228B22]/20 px-2 py-1 text-[11px] text-[#8bd98b]">
                            {typeof result.confidence === "number" ? `${Math.round(result.confidence * 100)}%` : "-"}
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1 text-[10px] text-zinc-400">
                          <span className="rounded border border-white/10 px-2 py-1">{result.object_type || objectType}</span>
                          {["upper_color", "lower_color", "dominant_color"].map((key) => result[key] ? (
                            <span key={key} className="rounded border border-white/10 px-2 py-1 inline-flex items-center gap-1">
                              <span className="h-2 w-2 rounded-full" style={{ background: colorHex[result[key]] || "#555" }} />
                              {result[key]}
                            </span>
                          ) : null)}
                        </div>
                        <div className="flex gap-2">
                          {url ? <Link className="flex-1 rounded border border-white/10 px-3 py-2 text-center text-[12px] text-[#228B22]" to={url}>Playback</Link> : null}
                          <button type="button" onClick={() => searchSimilar(result)} className="flex-1 rounded bg-[#228B22] px-3 py-2 text-[12px] text-white">
                            Search Similar
                          </button>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </section>
          )}
        </main>

        <aside className="rounded p-4 h-fit space-y-4" style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}>
          <div>
            <div className="text-[11px] uppercase tracking-wide text-zinc-400">Search Samples</div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              {[upperColor, lowerColor, dominantColor].filter((c) => c !== "any").map((name, index) => (
                <div key={`${name}-${index}`} className="rounded border border-white/10 bg-black p-2">
                  <div className="h-14 rounded" style={{ background: colorHex[name] || "#333" }} />
                  <div className="mt-2 text-[11px] capitalize text-zinc-300">{name}</div>
                </div>
              ))}
              {file && (
                <div className="rounded border border-white/10 bg-black p-2">
                  <div className="h-14 rounded overflow-hidden">{previewUrl && <img src={previewUrl} alt="" className="h-full w-full object-cover" />}</div>
                  <div className="mt-2 text-[11px] text-zinc-300 truncate">{file.name}</div>
                </div>
              )}
            </div>
            {!file && upperColor === "any" && lowerColor === "any" && dominantColor === "any" && (
              <div className="mt-3 text-[12px] text-zinc-600">Add a photo or choose color attributes.</div>
            )}
          </div>

          <div className="rounded border border-white/10 bg-black p-3">
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-zinc-400">
              <MapPinned className="h-4 w-4" />
              Movement Trajectory
            </div>
            {results.length === 0 ? (
              <div className="mt-4 text-[12px] text-zinc-600">No route until matches are available.</div>
            ) : (
              <div className="mt-4 space-y-3">
                {results.slice(0, 12).map((result, index) => (
                  <div key={`${result.result_id || result.id}-route`} className="flex gap-3">
                    <div className="flex flex-col items-center">
                      <div className="h-6 w-6 rounded-full bg-[#228B22] text-[11px] text-white flex items-center justify-center">{index + 1}</div>
                      {index < Math.min(results.length, 12) - 1 && <div className="h-8 w-px bg-white/10" />}
                    </div>
                    <div>
                      <div className="text-[12px] text-zinc-200">{result.camera_name || result.camera_id || "Camera"}</div>
                      <div className="text-[11px] text-zinc-500">{result.timestamp || result.triggered_at}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
};

export default SuspectSearchTab;
