// =============================================================================
// Camera Settings Page — Advanced camera config + linkage rules
// =============================================================================

import React from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getAllCameras } from "../api/cameras";
import { CameraSettingsPanel, LinkageRuleBuilder } from "../components/nvr";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";

const CameraSettings = () => {
  const [params, setParams] = useSearchParams();
  const cameraId = params.get("camera");

  const { data: cameras = [] } = useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
  });

  return (
    <div className="p-6 space-y-8 max-w-4xl mx-auto">
      {/* Camera selector */}
      <div className="space-y-1">
        <label className="text-sm font-medium">Select Camera</label>
        <Select
          value={cameraId || ""}
          onValueChange={(v) => setParams({ camera: v })}
        >
          <SelectTrigger className="w-72">
            <SelectValue placeholder="Choose a camera…" />
          </SelectTrigger>
          <SelectContent>
            {cameras.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Per-camera settings */}
      {cameraId ? (
        <CameraSettingsPanel cameraId={cameraId} />
      ) : (
        <p className="text-muted-foreground text-sm">
          Select a camera above to configure motion detection, privacy masks, and recording schedule.
        </p>
      )}

      {/* System-wide linkage rules */}
      <div className="border-t pt-6">
        <LinkageRuleBuilder />
      </div>
    </div>
  );
};

export default CameraSettings;
