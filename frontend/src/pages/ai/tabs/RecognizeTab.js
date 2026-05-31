// =============================================================================
// AI · Recognize tab (FRS) — one-shot image + async video recognition.
// =============================================================================
// IMAGE section: pick a file → preview → "Recognize" runs recognizeImage
// (synchronous) and renders the returned matches (person_name, confidence,
// watchlist badge), face count and liveness.
//
// VIDEO section: pick a file → "Submit" calls submitVideoJob, then we poll
// videoJobStatus every 2s (useQuery refetchInterval) showing a progress bar
// (frames_processed / frames_total + state). When state === "completed" we
// fetch videoJobResults and render a table of recognition events.
//
// Both flows route NVR UI → NVR backend → bridge HTTP → FRS gRPC. Image is
// returned immediately; video is async (submit → poll → results).
// =============================================================================

import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ScanFace, Upload, Film, Loader2, X, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import {
  recognizeImage,
  submitVideoJob,
  videoJobStatus,
  videoJobResults,
} from "../../../api/ai";

// ---------------------------------------------------------------------------
// shared primitives
// ---------------------------------------------------------------------------

const cardStyle = {
  background: "var(--console-panel)",
  border: "1px solid var(--console-border)",
};

const SectionHeader = ({ icon: Icon, title, count }) => (
  <div className="flex items-center gap-2">
    <Icon className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
    <span
      className="font-telemetry text-[11px] uppercase tracking-widest"
      style={{ color: "var(--console-muted)" }}
    >
      {title}
      {count != null ? ` · ${count}` : ""}
    </span>
  </div>
);

const PrimaryBtn = ({ children, ...props }) => (
  <button
    type="button"
    {...props}
    className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded disabled:opacity-50"
    style={{ background: "var(--console-accent)", color: "#fff" }}
  >
    {children}
  </button>
);

const GhostBtn = ({ children, danger, ...props }) => (
  <button
    type="button"
    {...props}
    className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded border disabled:opacity-50"
    style={{
      background: "var(--console-raised)",
      borderColor: "var(--console-border)",
      color: danger ? "var(--console-rec)" : "var(--console-muted)",
    }}
  >
    {children}
  </button>
);

const Metric = ({ label, value, color }) => (
  <div
    className="flex flex-col gap-0.5 rounded px-3 py-2"
    style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
  >
    <span
      className="font-telemetry text-[9px] uppercase tracking-widest"
      style={{ color: "var(--console-muted)" }}
    >
      {label}
    </span>
    <span
      className="font-telemetry text-[15px] font-semibold"
      style={{ color: color || "var(--console-text)" }}
    >
      {value}
    </span>
  </div>
);

const pct = (c) => (c != null ? `${(c * 100).toFixed(1)}%` : "—");

// ---------------------------------------------------------------------------
// image recognition section
// ---------------------------------------------------------------------------

const MatchRow = ({ match }) => (
  <div
    className="rounded p-3 flex items-center gap-3"
    style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
  >
    <div className="min-w-0 flex-1">
      <div
        className="font-telemetry text-[12px] font-semibold truncate"
        style={{ color: "var(--console-text)" }}
      >
        {match.person_name || "Unknown"}
      </div>
      <div
        className="font-telemetry text-[10px] uppercase tracking-widest truncate"
        style={{ color: "var(--console-muted)" }}
      >
        {match.category || "—"}
        {match.person_id ? ` · ${match.person_id}` : ""}
      </div>
    </div>
    {match.is_watchlist && (
      <span
        className="inline-flex items-center gap-1 font-telemetry text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded border"
        style={{
          background: "var(--console-raised)",
          borderColor: "var(--console-rec)",
          color: "var(--console-rec)",
        }}
      >
        <ShieldAlert className="h-3 w-3" />
        Watchlist
      </span>
    )}
    <span
      className="font-telemetry text-[13px] font-semibold"
      style={{ color: "var(--console-accent)" }}
    >
      {pct(match.confidence)}
    </span>
  </div>
);

