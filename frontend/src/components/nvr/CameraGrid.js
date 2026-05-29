// =============================================================================
// Camera Grid Component - Multi-Camera Display
// =============================================================================
// Responsive grid layout for displaying multiple cameras.
// Supports selectable layout presets (1×1, 2×2, 3×3, 4×4, 5×5, mixed-large).
// =============================================================================

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Plus,
  Camera,
  LayoutGrid,
  Play,
  Pause,
  Timer,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { CameraCard } from "./CameraCard";
import { Button } from "../ui/button";
import { Skeleton } from "../ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";

// Grid layout definitions: [columns, label, tailwind cols class]
const LAYOUTS = [
  { id: "1x1", label: "1×1", cols: "grid-cols-1", rows: "grid-rows-1", maxVisible: 1 },
  { id: "2x2", label: "2×2", cols: "grid-cols-2", rows: "grid-rows-2", maxVisible: 4 },
  { id: "3x3", label: "3×3", cols: "grid-cols-3", rows: "grid-rows-3", maxVisible: 9 },
  { id: "4x4", label: "4×4", cols: "grid-cols-4", rows: "grid-rows-4", maxVisible: 16 },
  { id: "5x5", label: "5×5", cols: "grid-cols-5", rows: "grid-rows-5", maxVisible: 25 },
];

/**
 * Camera Grid Layout Picker — compact toolbar shown above the grid.
 */
const LayoutPicker = ({ current, onChange }) => (
  <div className="flex items-center gap-1 bg-[var(--console-raised)] rounded-lg p-1">
    <LayoutGrid className="h-4 w-4 text-muted-foreground ml-1 mr-0.5 shrink-0" />
    {LAYOUTS.map((l) => (
      <button
        key={l.id}
        onClick={() => onChange(l.id)}
        className={cn(
          "px-2 py-0.5 rounded text-xs font-medium transition-colors",
          current === l.id
            ? "bg-[var(--console-accent)] text-white"
            : "text-[var(--console-muted)] hover:bg-[var(--console-border)]",
        )}
      >
        {l.label}
      </button>
    ))}
  </div>
);

/**
 * Camera Grid Component
 * Displays cameras in a user-selectable grid layout.
 *
 * New props:
 *   layout         – controlled layout id (optional)
 *   onLayoutChange – callback when user picks a layout (optional)
 *   onInstantPlayback – callback(camera) for the Instant Playback action
 */
