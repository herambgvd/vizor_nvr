// =============================================================================
// AI · Investigate tab (FRS) — forensic snapshot search by query face.
// =============================================================================
// Upload a query face image + similarity threshold + max results, submit to
// POST /api/ai/frs/investigate (proxied through the bridge to the FRS scenario),
// and render the ranked hits as a card grid: snapshot thumbnail (best-effort via
// the shared snapshotUrl helper, placeholder on miss), match score %, person
// name, and timestamp.
//
// Layout mirrors vizor-app's InvestigatePage: a 3/7 split — LEFT is the query
// form (drag-drop dropzone, name, similarity slider, max results, Search/Reset),
// RIGHT is the results pane (header + animated card grid). Past investigations
// live in a right-side history drawer; clicking one loads its stored results.
//
// NVR stays thin — all search logic + data live in the FRS scenario. This tab
// only POSTs the image and renders the JSON the bridge returns.
// =============================================================================

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  Upload,
  Loader2,
  ImageOff,
  X,
  UserCircle2,
  Clock,
  History,
  RotateCcw,
} from "lucide-react";
import { toast } from "sonner";
import { friendlyError } from "../../../../lib/utils";
import { formatDateTime } from "../../../../lib/datetime";

import { createInvestigation, listInvestigations, getInvestigation, scenarioSnapshotUrl } from "../../../../api/ai";

const FRS_SLUG = "frs";

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return formatDateTime(iso);
  } catch {
    return iso;
  }
}

function fmtScore(score) {
  if (score == null || Number.isNaN(Number(score))) return "—";
  return `${Math.round(Number(score) * 100)}%`;
}

function scoreColor(score) {
  if (score == null) return "var(--console-muted)";
  if (score >= 0.85) return "var(--console-accent)";
  if (score >= 0.6) return "#f59e0b";
  return "var(--console-rec)";
}

// Hit thumbnail. Investigate hits are captured live SIGHTINGS — the face
// snapshot lives behind the service-token-gated scenario proxy, so a bare
// <img src> can't authenticate. Fetch the bytes with the bearer token via
// scenarioSnapshotUrl and render the object URL (revoked on unmount).
function HitThumb({ snapshotPath }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!snapshotPath) { setUrl(null); return undefined; }
    let active = true;
    let obj = null;
    scenarioSnapshotUrl(FRS_SLUG, snapshotPath).then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      obj = u;
      setUrl(u);
    });
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
  }, [snapshotPath]);

  if (!url) {
    return (
      <div
        className="w-full aspect-square flex items-center justify-center"
        style={{ background: "var(--console-raised)" }}
      >
        <ImageOff className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
      </div>
    );
  }
  return <img src={url} alt="match" loading="lazy" className="w-full aspect-square object-cover" />;
}

const HitCard = ({ hit, onClick }) => (
  <div
    onClick={onClick}
    className="rounded overflow-hidden flex flex-col transition-all hover:-translate-y-0.5 cursor-pointer"
    style={{
      background: "var(--console-panel)",
      border: "1px solid var(--console-border)",
      animation: "frsFadeIn 300ms ease-out",
    }}
  >
    <div className="relative">
      <HitThumb snapshotPath={hit.snapshot_path} />
      <span
        className="absolute top-1.5 right-1.5 font-telemetry text-[11px] font-semibold uppercase tracking-widest px-1.5 py-0.5 rounded"
        style={{ background: "rgba(0,0,0,0.7)", color: scoreColor(hit.score) }}
      >
        {fmtScore(hit.score)}
      </span>
    </div>
    <div className="px-2.5 py-2 flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 min-w-0">
        <UserCircle2 className="h-3.5 w-3.5 shrink-0" style={{ color: "var(--console-accent)" }} />
        <span
          className="font-telemetry text-[12px] font-semibold truncate"
          style={{ color: "var(--console-text)" }}
        >
          {hit.person_name || (hit.person_id ? `Person ${String(hit.person_id).slice(0, 8)}` : "Unknown")}
        </span>
      </div>
      <div className="flex items-center gap-1.5 font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
        <Clock className="h-3 w-3 shrink-0" />
        <span>{fmtTime(hit.timestamp || hit.created_at)}</span>
      </div>
    </div>
  </div>
);

