// =============================================================================
// AI · PPE Media tab — on-demand video analysis (no live camera needed).
//
// Upload a clip (<=500 MB) -> draw an ROI on its first frame -> pick required PPE
// -> run the FULL PPE pipeline on the server -> watch progress -> play the
// annotated result + browse the detected events. Lets the operator validate the
// model and run a video-file workflow while cameras are offline. All calls go
// through the authenticated scenario proxy.
// =============================================================================

import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Upload,
  Play,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  Film,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";
import { proxyScenario } from "../../../../api/ai";

const REQUIRED_OPTIONS = ["helmet", "vest", "goggles", "boots"];

// Coerce any backend error (string, FastAPI 422 array, or object) to a readable
// string — never return an object, or React crashes trying to render it.
function errMsg(e, fallback) {
  const d = e?.response?.data?.detail ?? e?.response?.data ?? e?.message;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || JSON.stringify(x)).join("; ");
  if (d && typeof d === "object") return d.msg || JSON.stringify(d);
  return fallback;
}

// ── ROI editor (click to add · drag corner to resize · drag inside to move) ──
function RoiEditor({ imgUrl, points, onChange, aspect = 16 / 9 }) {
  const wrapRef = useRef(null);
  const drag = useRef(null);
  const [dragging, setDragging] = useState(false);
  const rel = (e) => {
    const b = wrapRef.current?.getBoundingClientRect();
    if (!b) return null;
    return [
      Math.min(1, Math.max(0, (e.clientX - b.left) / b.width)),
      Math.min(1, Math.max(0, (e.clientY - b.top) / b.height)),
    ];
  };
  const round = (n) => Number(n.toFixed(4));
  const addPoint = (e) => {
    if (drag.current) return;
    const p = rel(e);
    if (p) onChange([...points, [round(p[0]), round(p[1])]]);
  };
  const startVertex = (e, i) => { e.stopPropagation(); drag.current = { type: "v", i }; setDragging(true); };
  const startPoly = (e) => {
    e.stopPropagation();
    const p = rel(e);
    if (p) { drag.current = { type: "p", o: p, base: points.map((q) => [...q]) }; setDragging(true); }
  };
  useEffect(() => {
    if (!dragging) return;
    const move = (e) => {
      const d = drag.current; if (!d) return;
      const p = rel(e); if (!p) return;
      if (d.type === "v") onChange(points.map((q, i) => (i === d.i ? [round(p[0]), round(p[1])] : q)));
      else {
        const dx = p[0] - d.o[0], dy = p[1] - d.o[1];
        onChange(d.base.map(([x, y]) => [round(Math.min(1, Math.max(0, x + dx))), round(Math.min(1, Math.max(0, y + dy)))]));
      }
    };
    const up = () => { setDragging(false); setTimeout(() => { drag.current = null; }, 0); };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, [dragging, points, onChange]);
  const poly = points.map((p) => `${p[0] * 100},${p[1] * 100}`).join(" ");
  const closed = points.length > 2;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          Region of interest
        </span>
        <div className="flex gap-2">
          <button type="button" onClick={() => onChange(points.slice(0, -1))} disabled={!points.length}
            className="font-telemetry text-[10px] uppercase px-2 py-0.5 rounded border disabled:opacity-40"
            style={{ borderColor: "var(--console-border)", color: "var(--console-muted)", background: "var(--console-raised)" }}>Undo</button>
          <button type="button" onClick={() => onChange([])} disabled={!points.length}
            className="font-telemetry text-[10px] uppercase px-2 py-0.5 rounded border disabled:opacity-40"
            style={{ borderColor: "var(--console-border)", color: "var(--console-rec)", background: "var(--console-raised)" }}>Clear</button>
        </div>
      </div>
      <div ref={wrapRef} onClick={addPoint}
        className="relative w-full rounded border overflow-hidden"
        style={{ borderColor: "var(--console-border)", background: "#000", aspectRatio: String(aspect), cursor: dragging ? "grabbing" : "crosshair" }}>
        {imgUrl && <img src={imgUrl} alt="" className="absolute inset-0 w-full h-full object-contain pointer-events-none" />}
        <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          {points.length > 1 && (
            <polygon points={poly} fill="rgba(45,212,191,0.18)" stroke="var(--console-accent)" strokeWidth="0.4"
              style={{ cursor: closed ? "grab" : "default", pointerEvents: closed ? "auto" : "none" }}
              onMouseDown={closed ? startPoly : undefined} />
          )}
          {points.map((p, i) => (
            <g key={i}>
              <circle cx={p[0] * 100} cy={p[1] * 100} r="2.6" fill="transparent" style={{ cursor: "grab", pointerEvents: "auto" }}
                onMouseDown={(e) => startVertex(e, i)} />
              <circle cx={p[0] * 100} cy={p[1] * 100} r="1.1" fill="var(--console-accent)" stroke="#fff" strokeWidth="0.3" style={{ pointerEvents: "none" }} />
            </g>
          ))}
        </svg>
        {!points.length && (
          <div className="absolute inset-0 flex items-center justify-center font-telemetry text-[10px] uppercase tracking-widest pointer-events-none" style={{ color: "var(--console-muted)" }}>
            Click to add ROI points (empty = whole frame)
          </div>
        )}
      </div>
      <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
        {points.length} point{points.length === 1 ? "" : "s"} · click add · drag corner resize · drag inside move · empty = whole frame
      </span>
    </div>
  );
}

