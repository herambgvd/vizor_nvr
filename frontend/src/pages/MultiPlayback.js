// =============================================================================
// Playback — unified single + multi-camera synchronous review
// =============================================================================
// Replaces the old single-cam Playback page. One screen handles both:
//   • Single camera: opens with the camera pre-selected via ?camera=<id>
//   • Multiple cameras: operator picks from sidebar, picks grid layout
// =============================================================================

import React, {
  useRef, useState, useCallback, useEffect, useImperativeHandle,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  LayoutGrid, Play, Pause, FastForward, Rewind,
  SkipBack, SkipForward, Video, Calendar, Maximize2, Minimize2, X,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Slider } from "../components/ui/slider";
import { Checkbox } from "../components/ui/checkbox";
import { ScrollArea } from "../components/ui/scroll-area";
import { Popover, PopoverContent, PopoverTrigger } from "../components/ui/popover";
import { cn } from "../lib/utils";
import { format, subDays } from "date-fns";
import api, { BACKEND_URL } from "../api/client";

// Backend writes recording timestamps as naive UTC (datetime.utcnow()).
// Without a tz suffix the browser parses them as local time, which is
// wrong. Force a `Z` so Date treats the string as UTC, then everything
// downstream stays in local clock-time naturally.
function parseUtc(s) {
  if (!s) return new Date(NaN);
  // Already has tz info — trust it.
  if (/[Z+-]\d{2}:?\d{2}$|Z$/i.test(s)) return new Date(s);
  return new Date(`${s}Z`);
}


// ─── Constants ───────────────────────────────────────────────────────────────

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8];
const MAX_CAMERAS = 16;

const GRID_CONFIGS = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  3: "grid-cols-2",
  4: "grid-cols-2",
  6: "grid-cols-3",
  8: "grid-cols-4",
  9: "grid-cols-3",
  12: "grid-cols-4",
  16: "grid-cols-4",
};

function gridClass(count) {
  const keys = Object.keys(GRID_CONFIGS).map(Number).sort((a, b) => a - b);
  for (const k of keys) if (count <= k) return GRID_CONFIGS[k];
  return "grid-cols-4";
}

// ─── Single camera player cell ───────────────────────────────────────────────
// Exposes play/pause/seekTo/getCurrentDayOffset via useImperativeHandle so the
// parent can synchronise multiple cameras on a shared timeline.

