// =============================================================================
// PrivacyMaskEditor — Draw rectangular privacy mask zones on camera snapshot
// =============================================================================

import React, { useState, useRef, useCallback, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { EyeOff, Plus, Trash2, Save } from "lucide-react";
import { getPrivacyMasks, updatePrivacyMasks } from "../../api/events";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { toast } from "sonner";

export const PrivacyMaskEditor = ({ cameraId, snapshotUrl }) => {
  const qc = useQueryClient();
  const containerRef = useRef(null);

  // Masks: [{x, y, width, height, label}] — normalised 0.0-1.0
  const [masks, setMasks] = useState([]);
  const [drawing, setDrawing] = useState(false);
  const [drawStart, setDrawStart] = useState(null);
  const [currentRect, setCurrentRect] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(null);

  // Load existing masks from backend
  const { data: masksData } = useQuery({
    queryKey: ["privacy-masks", cameraId],
    queryFn: () => getPrivacyMasks(cameraId),
    enabled: !!cameraId,
  });

  useEffect(() => {
    if (masksData?.masks) setMasks(masksData.masks);
  }, [masksData]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (m) => updatePrivacyMasks(cameraId, m),
    onSuccess: () => {
      toast.success("Privacy masks saved");
      qc.invalidateQueries({ queryKey: ["privacy-masks", cameraId] });
    },
    onError: () => toast.error("Failed to save privacy masks"),
  });

  const getNormalisedPos = useCallback((e) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return null;
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
    };
  }, []);

  const handleMouseDown = (e) => {
    if (e.button !== 0) return;
    const pos = getNormalisedPos(e);
    if (!pos) return;
    setDrawing(true);
    setDrawStart(pos);
    setCurrentRect(null);
    setSelectedIdx(null);
  };

  const handleMouseMove = (e) => {
    if (!drawing || !drawStart) return;
    const pos = getNormalisedPos(e);
    if (!pos) return;
    setCurrentRect({
      x: Math.min(drawStart.x, pos.x),
      y: Math.min(drawStart.y, pos.y),
      width: Math.abs(pos.x - drawStart.x),
      height: Math.abs(pos.y - drawStart.y),
    });
  };

  const handleMouseUp = () => {
    if (
      drawing &&
      currentRect &&
      currentRect.width > 0.02 &&
      currentRect.height > 0.02
    ) {
      setMasks((prev) => [
        ...prev,
        { ...currentRect, label: `Mask ${prev.length + 1}` },
      ]);
    }
    setDrawing(false);
    setDrawStart(null);
    setCurrentRect(null);
  };

  const removeMask = (idx) => {
    setMasks((prev) => prev.filter((_, i) => i !== idx));
    setSelectedIdx(null);
  };

  const updateLabel = (idx, label) => {
    setMasks((prev) => prev.map((m, i) => (i === idx ? { ...m, label } : m)));
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <EyeOff className="h-5 w-5" />
        <h3 className="font-semibold">Privacy Masks</h3>
      </div>

      <p className="text-xs text-muted-foreground">
        Draw rectangles on the preview to add privacy masks. Masked areas appear
        black in live view and recordings.
      </p>

      {/* Drawing area */}
      <div
        ref={containerRef}
        className="relative border rounded-lg overflow-hidden select-none cursor-crosshair"
        style={{ aspectRatio: "16/9" }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        {/* Background snapshot */}
        {snapshotUrl ? (
          <img
            src={snapshotUrl}
            alt="Camera preview"
            className="absolute inset-0 w-full h-full object-cover"
            draggable={false}
          />
        ) : (
          <div className="absolute inset-0 bg-gray-800 flex items-center justify-center text-white/50 text-sm">
            No preview available
          </div>
        )}

        {/* Existing masks */}
        {masks.map((mask, idx) => (
          <div
            key={idx}
            className={`absolute bg-black/80 border-2 flex items-center justify-center text-white text-xs ${
              selectedIdx === idx ? "border-blue-400" : "border-red-500"
            }`}
            style={{
              left: `${mask.x * 100}%`,
              top: `${mask.y * 100}%`,
              width: `${mask.width * 100}%`,
              height: `${mask.height * 100}%`,
            }}
            onClick={(e) => {
              e.stopPropagation();
              setSelectedIdx(idx);
            }}
          >
            {mask.label || `Mask ${idx + 1}`}
          </div>
        ))}

        {/* Current drawing rect */}
        {currentRect && (
          <div
            className="absolute border-2 border-dashed border-yellow-400 bg-black/40"
            style={{
              left: `${currentRect.x * 100}%`,
              top: `${currentRect.y * 100}%`,
              width: `${currentRect.width * 100}%`,
              height: `${currentRect.height * 100}%`,
            }}
          />
        )}
      </div>

      {/* Mask list */}
      {masks.length > 0 && (
        <div className="space-y-2">
          <Label className="text-sm">Masks ({masks.length})</Label>
          {masks.map((mask, idx) => (
            <div
              key={idx}
              className={`flex items-center gap-2 p-2 rounded border ${
                selectedIdx === idx ? "border-blue-400 bg-blue-50/50" : ""
              }`}
            >
              <Input
                value={mask.label || ""}
                onChange={(e) => updateLabel(idx, e.target.value)}
                className="h-8 text-sm flex-1"
                placeholder="Label"
              />
              <span className="text-xs text-muted-foreground whitespace-nowrap">
                {Math.round(mask.width * 100)}% ×{" "}
                {Math.round(mask.height * 100)}%
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => removeMask(idx)}
                className="h-8 w-8 p-0 text-red-500"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Save */}
      <Button
        onClick={() => saveMutation.mutate(masks)}
        disabled={saveMutation.isPending}
        size="sm"
      >
        <Save className="h-4 w-4 mr-1" />
        Save Masks
      </Button>
    </div>
  );
};
