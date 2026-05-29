// =============================================================================
// PlaybackConsole — timeline-centric multi-camera review.
// Review set comes from the shell CameraTree (playbackCameras pref); seeded
// from ?camera=<id> on first load. Replaces the slider-based MultiPlayback.
// =============================================================================

import React, { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  Play, Pause, FastForward, Rewind, SkipBack, SkipForward,
  ChevronLeft, ChevronRight, Calendar, Video, Download,
} from "lucide-react";
import { format, subDays } from "date-fns";
import { useUiPrefs } from "../hooks";
import { useCamerasQuery } from "../hooks";
import { getRecordings, exportClip } from "../api/recordings";
import { getEvents } from "../api/events";
import { DAY_SECONDS, clampView, fmtClock } from "../lib/timeline";
import CameraCell from "../components/playback/CameraCell";
import MultiTimeline from "../components/playback/MultiTimeline";
import { toast } from "sonner";

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const FRAME = 1 / 15; // single frame step (~15fps wall tiles)

function gridCols(n) {
  if (n <= 1) return "grid-cols-1";
  if (n <= 4) return "grid-cols-2";
  if (n <= 9) return "grid-cols-3";
  return "grid-cols-4";
}

export default function PlaybackConsole() {
  const [prefs, setPrefs] = useUiPrefs();
  const { data: cameras = [] } = useCamerasQuery();
  const [searchParams] = useSearchParams();
  const cellRefs = useRef({});
  const syncIntervalRef = useRef(null);
  const dateInputRef = useRef(null);

  // Seed selection from ?camera=<id> once if the review set is empty.
  const seededRef = useRef(false);
  useEffect(() => {
    if (seededRef.current) return;
    const seed = searchParams.get("camera");
    if (seed && (!prefs.playbackCameras || prefs.playbackCameras.length === 0)) {
      setPrefs({ playbackCameras: [seed] });
    }
    seededRef.current = true;
  }, [searchParams, prefs.playbackCameras, setPrefs]);

  const selectedIds = useMemo(
    () => (Array.isArray(prefs.playbackCameras) ? prefs.playbackCameras : []),
    [prefs.playbackCameras]
  );
  const selectedCameras = useMemo(
    () => cameras.filter((c) => selectedIds.includes(c.id)),
    [cameras, selectedIds]
  );

  const [date, setDate] = useState(format(new Date(), "yyyy-MM-dd"));
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(2);
  const [currentTime, setCurrentTime] = useState(0);
  const [view, setView] = useState({ start: 0, end: DAY_SECONDS });
  const [range, setRange] = useState({ in: null, out: null });
  const speed = SPEEDS[speedIdx];

  // Per-camera segments for the timeline tracks.
  const segmentQueries = useQueries({
    queries: selectedIds.map((id) => ({
      queryKey: ["pb-segments", id, date],
      queryFn: () =>
        getRecordings({
          camera_id: id,
          start_after: `${date}T00:00:00`,
          end_before: `${date}T23:59:59`,
          limit: 500,
        }),
      staleTime: 30_000,
    })),
  });
  const segmentsByCam = useMemo(() => {
    const m = {};
    selectedIds.forEach((id, i) => { m[id] = segmentQueries[i]?.data || []; });
    return m;
  }, [selectedIds, segmentQueries]);

  // Per-camera events (ticks).
  const eventQueries = useQueries({
    queries: selectedIds.map((id) => ({
      queryKey: ["pb-events", id, date],
      queryFn: () =>
        getEvents({
          camera_id: id,
          start_date: `${date}T00:00:00`,
          end_date: `${date}T23:59:59`,
          limit: 1000,
        }),
      staleTime: 30_000,
    })),
  });
  const eventsByCam = useMemo(() => {
    const m = {};
    selectedIds.forEach((id, i) => { m[id] = eventQueries[i]?.data?.events || []; });
    return m;
  }, [selectedIds, eventQueries]);

  const allCells = () => Object.values(cellRefs.current).filter(Boolean);

  const play = useCallback(() => {
    allCells().forEach((c) => { c.playbackRate = speed; c.play(); });
    setPlaying(true);
  }, [speed]); // eslint-disable-line
  const pause = useCallback(() => {
    allCells().forEach((c) => c.pause());
    setPlaying(false);
  }, []); // eslint-disable-line
  const togglePlay = useCallback(() => { playing ? pause() : play(); }, [playing, play, pause]);

  const seekAll = useCallback((t) => {
    const clamped = Math.max(0, Math.min(DAY_SECONDS, t));
    setCurrentTime(clamped);
    allCells().forEach((c) => c.seekTo(clamped));
  }, []); // eslint-disable-line

  // Heartbeat: keep the shared playhead synced to whichever cells actually
  // have footage loaded. getCurrentDayOffset() returns null for idle cells, so
  // an empty first camera no longer drags the playhead back to midnight.
  useEffect(() => {
    if (selectedCameras.length === 0) return undefined;
    syncIntervalRef.current = setInterval(() => {
      const offsets = allCells()
        .map((c) => c.getCurrentDayOffset())
        .filter((v) => v != null);
      if (offsets.length) setCurrentTime(Math.floor(Math.max(...offsets)));
    }, 500);
    return () => clearInterval(syncIntervalRef.current);
  }, [selectedCameras.length]);

  // Apply speed mid-playback.
  useEffect(() => { allCells().forEach((c) => { c.playbackRate = speed; }); }, [speed]); // eslint-disable-line

  // Reset on date/selection change.
  useEffect(() => { pause(); setCurrentTime(0); setView({ start: 0, end: DAY_SECONDS }); }, [date, selectedIds]); // eslint-disable-line

  // Keyboard shortcuts.
  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "INPUT") return;
      switch (e.key) {
        case " ": e.preventDefault(); togglePlay(); break;
        case "ArrowLeft": e.preventDefault(); seekAll(currentTime - 10); break;
        case "ArrowRight": e.preventDefault(); seekAll(currentTime + 10); break;
        case ",": seekAll(currentTime - FRAME); break;
        case ".": seekAll(currentTime + FRAME); break;
        case "[": setSpeedIdx((i) => Math.max(0, i - 1)); break;
        case "]": setSpeedIdx((i) => Math.min(SPEEDS.length - 1, i + 1)); break;
        default: break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [togglePlay, seekAll, currentTime]);

  const removeCamera = (id) => {
    setPrefs({ playbackCameras: selectedIds.filter((x) => x !== id) });
  };

  const shiftDate = (days) => {
    const d = subDays(new Date(`${date}T00:00:00`), days);
    setDate(format(d, "yyyy-MM-dd"));
  };

  const doExport = async () => {
    if (range.in == null || range.out == null) {
      toast.error("Mark an In and Out point first");
      return;
    }
    const lo = Math.min(range.in, range.out);
    const hi = Math.max(range.in, range.out);
    const start = `${date}T${fmtClock(lo)}`;
    const end = `${date}T${fmtClock(hi)}`;
    try {
      await Promise.all(
        selectedIds.map((id) =>
          exportClip({ camera_id: id, start_time: start, end_time: end, format: "mp4" })
        )
      );
      toast.success(`Export queued for ${selectedIds.length} camera(s)`);
    } catch {
      toast.error("Export failed to queue");
    }
  };

  if (selectedCameras.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3" style={{ color: "var(--console-muted)" }}>
        <Video className="h-12 w-12 opacity-30" />
        <p className="text-sm">Double-click cameras in the tree to review them here.</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" style={{ background: "var(--console-bg)" }}>
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-2 h-9 border-b console-panel" style={{ borderColor: "var(--console-border)" }}>
        <button className="p-1 rounded hover:bg-white/5" title="Previous day" onClick={() => shiftDate(1)}>
          <ChevronLeft className="h-4 w-4" style={{ color: "var(--console-muted)" }} />
        </button>
        {/* Single themed date control. Clicking opens the native date picker
            (kept in a visually-hidden input) so we don't render the unstyled
            native date widget twice in the toolbar. */}
        <button
          type="button"
          title="Pick a date"
          onClick={() => {
            const el = dateInputRef.current;
            if (!el) return;
            if (typeof el.showPicker === "function") el.showPicker();
            else el.click();
          }}
          className="inline-flex items-center gap-1 text-xs font-telemetry px-1.5 py-0.5 rounded hover:bg-white/5"
          style={{ color: "var(--console-text)" }}
        >
          <Calendar className="h-3.5 w-3.5" /> {date}
        </button>
        <input
          ref={dateInputRef}
          type="date"
          value={date}
          max={format(new Date(), "yyyy-MM-dd")}
          onChange={(e) => setDate(e.target.value)}
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
        />
        <button className="p-1 rounded hover:bg-white/5" title="Next day" onClick={() => shiftDate(-1)}>
          <ChevronRight className="h-4 w-4" style={{ color: "var(--console-muted)" }} />
        </button>
        <span className="ml-auto text-xs font-telemetry" style={{ color: "var(--console-muted)" }}>
          {fmtClock(currentTime)}
        </span>
      </div>

      {/* Video grid */}
      <div className="flex-1 min-h-0 p-1">
        <div className={`grid gap-1 h-full ${gridCols(selectedCameras.length)}`}>
          {selectedCameras.map((cam) => (
            <div key={cam.id} className="relative group min-h-0 min-w-0 h-full">
              <CameraCell ref={(el) => { cellRefs.current[cam.id] = el; }} camera={cam} date={date} />
              <button
                className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 text-white text-xs bg-black/50 rounded px-1"
                onClick={() => removeCamera(cam.id)}
                title="Remove from review"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Timeline */}
      <MultiTimeline
        cameras={selectedCameras}
        segmentsByCam={segmentsByCam}
        eventsByCam={eventsByCam}
        date={date}
        view={view}
        currentTime={currentTime}
        range={range}
        onSeek={seekAll}
        onViewChange={(v) => setView(clampView(v))}
      />

      {/* Transport */}
      <div className="flex items-center gap-1 px-2 h-10 border-t console-panel" style={{ borderColor: "var(--console-border)" }}>
        <button className="p-1.5 rounded hover:bg-white/5" title="Back 60s" onClick={() => seekAll(currentTime - 60)}><SkipBack className="h-4 w-4" style={{ color: "var(--console-muted)" }} /></button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Back 10s (←)" onClick={() => seekAll(currentTime - 10)}><Rewind className="h-4 w-4" style={{ color: "var(--console-muted)" }} /></button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Prev frame (,)" onClick={() => seekAll(currentTime - FRAME)}>«</button>
        <button className="p-2 rounded-full" style={{ background: "var(--console-accent)", color: "#06231f" }} onClick={togglePlay}>
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Next frame (.)" onClick={() => seekAll(currentTime + FRAME)}>»</button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Forward 10s (→)" onClick={() => seekAll(currentTime + 10)}><FastForward className="h-4 w-4" style={{ color: "var(--console-muted)" }} /></button>
        <button className="p-1.5 rounded hover:bg-white/5" title="Forward 60s" onClick={() => seekAll(currentTime + 60)}><SkipForward className="h-4 w-4" style={{ color: "var(--console-muted)" }} /></button>

        <div className="flex items-center gap-0.5 ml-2">
          {SPEEDS.map((s, i) => (
            <button
              key={s}
              onClick={() => setSpeedIdx(i)}
              className="h-6 px-1.5 text-[11px] rounded font-telemetry"
              style={{
                background: speedIdx === i ? "var(--console-accent)" : "transparent",
                color: speedIdx === i ? "#06231f" : "var(--console-muted)",
              }}
            >
              {s}×
            </button>
          ))}
        </div>

        {/* Range + export */}
        <div className="ml-auto flex items-center gap-1">
          <button className="h-6 px-2 text-[11px] rounded border font-telemetry" style={{ borderColor: "var(--console-border)", color: "var(--console-muted)" }} onClick={() => setRange((r) => ({ ...r, in: currentTime }))}>
            Mark In {range.in != null ? fmtClock(range.in) : ""}
          </button>
          <button className="h-6 px-2 text-[11px] rounded border font-telemetry" style={{ borderColor: "var(--console-border)", color: "var(--console-muted)" }} onClick={() => setRange((r) => ({ ...r, out: currentTime }))}>
            Mark Out {range.out != null ? fmtClock(range.out) : ""}
          </button>
          <button className="h-6 px-2 text-[11px] rounded inline-flex items-center gap-1" style={{ background: "var(--console-accent-blue)", color: "#fff" }} onClick={doExport}>
            <Download className="h-3.5 w-3.5" /> Export
          </button>
        </div>
      </div>
    </div>
  );
}