const CameraCell = React.forwardRef(function CameraCell(
  { camera, date, className },
  ref
) {
  const videoRef = useRef(null);
  const segmentsRef = useRef([]);
  const currentSegIdxRef = useRef(0);
  const pendingSeekRef = useRef(null);
  const [currentSegIdx, setCurrentSegIdx] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [noRecording, setNoRecording] = useState(false);
  const [totalSegments, setTotalSegments] = useState(0);

  // Fetch all recordings for this camera+date
  const { data: recordings } = useQuery({
    queryKey: ["multi-recordings", camera?.id, date],
    queryFn: () =>
      api.get("/recordings", {
        params: {
          camera_id: camera.id,
          start_after: `${date}T00:00:00`,
          end_before: `${date}T23:59:59`,
          limit: 500,
        },
      }).then((r) => r.data),
    enabled: !!camera,
    staleTime: 30_000,
  });

  // Seconds since midnight of `date`
  const getDayOffset = useCallback(
    (isoTime) => {
      // Server timestamps are naive UTC; treat them as such, then
      // subtract local midnight to get the offset on the wall clock
      // the operator sees.
      const d = parseUtc(isoTime);
      const midnight = new Date(`${date}T00:00:00`);
      return (d.getTime() - midnight.getTime()) / 1000;
    },
    [date]
  );

  // Sort and store segments; reset to first when recordings change
  useEffect(() => {
    if (!recordings) return;
    const sorted = [...recordings].sort(
      (a, b) => parseUtc(a.start_time) - parseUtc(b.start_time)
    );
    segmentsRef.current = sorted;
    setTotalSegments(sorted.length);
    setNoRecording(sorted.length === 0);
    currentSegIdxRef.current = 0;
    setCurrentSegIdx(0);
    setLoaded(false);
  }, [recordings]);

  // Load video src whenever the active segment OR the recording list
  // changes. Without `totalSegments` in the dep array, the initial
  // segment never loaded because `currentSegIdx` stays at 0 across
  // re-runs (no value transition).
  useEffect(() => {
    const seg = segmentsRef.current[currentSegIdx];
    if (!seg || !videoRef.current) return;

    const token = localStorage.getItem("nvr_token") || "";
    videoRef.current.src = `${BACKEND_URL}/api/recordings/${seg.id}/download?token=${token}`;
    videoRef.current.load();

    // Apply a pending seek once metadata is available
    const pending = pendingSeekRef.current;
    if (pending != null) {
      pendingSeekRef.current = null;
      const applySeek = () => {
        if (videoRef.current) videoRef.current.currentTime = pending;
      };
      videoRef.current.addEventListener("loadedmetadata", applySeek, { once: true });
    }
  }, [currentSegIdx, totalSegments]);

  // Auto-advance to next segment
  const handleEnded = useCallback(() => {
    const next = currentSegIdxRef.current + 1;
    if (next < segmentsRef.current.length) {
      currentSegIdxRef.current = next;
      setCurrentSegIdx(next);
      setTimeout(() => videoRef.current?.play().catch(() => {}), 50);
    }
  }, []);

  // ── Public interface exposed to parent via ref ──────────────────────────────
  useImperativeHandle(ref, () => ({
    play: () => videoRef.current?.play().catch(() => {}),
    pause: () => videoRef.current?.pause(),
    get playbackRate() { return videoRef.current?.playbackRate || 1; },
    set playbackRate(v) { if (videoRef.current) videoRef.current.playbackRate = v; },

    getCurrentDayOffset: () => {
      const seg = segmentsRef.current[currentSegIdxRef.current];
      if (!seg || !videoRef.current) return 0;
      return getDayOffset(seg.start_time) + (videoRef.current.currentTime || 0);
    },

    seekTo: (dayOffset) => {
      const segs = segmentsRef.current;
      if (!segs.length || !videoRef.current) return;

      // Find segment that spans the requested day-offset
      let targetIdx = segs.findIndex((s) => {
        const start = getDayOffset(s.start_time);
        const end = start + (s.duration || 0);
        return dayOffset >= start && dayOffset <= end;
      });

      if (targetIdx === -1) {
        // No exact match — find nearest future segment
        targetIdx = segs.findIndex((s) => getDayOffset(s.start_time) > dayOffset);
        if (targetIdx === -1) return; // dayOffset is beyond all recordings
      }

      const offsetInSeg = Math.max(
        0,
        dayOffset - getDayOffset(segs[targetIdx].start_time)
      );

      if (targetIdx !== currentSegIdxRef.current) {
        // Need to load a different file first
        pendingSeekRef.current = offsetInSeg;
        currentSegIdxRef.current = targetIdx;
        setCurrentSegIdx(targetIdx);
      } else {
        videoRef.current.currentTime = offsetInSeg;
      }
    },
  }), [getDayOffset]);

  return (
    <div
      className={cn(
        // Drop fixed aspect-video — parent grid cell controls height.
        // Without this the tile expands beyond the viewport in 1×1
        // layouts and pushes the control bar off screen.
        "relative bg-black rounded-md overflow-hidden w-full h-full min-h-0",
        className
      )}
    >
      {camera ? (
        <>
          <video
            ref={videoRef}
            className="w-full h-full object-contain"
            muted
            playsInline
            onCanPlay={() => setLoaded(true)}
            onError={() => setNoRecording(true)}
            onEnded={handleEnded}
          />

          {/* Bottom overlay */}
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-2 py-1.5 flex items-center gap-2">
            <span className="text-white text-xs font-medium truncate">
              {camera.name}
            </span>
            {camera.status === "online" && (
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 flex-shrink-0" />
            )}
            {totalSegments > 1 && (
              <span className="ml-auto text-white/50 text-[10px]">
                {currentSegIdx + 1}/{totalSegments}
              </span>
            )}
          </div>

          {/* Loading spinner */}
          {!loaded && !noRecording && (
            <div className="absolute inset-0 flex items-center justify-center text-white/40">
              <Video className="h-8 w-8 animate-pulse" />
            </div>
          )}

          {/* No recording state */}
          {noRecording && (
            <div className="absolute inset-0 flex flex-col items-center justify-center text-white/40 gap-2">
              <X className="h-8 w-8" />
              <span className="text-xs">No recording</span>
            </div>
          )}
        </>
      ) : (
        <div className="flex items-center justify-center h-full text-white/20">
          <Video className="h-10 w-10" />
        </div>
      )}
    </div>
  );
});

