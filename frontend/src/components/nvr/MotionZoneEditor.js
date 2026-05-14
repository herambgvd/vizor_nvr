// =============================================================================
// MotionZoneEditor — Visual 16×12 grid editor for motion detection zones
// =============================================================================

import React, { useState, useCallback, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, Save, RotateCcw } from "lucide-react";
import { getMotionConfig, updateMotionConfig } from "../../api/events";
import { Button } from "../ui/button";
import { Slider } from "../ui/slider";
import { Switch } from "../ui/switch";
import { Label } from "../ui/label";
import { toast } from "sonner";

const GRID_COLS = 16;
const GRID_ROWS = 12;

export const MotionZoneEditor = ({ cameraId, snapshotUrl }) => {
  const qc = useQueryClient();

  const [enabled, setEnabled] = useState(false);
  const [sensitivity, setSensitivity] = useState(5);
  const [debounce, setDebounce] = useState(5);
  const [grid, setGrid] = useState(() =>
    Array.from({ length: GRID_ROWS }, () => Array(GRID_COLS).fill(true)),
  );
  const [isDragging, setIsDragging] = useState(false);
  const [dragValue, setDragValue] = useState(true);

  // Load existing config
  const { data: configData } = useQuery({
    queryKey: ["motion-config", cameraId],
    queryFn: () => getMotionConfig(cameraId),
    enabled: !!cameraId,
  });

  useEffect(() => {
    if (configData?.config) {
      const c = configData.config;
      setEnabled(c.enabled || false);
      setSensitivity(c.sensitivity || 5);
      setDebounce(c.debounce_seconds || 5);
      if (c.grid && Array.isArray(c.grid)) {
        setGrid(c.grid);
      }
    }
  }, [configData]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (config) => updateMotionConfig(cameraId, config),
    onSuccess: () => {
      toast.success("Motion detection config saved");
      qc.invalidateQueries({ queryKey: ["motion-config", cameraId] });
    },
    onError: () => toast.error("Failed to save motion config"),
  });

  const handleSave = () => {
    saveMutation.mutate({
      enabled,
      sensitivity,
      debounce_seconds: debounce,
      grid,
      zones: [],
    });
  };

  const handleReset = () => {
    setGrid(
      Array.from({ length: GRID_ROWS }, () => Array(GRID_COLS).fill(true)),
    );
    setSensitivity(5);
  };

  const toggleCell = useCallback((row, col, value) => {
    setGrid((prev) => {
      const next = prev.map((r) => [...r]);
      next[row][col] = value;
      return next;
    });
  }, []);

  const handleMouseDown = (row, col) => {
    const newVal = !grid[row][col];
    setIsDragging(true);
    setDragValue(newVal);
    toggleCell(row, col, newVal);
  };

  const handleMouseEnter = (row, col) => {
    if (isDragging) {
      toggleCell(row, col, dragValue);
    }
  };

  const handleMouseUp = () => setIsDragging(false);

  return (
    <div
      className="space-y-4"
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5" />
          <h3 className="font-semibold">Motion Detection</h3>
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor="motion-enabled">Enabled</Label>
          <Switch
            id="motion-enabled"
            checked={enabled}
            onCheckedChange={setEnabled}
          />
        </div>
      </div>

      {/* Sensitivity slider */}
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <Label>Sensitivity</Label>
          <span className="text-muted-foreground">{sensitivity}/10</span>
        </div>
        <Slider
          value={[sensitivity]}
          onValueChange={([v]) => setSensitivity(v)}
          min={1}
          max={10}
          step={1}
        />
      </div>

      {/* Debounce */}
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <Label>Debounce (seconds)</Label>
          <span className="text-muted-foreground">{debounce}s</span>
        </div>
        <Slider
          value={[debounce]}
          onValueChange={([v]) => setDebounce(v)}
          min={1}
          max={30}
          step={1}
        />
      </div>

      {/* Grid editor */}
      <div className="space-y-1">
        <Label className="text-sm">Detection Zone Grid</Label>
        <p className="text-xs text-muted-foreground">
          Click and drag to toggle cells. Green = active detection, grey =
          ignored.
        </p>
        <div
          className="relative border rounded-lg overflow-hidden select-none"
          style={{ aspectRatio: "16/9" }}
        >
          {/* Background snapshot */}
          {snapshotUrl && (
            <img
              src={snapshotUrl}
              alt="Camera preview"
              className="absolute inset-0 w-full h-full object-cover opacity-40"
              draggable={false}
            />
          )}
          {/* Grid overlay */}
          <div
            className="absolute inset-0 grid"
            style={{
              gridTemplateColumns: `repeat(${GRID_COLS}, 1fr)`,
              gridTemplateRows: `repeat(${GRID_ROWS}, 1fr)`,
              gap: "1px",
            }}
          >
            {grid.map((row, ri) =>
              row.map((active, ci) => (
                <div
                  key={`${ri}-${ci}`}
                  className={`cursor-crosshair border border-border transition-colors ${
                    active
                      ? "bg-green-500/40 hover:bg-green-500/50"
                      : "bg-gray-500/20 hover:bg-gray-500/30"
                  }`}
                  onMouseDown={() => handleMouseDown(ri, ci)}
                  onMouseEnter={() => handleMouseEnter(ri, ci)}
                />
              )),
            )}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <Button
          onClick={handleSave}
          disabled={saveMutation.isPending}
          size="sm"
        >
          <Save className="h-4 w-4 mr-1" />
          Save
        </Button>
        <Button variant="outline" onClick={handleReset} size="sm">
          <RotateCcw className="h-4 w-4 mr-1" />
          Reset Grid
        </Button>
      </div>
    </div>
  );
};