const ImageSection = () => {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);

  // revoke object URL on change / unmount.
  useEffect(() => {
    if (!file) {
      setPreview(null);
      return undefined;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const mut = useMutation({
    mutationFn: () => recognizeImage(file),
    onSuccess: (data) => setResult(data),
    onError: (e) => toast.error(e?.response?.data?.detail || "Recognition failed"),
  });

  const onPick = (e) => {
    const f = e.target.files?.[0];
    if (f) {
      setFile(f);
      setResult(null);
    }
    e.target.value = "";
  };

  const clear = () => {
    setFile(null);
    setResult(null);
    mut.reset();
  };

  const matches = result?.matches || [];
  const faces = result?.faces || [];
  const liveness = result?.liveness;

  return (
    <section className="rounded p-5 flex flex-col gap-4" style={cardStyle}>
      <SectionHeader icon={ScanFace} title="Image recognition" />

      <div className="flex flex-col md:flex-row gap-4">
        {/* picker + preview */}
        <div className="flex flex-col gap-3 md:w-[280px] shrink-0">
          <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPick} />
          {preview ? (
            <div
              className="relative rounded overflow-hidden"
              style={{ border: "1px solid var(--console-border)" }}
            >
              <img src={preview} alt="" className="w-full aspect-square" style={{ objectFit: "cover" }} />
              <button
                type="button"
                onClick={clear}
                className="absolute top-1 right-1 h-6 w-6 inline-flex items-center justify-center rounded"
                style={{ background: "rgba(0,0,0,0.6)", color: "#fff" }}
                title="Clear"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex flex-col items-center justify-center gap-2 rounded aspect-square"
              style={{ border: "1px dashed var(--console-border)", background: "var(--console-raised)" }}
            >
              <Upload className="h-5 w-5" style={{ color: "var(--console-muted)" }} />
              <span
                className="font-telemetry text-[10px] uppercase tracking-widest"
                style={{ color: "var(--console-muted)" }}
              >
                Pick an image
              </span>
            </button>
          )}
          <div className="flex items-center gap-2">
            <PrimaryBtn onClick={() => mut.mutate()} disabled={!file || mut.isPending}>
              {mut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ScanFace className="h-3.5 w-3.5" />}
              Recognize
            </PrimaryBtn>
            {file && (
              <GhostBtn onClick={() => fileRef.current?.click()}>
                <Upload className="h-3.5 w-3.5" />
                Change
              </GhostBtn>
            )}
          </div>
        </div>

        {/* results */}
        <div className="flex-1 min-w-0 flex flex-col gap-3">
          {mut.isPending ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
            </div>
          ) : !result ? (
            <div
              className="flex flex-col items-center justify-center gap-2 py-16 rounded"
              style={{ border: "1px dashed var(--console-border)" }}
            >
              <ScanFace className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
              <span
                className="font-telemetry text-[10px] uppercase tracking-widest"
                style={{ color: "var(--console-muted)" }}
              >
                Pick an image and run recognition
              </span>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-2">
                <Metric label="Faces" value={faces.length} />
                <Metric label="Matches" value={matches.length} />
                <Metric
                  label="Liveness"
                  value={liveness ? (liveness.live ? pct(liveness.score) : "Spoof") : "—"}
                  color={liveness && !liveness.live ? "var(--console-rec)" : undefined}
                />
              </div>
              {matches.length === 0 ? (
                <div
                  className="flex flex-col items-center justify-center gap-2 py-10 rounded"
                  style={{ border: "1px dashed var(--console-border)" }}
                >
                  <span
                    className="font-telemetry text-[10px] uppercase tracking-widest"
                    style={{ color: "var(--console-muted)" }}
                  >
                    No matches
                  </span>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {matches.map((m, i) => (
                    <MatchRow key={m.person_id || i} match={m} />
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
};

// ---------------------------------------------------------------------------
// video recognition section
// ---------------------------------------------------------------------------

const STATE_COLOR = {
  completed: "var(--console-online)",
  failed: "var(--console-rec)",
  running: "var(--console-accent)",
  queued: "var(--console-alarm)",
  pending: "var(--console-alarm)",
};

const fmtTs = (t) => {
  if (t == null) return "—";
  const n = Number(t);
  if (Number.isNaN(n)) return String(t);
  // sub-second epoch / frame-time tolerated; render seconds for video offsets.
  if (n > 1e11) return new Date(n).toLocaleString();
  if (n > 1e9) return new Date(n * 1000).toLocaleString();
  return `${n.toFixed(2)}s`;
};

const VideoSection = () => {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [jobId, setJobId] = useState(null);

  const submitMut = useMutation({
    mutationFn: () => submitVideoJob(file),
    onSuccess: (data) => {
      const id = data?.job_id;
      if (!id) {
        toast.error("No job id returned");
        return;
      }
      setJobId(id);
      toast.success("Video job submitted");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Submit failed"),
  });

  const { data: status } = useQuery({
    queryKey: ["frs-video-job", jobId],
    queryFn: () => videoJobStatus(jobId),
    enabled: !!jobId,
    // poll every 2s until terminal; stop once completed/failed.
    refetchInterval: (q) => {
      const s = q.state.data?.state;
      return s === "completed" || s === "failed" ? false : 2000;
    },
  });

  const done = status?.state === "completed";

  const { data: results } = useQuery({
    queryKey: ["frs-video-results", jobId],
    queryFn: () => videoJobResults(jobId),
    enabled: !!jobId && done,
  });

  const onPick = (e) => {
    const f = e.target.files?.[0];
    if (f) setFile(f);
    e.target.value = "";
  };

  const clear = () => {
    setFile(null);
    setJobId(null);
    submitMut.reset();
  };

  const total = status?.frames_total || 0;
  const processed = status?.frames_processed || 0;
  const progress = status?.progress != null
    ? Math.round(status.progress * 100)
    : total > 0
      ? Math.round((processed / total) * 100)
      : 0;
  const events = results?.events || [];

  return (
    <section className="rounded p-5 flex flex-col gap-4" style={cardStyle}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <SectionHeader icon={Film} title="Video recognition" count={jobId ? events.length || undefined : undefined} />
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept="video/*" className="hidden" onChange={onPick} />
          {!jobId && (
            <>
              <GhostBtn onClick={() => fileRef.current?.click()}>
                <Upload className="h-3.5 w-3.5" />
                {file ? "Change file" : "Pick video"}
              </GhostBtn>
              <PrimaryBtn onClick={() => submitMut.mutate()} disabled={!file || submitMut.isPending}>
                {submitMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Film className="h-3.5 w-3.5" />}
                Submit
              </PrimaryBtn>
            </>
          )}
          {jobId && (
            <GhostBtn danger onClick={clear}>
              <X className="h-3.5 w-3.5" />
              Clear
            </GhostBtn>
          )}
        </div>
      </div>

      {file && !jobId && (
        <p className="font-telemetry text-[10px] uppercase tracking-widest truncate" style={{ color: "var(--console-muted)" }}>
          {file.name}
        </p>
      )}

      {!jobId ? (
        <div
          className="flex flex-col items-center justify-center gap-2 py-12 rounded"
          style={{ border: "1px dashed var(--console-border)" }}
        >
          <Film className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
          <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Pick a video file and submit a recognition job
          </span>
        </div>
      ) : (
        <>
          {/* progress */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span
                className="font-telemetry text-[10px] uppercase tracking-widest"
                style={{ color: STATE_COLOR[status?.state] || "var(--console-muted)" }}
              >
                {status?.state || "submitting"}
              </span>
              <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
                {processed}
                {total ? ` / ${total}` : ""} frames · {progress}%
              </span>
            </div>
            <div className="h-2 rounded overflow-hidden" style={{ background: "var(--console-raised)" }}>
              <div
                className="h-full rounded transition-all"
                style={{
                  width: `${progress}%`,
                  background: STATE_COLOR[status?.state] || "var(--console-accent)",
                }}
              />
            </div>
            {status?.error && (
              <p className="font-telemetry text-[10px] break-all" style={{ color: "var(--console-rec)" }}>
                {status.error}
              </p>
            )}
          </div>

          {/* results */}
          {!done ? (
            <div className="flex items-center justify-center gap-2 py-10">
              <Loader2 className="h-4 w-4 animate-spin" style={{ color: "var(--console-muted)" }} />
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                Processing…
              </span>
            </div>
          ) : events.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center gap-2 py-10 rounded"
              style={{ border: "1px dashed var(--console-border)" }}
            >
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                No recognition events
              </span>
            </div>
          ) : (
            <div className="rounded overflow-hidden" style={{ border: "1px solid var(--console-border)" }}>
              <table className="w-full border-collapse">
                <thead>
                  <tr style={{ background: "var(--console-raised)" }}>
                    {["Person", "Confidence", "Watchlist", "Timestamp"].map((h) => (
                      <th
                        key={h}
                        className="text-left font-telemetry text-[9px] uppercase tracking-widest px-3 py-2"
                        style={{ color: "var(--console-muted)" }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {events.map((ev, i) => (
                    <tr key={ev.id || i} style={{ borderTop: "1px solid var(--console-border)" }}>
                      <td className="px-3 py-2 font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
                        {ev.person_name || "Unknown"}
                      </td>
                      <td className="px-3 py-2 font-telemetry text-[11px]" style={{ color: "var(--console-accent)" }}>
                        {pct(ev.confidence)}
                      </td>
                      <td className="px-3 py-2 font-telemetry text-[11px]" style={{ color: ev.is_watchlist ? "var(--console-rec)" : "var(--console-muted)" }}>
                        {ev.is_watchlist ? "Yes" : "—"}
                      </td>
                      <td className="px-3 py-2 font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
                        {fmtTs(ev.timestamp)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
};

// ---------------------------------------------------------------------------
// tab
// ---------------------------------------------------------------------------

const RecognizeTab = () => (
  <div className="p-6 flex flex-col gap-4">
    <ImageSection />
    <VideoSection />
  </div>
);

export default RecognizeTab;