// ─── Timeline scrubber ────────────────────────────────────────────────────────

// Format seconds-since-midnight as wall-clock HH:MM:SS.
function fmtClock(s) {
  const total = Math.max(0, Math.floor(s));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}


// Segment-aware scrub bar: dark track with teal bars where recordings
// exist. Click-to-seek anywhere; drag the playhead to scrub. Mimics
// the Hikvision/Dahua NVR timeline UX.
//
// Props:
//   currentTime   – seconds since midnight
//   duration      – seconds shown on the bar (default 86400 = full day)
//   segments      – array of { start_time, duration } from /api/recordings
//   onChange      – called with seconds when user clicks/drags
const TimelineScrubber = ({
  currentTime,
  duration = 86400,
  segments = [],
  date,
  onChange,
}) => {
  const trackRef = React.useRef(null);

  // Translate one segment into [leftPct, widthPct] on the bar.
  const segRanges = React.useMemo(() => {
    if (!segments || segments.length === 0 || !date) return [];
    const midnight = new Date(`${date}T00:00:00`).getTime();
    return segments
      .map((s) => {
        const start = (parseUtc(s.start_time).getTime() - midnight) / 1000;
        const dur = s.duration || 0;
        const end = Math.min(duration, start + dur);
        const safeStart = Math.max(0, start);
        if (end <= safeStart) return null;
        return {
          left: (safeStart / duration) * 100,
          width: ((end - safeStart) / duration) * 100,
        };
      })
      .filter(Boolean);
  }, [segments, date, duration]);

  // Hour ticks across the bar — every 2h on full-day, 1h on shorter spans.
  const hourTicks = React.useMemo(() => {
    const step = duration <= 6 * 3600 ? 3600 : 2 * 3600;
    const out = [];
    for (let t = 0; t <= duration; t += step) {
      out.push(t);
    }
    return out;
  }, [duration]);

  const seekFromPointer = React.useCallback(
    (e) => {
      if (!trackRef.current) return;
      const rect = trackRef.current.getBoundingClientRect();
      const x = Math.min(Math.max(0, e.clientX - rect.left), rect.width);
      const pct = x / rect.width;
      onChange?.(Math.floor(pct * duration));
    },
    [duration, onChange],
  );

  const onTrackPointerDown = (e) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    seekFromPointer(e);
  };
  const onTrackPointerMove = (e) => {
    if (e.buttons !== 1) return;
    seekFromPointer(e);
  };

  const playheadPct = Math.min(100, Math.max(0, (currentTime / duration) * 100));

  return (
    <div className="w-full space-y-1.5">
      {/* Clock readouts */}
      <div className="flex items-center justify-between text-[11px] text-muted-foreground tabular-nums px-0.5">
        <span>{fmtClock(currentTime)}</span>
        <span className="text-xs font-medium text-zinc-300">
          {segments?.length || 0} recording{segments?.length !== 1 ? "s" : ""}
        </span>
        <span>{fmtClock(duration)}</span>
      </div>

      {/* Track */}
      <div
        ref={trackRef}
        onPointerDown={onTrackPointerDown}
        onPointerMove={onTrackPointerMove}
        className="relative h-7 rounded-md bg-card/60 border border-border cursor-pointer select-none overflow-hidden"
        role="slider"
        aria-valuemin={0}
        aria-valuemax={duration}
        aria-valuenow={currentTime}
        tabIndex={0}
      >
        {/* Hour grid lines */}
        {hourTicks.map((t) => (
          <span
            key={t}
            className="absolute top-0 bottom-0 w-px bg-white/[0.06]"
            style={{ left: `${(t / duration) * 100}%` }}
          />
        ))}

        {/* Recording segments — teal blocks */}
        {segRanges.map((r, i) => (
          <span
            key={i}
            className="absolute top-1 bottom-1 rounded-sm bg-primary/70 hover:bg-primary"
            style={{ left: `${r.left}%`, width: `${Math.max(0.25, r.width)}%` }}
          />
        ))}

        {/* Playhead */}
        <span
          className="absolute top-0 bottom-0 w-0.5 bg-amber-400 shadow-[0_0_4px_rgba(245,158,11,0.7)] pointer-events-none"
          style={{ left: `${playheadPct}%` }}
        />
      </div>

      {/* Hour labels */}
      <div className="flex justify-between text-[10px] text-muted-foreground/70 tabular-nums px-0.5">
        {hourTicks.map((t) => (
          <span key={t}>
            {String(Math.floor(t / 3600)).padStart(2, "0")}:00
          </span>
        ))}
      </div>
    </div>
  );
};

