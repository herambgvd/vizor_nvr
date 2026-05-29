// =============================================================================
// Timeline Player Component - Recording Playback
// =============================================================================
// Displays a timeline for navigating recorded footage with thumbnails.
// Supports zooming, scrubbing, and playback controls.
// =============================================================================

import React, {
  useState,
  useRef,
  useEffect,
  forwardRef,
  useImperativeHandle,
} from "react";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  ChevronLeft,
  ChevronRight,
  Download,
  ZoomIn,
  ZoomOut,
  Bookmark,
  Maximize,
  RotateCcw,
  Zap,
} from "lucide-react";
import {
  format,
  addHours,
  subHours,
  startOfDay,
  differenceInMinutes,
  differenceInSeconds,
  isWithinInterval,
} from "date-fns";
import { cn } from "../../lib/utils";
import { Button } from "../ui/button";
import { Slider } from "../ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "../ui/tooltip";
import { getVideoUrl, getThumbnailUrl } from "../../api/recordings";

/**
 * Timeline Player Component
 * Video player with timeline scrubbing for recorded footage.
 */
export const TimelinePlayer = forwardRef(
  (
    {
      cameraId,
      recordings = [],
      selectedDate,
      onDateChange,
      onSeek,
      onExport,
      onBookmark,
      className,
      isLoading = false,
    },
    ref,
  ) => {
    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(new Date());
    const [playbackSpeed, setPlaybackSpeed] = useState("1");
    const [zoomLevel, setZoomLevel] = useState("24h"); // Default to 24h to show all recordings
    const [currentRecording, setCurrentRecording] = useState(null);
    const [isDragging, setIsDragging] = useState(false);
    const [hoverTime, setHoverTime] = useState(null);
    const [hoverX, setHoverX] = useState(0);
    const dragStartedRef = useRef(false);
    const timelineRef = useRef(null);
    const videoRef = useRef(null);
    const currentRecordingIdRef = useRef(null);
    const containerRef = useRef(null);
    const seekingRef = useRef(false); // Prevent recursive seek loops

    // Digital zoom state
    const [zoomScale, setZoomScale] = useState(1);
    const [panX, setPanX] = useState(0);
    const [panY, setPanY] = useState(0);
    const [isPanning, setIsPanning] = useState(false);
    const panStartRef = useRef({ x: 0, y: 0 });
    const videoContainerRef = useRef(null);

    // Smart playback state
    const [smartPlayback, setSmartPlayback] = useState(false);

    // Frame-by-frame navigation
    const stepFrame = (direction) => {
      const video = videoRef.current;
      if (!video || !currentRecording) return;
      const fps = currentRecording.fps || 30;
      const step = 1 / fps;
      const wasPaused = video.paused;
      video.pause();
      setIsPlaying(false);
      video.currentTime = Math.max(
        0,
        Math.min(video.duration, video.currentTime + direction * step),
      );
      // Sync timeline
      const recordingStart = new Date(currentRecording.start_time);
      setCurrentTime(
        new Date(recordingStart.getTime() + video.currentTime * 1000),
      );
    };

    // Speed cycle helpers
    const SPEEDS = ["0.5", "1", "2", "4", "8"];
    const cycleSpeed = (dir) => {
      const idx = SPEEDS.indexOf(playbackSpeed);
      const next = Math.max(0, Math.min(SPEEDS.length - 1, idx + dir));
      setPlaybackSpeed(SPEEDS[next]);
    };

    // ── Digital Zoom ─────────────────────────────────────────────────
    const handleWheelZoom = (e) => {
      if (!currentRecording) return;
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      setZoomScale((prev) => {
        const next = Math.max(1, Math.min(5, prev + delta));
        if (next === 1) {
          setPanX(0);
          setPanY(0);
        }
        return next;
      });
    };

    const getClientPos = (e) => {
      if (e.touches && e.touches.length > 0) {
        return { x: e.touches[0].clientX, y: e.touches[0].clientY };
      }
      if (e.changedTouches && e.changedTouches.length > 0) {
        return { x: e.changedTouches[0].clientX, y: e.changedTouches[0].clientY };
      }
      return { x: e.clientX, y: e.clientY };
    };

    const handlePanStart = (e) => {
      if (zoomScale <= 1) return;
      setIsPanning(true);
      const pos = getClientPos(e);
      panStartRef.current = { x: pos.x - panX, y: pos.y - panY };
    };

    const handlePanMove = (e) => {
      if (!isPanning || zoomScale <= 1) return;
      const pos = getClientPos(e);
      const maxPan = (zoomScale - 1) * 200;
      const newX = Math.max(-maxPan, Math.min(maxPan, pos.x - panStartRef.current.x));
      const newY = Math.max(-maxPan, Math.min(maxPan, pos.y - panStartRef.current.y));
      setPanX(newX);
      setPanY(newY);
    };

    const handlePanEnd = () => {
      setIsPanning(false);
    };

    const resetZoom = () => {
      setZoomScale(1);
      setPanX(0);
      setPanY(0);
    };

    // ── Smart Playback ────────────────────────────────────────────────
    const jumpToNextMotion = () => {
      if (!recordings || recordings.length === 0) return;
      const sorted = [...recordings].sort(
        (a, b) => new Date(a.start_time) - new Date(b.start_time),
      );
      const currentIdx = sorted.findIndex((r) => r.id === currentRecording?.id);
      // Find next recording with motion
      const next = sorted.slice(currentIdx + 1).find((r) => r.has_motion);
      if (next) {
        setCurrentTime(new Date(next.start_time));
        setCurrentRecording(next);
        setIsPlaying(true);
      }
    };

    // Override handleEnded for smart playback
    const originalHandleEnded = () => {
      if (smartPlayback) {
        jumpToNextMotion();
        return;
      }
      // Original logic
      if (!recordings || recordings.length === 0) return;
      const sortedRecordings = [...recordings].sort(
        (a, b) => new Date(a.start_time) - new Date(b.start_time),
      );
      const currentIndex = sortedRecordings.findIndex(
        (rec) => rec.id === currentRecording?.id,
      );
      if (currentIndex >= 0 && currentIndex < sortedRecordings.length - 1) {
        const nextRecording = sortedRecordings[currentIndex + 1];
        currentRecordingIdRef.current = null;
        setCurrentTime(new Date(nextRecording.start_time));
        setCurrentRecording(nextRecording);
        setIsPlaying(true);
      } else {
        setIsPlaying(false);
      }
    };

    // Keyboard shortcuts
    useEffect(() => {
      const el = containerRef.current;
      if (!el) return;

      const handleKeyDown = (e) => {
        // Ignore if user is typing in an input
        if (
          e.target.tagName === "INPUT" ||
          e.target.tagName === "TEXTAREA" ||
          e.target.tagName === "SELECT"
        )
          return;

        switch (e.key) {
          case " ":
            e.preventDefault();
            setIsPlaying((p) => !p);
            break;
          case ",":
            e.preventDefault();
            stepFrame(-1);
            break;
          case ".":
            e.preventDefault();
            stepFrame(1);
            break;
          case "ArrowLeft":
            e.preventDefault();
            setCurrentTime((prev) => {
              const t = new Date(prev.getTime() - 10000);
              onSeek?.(t);
              return t;
            });
            break;
          case "ArrowRight":
            e.preventDefault();
            setCurrentTime((prev) => {
              const t = new Date(prev.getTime() + 10000);
              onSeek?.(t);
              return t;
            });
            break;
          case "[":
            e.preventDefault();
            cycleSpeed(-1);
            break;
          case "]":
            e.preventDefault();
            cycleSpeed(1);
            break;
          case "b":
          case "B":
            e.preventDefault();
            onBookmark?.(currentTime, currentRecording);
            break;
          default:
            break;
        }
      };

      el.addEventListener("keydown", handleKeyDown);
      return () => el.removeEventListener("keydown", handleKeyDown);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentTime, currentRecording, playbackSpeed]);

    // Expose seekTo for parent components via ref
    useImperativeHandle(ref, () => ({
      seekTo(info) {
        if (info?.timestamp) {
          setCurrentTime(new Date(info.timestamp));
        }
      },
    }));

    // Calculate timeline range based on zoom level
    const getTimelineRange = () => {
      const hours = {
        "1h": 1,
        "6h": 6,
        "12h": 12,
        "24h": 24,
      }[zoomLevel];

      const start = startOfDay(selectedDate || new Date());
      const end = addHours(start, hours);

      return { start, end, hours };
    };

    const {
      start: timelineStart,
      end: timelineEnd,
      hours: timelineHours,
    } = getTimelineRange();

    // Set initial time to first recording when recordings change
    useEffect(() => {
      if (recordings && recordings.length > 0) {
        // Sort by start_time and set current time to the earliest recording
        const sortedRecordings = [...recordings].sort(
          (a, b) => new Date(a.start_time) - new Date(b.start_time),
        );
        const firstRecording = sortedRecordings[0];
        setCurrentTime(new Date(firstRecording.start_time));
        setCurrentRecording(firstRecording);
      }
    }, [recordings]);

    // Find and set current recording when currentTime changes
    // This allows playback to start as soon as data is available
    useEffect(() => {
      if (!recordings || recordings.length === 0) {
        setCurrentRecording(null);
        return;
      }

      const recording = recordings.find((rec) => {
        const start = new Date(rec.start_time);
        const end = new Date(rec.end_time);
        return isWithinInterval(currentTime, { start, end });
      });

      if (recording && recording.id !== currentRecording?.id) {
        setCurrentRecording(recording);
      } else if (!recording && currentRecording) {
        setCurrentRecording(null);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentTime, recordings]);

    // Generate hour markers
    const hourMarkers = Array.from({ length: timelineHours + 1 }, (_, i) => {
      return addHours(timelineStart, i);
    });

    // Calculate position for a given time
    const getPositionForTime = (time) => {
      const totalMinutes = timelineHours * 60;
      const minutesFromStart = differenceInMinutes(time, timelineStart);
      return Math.max(
        0,
        Math.min(100, (minutesFromStart / totalMinutes) * 100),
      );
    };

    // Calculate time from position (used for dragging and clicking)
    const getTimeFromPosition = (clientX) => {
      if (!timelineRef.current) return null;

      const rect = timelineRef.current.getBoundingClientRect();
      if (!rect.width) return null;
      const clickX = clientX - rect.left;
      const percentage = Math.max(0, Math.min(1, clickX / rect.width));

      const totalMinutes = timelineHours * 60;
      const minutesFromStart = Math.floor(percentage * totalMinutes);
      return addHours(timelineStart, minutesFromStart / 60);
    };

    // Handle timeline click
    const handleTimelineClick = (e) => {
      // Don't handle click if we just finished dragging
      if (dragStartedRef.current) {
        dragStartedRef.current = false;
        return;
      }

      const newTime = getTimeFromPosition(e.clientX);
      if (newTime) {
        setCurrentTime(newTime);
        onSeek?.(newTime);
      }
    };

    // Handle drag start
    const handleMouseDown = (e) => {
      dragStartedRef.current = true;
      setIsDragging(true);
      setIsPlaying(false); // Pause during drag
      const pos = getClientPos(e);
      const newTime = getTimeFromPosition(pos.x);
      if (newTime) {
        setCurrentTime(newTime);
        onSeek?.(newTime);
      }
    };

    // Handle drag move
    const handleMouseMove = (e) => {
      if (!isDragging) return;
      const pos = getClientPos(e);
      const newTime = getTimeFromPosition(pos.x);
      if (newTime) {
        setCurrentTime(newTime);
        onSeek?.(newTime);
      }
    };

    // Handle drag end
    const handleMouseUp = () => {
      setIsDragging(false);
      // dragStartedRef will be reset in handleTimelineClick
    };

    // Handle timeline hover for thumbnail preview
    const handleTimelineHover = (e) => {
      if (isDragging) return;
      const pos = getClientPos(e);
      const t = getTimeFromPosition(pos.x);
      if (t) {
        setHoverTime(t);
        const rect = timelineRef.current?.getBoundingClientRect();
        if (rect) setHoverX(pos.x - rect.left);
      }
    };

    const handleTimelineLeave = () => {
      setHoverTime(null);
    };

    // Add global mouse event listeners for dragging
    useEffect(() => {
      if (isDragging) {
        window.addEventListener("mousemove", handleMouseMove);
        window.addEventListener("mouseup", handleMouseUp);

        return () => {
          window.removeEventListener("mousemove", handleMouseMove);
          window.removeEventListener("mouseup", handleMouseUp);
        };
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isDragging, timelineHours, timelineStart]);

    // Playback controls
    const handlePlayPause = () => {
      setIsPlaying(!isPlaying);
    };

    const handleSkipBack = () => {
      setCurrentTime((prev) => subHours(prev, 1));
    };

    const handleSkipForward = () => {
      setCurrentTime((prev) => addHours(prev, 1));
    };

    // Update video source when recording changes
    useEffect(() => {
      const video = videoRef.current;
      if (!video || !currentRecording) {
        currentRecordingIdRef.current = null;
        return;
      }

      // Only reload video if recording ID actually changed
      if (currentRecordingIdRef.current === currentRecording.id) {
        return;
      }

      currentRecordingIdRef.current = currentRecording.id;
      const videoUrl = getVideoUrl(currentRecording.id);
      video.src = videoUrl;
      video.load();

      // When video loads, seek to the correct position within the recording
      const handleLoadedMetadata = () => {
        if (video && currentRecording) {
          const recordingStart = new Date(currentRecording.start_time);
          const offset = differenceInSeconds(currentTime, recordingStart);

          if (offset > 0 && offset < video.duration) {
            video.currentTime = offset;
          }

          if (isPlaying) {
            video.play().catch((err) => {
              console.error("Video playback error:", err);
              setIsPlaying(false);
            });
          }
        }
      };

      video.addEventListener("loadedmetadata", handleLoadedMetadata);

      return () => {
        video.removeEventListener("loadedmetadata", handleLoadedMetadata);
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentRecording]);

    // Update playback speed
    useEffect(() => {
      if (videoRef.current) {
        videoRef.current.playbackRate = parseFloat(playbackSpeed);
      }
    }, [playbackSpeed]);

    // Handle play/pause state
    useEffect(() => {
      if (videoRef.current && currentRecording) {
        if (isPlaying) {
          videoRef.current.play().catch((err) => {
            console.error("Video playback error:", err);
            setIsPlaying(false);
          });
        } else {
          videoRef.current.pause();
        }
      }
    }, [isPlaying, currentRecording]);

    // Seek video when currentTime changes but recording stays the same
    useEffect(() => {
      if (videoRef.current && currentRecording && videoRef.current.duration) {
        const recordingStart = new Date(currentRecording.start_time);
        const offset = differenceInSeconds(currentTime, recordingStart);

        // Only seek if the offset is significantly different from current playback position
        const currentPosition = videoRef.current.currentTime;
        const difference = Math.abs(currentPosition - offset);

        // Only seek if difference is more than 1 second (to avoid constant seeking)
        // and we're not already handling a seek operation
        if (
          !seekingRef.current &&
          difference > 1 &&
          offset >= 0 &&
          offset < videoRef.current.duration
        ) {
          seekingRef.current = true;
          videoRef.current.currentTime = offset;
          // Reset seeking flag after a short delay to allow timeupdate to settle
          setTimeout(() => {
            seekingRef.current = false;
          }, 100);
        }
      }
    }, [currentTime, currentRecording]);

    // Update currentTime based on video playback position
    useEffect(() => {
      const video = videoRef.current;
      if (!video || !currentRecording) return;

      const handleTimeUpdate = () => {
        // Skip timeupdate when we're programmatically seeking to avoid loops
        if (seekingRef.current) return;

        if (video && currentRecording) {
          const recordingStart = new Date(currentRecording.start_time);
          const videoPosition = video.currentTime;
          const newTime = new Date(
            recordingStart.getTime() + videoPosition * 1000,
          );

          // Only update if different to avoid triggering seek useEffect
          if (Math.abs(differenceInSeconds(newTime, currentTime)) > 0.5) {
            setCurrentTime(newTime);
          }
        }
      };

      // Handle video ended - move to next recording
      const handleEnded = originalHandleEnded;

      video.addEventListener("timeupdate", handleTimeUpdate);
      video.addEventListener("ended", handleEnded);

      return () => {
        video.removeEventListener("timeupdate", handleTimeUpdate);
        video.removeEventListener("ended", handleEnded);
      };
    }, [currentRecording, currentTime, recordings, smartPlayback]);

    return (
      <div
        ref={containerRef}
        tabIndex={0}
        data-testid="timeline-player"
        className={cn(
          "bg-[#0a0a0a] border border-[#1f1f1f] rounded-lg overflow-hidden outline-none focus:ring-2 focus:ring-teal-500/40",
          className,
        )}
      >
        {/* Video Display Area */}
        <div
          ref={videoContainerRef}
          className="w-full bg-black relative overflow-hidden cursor-crosshair"
          style={{ height: "60vh", maxHeight: "720px" }}
          onWheel={handleWheelZoom}
          onMouseDown={handlePanStart}
          onMouseMove={handlePanMove}
          onMouseUp={handlePanEnd}
          onMouseLeave={handlePanEnd}
          onTouchStart={handlePanStart}
          onTouchMove={handlePanMove}
          onTouchEnd={handlePanEnd}
        >
          {/* Loading Overlay */}
          {isLoading && recordings.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/80 z-20">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white mx-auto mb-4"></div>
                <p className="text-white text-lg">Loading recordings...</p>
              </div>
            </div>
          )}

          {currentRecording ? (
            <>
              <video
                ref={videoRef}
                className="w-full h-full object-contain transition-transform"
                controls={false}
                preload="auto"
                style={{
                  transform: `scale(${zoomScale}) translate(${panX / zoomScale}px, ${panY / zoomScale}px)`,
                  transformOrigin: "center center",
                }}
              />

              {/* Time Overlay */}
              <div className="absolute top-4 left-4 bg-black/60 px-3 py-1 rounded text-white text-sm">
                {format(currentTime, "PPpp")}
              </div>

              {/* Recording Info */}
              <div className="absolute bottom-4 left-4 bg-black/60 px-3 py-1 rounded text-white text-xs">
                Recording: {currentRecording.id.substring(0, 8)}...
              </div>

              {/* Playback Speed Indicator */}
              {playbackSpeed !== "1" && (
                <div className="absolute top-4 right-4 bg-black/60 px-3 py-1 rounded text-white text-sm">
                  {playbackSpeed}x
                </div>
              )}

              {/* Zoom Level Indicator */}
              {zoomScale > 1 && (
                <div className="absolute top-4 right-16 bg-black/60 px-3 py-1 rounded text-white text-sm flex items-center gap-2">
                  <Maximize className="h-3 w-3" />
                  {zoomScale.toFixed(1)}x
                </div>
              )}
            </>
          ) : recordings.length > 0 ? (
            <div className="absolute inset-0 flex items-center justify-center text-white text-center">
              <div>
                <p className="text-lg">No recording at current time</p>
                <p className="text-sm text-muted-foreground mt-2">
                  Seek to a time with available recordings
                </p>
                <p className="text-xs text-muted-foreground mt-2">
                  {format(currentTime, "PPpp")}
                </p>
              </div>
            </div>
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-center">
              <div>
                <p>No recordings available</p>
                <p className="text-sm mt-2">Select a date with recordings</p>
              </div>
            </div>
          )}
        </div>

        {/* Playback Controls */}
        <div className="px-4 py-3 border-t border-[#1f1f1f] flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <TooltipProvider>
              {/* Skip Back */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    data-testid="skip-back-btn"
                    variant="ghost"
                    size="icon"
                    onClick={handleSkipBack}
                  >
                    <SkipBack className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Skip Back 1 Hour</TooltipContent>
              </Tooltip>

              {/* Play/Pause */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    data-testid="play-pause-btn"
                    variant="default"
                    size="icon"
                    onClick={handlePlayPause}
                    className="bg-primary hover:bg-primary/60"
                  >
                    {isPlaying ? (
                      <Pause className="h-4 w-4" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{isPlaying ? "Pause" : "Play"}</TooltipContent>
              </Tooltip>

              {/* Skip Forward */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    data-testid="skip-forward-btn"
                    variant="ghost"
                    size="icon"
                    onClick={handleSkipForward}
                  >
                    <SkipForward className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Skip Forward 1 Hour</TooltipContent>
              </Tooltip>

              {/* Separator */}
              <div className="w-px h-5 bg-[#1f1f1f] mx-1" />

              {/* Frame Back */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    data-testid="frame-back-btn"
                    variant="ghost"
                    size="icon"
                    onClick={() => stepFrame(-1)}
                    disabled={!currentRecording}
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Previous Frame (,)</TooltipContent>
              </Tooltip>

              {/* Frame Forward */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    data-testid="frame-forward-btn"
                    variant="ghost"
                    size="icon"
                    onClick={() => stepFrame(1)}
                    disabled={!currentRecording}
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Next Frame (.)</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          {/* Current Time Display */}
          <div className="flex-1 text-center">
            <span className="text-sm font-mono text-zinc-400">
              {format(currentTime, "HH:mm:ss")}
            </span>
          </div>

          {/* Playback Speed */}
          <Select value={playbackSpeed} onValueChange={setPlaybackSpeed}>
            <SelectTrigger data-testid="playback-speed-select" className="w-20">
              <SelectValue placeholder="Speed" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0.5">0.5x</SelectItem>
              <SelectItem value="1">1x</SelectItem>
              <SelectItem value="2">2x</SelectItem>
              <SelectItem value="4">4x</SelectItem>
              <SelectItem value="8">8x</SelectItem>
            </SelectContent>
          </Select>

          {/* Smart Playback + Zoom Reset + Bookmark + Export */}
          <div className="flex items-center gap-2">
            <Button
              variant={smartPlayback ? "default" : "outline"}
              size="sm"
              onClick={() => setSmartPlayback((p) => !p)}
              title="Smart Playback: skip to motion events"
              className={smartPlayback ? "bg-amber-600 hover:bg-amber-700" : ""}
            >
              <Zap className="h-4 w-4 mr-2" />
              Smart
            </Button>
            {zoomScale > 1 && (
              <Button
                variant="outline"
                size="sm"
                onClick={resetZoom}
                title="Reset zoom"
              >
                <RotateCcw className="h-4 w-4 mr-2" />
                Reset
              </Button>
            )}
            <Button
              data-testid="bookmark-btn"
              variant="outline"
              size="sm"
              onClick={() => onBookmark?.(currentTime, currentRecording)}
              disabled={!currentRecording}
              title="Bookmark (B)"
            >
              <Bookmark className="h-4 w-4 mr-2" />
              Bookmark
            </Button>
            <Button
              data-testid="export-clip-btn"
              variant="outline"
              size="sm"
              onClick={onExport}
            >
              <Download className="h-4 w-4 mr-2" />
              Export
            </Button>
          </div>
        </div>

        {/* Timeline */}
        <div className="px-4 pb-4">
          {/* Zoom Controls */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setZoomLevel((prev) => {
                    const levels = ["1h", "6h", "12h", "24h"];
                    const idx = levels.indexOf(prev);
                    return levels[Math.max(0, idx - 1)];
                  })
                }
              >
                <ZoomIn className="h-4 w-4" />
              </Button>
              <span className="text-xs text-muted-foreground">{zoomLevel}</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setZoomLevel((prev) => {
                    const levels = ["1h", "6h", "12h", "24h"];
                    const idx = levels.indexOf(prev);
                    return levels[Math.min(levels.length - 1, idx + 1)];
                  })
                }
              >
                <ZoomOut className="h-4 w-4" />
              </Button>
            </div>

            <span className="text-xs text-muted-foreground">
              {format(selectedDate || new Date(), "EEEE, MMMM d, yyyy")}
            </span>
          </div>

          {/* Timeline Bar */}
          <div
            ref={timelineRef}
            data-testid="timeline-bar"
            className="relative h-16 bg-[#141414] rounded-lg cursor-pointer overflow-hidden select-none"
            onClick={handleTimelineClick}
            onMouseDown={handleMouseDown}
            onMouseMove={handleTimelineHover}
            onMouseLeave={handleTimelineLeave}
            onTouchStart={handleMouseDown}
            onTouchMove={handleTimelineHover}
            onTouchEnd={handleTimelineLeave}
          >
            {/* Thumbnail hover preview */}
            {hoverTime && cameraId && !isDragging && (
              <div
                className="absolute z-30 bottom-full mb-2 pointer-events-none"
                style={{ left: `${hoverX}px`, transform: "translateX(-50%)" }}
              >
                <div className="bg-black rounded shadow-lg overflow-hidden">
                  <img
                    src={getThumbnailUrl(cameraId, hoverTime.toISOString())}
                    alt=""
                    className="w-40 h-auto"
                    onError={(e) => {
                      e.target.style.display = "none";
                    }}
                  />
                  <div className="text-center text-[10px] text-white bg-black/80 px-2 py-0.5">
                    {format(hoverTime, "HH:mm:ss")}
                  </div>
                </div>
              </div>
            )}
            {/* Hour Markers */}
            <div className="absolute inset-0 flex">
              {hourMarkers.map((hour, index) => (
                <div
                  key={index}
                  className="flex-1 border-l border-[#1f1f1f] first:border-l-0"
                >
                  <span className="text-[10px] text-muted-foreground pl-1">
                    {format(hour, "HH:mm")}
                  </span>
                </div>
              ))}
            </div>

            {/* Recording Segments */}
            {recordings.map((rec) => {
              const startPos = getPositionForTime(new Date(rec.start_time));
              const endPos = getPositionForTime(new Date(rec.end_time));
              const width = endPos - startPos;

              if (width <= 0) return null;

              return (
                <div key={rec.id} className="absolute top-8 bottom-2">
                  {/* Base segment bar */}
                  <div
                    className={cn(
                      "absolute top-0 bottom-0 rounded border",
                      rec.has_motion
                        ? "bg-amber-500/40 border-amber-500"
                        : "bg-emerald-500/30 border-emerald-500"
                    )}
                    style={{
                      left: `${startPos}%`,
                      width: `${width}%`,
                    }}
                    title={rec.has_motion ? "Motion detected" : "Normal recording"}
                  />
                  {/* Event markers (motion dots) */}
                  {rec.event_markers?.map((marker, idx) => {
                    if (marker.type !== "motion") return null;
                    const markerTime = new Date(
                      new Date(rec.start_time).getTime() + marker.offset_seconds * 1000
                    );
                    const markerPos = getPositionForTime(markerTime);
                    return (
                      <div
                        key={idx}
                        className="absolute top-0 w-1.5 h-1.5 bg-red-500 rounded-full z-10"
                        style={{ left: `${markerPos}%`, transform: "translateX(-50%)" }}
                        title={`Motion at ${marker.offset_seconds}s (score: ${marker.score})`}
                      />
                    );
                  })}
                </div>
              );
            })}

            {/* Current Position Indicator */}
            <div
              className={cn(
                "absolute top-0 bottom-0 w-0.5 bg-red-500 z-10 transition-opacity",
                isDragging && "opacity-80",
              )}
              style={{ left: `${getPositionForTime(currentTime)}%` }}
            >
              <div
                className={cn(
                  "absolute -top-1 left-1/2 -translate-x-1/2 w-3 h-3 bg-red-500 rounded-full cursor-grab transition-transform hover:scale-125",
                  isDragging && "cursor-grabbing scale-125",
                )}
              />
            </div>
          </div>
        </div>
      </div>
    );
  },
);

TimelinePlayer.displayName = "TimelinePlayer";

export default TimelinePlayer;
