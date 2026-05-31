// =============================================================================
// AI · PPE Detect tab — one-shot image + async video compliance detection.
// =============================================================================
// IMAGE section: pick a file → preview → "Detect" runs detectPPE (synchronous)
// and renders per-person compliance: a PPE-item grid (helmet/vest/mask/gloves/
// goggles/shoes) with present/missing badges, a compliant/violation verdict and
// the missing-item violations list, plus summary metrics.
//
// VIDEO section: pick a file → "Submit" calls submitPPEVideoJob, then we poll
// ppeVideoJobStatus every 2s showing a progress bar; when state is terminal we
// fetch ppeVideoJobResults and render a table of compliance events.
//
// Both flows route NVR UI → NVR backend → bridge HTTP → PPE gRPC (:50052). The
// NVR is a pure proxy; all compliance logic lives in the PPE scenario.
// =============================================================================

import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { HardHat, Upload, Film, Loader2, X, ShieldCheck, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import {
  detectPPE,
  submitPPEVideoJob,
  ppeVideoJobStatus,
  ppeVideoJobResults,
} from "../../../api/ai";

// ---------------------------------------------------------------------------
// shared primitives
// ---------------------------------------------------------------------------

const cardStyle = {
  background: "var(--console-panel)",
  border: "1px solid var(--console-border)",
};

// PPE item flags in render order. Keyed to detectPPE person fields.
const PPE_ITEMS = [
  { key: "has_helmet", label: "Helmet" },
  { key: "has_vest", label: "Vest" },
  { key: "has_mask", label: "Mask" },
  { key: "has_gloves", label: "Gloves" },
  { key: "has_goggles", label: "Goggles" },
  { key: "has_shoes", label: "Shoes" },
];

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

// ---------------------------------------------------------------------------
// image detection section
// ---------------------------------------------------------------------------

const PPEItemBadge = ({ label, present }) => (
  <span
    className="inline-flex items-center justify-center font-telemetry text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded border"
    style={{
      background: "var(--console-raised)",
      borderColor: present ? "var(--console-online)" : "var(--console-border)",
      color: present ? "var(--console-online)" : "var(--console-muted)",
    }}
    title={present ? `${label}: present` : `${label}: missing`}
  >
    {label}
  </span>
);

const PersonRow = ({ person, index }) => {
  const compliant = !!person.compliant;
  return (
    <div
      className="rounded p-3 flex flex-col gap-2"
      style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
    >
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div
            className="font-telemetry text-[12px] font-semibold truncate"
            style={{ color: "var(--console-text)" }}
          >
            {person.track_id ? `Track #${person.track_id}` : `Person ${index + 1}`}
          </div>
          <div
            className="font-telemetry text-[10px] uppercase tracking-widest truncate"
            style={{ color: "var(--console-muted)" }}
          >
            conf {person.confidence != null ? `${(person.confidence * 100).toFixed(0)}%` : "—"}
          </div>
        </div>
        <span
          className="inline-flex items-center gap-1 font-telemetry text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded border"
          style={{
            background: "var(--console-raised)",
            borderColor: compliant ? "var(--console-online)" : "var(--console-rec)",
            color: compliant ? "var(--console-online)" : "var(--console-rec)",
          }}
        >
          {compliant ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
          {compliant ? "Compliant" : "Violation"}
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {PPE_ITEMS.map((it) => (
          <PPEItemBadge key={it.key} label={it.label} present={!!person[it.key]} />
        ))}
      </div>

      {Array.isArray(person.violations) && person.violations.length > 0 && (
        <div
          className="font-telemetry text-[10px] uppercase tracking-widest"
          style={{ color: "var(--console-rec)" }}
        >
          Missing: {person.violations.join(", ")}
        </div>
      )}
    </div>
  );
};

const ImageSection = () => {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);

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
    mutationFn: () => detectPPE(file),
    onSuccess: (data) => setResult(data),
    onError: (e) => toast.error(e?.response?.data?.detail || "Detection failed"),
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

  const persons = result?.persons || [];

  return (
    <section className="rounded p-5 flex flex-col gap-4" style={cardStyle}>
      <SectionHeader icon={HardHat} title="Image compliance" />

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
              {mut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <HardHat className="h-3.5 w-3.5" />}
              Detect
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
              <HardHat className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
              <span
                className="font-telemetry text-[10px] uppercase tracking-widest"
                style={{ color: "var(--console-muted)" }}
              >
                Pick an image and run compliance detection
              </span>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-2">
                <Metric label="People" value={persons.length} />
                <Metric label="Compliant" value={result.compliant_count ?? 0} color="var(--console-online)" />
                <Metric
                  label="Violations"
                  value={result.violation_count ?? 0}
                  color={(result.violation_count ?? 0) > 0 ? "var(--console-rec)" : undefined}
                />
              </div>
              {persons.length === 0 ? (
                <div
                  className="flex flex-col items-center justify-center gap-2 py-10 rounded"
                  style={{ border: "1px dashed var(--console-border)" }}
                >
                  <span
                    className="font-telemetry text-[10px] uppercase tracking-widest"
                    style={{ color: "var(--console-muted)" }}
                  >
                    No people detected
                  </span>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {persons.map((p, i) => (
                    <PersonRow key={p.person_id || p.track_id || i} person={p} index={i} />
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
// video detection section
// ---------------------------------------------------------------------------

// PPE job states are proto enum names (JobState). Map terminal/active to colors.
const STATE_COLOR = {
  JOB_COMPLETED: "var(--console-online)",
  JOB_FAILED: "var(--console-rec)",
  JOB_CANCELLED: "var(--console-rec)",
  JOB_PROCESSING: "var(--console-accent)",
  JOB_QUEUED: "var(--console-alarm)",
};

const isTerminal = (s) =>
  s === "JOB_COMPLETED" || s === "JOB_FAILED" || s === "JOB_CANCELLED";

const fmtTs = (t) => {
  if (t == null) return "—";
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleString();
};

const VideoSection = () => {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [jobId, setJobId] = useState(null);

  const submitMut = useMutation({
    mutationFn: () => submitPPEVideoJob(file),
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
    queryKey: ["ppe-video-job", jobId],
    queryFn: () => ppeVideoJobStatus(jobId),
    enabled: !!jobId,
    refetchInterval: (q) => (isTerminal(q.state.data?.state) ? false : 2000),
  });

  const done = status?.state === "JOB_COMPLETED";

  const { data: results } = useQuery({
    queryKey: ["ppe-video-results", jobId],
    queryFn: () => ppeVideoJobResults(jobId),
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
        <SectionHeader icon={Film} title="Video compliance" count={jobId ? events.length || undefined : undefined} />
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
            Pick a video file and submit a compliance job
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
                No compliance events
              </span>
            </div>
          ) : (
            <div className="rounded overflow-hidden" style={{ border: "1px solid var(--console-border)" }}>
              <table className="w-full border-collapse">
                <thead>
                  <tr style={{ background: "var(--console-raised)" }}>
                    {["Track", "Verdict", "Missing", "Timestamp"].map((h) => (
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
                  {events.map((ev, i) => {
                    const c = ev.compliance || {};
                    const compliant = !!c.compliant;
                    return (
                      <tr key={ev.id || i} style={{ borderTop: "1px solid var(--console-border)" }}>
                        <td className="px-3 py-2 font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
                          {ev.track_id || c.track_id || "—"}
                        </td>
                        <td
                          className="px-3 py-2 font-telemetry text-[11px]"
                          style={{ color: compliant ? "var(--console-online)" : "var(--console-rec)" }}
                        >
                          {compliant ? "Compliant" : "Violation"}
                        </td>
                        <td className="px-3 py-2 font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
                          {Array.isArray(c.violations) && c.violations.length ? c.violations.join(", ") : "—"}
                        </td>
                        <td className="px-3 py-2 font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
                          {fmtTs(ev.timestamp)}
                        </td>
                      </tr>
                    );
                  })}
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

const PPEDetectTab = () => (
  <div className="p-6 flex flex-col gap-4">
    <ImageSection />
    <VideoSection />
  </div>
);

export default PPEDetectTab;