// ─── Camera selector popover ──────────────────────────────────────────────────

const CameraSelector = ({ cameras, selected, onToggle }) => (
  <Popover>
    <PopoverTrigger asChild>
      <Button variant="outline" size="sm">
        <LayoutGrid className="h-4 w-4 mr-2" />
        {selected.length} Camera{selected.length !== 1 ? "s" : ""} selected
      </Button>
    </PopoverTrigger>
    <PopoverContent className="w-72 p-3" align="start">
      <p className="text-sm font-semibold mb-2">
        Select cameras (max {MAX_CAMERAS})
      </p>
      <ScrollArea className="h-64">
        <div className="space-y-1">
          {cameras.map((cam) => {
            const checked = selected.includes(cam.id);
            const disabled = !checked && selected.length >= MAX_CAMERAS;
            return (
              <div
                key={cam.id}
                className={cn(
                  "flex items-center gap-2 p-1.5 rounded hover:bg-card/40 dark:hover:bg-primary/60",
                  disabled && "opacity-50 cursor-not-allowed"
                )}
              >
                <Checkbox
                  id={`sel-${cam.id}`}
                  checked={checked}
                  disabled={disabled}
                  onCheckedChange={() => !disabled && onToggle(cam.id)}
                />
                <label
                  htmlFor={`sel-${cam.id}`}
                  className={cn(
                    "text-sm flex-1 cursor-pointer",
                    disabled && "cursor-not-allowed"
                  )}
                >
                  {cam.name}
                </label>
                <span
                  className={cn(
                    "w-2 h-2 rounded-full flex-shrink-0",
                    cam.status === "online" ? "bg-green-400" : "bg-slate-300"
                  )}
                />
              </div>
            );
          })}
        </div>
      </ScrollArea>
    </PopoverContent>
  </Popover>
);

// ─── Main page ────────────────────────────────────────────────────────────────

