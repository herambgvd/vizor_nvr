// =============================================================================
// CameraCell — one synchronized recording player.
// Fetches a camera's segments for a date, plays them back-to-back, and exposes
// play/pause/playbackRate/getCurrentDayOffset/seekTo via ref so a parent can
// scrub many cameras on one shared timeline.
// =============================================================================

import React, {
  useRef, useState, useCallback, useEffect, useImperativeHandle,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { Video, X } from "lucide-react";
import { cn } from "../../lib/utils";
import { dayOffset } from "../../lib/timeline";
import { parseUtc } from "../../lib/timeline";
import api, { BACKEND_URL } from "../../api/client";

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

  const getDayOffset = useCallback(
    (isoTime) => dayOffset(isoTime, date),
    [date]
  );

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

  useEffect(() => {
    const seg = segmentsRef.current[currentSegIdx];
    if (!seg || !videoRef.current) return;

    const token = localStorage.getItem("nvr_token") || "";
    videoRef.current.src = `${BACKEND_URL}/api/recordings/${seg.id}/download?token=${token}`;
    videoRef.current.load();

    const pending = pendingSeekRef.current;
    if (pending != null) {
      pendingSeekRef.current = null;
      const applySeek = () => {
        if (videoRef.current) videoRef.current.currentTime = pending;
      };
      videoRef.current.addEventListener("loadedmetadata", applySeek, { once: true });
    }
  }, [currentSegIdx, totalSegments]);

  const handleEnded = useCallback(() => {
    const next = currentSegIdxRef.current + 1;
    if (next < segmentsRef.current.length) {
      currentSegIdxRef.current = next;
      setCurrentSegIdx(next);
      setTimeout(() => videoRef.current?.play().catch(() => {}), 50);
    }
  }, []);

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

    seekTo: (dayOffsetSec) => {
      const segs = segmentsRef.current;
      if (!segs.length || !videoRef.current) return;

      let targetIdx = segs.findIndex((s) => {
        const start = getDayOffset(s.start_time);
        const end = start + (s.duration || 0);
        return dayOffsetSec >= start && dayOffsetSec <= end;
      });

      if (targetIdx === -1) {
        targetIdx = segs.findIndex((s) => getDayOffset(s.start_time) > dayOffsetSec);
        if (targetIdx === -1) return;
      }

      const offsetInSeg = Math.max(
        0,
        dayOffsetSec - getDayOffset(segs[targetIdx].start_time)
      );

      if (targetIdx !== currentSegIdxRef.current) {
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

          {!loaded && !noRecording && (
            <div className="absolute inset-0 flex items-center justify-center text-white/40">
              <Video className="h-8 w-8 animate-pulse" />
            </div>
          )}

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

export default CameraCell;
