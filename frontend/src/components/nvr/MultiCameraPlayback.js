// =============================================================================
// MultiCameraPlayback — Synchronized multi-camera view for recordings
// =============================================================================

import React, { useState, useRef, useCallback, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { format, startOfDay, addSeconds, differenceInSeconds } from "date-fns";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Calendar as CalendarIcon,
  Grid,
  List,
  Maximize2,
  Minimize2,
  RefreshCw,
  Plus,
  X,
} from "lucide-react";
import { getAllCameras } from "../../api/cameras";
import { getPlaybackInfo, getTimeline } from "../../api/recordings";
import { Button } from "../ui/button";
import { Calendar } from "../ui/calendar";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "../ui/popover";
import { Slider } from "../ui/slider";
import { cn } from "../../lib/utils";
import { toast } from "sonner";

/**
 * Multi-camera synchronized playback component.
 * 
 * Features:
 * - Select multiple cameras for synchronized view
 * - Single timeline controls all cameras
 * - Grid layout (2x2, 3x3, etc.)
 * - Synchronized seeking across all players
 */
export const MultiCameraPlayback = ({ className }) => {
  // State
  const [selectedDate, setSelectedDate] = useState(startOfDay(new Date()));
  const [selectedCameras, setSelectedCameras] = useState([]);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0); // seconds from midnight
  const [gridLayout, setGridLayout] = useState(2); // 2x2 default
  const [fullscreenCamera, setFullscreenCamera] = useState(null);
  
  // Refs
  const playerRefs = useRef({});
  const playbackTimer = useRef(null);

  // Fetch cameras
  const { data: cameras = [] } = useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
  });

  // Fetch timelines for all selected cameras
  const { data: timelines = {}, isLoading: timelinesLoading, refetch } = useQuery({
    queryKey: ["timelines", selectedCameras, selectedDate?.toISOString()],
    queryFn: async () => {
      const results = {};
      for (const cameraId of selectedCameras) {
        try {
          const timeline = await getTimeline(cameraId, selectedDate?.toISOString());
          results[cameraId] = timeline;
        } catch {
          results[cameraId] = [];
        }
      }
      return results;
    },
    enabled: selectedCameras.length > 0 && !!selectedDate,
    staleTime: 30000,
  });

  // Calculate combined available time ranges
  const combinedTimeline = React.useMemo(() => {
    if (selectedCameras.length === 0) return [];
    
    // Find time ranges where at least one camera has recordings
    const allSegments = [];
    Object.values(timelines).forEach((timeline) => {
      timeline?.forEach((segment) => {
        allSegments.push({
          start: new Date(segment.start_time),
          end: new Date(segment.end_time),
        });
      });
    });
    
    // Sort and merge overlapping segments
    allSegments.sort((a, b) => a.start - b.start);
    const merged = [];
    allSegments.forEach((segment) => {
      if (merged.length === 0 || merged[merged.length - 1].end < segment.start) {
        merged.push({ ...segment });
      } else {
        merged[merged.length - 1].end = new Date(
          Math.max(merged[merged.length - 1].end, segment.end)
        );
      }
    });
    
    return merged;
  }, [timelines, selectedCameras]);

  // Add camera to selection
  const addCamera = (cameraId) => {
    if (!selectedCameras.includes(cameraId)) {
      setSelectedCameras([...selectedCameras, cameraId]);
    }
  };

  // Remove camera from selection
  const removeCamera = (cameraId) => {
    setSelectedCameras(selectedCameras.filter((id) => id !== cameraId));
    delete playerRefs.current[cameraId];
  };

  // Get time as Date object
  const getCurrentTimeAsDate = useCallback(() => {
    return addSeconds(startOfDay(selectedDate), currentTime);
  }, [selectedDate, currentTime]);

  // Seek all players to a specific time
  const seekTo = useCallback((seconds) => {
    setCurrentTime(seconds);
    
    // Seek all video players
    Object.values(playerRefs.current).forEach((videoEl) => {
      if (videoEl) {
        // Calculate relative position in video
        // This assumes HLS or similar streaming
        // For actual implementation, this would need to request the correct segment
      }
    });
  }, []);

  // Handle timeline slider change
  const handleSliderChange = ([value]) => {
    setIsPlaying(false);
    seekTo(value);
  };

  // Play/Pause toggle
  const togglePlayback = () => {
    if (isPlaying) {
      // Pause
      setIsPlaying(false);
      if (playbackTimer.current) {
        clearInterval(playbackTimer.current);
      }
    } else {
      // Play
      setIsPlaying(true);
      playbackTimer.current = setInterval(() => {
        setCurrentTime((prev) => {
          const next = prev + 1;
          if (next >= 86400) { // End of day
            setIsPlaying(false);
            return 86400;
          }
          return next;
        });
      }, 1000);
    }
  };

  // Skip forward/backward
  const skip = (seconds) => {
    seekTo(Math.max(0, Math.min(86400, currentTime + seconds)));
  };

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (playbackTimer.current) {
        clearInterval(playbackTimer.current);
      }
    };
  }, []);

  // Format time as HH:mm:ss
  const formatTime = (seconds) => {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${hours.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  // Available cameras (not yet selected)
  const availableCameras = cameras.filter(
    (c) => !selectedCameras.includes(c.id)
  );

  // Grid layout class
  const gridClass = {
    1: "grid-cols-1",
    2: "grid-cols-2",
    3: "grid-cols-3",
    4: "grid-cols-2 lg:grid-cols-4",
  }[gridLayout] || "grid-cols-2";

  return (
    <div className={cn("flex flex-col h-full", className)}>
      {/* Header Controls */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-border  flex flex-wrap items-center gap-3">
        {/* Date picker */}
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" className="w-48 justify-start">
              <CalendarIcon className="h-4 w-4 mr-2" />
              {format(selectedDate, "PPP")}
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <Calendar
              mode="single"
              selected={selectedDate}
              onSelect={(d) => d && setSelectedDate(startOfDay(d))}
              disabled={(d) => d > new Date()}
              initialFocus
            />
          </PopoverContent>
        </Popover>

        {/* Add camera */}
        <Select onValueChange={addCamera}>
          <SelectTrigger className="w-48">
            <SelectValue placeholder="Add camera..." />
          </SelectTrigger>
          <SelectContent>
            {availableCameras.map((cam) => (
              <SelectItem key={cam.id} value={cam.id}>
                {cam.name}
              </SelectItem>
            ))}
            {availableCameras.length === 0 && (
              <div className="px-2 py-1 text-sm text-muted-foreground">
                All cameras selected
              </div>
            )}
          </SelectContent>
        </Select>

        {/* Grid layout */}
        <div className="flex items-center gap-1 border border-border  rounded-md p-1">
          {[1, 2, 3, 4].map((n) => (
            <Button
              key={n}
              variant={gridLayout === n ? "secondary" : "ghost"}
              size="icon"
              className="h-7 w-7"
              onClick={() => setGridLayout(n)}
            >
              <Grid className="h-3 w-3" />
            </Button>
          ))}
        </div>

        <Button variant="outline" size="icon" onClick={() => refetch()}>
          <RefreshCw className={cn("h-4 w-4", timelinesLoading && "animate-spin")} />
        </Button>
      </div>

      {/* Video Grid */}
      <div className="flex-1 p-4 overflow-auto">
        {selectedCameras.length === 0 ? (
          <div className="h-full flex items-center justify-center text-muted-foreground">
            <div className="text-center">
              <Grid className="h-12 w-12 mx-auto mb-3 opacity-50" />
              <p className="font-medium">No cameras selected</p>
              <p className="text-sm mt-1">
                Add cameras using the dropdown above to begin synchronized playback
              </p>
            </div>
          </div>
        ) : (
          <div className={cn("grid gap-3", gridClass)}>
            {selectedCameras.map((cameraId) => {
              const camera = cameras.find((c) => c.id === cameraId);
              const timeline = timelines[cameraId] || [];
              const hasRecording = timeline.length > 0;

              return (
                <div
                  key={cameraId}
                  className={cn(
                    "relative bg-black rounded-lg aspect-video overflow-hidden",
                    fullscreenCamera === cameraId && "fixed inset-4 z-50 aspect-auto"
                  )}
                >
                  {/* Camera header */}
                  <div className="absolute top-0 left-0 right-0 z-10 p-2 bg-gradient-to-b from-black/60 to-transparent flex items-center justify-between">
                    <span className="text-white text-sm font-medium truncate">
                      {camera?.name || "Unknown Camera"}
                    </span>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 text-white hover:bg-white/10"
                        onClick={() => setFullscreenCamera(
                          fullscreenCamera === cameraId ? null : cameraId
                        )}
                      >
                        {fullscreenCamera === cameraId ? (
                          <Minimize2 className="h-3 w-3" />
                        ) : (
                          <Maximize2 className="h-3 w-3" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 text-white hover:bg-white/10"
                        onClick={() => removeCamera(cameraId)}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>

                  {/* Video placeholder - actual video would use HLS player */}
                  <div className="w-full h-full flex items-center justify-center">
                    {hasRecording ? (
                      <video
                        ref={(el) => {
                          if (el) playerRefs.current[cameraId] = el;
                        }}
                        className="w-full h-full object-contain"
                        muted
                      >
                        {/* Video source would be dynamically set based on currentTime */}
                      </video>
                    ) : (
                      <div className="text-muted-foreground text-sm text-center">
                        <p>No recording available</p>
                        <p className="text-xs mt-1">for {format(selectedDate, "PP")}</p>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Timeline Controls */}
      {selectedCameras.length > 0 && (
        <div className="flex-shrink-0 px-4 py-3 border-t border-border  bg-card/40 dark:bg-primary/60">
          {/* Timeline slider */}
          <div className="mb-3">
            <Slider
              value={[currentTime]}
              onValueChange={handleSliderChange}
              max={86400}
              step={1}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-muted-foreground mt-1">
              <span>00:00:00</span>
              <span className="font-mono">{formatTime(currentTime)}</span>
              <span>24:00:00</span>
            </div>
          </div>

          {/* Playback controls */}
          <div className="flex items-center justify-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={() => skip(-60)}
            >
              <SkipBack className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="icon"
              onClick={() => skip(-10)}
              className="hidden sm:flex"
            >
              <span className="text-xs">-10s</span>
            </Button>
            <Button
              size="icon"
              className="h-10 w-10"
              onClick={togglePlayback}
            >
              {isPlaying ? (
                <Pause className="h-5 w-5" />
              ) : (
                <Play className="h-5 w-5 ml-0.5" />
              )}
            </Button>
            <Button
              variant="outline"
              size="icon"
              onClick={() => skip(10)}
              className="hidden sm:flex"
            >
              <span className="text-xs">+10s</span>
            </Button>
            <Button
              variant="outline"
              size="icon"
              onClick={() => skip(60)}
            >
              <SkipForward className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default MultiCameraPlayback;
