// =============================================================================
// AI · PPE Video tab — upload a clip, watch it analysed live, get events + a result.
//
// Flow:
//   1. Pick a video + required PPE + (optional) ROI polygon drawn on the first frame.
//   2. Upload → backend runs the SAME Triton PPE pipeline frame-by-frame in a job.
//   3. While processing we poll the latest annotated frame (auth'd JPEG) + status
//      (progress, live violation alerts). Violations also land in the Events tab.
//   4. On done, replay the annotated MP4 + a per-worker compliance summary.
//
// ROI is drawn as a polygon (click to add points) over the first frame; it's sent
// as normalised [x,y] pairs and applied by the backend's build_roi/in_roi feet-gate.
// =============================================================================
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Upload,
  PlaySquare,
  ShieldAlert,
  ShieldCheck,
  Loader2,
  X,
  RotateCcw,
  Check,
} from "lucide-react";

import {
  uploadPpeVideo,
  getPpeVideoStatus,
  getPpeVideoResult,
  fetchPpeVideoFrame,
  fetchPpeVideoOutput,
} from "../../../../api/ppe";

const PPE_ITEMS = ["helmet", "vest", "goggles", "boots"];

export default function VideoTab() {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);     // first-frame for ROI draw
  const [required, setRequired] = useState(["helmet", "vest"]);
  const [emitCompliant, setEmitCompliant] = useState(false);
  const [roiPoints, setRoiPoints] = useState([]);          // [{x,y}] normalised 0..1

  const [job, setJob] = useState(null);                    // {job_id, state}
  const [status, setStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [frameUrl, setFrameUrl] = useState(null);
  const [outputUrl, setOutputUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const fileInputRef = useRef(null);

  // ── first-frame preview for ROI drawing ──────────────────────────────────
  const onPick = useCallback((f) => {
    if (!f) return;
    setFile(f);
    setRoiPoints([]);
    setResult(null);
    setJob(null);
    setStatus(null);
    setError(null);
    // grab the first frame via a hidden <video> for the ROI canvas backdrop
    const url = URL.createObjectURL(f);
    const v = document.createElement("video");
    v.preload = "metadata";
    v.muted = true;
    v.src = url;
    v.onloadeddata = () => {
      v.currentTime = Math.min(0.1, v.duration || 0.1);
    };
    v.onseeked = () => {
      const c = document.createElement("canvas");
      c.width = v.videoWidth || 1280;
      c.height = v.videoHeight || 720;
      c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
      setPreviewUrl(c.toDataURL("image/jpeg", 0.7));
      URL.revokeObjectURL(url);
    };
    v.onerror = () => {
      setPreviewUrl(null);
      URL.revokeObjectURL(url);
    };
  }, []);

  // ── ROI canvas click ──────────────────────────────────────────────────────
  const canvasWrapRef = useRef(null);
  const onCanvasClick = (e) => {
    if (job) return; // locked once processing
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    setRoiPoints((p) => [...p, { x: clamp01(x), y: clamp01(y) }]);
  };

  // ── upload ────────────────────────────────────────────────────────────────
  const startUpload = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      // build_roi accepts a bare normalised polygon [[x,y],...] (auto-scales to px).
      const roi = roiPoints.length >= 3
        ? roiPoints.map((p) => [p.x, p.y])
        : null;
      const res = await uploadPpeVideo(file, {
        required_items: required,
        roi,
        emit_compliant: emitCompliant,
      });
      setJob(res);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "upload failed");
    } finally {
      setBusy(false);
    }
  };

  // ── poll status + latest frame while processing ──────────────────────────
  useEffect(() => {
    if (!job?.job_id || result) return undefined;
    let alive = true;
    let frameObj = null;

    const tick = async () => {
      if (!alive) return;
      try {
        const st = await getPpeVideoStatus(job.job_id);
        if (!alive) return;
        setStatus(st);
        if (st.state === "processing") {
          const u = await fetchPpeVideoFrame(job.job_id);
          if (!alive) { if (u) URL.revokeObjectURL(u); return; }
          setFrameUrl((old) => {
            if (old) URL.revokeObjectURL(old);
            return u;
          });
          frameObj = u;
        } else if (st.state === "done") {
          const r = await getPpeVideoResult(job.job_id);
          if (!alive) return;
          setResult(r);
          const out = await fetchPpeVideoOutput(job.job_id);
          if (alive) setOutputUrl(out);
        } else if (st.state === "error") {
          setError(st.error || "processing failed");
        }
      } catch (_e) {
        /* transient — keep polling */
      }
    };

    tick();
    const id = setInterval(tick, 700);
    return () => {
      alive = false;
      clearInterval(id);
      if (frameObj) URL.revokeObjectURL(frameObj);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.job_id, result]);

  // cleanup output blob
  useEffect(() => () => { if (outputUrl) URL.revokeObjectURL(outputUrl); }, [outputUrl]);

  const reset = () => {
    setFile(null); setPreviewUrl(null); setRoiPoints([]);
    setJob(null); setStatus(null); setResult(null); setError(null);
    if (frameUrl) URL.revokeObjectURL(frameUrl);
    if (outputUrl) URL.revokeObjectURL(outputUrl);
    setFrameUrl(null); setOutputUrl(null);
  };

  const toggleItem = (it) =>
    setRequired((r) => (r.includes(it) ? r.filter((x) => x !== it) : [...r, it]));

  const processing = job && !result && status?.state !== "error";

  return (
    <div className="p-4 grid grid-cols-1 lg:grid-cols-3 gap-4 h-full overflow-y-auto">
      {/* ── left: config / upload ─────────────────────────────────────────── */}
      <div className="lg:col-span-1 space-y-4">
        <Section title="Upload video">
          {!file ? (
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-full h-28 rounded border border-dashed flex flex-col items-center justify-center gap-2 text-sm"
              style={{ borderColor: "var(--console-border)" }}
            >
              <Upload className="h-5 w-5 opacity-70" />
              Click to choose a video
            </button>
          ) : (
            <div className="flex items-center justify-between text-sm">
              <span className="truncate">{file.name}</span>
              {!job && (
                <button onClick={reset} className="opacity-70 hover:opacity-100">
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={(e) => onPick(e.target.files?.[0])}
          />
        </Section>

        <Section title="Required PPE">
          <div className="flex flex-wrap gap-2">
            {PPE_ITEMS.map((it) => {
              const on = required.includes(it);
              return (
                <button
                  key={it}
                  disabled={!!job}
                  onClick={() => toggleItem(it)}
                  className="px-3 h-8 rounded text-xs uppercase tracking-wide border-2 flex items-center gap-1.5 transition-colors disabled:opacity-50"
                  style={{
                    borderColor: on ? "#16a34a" : "#3f3f46",
                    background: on ? "#16a34a" : "transparent",
                    color: on ? "#fff" : "#a1a1aa",
                    fontWeight: on ? 700 : 500,
                  }}
                >
                  {on && <Check className="h-3 w-3" />}
                  {it}
                </button>
              );
            })}
          </div>
          <p className="text-[11px] opacity-50 mt-2">
            Selected (green) items are checked on every worker. Tap to toggle.
          </p>
          <label className="flex items-center gap-2 mt-3 text-xs">
            <input
              type="checkbox"
              disabled={!!job}
              checked={emitCompliant}
              onChange={(e) => setEmitCompliant(e.target.checked)}
            />
            Also record compliant events
          </label>
        </Section>

        {!job && (
          <button
            disabled={!file || busy || required.length === 0}
            onClick={startUpload}
            className="w-full h-11 rounded-lg font-semibold text-sm flex items-center justify-center gap-2 shadow-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ background: "#16a34a", color: "#fff", border: "1px solid #15803d" }}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlaySquare className="h-4 w-4" />}
            {busy ? "Uploading…" : "Analyse video"}
          </button>
        )}

        {error && (
          <div className="text-xs text-red-400 border border-red-500/40 rounded p-2">{error}</div>
        )}

        {(processing || result) && (
          <button onClick={reset} className="w-full h-9 rounded text-xs border flex items-center justify-center gap-2"
            style={{ borderColor: "var(--console-border)" }}>
            <RotateCcw className="h-3.5 w-3.5" /> New video
          </button>
        )}
      </div>

      {/* ── center: ROI draw (pre-run) OR live/result video ───────────────── */}
      <div className="lg:col-span-2 space-y-4">
        <Section
          title={result ? "Result" : processing ? "Analysing…" : "Region of interest (optional)"}
          right={
            !job && roiPoints.length > 0 ? (
              <button onClick={() => setRoiPoints([])} className="text-xs opacity-70 hover:opacity-100">
                Clear ROI
              </button>
            ) : null
          }
        >
          {/* result video */}
          {result && outputUrl && (
            <video src={outputUrl} controls className="w-full rounded bg-black" />
          )}
          {result && !outputUrl && (
            <div className="aspect-video rounded bg-black flex items-center justify-center text-xs opacity-70">
              <Loader2 className="h-4 w-4 animate-spin mr-2" /> loading result video…
            </div>
          )}

          {/* live annotated frame */}
          {processing && (
            <div className="space-y-2">
              <div className="aspect-video rounded bg-black overflow-hidden flex items-center justify-center">
                {frameUrl ? (
                  <img src={frameUrl} alt="live" className="w-full h-full object-contain" />
                ) : (
                  <div className="text-xs opacity-70 flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin" /> preparing…
                  </div>
                )}
              </div>
              <Progress value={status?.progress || 0} />
              <div className="text-xs opacity-70">
                {status?.processed_frames || 0}/{status?.total_frames || "?"} frames ·{" "}
                {status?.violation_count || 0} violations
              </div>
            </div>
          )}

          {/* ROI draw canvas (before run) */}
          {!job && (
            <div
              ref={canvasWrapRef}
              onClick={onCanvasClick}
              className="relative aspect-video rounded bg-black overflow-hidden cursor-crosshair"
            >
              {previewUrl ? (
                <img src={previewUrl} alt="first frame" className="absolute inset-0 w-full h-full object-contain" />
              ) : (
                <div className="absolute inset-0 flex items-center justify-center text-xs opacity-60">
                  {file ? "loading first frame…" : "pick a video to draw an ROI"}
                </div>
              )}
              <RoiOverlay points={roiPoints} />
            </div>
          )}
          {!job && (
            <p className="text-[11px] opacity-60 mt-1">
              Click to add polygon points (≥3). Only workers whose feet fall inside are
              evaluated. Leave empty to use the whole frame.
            </p>
          )}
        </Section>

        {/* alerts + summary */}
        {processing && status?.alerts?.length > 0 && (
          <Section title="Live violations">
            <div className="space-y-1 max-h-48 overflow-auto">
              {status.alerts.map((a, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <ShieldAlert className="h-3.5 w-3.5 text-red-400" />
                  Worker #{a.track_id} — missing {a.missing?.join(", ")}
                </div>
              ))}
            </div>
          </Section>
        )}

        {result && (
          <Section title={`Per-worker summary (${result.persons_summary?.length || 0})`}>
            <div className="space-y-1">
              {(result.persons_summary || []).map((p) => (
                <div key={p.person_number} className="flex items-center gap-2 text-xs">
                  {p.compliant ? (
                    <ShieldCheck className="h-3.5 w-3.5 text-green-400" />
                  ) : (
                    <ShieldAlert className="h-3.5 w-3.5 text-red-400" />
                  )}
                  Worker #{p.track_id} —{" "}
                  {p.compliant ? "compliant" : `missing ${p.missing.join(", ")}`}
                </div>
              ))}
            </div>
            <div className="text-xs opacity-70 mt-2">
              {result.violation_count} violations · {result.compliant_count} compliant events
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}

function Section({ title, right, children }) {
  return (
    <div className="rounded border p-3" style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-widest opacity-70 font-telemetry">{title}</div>
        {right}
      </div>
      {children}
    </div>
  );
}

function Progress({ value }) {
  return (
    <div className="h-2 rounded bg-black/40 overflow-hidden">
      <div className="h-full transition-all" style={{ width: `${value}%`, background: "var(--accent, #16a34a)" }} />
    </div>
  );
}

function RoiOverlay({ points }) {
  if (!points.length) return null;
  const pct = (n) => `${n * 100}%`;
  const poly = points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ");
  return (
    <svg className="absolute inset-0 w-full h-full pointer-events-none" viewBox="0 0 100 100" preserveAspectRatio="none">
      {points.length >= 3 && (
        <polygon points={poly} fill="rgba(70,200,235,0.18)" stroke="#46c8eb" strokeWidth="0.4" />
      )}
      {points.map((p, i) => (
        <circle key={i} cx={p.x * 100} cy={p.y * 100} r="0.9" fill="#46c8eb" />
      ))}
    </svg>
  );
}

function clamp01(n) {
  return Math.max(0, Math.min(1, n));
}
