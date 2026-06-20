// =============================================================================
// PTZ Controls — Pan / Tilt / Zoom overlay for live camera view
// =============================================================================

import React, { useState, useCallback, useRef, useEffect } from "react";
import {
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ZoomIn,
  ZoomOut,
  Home,
  Star,
  StopCircle,
  Save,
  Trash2,
} from "lucide-react";
import {
  ptzMove,
  ptzStop,
  ptzGetPresets,
  ptzGotoPreset,
  ptzSavePreset,
  ptzDeletePreset,
} from "../../api/cameras";
import { Button } from "../ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { cn } from "../../lib/utils";
import { toast } from "sonner";

/**
 * PTZ Controls overlay — absolute-positioned within a camera player container.
 *
 * Props:
 *  cameraId   – camera UUID
 *  className  – additional wrapper classes
 *  speed      – movement speed 0.0 – 1.0 (default 0.5)
 *  ptzCapable – when explicitly false, the controls are hidden entirely so a
 *               non-PTZ camera never shows controls that would silently fail.
 */
export const PTZControls = ({ cameraId, className, speed = 0.5, ptzCapable = true }) => {
  const [presets, setPresets] = useState([]);
  const [showPresets, setShowPresets] = useState(false);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [saving, setSaving] = useState(false);
  const moveTimer = useRef(null);

  // Fetch presets
  const fetchPresets = useCallback(() => {
    if (!cameraId) return;
    ptzGetPresets(cameraId)
      .then((res) =>
        setPresets(Array.isArray(res) ? res : (res?.presets ?? [])),
      )
      .catch(() => {});
  }, [cameraId]);

  useEffect(() => {
    fetchPresets();
  }, [fetchPresets]);

  // Save current position as preset
  const handleSavePreset = async () => {
    if (!presetName.trim()) {
      toast.error("Please enter a preset name");
      return;
    }
    setSaving(true);
    try {
      await ptzSavePreset(cameraId, { name: presetName.trim() });
      toast.success(`Preset "${presetName}" saved`);
      setShowSaveDialog(false);
      setPresetName("");
      // Refresh presets list
      fetchPresets();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Failed to save preset");
    } finally {
      setSaving(false);
    }
  };

  // Continuous move while button is held
  const startMove = useCallback(
    (direction) => {
      const params = { speed };
      if (direction === "up") params.tilt = speed;
      else if (direction === "down") params.tilt = -speed;
      else if (direction === "left") params.pan = -speed;
      else if (direction === "right") params.pan = speed;
      else if (direction === "zoom_in") params.zoom = speed;
      else if (direction === "zoom_out") params.zoom = -speed;

      ptzMove(cameraId, params).catch(() => toast.error("PTZ move failed"));

      // keep sending move while held
      moveTimer.current = setInterval(() => {
        ptzMove(cameraId, params).catch(() => {});
      }, 250);
    },
    [cameraId, speed],
  );

  const stopMove = useCallback(() => {
    clearInterval(moveTimer.current);
    ptzStop(cameraId).catch(() => {});
  }, [cameraId]);

  const handleGotoPreset = (preset) => {
    ptzGotoPreset(cameraId, {
      preset_token: preset.token ?? preset.id ?? preset.name,
    })
      .then(() => toast.success(`Moved to preset "${preset.name}"`))
      .catch(() => toast.error("Failed to go to preset"));
  };

  const handleDeletePreset = (preset, e) => {
    e.stopPropagation();
    const token = preset.token ?? preset.id ?? preset.name;
    ptzDeletePreset(cameraId, token)
      .then(() => {
        toast.success(`Preset "${preset.name}" deleted`);
        fetchPresets();
      })
      .catch(() => toast.error("Failed to delete preset"));
  };

  const DPadBtn = ({ direction, icon: Icon, label }) => (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          className={cn(
            "h-9 w-9 flex items-center justify-center rounded-full",
            "bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm",
            "transition-colors active:scale-95",
          )}
          onMouseDown={() => startMove(direction)}
          onMouseUp={stopMove}
          onMouseLeave={stopMove}
          onTouchStart={() => startMove(direction)}
          onTouchEnd={stopMove}
        >
          <Icon className="h-4 w-4" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );

  // Defense in depth: never render controls for a non-PTZ camera.
  if (ptzCapable === false) return null;

  return (
    <TooltipProvider delayDuration={200}>
      <div
        className={cn(
          "absolute bottom-4 right-4 flex flex-col items-end gap-3 z-20",
          className,
        )}
      >
        {/* Presets popover */}
        {showPresets && presets.length > 0 && (
          <div className="bg-black/70 backdrop-blur-md rounded-lg p-2 space-y-1 max-h-48 overflow-y-auto min-w-[160px]">
            {presets.map((p, i) => (
              <div
                key={p.token ?? i}
                className="flex items-center gap-1 group/preset"
              >
                <button
                  className="flex-1 text-left text-xs text-white/90 hover:bg-card/20 px-3 py-1.5 rounded"
                  onClick={() => handleGotoPreset(p)}
                >
                  {p.name || `Preset ${i + 1}`}
                </button>
                <button
                  className="opacity-0 group-hover/preset:opacity-100 p-1 rounded hover:bg-red-500/60 text-white/70 hover:text-white transition-all"
                  onClick={(e) => handleDeletePreset(p, e)}
                  title="Delete preset"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Controls cluster */}
        <div className="flex items-end gap-3">
          {/* Preset & Home */}
          <div className="flex flex-col gap-1.5">
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  className={cn(
                    "h-9 w-9 flex items-center justify-center rounded-full",
                    "bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm",
                    showPresets && "ring-2 ring-white/40",
                  )}
                  onClick={() => setShowPresets(!showPresets)}
                >
                  <Star className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>Presets</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  className="h-9 w-9 flex items-center justify-center rounded-full bg-emerald-500/80 hover:bg-emerald-600 text-white backdrop-blur-sm"
                  onClick={() => setShowSaveDialog(true)}
                >
                  <Save className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>Save Preset</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  className="h-9 w-9 flex items-center justify-center rounded-full bg-black/50 hover:bg-black/70 text-white backdrop-blur-sm"
                  onClick={() => {
                    const home = presets.find(
                      (p) =>
                        p.name?.toLowerCase() === "home" || p.token === "1",
                    );
                    if (home) handleGotoPreset(home);
                    else toast.info("No home preset configured");
                  }}
                >
                  <Home className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>Home</TooltipContent>
            </Tooltip>
          </div>

          {/* Zoom */}
          <div className="flex flex-col gap-1.5">
            <DPadBtn direction="zoom_in" icon={ZoomIn} label="Zoom In" />
            <DPadBtn direction="zoom_out" icon={ZoomOut} label="Zoom Out" />
          </div>

          {/* D-Pad */}
          <div className="grid grid-cols-3 gap-0.5">
            <div />
            <DPadBtn direction="up" icon={ArrowUp} label="Tilt Up" />
            <div />
            <DPadBtn direction="left" icon={ArrowLeft} label="Pan Left" />
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  className="h-9 w-9 flex items-center justify-center rounded-full bg-red-500/80 hover:bg-destructive text-white backdrop-blur-sm transition-colors"
                  onClick={stopMove}
                >
                  <StopCircle className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>Stop</TooltipContent>
            </Tooltip>
            <DPadBtn direction="right" icon={ArrowRight} label="Pan Right" />
            <div />
            <DPadBtn direction="down" icon={ArrowDown} label="Tilt Down" />
            <div />
          </div>
        </div>
      </div>

      {/* Save Preset Dialog */}
      <Dialog open={showSaveDialog} onOpenChange={setShowSaveDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Save Preset</DialogTitle>
            <DialogDescription>
              Save the current camera position as a preset for quick access.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div>
              <Label htmlFor="preset-name">Preset Name</Label>
              <Input
                id="preset-name"
                value={presetName}
                onChange={(e) => setPresetName(e.target.value)}
                placeholder="e.g., Front Door, Parking Lot"
                className="mt-1"
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowSaveDialog(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button onClick={handleSavePreset} disabled={saving}>
              {saving ? "Saving..." : "Save Preset"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
};

export default PTZControls;
