// =============================================================================
// CameraThumbnail — auth blob fetch for /cameras/{id}/thumbnail
// =============================================================================
// Plain <img> with src=/api/... won't work because the backend requires
// a Bearer token. Fetch the JPEG manually, wrap in a blob URL.
// =============================================================================

import React, { useEffect, useState } from "react";
import { Video } from "lucide-react";
import { BACKEND_URL, getAccessToken } from "../../api/client";
import { cn } from "../../lib/utils";

const CameraThumbnail = ({ cameraId, className, refreshSec = 30 }) => {
  const [url, setUrl] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!cameraId) return undefined;

    let cancelled = false;
    let currentObj = null;

    const fetchOnce = async () => {
      try {
        const token = getAccessToken();
        const url = `${BACKEND_URL}/api/cameras/${cameraId}/thumbnail?t=${Date.now()}`;
        const hdrs = token ? { Authorization: `Bearer ${token}` } : {};
        let res = await fetch(url, { headers: hdrs });
        // First miss may have triggered on-demand capture. Retry once.
        if (!res.ok && res.status === 404) {
          await new Promise((r) => setTimeout(r, 1500));
          res = await fetch(url, { headers: hdrs });
        }
        if (!res.ok) {
          if (!cancelled && !currentObj) setFailed(true);
          return;
        }
        const blob = await res.blob();
        const obj = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(obj);
          return;
        }
        const prev = currentObj;
        currentObj = obj;
        setUrl(obj);
        setFailed(false);
        if (prev) URL.revokeObjectURL(prev);
      } catch {
        if (!cancelled && !currentObj) setFailed(true);
      }
    };

    fetchOnce();
    const interval = setInterval(fetchOnce, Math.max(5, refreshSec) * 1000);

    return () => {
      cancelled = true;
      clearInterval(interval);
      if (currentObj) URL.revokeObjectURL(currentObj);
    };
  }, [cameraId, refreshSec]);

  if (failed || !url) {
    return (
      <div
        className={cn(
          "flex items-center justify-center bg-card/60 rounded-md",
          className,
        )}
      >
        <Video className="h-4 w-4 text-muted-foreground" />
      </div>
    );
  }

  return (
    <img
      src={url}
      alt="thumbnail"
      className={cn("object-cover rounded-md", className)}
    />
  );
};

export default CameraThumbnail;
