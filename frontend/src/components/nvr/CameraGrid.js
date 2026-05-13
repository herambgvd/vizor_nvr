// =============================================================================
// Camera Grid Component - Multi-Camera Display
// =============================================================================
// Responsive grid layout for displaying multiple cameras.
// Supports selectable layout presets (1×1, 2×2, 3×3, 4×4, 5×5, mixed-large).
// =============================================================================

import React, { useState, useEffect, useRef, useCallback } from "react";
import { Plus, Camera, LayoutGrid, Play, Pause, Timer } from "lucide-react";
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
  { id: "1x1", label: "1×1", cols: "grid-cols-1", maxVisible: 1 },
  { id: "2x2", label: "2×2", cols: "grid-cols-2", maxVisible: 4 },
  { id: "3x3", label: "3×3", cols: "grid-cols-3", maxVisible: 9 },
  { id: "4x4", label: "4×4", cols: "grid-cols-4", maxVisible: 16 },
  { id: "5x5", label: "5×5", cols: "grid-cols-5", maxVisible: 25 },
];

/**
 * Camera Grid Layout Picker — compact toolbar shown above the grid.
 */
const LayoutPicker = ({ current, onChange }) => (
  <div className="flex items-center gap-1 bg-white/[0.04] rounded-lg p-1">
    <LayoutGrid className="h-4 w-4 text-zinc-500 ml-1 mr-0.5 shrink-0" />
    {LAYOUTS.map((l) => (
      <button
        key={l.id}
        onClick={() => onChange(l.id)}
        className={cn(
          "px-2 py-0.5 rounded text-xs font-medium transition-colors",
          current === l.id
            ? "bg-zinc-900 text-white"
            : "text-zinc-400 hover:bg-white/[0.06]",
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
}) => {
  // Internal state when parent doesn't control layout
  const [internalLayout, setInternalLayout] = useState("2x2");
  const activeLayoutId = layoutProp ?? internalLayout;
  const activeLayout =
    LAYOUTS.find((l) => l.id === activeLayoutId) ?? LAYOUTS[1];

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
          "bg-zinc-950/40 rounded-lg border border-dashed border-white/15",
          className,
        )}
      >
        <div className="p-4 bg-white/[0.04] rounded-full mb-4">
          <Camera className="h-12 w-12 text-zinc-500" />
        </div>
        <h3 className="text-lg font-medium text-white mb-2">
          No Cameras Added
        </h3>
        <p className="text-zinc-500 text-center mb-6 max-w-md">
          Add your first RTSP camera to start monitoring and recording. You can
          add up to {maxCameras} cameras with your license.
        </p>
        <Button
          data-testid="add-first-camera-btn"
          onClick={onAddCamera}
          className="bg-zinc-900 hover:bg-zinc-900/60"
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
        className={cn(`grid ${activeLayout.cols} gap-4`, className)}
      >
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="aspect-video">
            <Skeleton className="w-full h-full rounded-lg" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Layout toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <LayoutPicker
            current={activeLayoutId}
            onChange={handleLayoutChange}
          />

          {/* Tour controls */}
          <div className="flex items-center gap-1 bg-white/[0.04] rounded-lg p-1">
            <Timer className="h-4 w-4 text-zinc-500 ml-1 mr-0.5 shrink-0" />
            {tourActive ? (
              <button
                onClick={stopTour}
                className="flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-600 text-white"
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
                    ? "text-zinc-500 cursor-not-allowed"
                    : "text-zinc-400 hover:bg-white/[0.06]",
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

        <span className="text-xs text-zinc-500">
          {tourActive
            ? `Tour: ${tourIndex + 1}/${tourCameras.length} — ${tourCameras[tourIndex]?.name || ""}`
            : `${cameras.length} camera${cameras.length !== 1 ? "s" : ""}${
                activeLayout.maxVisible < cameras.length
                  ? ` (showing first ${activeLayout.maxVisible})`
                  : ""
              }`}
        </span>
      </div>

      {/* Grid — show single camera in tour mode */}
      {tourActive && tourCameras.length > 0 ? (
        <div
          data-testid="camera-grid-tour"
          className={cn("grid grid-cols-1 gap-4", className)}
        >
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
          />
        </div>
      ) : (
        <div
          data-testid="camera-grid"
          className={cn(`grid ${activeLayout.cols} gap-4`, className)}
        >
          {cameras.slice(0, activeLayout.maxVisible).map((camera) => (
            <CameraCard
              key={camera.id}
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
            />
          ))}

          {/* Add Camera Card — only in 2×2+ layouts */}
          {activeLayoutId !== "1x1" && cameras.length < maxCameras && (
            <button
              data-testid="add-camera-card"
              onClick={onAddCamera}
              className={cn(
                "aspect-video rounded-lg border-2 border-dashed border-white/15",
                "flex flex-col items-center justify-center gap-2",
                "text-zinc-500 hover:text-zinc-400 hover:border-slate-400",
                "transition-all duration-200 bg-zinc-950/40 hover:bg-white/[0.04]",
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