export default function MultiPlayback() {
  const cellRefs = useRef({});
  const [searchParams] = useSearchParams();
  // Seed initial selection from ?camera=<id> so the Cameras page row-click
  // → Playback flow stays a single click.
  const initialCamId = searchParams.get("camera");
  const [selectedCameraIds, setSelectedCameraIds] = useState(
    initialCamId ? [initialCamId] : [],
  );
  const [date, setDate] = useState(format(new Date(), "yyyy-MM-dd"));
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(2);
  const [currentTime, setCurrentTime] = useState(0);
  const [fullscreenId, setFullscreenId] = useState(null);
  const syncIntervalRef = useRef(null);

  const speed = SPEEDS[speedIdx];

  const { data: cameras = [] } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => api.get("/cameras").then((r) => r.data),
  });

  const selectedCameras = cameras.filter((c) =>
    selectedCameraIds.includes(c.id)
  );

  // Aggregate recording segments across every selected camera so the
  // scrub bar shows which parts of the day actually have footage. Hit
  // /recordings once per (cam, date) and merge.
  const { data: aggregateSegments = [] } = useQuery({
    queryKey: ["aggregate-segments", date, selectedCameraIds.sort().join(",")],
    queryFn: async () => {
      if (selectedCameraIds.length === 0) return [];
      const lists = await Promise.all(
        selectedCameraIds.map((id) =>
          api
            .get("/recordings", {
              params: {
                camera_id: id,
                start_after: `${date}T00:00:00`,
                end_before: `${date}T23:59:59`,
                limit: 500,
              },
            })
            .then((r) => r.data)
            .catch(() => []),
        ),
      );
      return lists.flat();
    },
    enabled: selectedCameraIds.length > 0,
    staleTime: 30_000,
  });

  const toggleCamera = useCallback((id) => {
    setSelectedCameraIds((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    );
  }, []);

  // ── Helpers ───────────────────────────────────────────────────────────────

  const allCells = () => Object.values(cellRefs.current).filter(Boolean);

  const applySpeed = useCallback(() => {
    allCells().forEach((ctrl) => { ctrl.playbackRate = speed; });
  }, [speed]); // eslint-disable-line

  const pause = useCallback(() => {
    allCells().forEach((ctrl) => ctrl.pause());
    setPlaying(false);
    // Heartbeat interval is owned by the always-on effect below, no
    // need to tear it down on pause.
  }, []); // eslint-disable-line

  const play = useCallback(() => {
    allCells().forEach((ctrl) => {
      ctrl.playbackRate = speed;
      ctrl.play();
    });
    setPlaying(true);
  }, [speed]); // eslint-disable-line

  // Always poll the active cell for its current day offset — keeps the
  // timestamp + playhead in sync even when paused, after a seek, or
  // after the user clicks the scrub bar.
  useEffect(() => {
    if (selectedCameras.length === 0) return undefined;
    syncIntervalRef.current = setInterval(() => {
      const cells = allCells();
      if (cells[0]) {
        setCurrentTime(Math.floor(cells[0].getCurrentDayOffset()));
      }
    }, 500);
    return () => {
      if (syncIntervalRef.current) {
        clearInterval(syncIntervalRef.current);
        syncIntervalRef.current = null;
      }
    };
  }, [selectedCameras.length]);

  const togglePlay = useCallback(() => {
    playing ? pause() : play();
  }, [playing, play, pause]);

  const seekAll = useCallback((time) => {
    setCurrentTime(time);
    allCells().forEach((ctrl) => ctrl.seekTo(time));
  }, []); // eslint-disable-line

  // Apply speed when it changes mid-playback
  useEffect(() => { applySpeed(); }, [applySpeed, speed]);

  // Reset on date/selection change
  useEffect(() => {
    pause();
    setCurrentTime(0);
  }, [date, selectedCameraIds]); // eslint-disable-line

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (syncIntervalRef.current) clearInterval(syncIntervalRef.current);
    };
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === "INPUT") return;
      switch (e.key) {
        case " ": e.preventDefault(); togglePlay(); break;
        case "ArrowLeft": e.preventDefault(); seekAll(Math.max(0, currentTime - 10)); break;
        case "ArrowRight": e.preventDefault(); seekAll(currentTime + 10); break;
        case "[": setSpeedIdx((i) => Math.max(0, i - 1)); break;
        case "]": setSpeedIdx((i) => Math.min(SPEEDS.length - 1, i + 1)); break;
        default: break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [togglePlay, seekAll, currentTime]);

  const datePresets = [
    { label: "Today", value: format(new Date(), "yyyy-MM-dd") },
    { label: "Yesterday", value: format(subDays(new Date(), 1), "yyyy-MM-dd") },
    { label: "2 days ago", value: format(subDays(new Date(), 2), "yyyy-MM-dd") },
  ];

  return (
    <div className="p-6 space-y-4 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h1 className="text-2xl font-bold text-white ">
            Playback
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {selectedCameras.length === 0
              ? "Pick one or more cameras to start"
              : selectedCameras.length === 1
              ? `Single-camera review · ${selectedCameras[0].name}`
              : `Synchronized review across ${selectedCameras.length} cameras`}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Date selector */}
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm">
                <Calendar className="h-4 w-4 mr-2" />
                {date}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56 p-2" align="end">
              <div className="space-y-1">
                {datePresets.map((p) => (
                  <Button
                    key={p.value}
                    variant={date === p.value ? "default" : "ghost"}
                    size="sm"
                    className="w-full justify-start"
                    onClick={() => setDate(p.value)}
                  >
                    {p.label}
                    <span className="ml-auto text-xs text-muted-foreground">
                      {p.value}
                    </span>
                  </Button>
                ))}
                <div className="pt-1 border-t">
                  <input
                    type="date"
                    value={date}
                    max={format(new Date(), "yyyy-MM-dd")}
                    onChange={(e) => setDate(e.target.value)}
                    className="w-full text-sm px-2 py-1 border rounded bg-transparent"
                  />
                </div>
              </div>
            </PopoverContent>
          </Popover>

          <CameraSelector
            cameras={cameras}
            selected={selectedCameraIds}
            onToggle={toggleCamera}
          />
        </div>
      </div>

      {/* Camera grid */}
      {selectedCameras.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-4">
          <LayoutGrid className="h-16 w-16 opacity-30" />
          <div className="text-center">
            <p className="text-lg font-medium">No cameras selected</p>
            <p className="text-sm mt-1">
              Use the camera selector above to pick cameras to review together.
            </p>
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-hidden flex flex-col gap-4 min-h-0">
          {/* Video grid */}
          <div
            className={cn(
              "grid gap-2 flex-1 min-h-0",
              fullscreenId
                ? "grid-cols-1"
                : gridClass(selectedCameras.length)
            )}
          >
            {(fullscreenId
              ? selectedCameras.filter((c) => c.id === fullscreenId)
              : selectedCameras
            ).map((cam) => (
              <div
                key={cam.id}
                className="relative group min-h-0 min-w-0 h-full"
              >
                <CameraCell
                  ref={(el) => { cellRefs.current[cam.id] = el; }}
                  camera={cam}
                  date={date}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 transition-opacity text-white hover:text-white hover:bg-black/40"
                  onClick={() =>
                    setFullscreenId(fullscreenId ? null : cam.id)
                  }
                >
                  {fullscreenId ? (
                    <Minimize2 className="h-3.5 w-3.5" />
                  ) : (
                    <Maximize2 className="h-3.5 w-3.5" />
                  )}
                </Button>
              </div>
            ))}
          </div>

          {/* Controls bar */}
          <Card className="flex-shrink-0">
            <CardContent className="py-3 px-4 space-y-3">
              <TimelineScrubber
                currentTime={currentTime}
                duration={86400}
                segments={aggregateSegments}
                date={date}
                onChange={seekAll}
              />

              <div className="flex items-center justify-between">
                {/* Transport */}
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => seekAll(Math.max(0, currentTime - 60))}
                    title="Back 60s"
                  >
                    <SkipBack className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => seekAll(Math.max(0, currentTime - 10))}
                    title="Back 10s (←)"
                  >
                    <Rewind className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="default"
                    size="sm"
                    className="w-10 h-10 rounded-full"
                    onClick={togglePlay}
                  >
                    {playing ? (
                      <Pause className="h-4 w-4" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => seekAll(currentTime + 10)}
                    title="Forward 10s (→)"
                  >
                    <FastForward className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => seekAll(currentTime + 60)}
                    title="Forward 60s"
                  >
                    <SkipForward className="h-4 w-4" />
                  </Button>
                </div>

                {/* Speed */}
                <div className="flex items-center gap-1">
                  {SPEEDS.map((s, i) => (
                    <Button
                      key={s}
                      variant={speedIdx === i ? "default" : "outline"}
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => setSpeedIdx(i)}
                    >
                      {s}×
                    </Button>
                  ))}
                </div>

                {/* Info */}
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Badge variant="outline">
                    {selectedCameras.length} camera
                    {selectedCameras.length !== 1 ? "s" : ""}
                  </Badge>
                  <span className="text-xs font-mono">{date}</span>
                </div>
              </div>

              <p className="text-xs text-muted-foreground text-center">
                Space: play/pause · ← / → : ±10s · [ / ] : speed
              </p>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
