// =============================================================================
// ClipBuilder — Mark IN/OUT segments and export as a stitched clip
// =============================================================================

import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Scissors,
  Plus,
  Trash2,
  Download,
  Loader2,
} from "lucide-react";
import { exportMultiSegment, getExportStatus, getExportDownloadUrl } from "../../api/recordings";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Switch } from "../ui/switch";
import { cn } from "../../lib/utils";
import { toast } from "sonner";

/**
 * ClipBuilder — allows marking IN/OUT points across cameras and queuing a
 * multi-segment export.
 *
 * @param {string}   cameraId     - Active camera ID (for default segment)
 * @param {Date}     currentTime  - Current playback time for quick mark
 * @param {string}   className
 */
export const ClipBuilder = ({ cameraId, currentTime, className }) => {
  const [segments, setSegments] = useState([]);
  const [burnTimestamp, setBurnTimestamp] = useState(false);
  const [exportId, setExportId] = useState(null);

  // Add a new segment with IN point set to current time
  const addSegment = () => {
    const now = currentTime || new Date();
    setSegments((prev) => [
      ...prev,
      {
        id: Date.now(),
        camera_id: cameraId || "",
        start_time: now.toISOString().slice(0, 19),
        end_time: new Date(now.getTime() + 60000).toISOString().slice(0, 19),
      },
    ]);
  };

  const removeSegment = (id) => {
    setSegments((prev) => prev.filter((s) => s.id !== id));
  };

  const updateSegment = (id, field, value) => {
    setSegments((prev) =>
      prev.map((s) => (s.id === id ? { ...s, [field]: value } : s)),
    );
  };

  // Export mutation
  const mutation = useMutation({
    mutationFn: (data) => exportMultiSegment(data),
    onSuccess: (result) => {
      setExportId(result.export_id);
      toast.success("Export started — check back for download");
      pollExport(result.export_id);
    },
    onError: (e) =>
      toast.error(e.response?.data?.detail || "Export failed"),
  });

  // Simple poll for export completion
  const pollExport = async (id) => {
    const maxAttempts = 60;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const status = await getExportStatus(id);
        if (status.status === "done") {
          toast.success("Export ready for download");
          return;
        }
        if (status.status === "failed") {
          toast.error("Export failed");
          return;
        }
      } catch {
        // Network blip — continue polling with backoff rather than aborting
        await new Promise((r) => setTimeout(r, 4000));
        continue;
      }
    }
  };

  const handleExport = () => {
    if (segments.length === 0) {
      toast.error("Add at least one clip segment");
      return;
    }
    mutation.mutate({
      segments: segments.map((s) => ({
        camera_id: s.camera_id,
        start_time: new Date(s.start_time).toISOString(),
        end_time: new Date(s.end_time).toISOString(),
      })),
      format: "mp4",
      burn_timestamp: burnTimestamp,
    });
  };

  return (
    <div
      className={cn(
        "bg-card border border-border rounded-lg p-4 space-y-4",
        className,
      )}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Scissors className="h-4 w-4" />
          Clip Builder
        </h3>
        <Button variant="outline" size="sm" onClick={addSegment}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add Clip
        </Button>
      </div>

      {segments.length === 0 ? (
        <p className="text-xs text-muted-foreground text-center py-4">
          No clips added. Click "Add Clip" to mark an IN/OUT range.
        </p>
      ) : (
        <div className="space-y-3">
          {segments.map((seg, idx) => (
            <div
              key={seg.id}
              className="border border-border rounded-lg p-3 space-y-2"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-400">
                  Clip {idx + 1}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-muted-foreground hover:text-red-500"
                  onClick={() => removeSegment(seg.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-[10px] text-muted-foreground">IN</Label>
                  <Input
                    type="datetime-local"
                    step="1"
                    value={seg.start_time}
                    onChange={(e) =>
                      updateSegment(seg.id, "start_time", e.target.value)
                    }
                    className="h-7 text-xs"
                  />
                </div>
                <div>
                  <Label className="text-[10px] text-muted-foreground">OUT</Label>
                  <Input
                    type="datetime-local"
                    step="1"
                    value={seg.end_time}
                    onChange={(e) =>
                      updateSegment(seg.id, "end_time", e.target.value)
                    }
                    className="h-7 text-xs"
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Options */}
      <div className="flex items-center justify-between pt-2 border-t border-slate-100">
        <div className="flex items-center gap-2">
          <Switch
            id="burn-ts"
            checked={burnTimestamp}
            onCheckedChange={setBurnTimestamp}
          />
          <Label htmlFor="burn-ts" className="text-xs">
            Burn-in timestamp
          </Label>
        </div>
      </div>

      {/* Export button */}
      <Button
        className="w-full bg-primary hover:bg-primary/60"
        size="sm"
        onClick={handleExport}
        disabled={segments.length === 0 || mutation.isPending}
      >
        {mutation.isPending ? (
          <Loader2 className="h-4 w-4 mr-2 animate-spin" />
        ) : (
          <Download className="h-4 w-4 mr-2" />
        )}
        Export {segments.length} Clip{segments.length !== 1 ? "s" : ""}
      </Button>

      {/* Download link when ready */}
      {exportId && (
        <a
          href={getExportDownloadUrl(exportId)}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-center text-xs text-emerald-600 hover:underline"
        >
          Download last export
        </a>
      )}
    </div>
  );
};

export default ClipBuilder;
