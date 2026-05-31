// =============================================================================
// AI · Investigate tab (FRS) — forensic snapshot search by query face.
// =============================================================================
// Upload a query face image + top_k, submit to POST /api/ai/frs/investigate
// (proxied through the bridge to the FRS scenario), and render the ranked hits
// as a grid: snapshot thumbnail (best-effort via the shared snapshotUrl helper,
// placeholder on miss), person name, match score %, camera, and timestamp.
//
// NVR stays thin — all search logic + data live in the FRS scenario. This tab
// only POSTs the image and renders the JSON the bridge returns.
// =============================================================================

import React, { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Search,
  Upload,
  Loader2,
  ImageOff,
  X,
  UserCircle2,
  Video,
  Clock,
} from "lucide-react";
import { toast } from "sonner";
import { format } from "date-fns";

import { createInvestigation } from "../../../api/ai";
import { snapshotUrl } from "./frsShared";

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return format(new Date(iso), "MMM d, HH:mm:ss");
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

// Best-effort snapshot thumbnail. The FRS snapshot_key is a bare storage key;
// snapshotUrl resolves it to a servable URL — fall back to a placeholder when
// it cannot be served.
function HitThumb({ snapshotKey }) {
  const [errored, setErrored] = useState(false);
  const url = snapshotUrl(snapshotKey);
  if (!url || errored) {
    return (
      <div
        className="w-full aspect-video flex items-center justify-center"
        style={{ background: "var(--console-raised)" }}
      >
        <ImageOff className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
      </div>
    );
  }
  return (
    <img
      src={url}
      alt="snapshot"
      loading="lazy"
      onError={() => setErrored(true)}
      className="w-full aspect-video object-cover"
    />
  );
}

const HitCard = ({ hit }) => (
  <div
    className="rounded overflow-hidden flex flex-col"
    style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
  >
    <div className="relative">
      <HitThumb snapshotKey={hit.snapshot_key} />
      <span
        className="absolute top-1.5 right-1.5 font-telemetry text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded"
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
      <div className="flex items-center gap-1.5 min-w-0 font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        <Video className="h-3 w-3 shrink-0" />
        <span className="truncate">{hit.camera_name || "—"}</span>
      </div>
      <div className="flex items-center gap-1.5 font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
        <Clock className="h-3 w-3 shrink-0" />
        <span>{fmtTime(hit.timestamp)}</span>
      </div>
    </div>
  </div>
);

const InvestigateTab = () => {
  const fileRef = useRef(null);
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [topK, setTopK] = useState(50);

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const mut = useMutation({
    mutationFn: () => createInvestigation(file, { top_k: Number(topK) || 50 }),
    onError: (e) =>
      toast.error(e?.response?.data?.detail || "Investigation failed"),
  });

  const onPick = (e) => {
    const f = e.target.files?.[0];
    if (f) {
      setFile(f);
      mut.reset();
    }
    e.target.value = "";
  };

  const clear = () => {
    setFile(null);
    mut.reset();
  };

  const submit = () => {
    if (!file) {
      toast.error("Choose a query face image first");
      return;
    }
    mut.mutate();
  };

  const hits = mut.data?.hits || [];

  return (
    <div className="p-6 flex flex-col gap-4">
      {/* query bar */}
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
        <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          Forensic Search
        </span>
      </div>

      <div
        className="rounded p-4 flex flex-wrap items-center gap-4"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
      >
        {/* query preview / picker */}
        {previewUrl ? (
          <div className="relative h-28 w-28 rounded overflow-hidden shrink-0" style={{ border: "1px solid var(--console-border)" }}>
            <img src={previewUrl} alt="query" className="h-full w-full object-cover" />
            <button
              type="button"
              onClick={clear}
              className="absolute top-1 right-1 h-6 w-6 inline-flex items-center justify-center rounded"
              style={{ background: "rgba(0,0,0,0.65)", color: "#fff" }}
              title="Clear"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="h-28 w-28 rounded flex flex-col items-center justify-center gap-1.5 shrink-0"
            style={{ border: "1px dashed var(--console-border)", background: "var(--console-raised)", color: "var(--console-muted)" }}
          >
            <Upload className="h-5 w-5" />
            <span className="font-telemetry text-[9px] uppercase tracking-widest">Query face</span>
          </button>
        )}
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onPick} />

        <div className="flex flex-col gap-1.5">
          <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Top results
          </label>
          <input
            type="number"
            min={1}
            max={500}
            value={topK}
            onChange={(e) => setTopK(e.target.value)}
            className="w-24 rounded px-2.5 py-1.5 font-telemetry text-[12px] outline-none"
            style={inputStyle}
          />
        </div>

        <button
          type="button"
          onClick={submit}
          disabled={mut.isPending || !file}
          className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-4 py-2 rounded disabled:opacity-50"
          style={{ background: "var(--console-accent)", color: "#fff" }}
        >
          {mut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
          Search
        </button>

        {mut.isSuccess && (
          <span className="ml-auto font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
            {hits.length} hit{hits.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {/* results */}
      {mut.isPending ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
        </div>
      ) : mut.isError ? (
        <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
          <ImageOff className="h-6 w-6" style={{ color: "var(--console-rec)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-rec)" }}>
            Search failed
          </span>
        </div>
      ) : mut.isSuccess && hits.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
          <Search className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            No matching snapshots
          </span>
        </div>
      ) : mut.isSuccess ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
          {hits.map((h, i) => (
            <HitCard key={h.id || `${h.snapshot_key}-${i}`} hit={h} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center gap-2 py-16 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
          <Search className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Upload a query face to search recorded snapshots
          </span>
        </div>
      )}
    </div>
  );
};

export default InvestigateTab;