// ── Hit detail modal (click a result → full snapshot + metadata) ────────────
function HitDetailModal({ hit, onClose }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let obj = null, dead = false;
    scenarioSnapshotUrl("frs", hit.snapshot_path).then((u) => {
      if (!dead && u) { obj = u; setUrl(u); }
    });
    return () => { dead = true; if (obj) URL.revokeObjectURL(obj); };
  }, [hit.snapshot_path]);
  const name = hit.person_name || (hit.person_id ? `Person ${String(hit.person_id).slice(0, 8)}` : "Unknown");
  const rows = [
    ["Person", name],
    ["Similarity", fmtScore(hit.score)],
    ["Time", fmtTime(hit.timestamp || hit.created_at)],
    ["Camera", hit.camera_name || hit.camera_id || "—"],
    ["Event", hit.event_type || "—"],
    ["Liveness", hit.liveness_score != null ? `${Math.round(hit.liveness_score * 100)}%` : null],
    ["Age", hit.age || hit.age_range || null],
    ["Gender", hit.gender || null],
  ].filter(([, v]) => v != null && v !== "");
  return (
    <div onClick={onClose} className="fixed inset-0 z-[80] flex items-center justify-center p-6" style={{ background: "rgba(0,0,0,0.75)" }}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-3xl rounded-lg overflow-hidden flex flex-col"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}>
        <div className="flex items-center justify-between px-4 py-2.5" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <span className="font-telemetry text-[12px] uppercase tracking-widest" style={{ color: "var(--console-accent)" }}>Match detail</span>
          <button type="button" onClick={onClose} className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70" style={{ color: "var(--console-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4 p-4">
          <div className="md:col-span-3 rounded border overflow-hidden flex items-center justify-center" style={{ borderColor: "var(--console-border)", background: "#000", minHeight: 260 }}>
            {url ? <img src={url} alt="match" className="w-full h-full object-contain" /> :
              <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>Loading…</span>}
          </div>
          <div className="md:col-span-2 flex flex-col gap-2.5">
            {rows.map(([k, v]) => (
              <div key={k}>
                <div className="font-telemetry text-[9px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>{k}</div>
                <div className="font-telemetry text-[13px]" style={{ color: k === "Similarity" ? scoreColor(hit.score) : "var(--console-text)" }}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Right-side history drawer ───────────────────────────────────────────────
function HistoryDrawer({ open, onClose, onSelect }) {
  const { data, isLoading } = useQuery({
    queryKey: ["frs-investigations"],
    queryFn: () => listInvestigations(50),
    enabled: open,
  });
  const jobs = data?.items || [];

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="flex-1" style={{ background: "rgba(0,0,0,0.4)" }} onClick={onClose} />
      <div
        className="w-full max-w-md shadow-xl flex flex-col"
        style={{ background: "var(--console-panel)", borderLeft: "1px solid var(--console-border)" }}
      >
        <div
          className="px-4 py-3 flex items-center justify-between shrink-0"
          style={{ borderBottom: "1px solid var(--console-border)" }}
        >
          <div className="flex items-center gap-2">
            <History className="h-4 w-4" style={{ color: "var(--console-muted)" }} />
            <span className="font-telemetry text-[12px] font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>
              History
            </span>
            <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
              ({jobs.length})
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70"
            style={{ color: "var(--console-muted)" }}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
            </div>
          ) : jobs.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16">
              <History className="h-7 w-7" style={{ color: "var(--console-muted)" }} />
              <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                No investigations yet
              </span>
            </div>
          ) : (
            jobs.map((j) => (
              <button
                key={j.id}
                type="button"
                onClick={() => { onSelect(j.id); onClose(); }}
                className="w-full text-left px-4 py-3 flex flex-col gap-0.5 hover:bg-white/[0.04] transition-colors"
                style={{ borderBottom: "1px solid var(--console-border)" }}
              >
                <div className="flex items-center gap-2">
                  <span className="flex-1 font-telemetry text-[12px] font-medium truncate" style={{ color: "var(--console-text)" }}>
                    {j.name || `Search ${String(j.id).slice(0, 8)}`}
                  </span>
                  <span
                    className="font-telemetry text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded"
                    style={{ background: "var(--console-raised)", color: "var(--console-muted)" }}
                  >
                    {j.status || "done"}
                  </span>
                </div>
                <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
                  {j.result_count ?? 0} match{(j.result_count ?? 0) === 1 ? "" : "es"} · {fmtTime(j.created_at)}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// 0.45, not 0.6 — top-down CCTV faces legitimately match the snapshot index at
// ~0.5, so a 0.6 floor hid every real result and made investigate look broken.
const DEFAULT_THRESHOLD = 0.45;
const DEFAULT_MAX_RESULTS = 100;

const InvestigateTab = () => {
  const qc = useQueryClient();
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [name, setName] = useState("");
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD); // similarity filter
  const [maxResults, setMaxResults] = useState(DEFAULT_MAX_RESULTS);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [loadedJob, setLoadedJob] = useState(null); // job loaded from history
  const [selected, setSelected] = useState(null);   // hit opened in the detail modal

  // Preview object URL lifecycle.
  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const mut = useMutation({
    mutationFn: () =>
      createInvestigation(file, {
        top_k: Number(maxResults) || DEFAULT_MAX_RESULTS,
        min_score: Number(threshold),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["frs-investigations"] }),
    onError: (e) => toast.error(friendlyError(e, "Investigation failed")),
  });

  const setQueryFile = useCallback((f) => {
    if (!f) return;
    if (!f.type?.startsWith("image/")) {
      toast.error("Please drop an image file");
      return;
    }
    setFile(f);
    setLoadedJob(null);
    mut.reset();
  }, [mut]);

  const onPick = (e) => {
    setQueryFile(e.target.files?.[0]);
    e.target.value = "";
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    setQueryFile(e.dataTransfer?.files?.[0]);
  };

  const reset = () => {
    setFile(null);
    setName("");
    setThreshold(DEFAULT_THRESHOLD);
    setMaxResults(DEFAULT_MAX_RESULTS);
    setLoadedJob(null);
    mut.reset();
  };

  const submit = (e) => {
    e?.preventDefault?.();
    if (!file) {
      toast.error("Choose a query face image first");
      return;
    }
    setLoadedJob(null); // fresh search overrides any loaded history result
    mut.mutate();
  };

  const loadHistory = async (jobId) => {
    try {
      const job = await getInvestigation(jobId);
      setFile(null);
      mut.reset();
      setLoadedJob(job);
    } catch {
      toast.error("Couldn't load investigation");
    }
  };

  // Active result set: a loaded history job, else the live mutation result.
  const activeJob = loadedJob;
  const rawHits = loadedJob
    ? (loadedJob.results || loadedJob.hits || [])
    : (mut.data?.hits || []);
  const hits = useMemo(
    () => rawHits.filter((h) => h.score == null || Number(h.score) >= threshold),
    [rawHits, threshold],
  );

  const hasResults = loadedJob != null || mut.isSuccess;
  const headerTitle = activeJob?.name || (mut.isSuccess ? "Results" : "Results");
  const headerStatus = activeJob?.status || (mut.isSuccess ? "completed" : null);

  return (
    <div className="p-4 flex flex-col min-h-0" style={{ height: "100%" }}>
      <style>{`@keyframes frsFadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}`}</style>

      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <Search className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
        <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          Forensic Search
        </span>
        <button
          type="button"
          onClick={() => setHistoryOpen(true)}
          className="ml-auto inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-2.5 py-1 rounded border"
          style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
        >
          <History className="h-3.5 w-3.5" /> History
        </button>
      </div>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-10 gap-4 min-h-0">
        {/* LEFT — query form (30%) */}
        <form
          onSubmit={submit}
          className="lg:col-span-3 rounded-lg p-4 flex flex-col gap-3 overflow-y-auto"
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        >
          {/* Query image dropzone */}
          <div className="flex flex-col gap-1.5">
            <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              Query face
            </label>
            <div
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className="relative h-40 rounded-md flex items-center justify-center overflow-hidden cursor-pointer transition-colors"
              style={{
                border: `2px dashed ${dragOver ? "var(--console-accent)" : "var(--console-border)"}`,
                background: dragOver ? "var(--console-raised)" : "var(--console-raised)",
              }}
            >
              {previewUrl ? (
                <>
                  <img src={previewUrl} alt="query" className="h-full w-full object-contain" />
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setFile(null); mut.reset(); }}
                    className="absolute top-1.5 right-1.5 h-6 w-6 inline-flex items-center justify-center rounded"
                    style={{ background: "rgba(0,0,0,0.65)", color: "#fff" }}
                    title="Clear"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </>
              ) : (
                <span className="flex flex-col items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  <Upload className="h-5 w-5" />
                  Drop image or click
                </span>
              )}
            </div>
            <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPick} />
          </div>

          {/* Name */}
          <div className="flex flex-col gap-1.5">
            <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Optional label"
              className="rounded px-2.5 py-1.5 font-telemetry text-[12px] outline-none"
              style={inputStyle}
            />
          </div>

          {/* Similarity threshold slider */}
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                Similarity
              </label>
              <span className="font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
                {Number(threshold).toFixed(2)}
              </span>
            </div>
            <input
              type="range"
              min={0.3}
              max={0.95}
              step={0.01}
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value))}
              className="w-full"
              style={{ accentColor: "var(--console-accent)" }}
            />
          </div>

          {/* Max results */}
          <div className="flex flex-col gap-1.5">
            <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              Max results
            </label>
            <input
              type="number"
              min={1}
              max={1000}
              value={maxResults}
              onChange={(e) => setMaxResults(e.target.value)}
              className="rounded px-2.5 py-1.5 font-telemetry text-[12px] outline-none"
              style={inputStyle}
            />
          </div>

          {/* Actions */}
          <button
            type="submit"
            disabled={mut.isPending || !file}
            className="inline-flex items-center justify-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-4 py-2 rounded disabled:opacity-50"
            style={{ background: "var(--console-accent)", color: "#fff" }}
          >
            {mut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
            Search
          </button>
          <button
            type="button"
            onClick={reset}
            className="inline-flex items-center justify-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-4 py-2 rounded border"
            style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
          >
            <RotateCcw className="h-3.5 w-3.5" /> Reset
          </button>
        </form>

        {/* RIGHT — results pane (70%) */}
        <div
          className="lg:col-span-7 rounded-lg flex flex-col min-h-0 overflow-hidden"
          style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        >
          {/* Results header */}
          <div
            className="px-4 py-3 flex items-center justify-between shrink-0"
            style={{ borderBottom: "1px solid var(--console-border)" }}
          >
            <div className="min-w-0">
              <div className="font-telemetry text-[12px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
                {headerTitle}
              </div>
              <div className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                {hasResults
                  ? `${hits.length} match${hits.length === 1 ? "" : "es"} · similarity ${Number(threshold).toFixed(2)}`
                  : "Upload a query face to search recorded snapshots"}
              </div>
            </div>
            {headerStatus && (
              <span
                className="font-telemetry text-[9px] uppercase tracking-widest px-2 py-0.5 rounded shrink-0"
                style={{ background: "var(--console-raised)", color: "var(--console-muted)" }}
              >
                {headerStatus}
              </span>
            )}
          </div>

          {/* Results body */}
          <div className="flex-1 min-h-0 overflow-y-auto p-3">
            {mut.isPending ? (
              <div className="h-full flex flex-col items-center justify-center gap-3">
                <Loader2 className="h-6 w-6 animate-spin" style={{ color: "var(--console-accent)" }} />
                <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  Searching for matches…
                </span>
              </div>
            ) : mut.isError ? (
              <div className="h-full flex flex-col items-center justify-center gap-2">
                <ImageOff className="h-6 w-6" style={{ color: "var(--console-rec)" }} />
                <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-rec)" }}>
                  Search failed
                </span>
              </div>
            ) : hasResults && hits.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center gap-2">
                <Search className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
                <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  No matches above {Number(threshold).toFixed(2)} similarity
                </span>
              </div>
            ) : hasResults ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 gap-3">
                {hits.map((h, i) => (
                  <HitCard key={h.id || h.photo_id || `${h.snapshot_path}-${i}`} hit={h}
                    onClick={() => setSelected(h)} />
                ))}
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center gap-2">
                <Search className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
                <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                  Run an investigation to see matches here
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      <HistoryDrawer
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onSelect={loadHistory}
      />
      {selected && <HitDetailModal hit={selected} onClose={() => setSelected(null)} />}
    </div>
  );
};

export default InvestigateTab;
