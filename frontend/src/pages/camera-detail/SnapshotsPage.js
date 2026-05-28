// =============================================================================
// SnapshotsPage — /cameras/:id/snapshots
// Scheduled snapshot config + gallery grid with lightbox + date range picker.
// =============================================================================

import React, { useState, useCallback } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Camera,
  RefreshCw,
  Save,
  X,
  ChevronLeft,
  ChevronRight,
  Calendar,
  Pencil,
} from "lucide-react";
import SnapshotAnnotator from "../../components/nvr/SnapshotAnnotator";
import { toast } from "sonner";
import {
  getScheduledSnapshotConfig,
  updateScheduledSnapshotConfig,
  listSnapshots,
} from "../../api/cameras";
import { Button } from "../../components/ui/button";
import { BACKEND_URL } from "../../api/client";

// Pre-set interval helpers
const INTERVAL_PRESETS = [
  { label: "30 s", value: 30 },
  { label: "1 min", value: 60 },
  { label: "5 min", value: 300 },
  { label: "15 min", value: 900 },
  { label: "Hourly", value: 3600 },
];

const iso24hAgo = () => {
  const d = new Date();
  d.setHours(d.getHours() - 24);
  return d.toISOString();
};

const isoNow = () => new Date().toISOString();

const SnapshotsPage = () => {
  const { cameraId } = useOutletContext();
  const qc = useQueryClient();

  // ── Config state ─────────────────────────────────────────────────────
  const { data: cfg, isLoading: cfgLoading } = useQuery({
    queryKey: ["snapshot-config", cameraId],
    queryFn: () => getScheduledSnapshotConfig(cameraId),
  });

  const [enabled, setEnabled] = useState(null);
  const [intervalSec, setIntervalSec] = useState(null);
  const [retentionDays, setRetentionDays] = useState(null);

  // Initialise form from fetched config (only once)
  const eff_enabled = enabled !== null ? enabled : (cfg?.enabled ?? false);
  const eff_interval = intervalSec !== null ? intervalSec : (cfg?.interval_seconds ?? 60);
  const eff_retention = retentionDays !== null ? retentionDays : (cfg?.retention_days ?? "");

  const saveMutation = useMutation({
    mutationFn: (data) => updateScheduledSnapshotConfig(cameraId, data),
    onSuccess: () => {
      toast.success("Snapshot schedule saved");
      qc.invalidateQueries(["snapshot-config", cameraId]);
    },
    onError: (e) => toast.error(`Save failed: ${e?.response?.data?.detail || e.message}`),
  });

  const handleSave = () => {
    saveMutation.mutate({
      enabled: eff_enabled,
      interval_seconds: Number(eff_interval) || 60,
      retention_days: eff_retention ? Number(eff_retention) : null,
    });
  };

  // ── Gallery state ─────────────────────────────────────────────────────
  const [fromDt, setFromDt] = useState(iso24hAgo());
  const [toDt, setToDt] = useState(isoNow());
  const [lightboxIdx, setLightboxIdx] = useState(null);
  const [annotatorUrl, setAnnotatorUrl] = useState(null);

  const { data: snaps = [], isFetching: snapsFetching, refetch: refetchSnaps } = useQuery({
    queryKey: ["snapshots-list", cameraId, fromDt, toDt],
    queryFn: () => listSnapshots(cameraId, { from: fromDt, to: toDt, limit: 200 }),
    enabled: true,
  });

  const getImgSrc = (url) => `${BACKEND_URL}${url.startsWith("/api") ? "" : "/api"}${url}`;

  const openLightbox = (idx) => setLightboxIdx(idx);
  const closeLightbox = () => setLightboxIdx(null);
  const prev = () => setLightboxIdx((i) => Math.max(0, i - 1));
  const next = () => setLightboxIdx((i) => Math.min(snaps.length - 1, i + 1));

  // Keyboard nav in lightbox
  const handleKeyDown = useCallback((e) => {
    if (lightboxIdx === null) return;
    if (e.key === "ArrowLeft") prev();
    if (e.key === "ArrowRight") next();
    if (e.key === "Escape") closeLightbox();
  }, [lightboxIdx, snaps.length]); // eslint-disable-line

  return (
    <div
      className="p-4 md:p-6 space-y-8 max-w-5xl outline-none"
      tabIndex={-1}
      onKeyDown={handleKeyDown}
    >
      {/* ── Config card ── */}
      <div className="bg-card border border-border rounded-lg p-6 space-y-5">
        <div className="flex items-center gap-2 mb-1">
          <Camera className="h-5 w-5 text-zinc-400" />
          <h2 className="text-base font-semibold text-white">Snapshot Schedule</h2>
        </div>

        {cfgLoading ? (
          <div className="flex items-center gap-2 text-zinc-400 text-sm">
            <RefreshCw className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : (
          <>
            {/* Enable toggle */}
            <div className="flex items-center gap-3">
              <button
                onClick={() => setEnabled(!eff_enabled)}
                className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  eff_enabled ? "bg-teal-500" : "bg-zinc-700"
                }`}
              >
                <span
                  className={`inline-block h-4 w-4 translate-x-1 transform rounded-full bg-white transition-transform ${
                    eff_enabled ? "translate-x-6" : ""
                  }`}
                />
              </button>
              <span className="text-sm text-zinc-200">
                {eff_enabled ? "Enabled" : "Disabled"}
              </span>
            </div>

            {/* Interval presets */}
            <div className="space-y-2">
              <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wide">
                Capture Interval
              </label>
              <div className="flex flex-wrap gap-2">
                {INTERVAL_PRESETS.map((p) => (
                  <button
                    key={p.value}
                    onClick={() => setIntervalSec(p.value)}
                    className={`px-3 py-1.5 text-xs rounded-md border transition-colors ${
                      eff_interval === p.value
                        ? "border-teal-500 bg-teal-500/10 text-teal-300"
                        : "border-border text-zinc-400 hover:border-zinc-500"
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
                <input
                  type="number"
                  min={5}
                  value={eff_interval}
                  onChange={(e) => setIntervalSec(Number(e.target.value))}
                  className="w-24 px-2 py-1 text-xs bg-zinc-900 border border-border rounded-md text-zinc-200"
                  placeholder="Custom (s)"
                />
              </div>
            </div>

            {/* Retention */}
            <div className="space-y-2">
              <label className="block text-xs font-medium text-zinc-400 uppercase tracking-wide">
                Retention (days — blank = keep forever)
              </label>
              <input
                type="number"
                min={1}
                value={eff_retention}
                onChange={(e) => setRetentionDays(e.target.value)}
                className="w-32 px-3 py-2 text-sm bg-zinc-900 border border-border rounded-md text-zinc-200"
                placeholder="e.g. 7"
              />
            </div>

            <Button
              onClick={handleSave}
              disabled={saveMutation.isPending}
              className="bg-teal-600 hover:bg-teal-500 text-white"
            >
              {saveMutation.isPending ? (
                <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Save className="h-4 w-4 mr-2" />
              )}
              Save Schedule
            </Button>
          </>
        )}
      </div>

      {/* ── Gallery ── */}
      <div className="bg-card border border-border rounded-lg p-6 space-y-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <Calendar className="h-5 w-5 text-zinc-400" />
            <h2 className="text-base font-semibold text-white">Gallery</h2>
            {snapsFetching && <RefreshCw className="h-4 w-4 text-zinc-400 animate-spin" />}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetchSnaps()}
            disabled={snapsFetching}
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${snapsFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        {/* Date range */}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-zinc-400">From</span>
          <input
            type="datetime-local"
            value={fromDt.slice(0, 16)}
            onChange={(e) => setFromDt(new Date(e.target.value).toISOString())}
            className="px-2 py-1 bg-zinc-900 border border-border rounded-md text-zinc-200 text-xs"
          />
          <span className="text-zinc-400">To</span>
          <input
            type="datetime-local"
            value={toDt.slice(0, 16)}
            onChange={(e) => setToDt(new Date(e.target.value).toISOString())}
            className="px-2 py-1 bg-zinc-900 border border-border rounded-md text-zinc-200 text-xs"
          />
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setFromDt(iso24hAgo());
              setToDt(isoNow());
            }}
          >
            Last 24h
          </Button>
        </div>

        {snaps.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No snapshots found in selected range.
          </p>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {snaps.map((snap, idx) => (
              <div key={snap.url} className="relative group rounded-md overflow-hidden border border-border hover:border-teal-500/60 transition-colors aspect-video">
                <button className="w-full h-full" onClick={() => openLightbox(idx)}>
                  <img
                    src={getImgSrc(snap.url)}
                    alt={snap.timestamp}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                </button>
                <div className="absolute bottom-0 left-0 right-0 bg-black/60 px-2 py-1 text-[10px] text-zinc-300 font-mono opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-between">
                  <span>{new Date(snap.timestamp).toLocaleTimeString()}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); setAnnotatorUrl(snap.url); }}
                    className="flex items-center gap-0.5 text-teal-300 hover:text-teal-100"
                    title="Annotate this snapshot"
                  >
                    <Pencil className="h-3 w-3" />
                    <span className="text-[9px]">Annotate</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Lightbox ── */}
      {lightboxIdx !== null && snaps[lightboxIdx] && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90"
          onClick={closeLightbox}
        >
          <button
            className="absolute top-4 right-4 text-zinc-400 hover:text-white p-2"
            onClick={closeLightbox}
          >
            <X className="h-6 w-6" />
          </button>
          <button
            className="absolute left-4 text-zinc-400 hover:text-white p-2 disabled:opacity-30"
            onClick={(e) => { e.stopPropagation(); prev(); }}
            disabled={lightboxIdx === 0}
          >
            <ChevronLeft className="h-8 w-8" />
          </button>
          <div
            className="max-w-5xl max-h-[90vh] flex flex-col items-center gap-3"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={getImgSrc(snaps[lightboxIdx].url)}
              alt={snaps[lightboxIdx].timestamp}
              className="max-w-full max-h-[80vh] rounded-lg shadow-2xl"
            />
            <div className="flex items-center gap-4">
              <p className="text-sm text-zinc-400 font-mono">
                {new Date(snaps[lightboxIdx].timestamp).toLocaleString()}
                <span className="ml-3 text-zinc-600">
                  {lightboxIdx + 1} / {snaps.length}
                </span>
              </p>
              <button
                onClick={() => { setAnnotatorUrl(snaps[lightboxIdx].url); closeLightbox(); }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-teal-600/20 text-teal-300 border border-teal-600/40 hover:bg-teal-600/40 transition-colors"
              >
                <Pencil className="h-3.5 w-3.5" />
                Annotate
              </button>
            </div>
          </div>
          <button
            className="absolute right-4 text-zinc-400 hover:text-white p-2 disabled:opacity-30"
            onClick={(e) => { e.stopPropagation(); next(); }}
            disabled={lightboxIdx === snaps.length - 1}
          >
            <ChevronRight className="h-8 w-8" />
          </button>
        </div>
      )}
      {/* ── Annotator overlay ── */}
      {annotatorUrl && (
        <div className="fixed inset-0 z-[60] bg-black/95">
          <SnapshotAnnotator
            cameraId={cameraId}
            sourceUrl={annotatorUrl}
            onClose={() => setAnnotatorUrl(null)}
            onSaved={() => { setAnnotatorUrl(null); refetchSnaps(); }}
          />
        </div>
      )}
    </div>
  );
};

export default SnapshotsPage;