const fmtTs = (s) => {
  if (s == null) return "—";
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
};

// Event crop thumbnail — fetches the stored snapshot JPEG through the auth proxy.
// snapshot_path is "/snapshot?key=live:<id>"; we request the cropped variant.
function EventThumb({ slug, snapshotPath, onPreview }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url = null, dead = false;
    if (!snapshotPath) return undefined;
    const key = (snapshotPath.split("key=")[1] || "").split("&")[0];
    if (!key) return undefined;
    proxyScenario(slug, "/snapshot", { params: { key, crop: true }, responseType: "blob" })
      .then((b) => { if (!dead && b) { url = URL.createObjectURL(b); setSrc(url); } })
      .catch(() => {});
    return () => { dead = true; if (url) URL.revokeObjectURL(url); };
  }, [slug, snapshotPath]);
  return (
    <div onClick={(e) => { e.stopPropagation(); if (src) onPreview?.(src); }}
      className="h-14 w-14 shrink-0 rounded overflow-hidden cursor-zoom-in"
      style={{ background: "#000", border: "1px solid var(--console-border)" }} title="View snapshot">
      {src && <img src={src} alt="" className="h-full w-full object-cover" />}
    </div>
  );
}

export default function MediaTab({ scenario }) {
  const slug = scenario?.slug || "ppe";
  const [stage, setStage] = useState("upload");   // upload | config | running | done | error
  const [upload, setUpload] = useState(null);      // {upload_id, width, height, frames, fps, bytes}
  const [frameUrl, setFrameUrl] = useState(null);
  const [roi, setRoi] = useState([]);
  const [required, setRequired] = useState(["helmet", "vest"]);
  const [job, setJob] = useState(null);            // status payload
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [videoUrl, setVideoUrl] = useState(null);
  const fileRef = useRef(null);
  const pollRef = useRef(null);
  const videoRef = useRef(null);
  const [preview, setPreview] = useState(null);   // {src} enlarged event snapshot

  const seekTo = (ts) => {
    if (videoRef.current && ts != null) {
      videoRef.current.currentTime = ts;
      videoRef.current.play?.().catch(() => {});
    }
  };

  const reset = () => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (frameUrl) URL.revokeObjectURL(frameUrl);
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    setStage("upload"); setUpload(null); setFrameUrl(null); setRoi([]); setRequired(["helmet", "vest"]);
    setJob(null); setErr(null); setBusy(false); setVideoUrl(null);
  };

  // ── upload ────────────────────────────────────────────────────────────────
  const onFile = async (file) => {
    if (!file) return;
    if (file.size > 500 * 1024 * 1024) { setErr("Video exceeds the 500 MB limit."); return; }
    setBusy(true); setErr(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await proxyScenario(slug, "/media/upload", { method: "POST", data: fd, timeout: 600000 });
      setUpload(r);
      // fetch first frame for ROI drawing (auth blob)
      const blob = await proxyScenario(slug, "/media/frame", { params: { upload_id: r.upload_id }, responseType: "blob" })
        .catch(() => null);
      if (blob) setFrameUrl(URL.createObjectURL(blob));
      setStage("config");
    } catch (e) {
      setErr(errMsg(e, "Upload failed."));
    } finally { setBusy(false); }
  };

  // ── analyze ───────────────────────────────────────────────────────────────
  const run = async () => {
    setBusy(true); setErr(null);
    try {
      const config = { required_items: required, fps: 5 };
      if (roi.length > 2) config.roi = roi;
      const r = await proxyScenario(slug, "/media/analyze", {
        method: "POST", data: { upload_id: upload.upload_id, config, sample_fps: 5 },
      });
      setStage("running");
      pollRef.current = setInterval(() => poll(r.job_id), 2000);
    } catch (e) {
      setErr(errMsg(e, "Could not start analysis."));
      setBusy(false);
    }
  };

  const loadResult = async (jobId) => {
    const blob = await proxyScenario(slug, "/media/result", { params: { job_id: jobId }, responseType: "blob" }).catch(() => null);
    if (blob) setVideoUrl(URL.createObjectURL(blob));
  };

  const poll = async (jobId) => {
    try {
      const s = await proxyScenario(slug, "/media/status", { params: { job_id: jobId } });
      setJob(s);
      if (s.status === "done") {
        clearInterval(pollRef.current);
        setStage("done"); setBusy(false);
        await loadResult(jobId);
      } else if (s.status === "error") {
        clearInterval(pollRef.current);
        setStage("error"); setErr(s.error || "Analysis failed."); setBusy(false);
      }
    } catch (e) { /* keep polling */ }
  };

  // ── history ────────────────────────────────────────────────────────────────
  const [history, setHistory] = useState([]);
  const loadHistory = async () => {
    try {
      const r = await proxyScenario(slug, "/media/list");
      setHistory(r?.jobs || []);
    } catch { /* ignore */ }
  };
  useEffect(() => { loadHistory(); }, []);   // eslint-disable-line

  // Delete a job completely (result + source + metadata).
  const deleteJob = async (jobId, e) => {
    e?.stopPropagation?.();
    if (!window.confirm("Delete this analysis and its video completely?")) return;
    try {
      await proxyScenario(slug, "/media/delete", { method: "POST", data: { job_id: jobId } });
      setHistory((h) => h.filter((j) => j.job_id !== jobId));
      if (job?.job_id === jobId) reset();
    } catch (err) { setErr(errMsg(err, "Delete failed.")); }
  };

  // Open a previously-finished job from history.
  const openJob = async (jobId) => {
    setErr(null); setVideoUrl(null);
    try {
      const s = await proxyScenario(slug, "/media/status", { params: { job_id: jobId } });
      setJob(s);
      if (s.status === "done") { setStage("done"); await loadResult(jobId); }
      else if (s.status === "error") { setStage("error"); setErr(s.error || "Analysis failed."); }
      else { setStage("running"); pollRef.current = setInterval(() => poll(jobId), 2000); }
    } catch (e) { setErr(errMsg(e, "Could not open job.")); }
  };

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const toggleReq = (item) =>
    setRequired((r) => (r.includes(item) ? r.filter((x) => x !== item) : [...r, item]));

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="w-full max-w-[1600px] mx-auto flex flex-col gap-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Film className="h-5 w-5" style={{ color: "var(--console-accent)" }} />
            <h2 className="font-telemetry text-[14px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
              Video analysis
            </h2>
          </div>
          {stage !== "upload" && (
            <button type="button" onClick={reset}
              className="inline-flex items-center gap-1.5 font-telemetry text-[11px] uppercase tracking-wide px-2.5 py-1 rounded border"
              style={{ borderColor: "var(--console-border)", color: "var(--console-muted)", background: "var(--console-raised)" }}>
              <RotateCcw className="h-3.5 w-3.5" /> New
            </button>
          )}
        </div>

        {err && (
          <div className="flex items-center gap-2 px-3 py-2 rounded text-[12px]"
            style={{ background: "rgba(248,113,113,0.1)", color: "#f87171", border: "1px solid rgba(248,113,113,0.3)" }}>
            <AlertTriangle className="h-4 w-4" /> {err}
          </div>
        )}

        {/* STEP 1 — upload */}
        {stage === "upload" && (
          <div className="rounded-lg border p-10 flex flex-col items-center justify-center text-center gap-4"
            style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
            <Upload className="h-9 w-9" style={{ color: "var(--console-muted)" }} />
            <div>
              <p className="font-telemetry text-[13px]" style={{ color: "var(--console-text)" }}>Upload a video to analyse</p>
              <p className="font-telemetry text-[11px] mt-1" style={{ color: "var(--console-muted)" }}>MP4 / H.264 · up to 500 MB</p>
            </div>
            <input ref={fileRef} type="file" accept="video/*" className="hidden"
              onChange={(e) => onFile(e.target.files?.[0])} />
            <button type="button" disabled={busy} onClick={() => fileRef.current?.click()}
              className="inline-flex items-center gap-2 px-4 h-9 rounded font-telemetry text-[12px] uppercase tracking-wide disabled:opacity-50"
              style={{ background: "var(--console-accent)", color: "#04201c" }}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              {busy ? "Uploading…" : "Choose video"}
            </button>
          </div>
        )}

        {/* History — past analyses (click to reopen) */}
        {stage === "upload" && history.length > 0 && (
          <div className="rounded-lg border" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
            <div className="flex items-center justify-between px-4 py-2.5" style={{ borderBottom: "1px solid var(--console-border)" }}>
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-accent)" }}>Recent analyses</span>
              <button type="button" onClick={loadHistory} className="font-telemetry text-[10px] uppercase" style={{ color: "var(--console-muted)" }}>Refresh</button>
            </div>
            <div className="max-h-72 overflow-y-auto">
              {history.map((h) => (
                <div key={h.job_id} onClick={() => openJob(h.job_id)}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-black/5 cursor-pointer"
                  style={{ borderBottom: "1px solid var(--console-border)" }}>
                  <Film className="h-4 w-4 shrink-0" style={{ color: "var(--console-muted)" }} />
                  <span className="flex-1 truncate font-telemetry text-[12px]" style={{ color: "var(--console-text)" }}>{h.name || "video"}</span>
                  <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>{h.event_count ?? 0} events</span>
                  <span className="font-telemetry text-[10px] uppercase px-1.5 py-0.5 rounded"
                    style={{
                      color: h.status === "done" ? "#34d399" : h.status === "error" ? "#f87171" : "#fbbf24",
                      background: "var(--console-raised)",
                    }}>{h.status}</span>
                  <button type="button" onClick={(e) => deleteJob(h.job_id, e)} title="Delete"
                    className="shrink-0 p-1 rounded hover:bg-black/10" style={{ color: "var(--console-rec)" }}>
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* STEP 2 — config (ROI + required) */}
        {stage === "config" && (
          <div className="flex flex-col gap-5">
            <div className="rounded-lg border p-4" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
              <RoiEditor imgUrl={frameUrl} points={roi} onChange={setRoi}
                aspect={upload?.width && upload?.height ? upload.width / upload.height : 16 / 9} />
            </div>
            <div className="rounded-lg border p-4 flex flex-col gap-3" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>Required PPE</span>
              <div className="flex flex-wrap gap-2">
                {REQUIRED_OPTIONS.map((it) => {
                  const on = required.includes(it);
                  return (
                    <button key={it} type="button" onClick={() => toggleReq(it)}
                      className="px-3 h-8 rounded font-telemetry text-[12px] uppercase tracking-wide border transition-colors"
                      style={{
                        borderColor: on ? "var(--console-accent)" : "var(--console-border)",
                        background: on ? "rgba(45,212,191,0.15)" : "var(--console-raised)",
                        color: on ? "var(--console-accent)" : "var(--console-muted)",
                      }}>{it}</button>
                  );
                })}
              </div>
              <p className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
                {upload?.width}×{upload?.height} · {upload?.frames} frames · {upload?.fps} fps
              </p>
            </div>
            <button type="button" disabled={busy || !required.length} onClick={run}
              className="self-start inline-flex items-center gap-2 px-5 h-10 rounded font-telemetry text-[12px] uppercase tracking-wide disabled:opacity-50"
              style={{ background: "var(--console-accent)", color: "#04201c" }}>
              <Play className="h-4 w-4" /> Run analysis
            </button>
          </div>
        )}

        {/* STEP 3 — running */}
        {stage === "running" && (
          <div className="rounded-lg border p-8 flex flex-col items-center gap-4" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
            <Loader2 className="h-8 w-8 animate-spin" style={{ color: "var(--console-accent)" }} />
            <p className="font-telemetry text-[13px]" style={{ color: "var(--console-text)" }}>
              {job?.status === "encoding" ? "Encoding annotated video…" : "Analysing video…"}
            </p>
            <div className="w-full max-w-md h-2 rounded-full overflow-hidden" style={{ background: "var(--console-raised)" }}>
              <div className="h-full transition-all" style={{ width: `${Math.round((job?.progress || 0) * 100)}%`, background: "var(--console-accent)" }} />
            </div>
            <p className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
              {Math.round((job?.progress || 0) * 100)}% · {job?.frames_done || 0}/{job?.frames_total || "—"} frames · {job?.event_count || 0} events
            </p>
          </div>
        )}

        {/* STEP 4 — done: annotated video (left) + events with crop image (right) */}
        {stage === "done" && (
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-[12px]" style={{ color: "#34d399" }}>
                <CheckCircle2 className="h-4 w-4" /> Analysis complete · {job?.event_count ?? job?.events?.length ?? 0} events
              </div>
              {job?.job_id && (
                <button type="button" onClick={(e) => deleteJob(job.job_id, e)}
                  className="inline-flex items-center gap-1.5 font-telemetry text-[11px] uppercase tracking-wide px-2.5 py-1 rounded border"
                  style={{ borderColor: "var(--console-border)", color: "var(--console-rec)", background: "var(--console-raised)" }}>
                  <Trash2 className="h-3.5 w-3.5" /> Delete
                </button>
              )}
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
              {/* annotated video */}
              <div className="lg:col-span-3">
                {videoUrl ? (
                  <video ref={videoRef} src={videoUrl} controls
                    className="w-full rounded-lg border" style={{ borderColor: "var(--console-border)", background: "#000" }} />
                ) : (
                  <div className="w-full rounded-lg border flex items-center justify-center"
                    style={{ borderColor: "var(--console-border)", background: "#000", aspectRatio: "16/9", color: "var(--console-muted)" }}>
                    <Loader2 className="h-5 w-5 animate-spin" />
                  </div>
                )}
              </div>
              {/* events list */}
              <div className="lg:col-span-2 rounded-lg border flex flex-col" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
                <div className="px-4 py-2.5 font-telemetry text-[10px] uppercase tracking-widest shrink-0" style={{ borderBottom: "1px solid var(--console-border)", color: "var(--console-accent)" }}>
                  Detected events ({job?.events?.length || 0})
                </div>
                <div className="overflow-y-auto" style={{ maxHeight: "60vh" }}>
                  {(job?.events || []).length === 0 ? (
                    <div className="px-4 py-6 text-center font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>No violations detected.</div>
                  ) : (
                    (job?.events || []).map((e, i) => (
                      <button key={i} type="button" onClick={() => seekTo(e.video_ts)}
                        className="w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-black/5"
                        style={{ borderBottom: i < job.events.length - 1 ? "1px solid var(--console-border)" : "none" }}>
                        <EventThumb slug={slug} snapshotPath={e.snapshot_path} onPreview={(s) => setPreview({ src: s })} />
                        <span className="flex-1 min-w-0">
                          <span className="flex items-center gap-1.5 text-[12px]" style={{ color: "var(--console-text)" }}>
                            <ShieldAlert className="h-3.5 w-3.5 shrink-0" style={{ color: e.event_type === "ppe_compliant" ? "#34d399" : "#f87171" }} />
                            {e.event_type === "ppe_compliant" ? "Compliant" : `No ${(e.missing_items || []).join(", ") || "PPE"}`}
                          </span>
                          <span className="block font-telemetry text-[10px] mt-0.5" style={{ color: "var(--console-muted)" }}>
                            worker #{e.worker_track_id} · {fmtTs(e.video_ts)}
                          </span>
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Snapshot preview overlay */}
      {preview && (
        <div onClick={() => setPreview(null)}
          className="fixed inset-0 z-50 flex items-center justify-center p-8"
          style={{ background: "rgba(0,0,0,0.8)" }}>
          <button type="button" onClick={() => setPreview(null)}
            className="absolute top-4 right-4 p-2 rounded" style={{ color: "#fff", background: "rgba(255,255,255,0.1)" }}>
            <X className="h-5 w-5" />
          </button>
          <img src={preview.src} alt="" className="max-h-full max-w-full rounded-lg"
            style={{ border: "1px solid var(--console-border)" }} onClick={(e) => e.stopPropagation()} />
        </div>
      )}
    </div>
  );
}