export const CameraGrid = ({
  cameras = [],
  isLoading = false,
  loadingCameras = [],
  onCameraClick,
  onStartRecording,
  onStopRecording,
  onTestConnection,
  onCameraSettings,
  onCameraFullscreen,
  onAddCamera,
  onInstantPlayback,
  maxCameras = 16,
  layout: layoutProp,
  onLayoutChange,
  className,
  headerLeftSlot,
  headerRightSlot,
}) => {
  // Internal state when parent doesn't control layout
  const [internalLayout, setInternalLayout] = useState("2x2");
  const activeLayoutId = layoutProp ?? internalLayout;
  const activeLayout =
    LAYOUTS.find((l) => l.id === activeLayoutId) ?? LAYOUTS[1];

  // Index of camera shown in 1×1 mode. Picked by user via prev/next or
  // dropdown. Defaults to 0 (first camera).
  const [singleIdx, setSingleIdx] = useState(0);
  // Clamp index when camera list shrinks.
  useEffect(() => {
    if (singleIdx >= cameras.length && cameras.length > 0) {
      setSingleIdx(0);
    }
  }, [cameras.length, singleIdx]);
  const activeSingleCamera = cameras[singleIdx] || cameras[0];
  const nextSingle = useCallback(() => {
    setSingleIdx((i) => (cameras.length ? (i + 1) % cameras.length : 0));
  }, [cameras.length]);
  const prevSingle = useCallback(() => {
    setSingleIdx((i) =>
      cameras.length ? (i - 1 + cameras.length) % cameras.length : 0,
    );
  }, [cameras.length]);

  // Tour / sequence mode
  const [tourActive, setTourActive] = useState(false);
  const [tourIndex, setTourIndex] = useState(0);
  const [tourDwell, setTourDwell] = useState("10"); // seconds per camera
  const tourTimerRef = useRef(null);

  const tourCameras = cameras.filter(
    (c) => c.status === "online" || c.is_recording,
  );

  const startTour = useCallback(() => {
    if (tourCameras.length === 0) return;
    setTourActive(true);
    setTourIndex(0);
  }, [tourCameras.length]);

  const stopTour = useCallback(() => {
    setTourActive(false);
    if (tourTimerRef.current) clearInterval(tourTimerRef.current);
    tourTimerRef.current = null;
  }, []);

  // Tour cycle timer
  useEffect(() => {
    if (!tourActive || tourCameras.length === 0) {
      if (tourTimerRef.current) clearInterval(tourTimerRef.current);
      tourTimerRef.current = null;
      return;
    }

    tourTimerRef.current = setInterval(
      () => {
        setTourIndex((prev) => (prev + 1) % tourCameras.length);
      },
      parseInt(tourDwell) * 1000,
    );

    return () => {
      if (tourTimerRef.current) clearInterval(tourTimerRef.current);
    };
  }, [tourActive, tourDwell, tourCameras.length]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (tourTimerRef.current) clearInterval(tourTimerRef.current);
    };
  }, []);

  const handleLayoutChange = (id) => {
    setInternalLayout(id);
    onLayoutChange?.(id);
  };

  // Empty state
  if (!isLoading && cameras.length === 0) {
    return (
      <div
        data-testid="camera-grid-empty"
        className={cn(
          "flex flex-col items-center justify-center py-16 px-4",
          "bg-[var(--console-panel)] rounded-lg border border-dashed border-border",
          className,
        )}
      >
        <div className="p-4 bg-[var(--console-raised)] rounded-full mb-4">
          <Camera className="h-12 w-12 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-medium text-white mb-2">
          No Cameras Added
        </h3>
        <p className="text-muted-foreground text-center mb-6 max-w-md">
          Add your first IP camera to start monitoring and recording. You can
          add up to {maxCameras} cameras with your license.
        </p>
        <Button
          data-testid="add-first-camera-btn"
          onClick={onAddCamera}
          className="text-white hover:opacity-90"
          style={{ backgroundColor: 'var(--console-accent)' }}
        >
          <Plus className="h-4 w-4 mr-2" />
          Add Camera
        </Button>
      </div>
    );
  }

  // Loading state
  if (isLoading) {
    return (
      <div
        data-testid="camera-grid-loading"
        className={cn(
          `grid ${activeLayout.cols} ${activeLayout.rows} gap-2 h-full min-h-0`,
          className,
        )}
      >
        {Array.from({ length: activeLayout.maxVisible }).map((_, index) => (
          <div key={index} className="min-h-0 min-w-0">
            <Skeleton className="w-full h-full rounded-lg" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 h-full min-h-0">
      {/* Layout toolbar */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          {headerLeftSlot}
          <LayoutPicker
            current={activeLayoutId}
            onChange={handleLayoutChange}
          />

          {/* Tour controls */}
          <div className="flex items-center gap-1 bg-[var(--console-raised)] rounded-lg p-1">
            <Timer className="h-4 w-4 text-muted-foreground ml-1 mr-0.5 shrink-0" />
            {tourActive ? (
              <button
                onClick={stopTour}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-destructive text-white"
              >
                <Pause className="h-3 w-3" />
                Stop Tour
              </button>
            ) : (
              <button
                onClick={startTour}
                disabled={tourCameras.length < 2}
                className={cn(
                  "flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors",
                  tourCameras.length < 2
                    ? "text-muted-foreground cursor-not-allowed"
                    : "text-[var(--console-muted)] hover:bg-[var(--console-border)]",
                )}
              >
                <Play className="h-3 w-3" />
                Tour
              </button>
            )}
            <Select value={tourDwell} onValueChange={setTourDwell}>
              <SelectTrigger className="h-6 w-14 text-xs border-0 bg-transparent p-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="5">5s</SelectItem>
                <SelectItem value="10">10s</SelectItem>
                <SelectItem value="15">15s</SelectItem>
                <SelectItem value="30">30s</SelectItem>
                <SelectItem value="60">60s</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">
            {tourActive
              ? `Tour: ${tourIndex + 1}/${tourCameras.length} — ${tourCameras[tourIndex]?.name || ""}`
              : `${cameras.length} camera${cameras.length !== 1 ? "s" : ""}${
                  activeLayout.maxVisible < cameras.length
                    ? ` (showing first ${activeLayout.maxVisible})`
                    : ""
                }`}
          </span>
          {headerRightSlot}
        </div>
      </div>

      {/* Grid — fills remaining viewport, no scroll. Tiles auto-shrink
          to fit N×M cells. Match Hikvision / Dahua NVR behavior. */}
      {tourActive && tourCameras.length > 0 ? (
        <div
          data-testid="camera-grid-tour"
          className={cn(
            "grid grid-cols-1 grid-rows-1 gap-2 flex-1 min-h-0",
            className,
          )}
        >
          <div className="min-h-0 min-w-0 h-full">
            <CameraCard
              key={tourCameras[tourIndex]?.id}
              camera={tourCameras[tourIndex]}
              isLoading={false}
              showLiveByDefault={true}
              onClick={onCameraClick}
              onStartRecording={onStartRecording}
              onStopRecording={onStopRecording}
              onTestConnection={onTestConnection}
              onSettings={onCameraSettings}
              onFullscreen={onCameraFullscreen}
              onInstantPlayback={onInstantPlayback}
              fitParent
            />
          </div>
        </div>
      ) : activeLayoutId === "1x1" && cameras.length > 0 ? (
        // Single-cam focus mode — operator picks which camera via
        // prev/next buttons or dropdown. Mirrors classic NVR PTZ deck.
        <div
          data-testid="camera-grid-single"
          className={cn("flex flex-col gap-2 flex-1 min-h-0", className)}
        >
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={prevSingle}
              disabled={cameras.length < 2}
              className="p-1.5 rounded-md border border-border bg-[var(--console-raised)] hover:bg-[var(--console-border)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Previous camera"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <Select
              value={String(singleIdx)}
              onValueChange={(v) => setSingleIdx(parseInt(v, 10))}
            >
              <SelectTrigger className="h-8 flex-1 min-w-0 bg-[var(--console-raised)] border-border">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {cameras.map((c, i) => (
                  <SelectItem key={c.id} value={String(i)}>
                    <span className="inline-flex items-center gap-2">
                      <span
                        className={cn(
                          "h-1.5 w-1.5 rounded-full",
                          c.status === "online"
                            ? "bg-success"
                            : "bg-muted-foreground/40",
                        )}
                      />
                      <span>{c.name}</span>
                      <span className="text-muted-foreground text-[10px]">
                        {i + 1}/{cameras.length}
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <button
              onClick={nextSingle}
              disabled={cameras.length < 2}
              className="p-1.5 rounded-md border border-border bg-[var(--console-raised)] hover:bg-[var(--console-border)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Next camera"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 min-h-0">
            {activeSingleCamera && (
              <CameraCard
                key={activeSingleCamera.id}
                camera={activeSingleCamera}
                isLoading={loadingCameras.includes(activeSingleCamera.id)}
                showLiveByDefault={true}
                onClick={onCameraClick}
                onStartRecording={onStartRecording}
                onStopRecording={onStopRecording}
                onTestConnection={onTestConnection}
                onSettings={onCameraSettings}
                onFullscreen={onCameraFullscreen}
                onInstantPlayback={onInstantPlayback}
                fitParent
              />
            )}
          </div>
        </div>
      ) : (
        <div
          data-testid="camera-grid"
          className={cn(
            `grid ${activeLayout.cols} ${activeLayout.rows} gap-2 flex-1 min-h-0`,
            className,
          )}
        >
          {cameras.slice(0, activeLayout.maxVisible).map((camera) => (
            <div key={camera.id} className="min-h-0 min-w-0 h-full">
              <CameraCard
                camera={camera}
                isLoading={loadingCameras.includes(camera.id)}
                showLiveByDefault={true}
                onClick={onCameraClick}
                onStartRecording={onStartRecording}
                onStopRecording={onStopRecording}
                onTestConnection={onTestConnection}
                onSettings={onCameraSettings}
                onFullscreen={onCameraFullscreen}
                onInstantPlayback={onInstantPlayback}
                fitParent
              />
            </div>
          ))}

          {/* Add Camera tile — fills empty grid cell (no aspect-video so
              it matches sibling tile dims) */}
          {activeLayoutId !== "1x1" &&
            cameras.length < activeLayout.maxVisible &&
            cameras.length < maxCameras && (
            <button
              data-testid="add-camera-card"
              onClick={onAddCamera}
              className={cn(
                "h-full min-h-0 rounded-lg border-2 border-dashed border-border",
                "flex flex-col items-center justify-center gap-2",
                "text-muted-foreground hover:text-[var(--console-text)] hover:border-[var(--console-accent)]",
                "transition-all duration-200 bg-[var(--console-panel)] hover:bg-[var(--console-raised)]",
              )}
            >
              <Plus className="h-8 w-8" />
              <span className="text-sm font-medium">Add Camera</span>
              <span className="text-xs">
                {cameras.length}/{maxCameras} slots used
              </span>
            </button>
          )}
        </div>
      )}
    </div>
  );
};

export default CameraGrid;
