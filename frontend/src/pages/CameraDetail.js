// =============================================================================
// Camera Detail — Live view, recordings, and config for a single camera
// =============================================================================

import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format, startOfDay } from "date-fns";
import {
  ArrowLeft,
  Video,
  Film,
  SlidersHorizontal,
  Play,
  Square,
  RefreshCw,
  Volume2,
  VolumeX,
  Download,
  Trash2,
  Camera,
  ChevronLeft,
  ChevronRight,
  Calendar as CalendarIcon,
  CheckSquare,
  Square as SquareIcon,
  HardDrive,
  Search,
  Maximize2,
  Radio,
  ImageIcon,
  Sparkles,
} from "lucide-react";
import {
  getCamera,
  getStreamUrls,
  startRecording,
  stopRecording,
  getCameraSnapshots,
} from "../api/cameras";
import {
  getRecordings,
  deleteRecording,
  bulkDeleteRecordings,
  getRecordingDownloadUrl,
  getTimeline,
  getRecordingDates,
  getPlaybackInfo,
  exportClip,
} from "../api/recordings";
import { createBookmark } from "../api/bookmarks";
import { WebRTCPlayer } from "../components/nvr/WebRTCPlayer";
import { PTZControls } from "../components/nvr/PTZControls";
import { StatusBadge } from "../components/nvr/StatusBadge";
import {
  TimelinePlayer,
  RecordingCalendar,
  ClipBuilder,
  CameraSettingsPanel,
  LinkageRuleBuilder,
  ONVIFSettingsPanel,
} from "../components/nvr";
import CameraAITab from "../components/camera/CameraAITab";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/ui/alert-dialog";
import { Calendar } from "../components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "../components/ui/popover";
import { cn } from "../lib/utils";
import { toast } from "sonner";
import { usePermissions } from "../hooks/usePermissions";

const PAGE_SIZE = 25;

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

const formatDuration = (seconds) => {
  if (!seconds) return "-";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
};

// =============================================================================
// Main Camera Detail Page
// =============================================================================

const CameraDetail = () => {
  const { cameraId } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialTab = searchParams.get("tab") || "live";

  const { data: camera, isLoading } = useQuery({
    queryKey: ["camera", cameraId],
    queryFn: () => getCamera(cameraId),
    refetchInterval: 10000,
  });

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <RefreshCw className="h-8 w-8 text-muted-foreground animate-spin" />
      </div>
    );
  }

  if (!camera) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <Camera className="h-12 w-12 text-slate-300 mx-auto mb-4" />
          <p className="text-muted-foreground text-lg mb-4">Camera not found</p>
          <Button variant="outline" onClick={() => navigate("/cameras")}>
            Back to Cameras
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-4 md:px-8 pt-4 md:pt-6 pb-3 md:pb-4 border-b border-border ">
        <div className="flex items-center gap-3 mb-1">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => navigate("/cameras")}
            className="h-8 w-8"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <div>
              <div className="flex items-center gap-2">
                <h1
                  className="text-2xl md:text-3xl font-bold text-white  tracking-tight truncate"
                  style={{ fontFamily: "Manrope, sans-serif" }}
                >
                  {camera.name}
                </h1>
                <StatusBadge status={camera.status} />
                {camera.is_recording && (
                  <div className="flex items-center gap-1 bg-red-50 text-red-600 px-2 py-0.5 rounded-full text-xs font-medium">
                    <div className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
                    REC
                  </div>
                )}
              </div>
              <p className="text-muted-foreground dark:text-muted-foreground text-sm truncate">
                {camera.location || camera.main_stream_url}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs
        defaultValue={initialTab}
        className="flex-1 flex flex-col overflow-hidden"
      >
        <div className="flex-shrink-0 px-4 md:px-8 border-b border-border ">
          <TabsList className="h-auto bg-transparent gap-0 p-0">
            <TabsTrigger
              value="live"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <Video className="h-4 w-4" />
              Live View
            </TabsTrigger>
            <TabsTrigger
              value="recordings"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <Film className="h-4 w-4" />
              Recordings
            </TabsTrigger>
            <TabsTrigger
              value="config"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <SlidersHorizontal className="h-4 w-4" />
              Config
            </TabsTrigger>
            <TabsTrigger
              value="onvif"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <Radio className="h-4 w-4" />
              ONVIF
            </TabsTrigger>
            <TabsTrigger
              value="snapshots"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <ImageIcon className="h-4 w-4" />
              Snapshots
            </TabsTrigger>
            <TabsTrigger
              value="ai"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <Sparkles className="h-4 w-4" />
              AI Scenarios
            </TabsTrigger>
          </TabsList>
        </div>

        <div className="flex-1 overflow-y-auto">
          <TabsContent value="live" className="m-0 h-full">
            <LiveViewTab camera={camera} cameraId={cameraId} />
          </TabsContent>
          <TabsContent value="recordings" className="m-0">
            <RecordingsTab cameraId={cameraId} camera={camera} />
          </TabsContent>
          <TabsContent value="config" className="m-0">
            <ConfigTab cameraId={cameraId} />
          </TabsContent>
          <TabsContent value="onvif" className="m-0">
            <div className="p-4 md:p-6 max-w-4xl">
              <ONVIFSettingsPanel cameraId={cameraId} />
            </div>
          </TabsContent>
          <TabsContent value="snapshots" className="m-0">
            <SnapshotsTab cameraId={cameraId} />
          </TabsContent>
          <TabsContent value="ai" className="m-0">
            <CameraAITab cameraId={cameraId} />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
};

// =============================================================================
// Live View Tab
// =============================================================================

const LiveViewTab = ({ camera, cameraId }) => {
  const qc = useQueryClient();
  const [isMuted, setIsMuted] = useState(true);
  const [streamReady, setStreamReady] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [liveStreamId, setLiveStreamId] = useState(null);

  const isOnline = camera.status === "online";

  useEffect(() => {
    let mounted = true;
    const register = async () => {
      if (!camera || camera.status !== "online" || streamReady) return;
      setRegistering(true);
      try {
        const streamUrls = await getStreamUrls(cameraId);
        if (mounted) {
          setLiveStreamId(streamUrls.live_stream_id || cameraId);
          setStreamReady(true);
        }
      } catch {
        if (mounted) {
          toast.error("Failed to start stream");
          setLiveStreamId(cameraId);
        }
      } finally {
        if (mounted) setRegistering(false);
      }
    };
    register();
    return () => {
      mounted = false;
    };
  }, [camera, cameraId, streamReady]);

  const handleRecordingToggle = async () => {
    try {
      if (camera.is_recording) {
        await stopRecording(cameraId);
        toast.success("Recording stopped");
      } else {
        await startRecording(cameraId);
        toast.success("Recording started");
      }
      qc.invalidateQueries({ queryKey: ["camera", cameraId] });
      qc.invalidateQueries({ queryKey: ["cameras"] });
    } catch {
      toast.error(
        `Failed to ${camera.is_recording ? "stop" : "start"} recording`,
      );
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-2 flex-wrap">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setIsMuted(!isMuted)}
        >
          {isMuted ? (
            <VolumeX className="h-4 w-4 mr-1" />
          ) : (
            <Volume2 className="h-4 w-4 mr-1" />
          )}
          {isMuted ? "Unmute" : "Mute"}
        </Button>
        <Button
          variant={camera.is_recording ? "destructive" : "default"}
          size="sm"
          onClick={handleRecordingToggle}
          disabled={!isOnline}
        >
          {camera.is_recording ? (
            <>
              <Square className="h-4 w-4 mr-1" /> Stop Recording
            </>
          ) : (
            <>
              <Video className="h-4 w-4 mr-1" /> Start Recording
            </>
          )}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => window.open(`/live/${cameraId}`, "_blank")}
        >
          <Maximize2 className="h-4 w-4 mr-1" />
          Fullscreen
        </Button>
      </div>

      {/* Video player */}
      <div className="relative bg-black rounded-lg overflow-hidden aspect-video max-h-[60vh]">
        {isOnline && streamReady && !registering && liveStreamId ? (
          <>
            <WebRTCPlayer
              streamId={liveStreamId}
              cameraId={cameraId}
              autoPlay
              muted={isMuted}
              controls={false}
              className="w-full h-full object-contain"
            />
            {camera.ptz_capable && <PTZControls cameraId={cameraId} />}
          </>
        ) : (
          <div className="w-full h-full flex items-center justify-center text-white min-h-[200px]">
            {registering ? (
              <div className="text-center">
                <RefreshCw className="h-10 w-10 mx-auto mb-2 animate-spin opacity-70" />
                <p className="text-sm">Starting stream…</p>
              </div>
            ) : !isOnline ? (
              <div className="text-center">
                <Video className="h-10 w-10 mx-auto mb-2 opacity-50" />
                <p className="text-sm">Camera offline</p>
              </div>
            ) : (
              <RefreshCw className="h-10 w-10 animate-spin opacity-70" />
            )}
          </div>
        )}
      </div>

      {/* Camera info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <InfoCard label="Status" value={camera.status} />
        <InfoCard label="Resolution" value={camera.resolution || "-"} />
        <InfoCard label="Location" value={camera.location || "-"} />
        <InfoCard label="PTZ" value={camera.ptz_capable ? "Yes" : "No"} />
      </div>
    </div>
  );
};

const InfoCard = ({ label, value }) => (
  <div className="bg-card/40 dark:bg-primary/60 rounded-lg p-3">
    <p className="text-xs text-muted-foreground dark:text-muted-foreground">{label}</p>
    <p className="text-sm font-medium text-white  capitalize">
      {value}
    </p>
  </div>
);

// =============================================================================
// Recordings Tab — Recordings list + Playback player for this camera
// =============================================================================

const RecordingsTab = ({ cameraId, camera }) => {
  const qc = useQueryClient();
  const playerRef = useRef(null);

  // Playback state
  const [selectedDate, setSelectedDate] = useState(startOfDay(new Date()));
  const [availableDates, setAvailableDates] = useState([]);

  // Recordings list state
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [startDateFilter, setStartDateFilter] = useState("");
  const [endDateFilter, setEndDateFilter] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [showBulkDelete, setShowBulkDelete] = useState(false);

  // View mode: "playback" or "list"
  const [viewMode, setViewMode] = useState("playback");

  // --- Playback queries ---
  const { data: recordingDates } = useQuery({
    queryKey: ["recordingDates", cameraId],
    queryFn: () => getRecordingDates(cameraId),
    enabled: !!cameraId,
  });

  const { data: timeline = [], isLoading: timelineLoading } = useQuery({
    queryKey: ["timeline", cameraId, selectedDate?.toISOString()],
    queryFn: () => getTimeline(cameraId, selectedDate?.toISOString()),
    enabled: !!cameraId && !!selectedDate,
    staleTime: 30000,
    select: (data) => {
      const segments = Array.isArray(data) ? data : (data?.segments ?? []);
      return segments.map((seg) => ({
        ...seg,
        start_time: seg.start_time || seg.start,
        end_time: seg.end_time || seg.end,
        id: seg.recording_id || seg.id,
      }));
    },
  });

  // --- Recordings list queries ---
  const listParams = useMemo(() => {
    const p = { page, page_size: PAGE_SIZE, camera_id: cameraId };
    if (search.trim()) p.search = search.trim();
    if (startDateFilter) p.start_date = startDateFilter;
    if (endDateFilter) p.end_date = endDateFilter;
    return p;
  }, [page, cameraId, search, startDateFilter, endDateFilter]);

  const { data: recordingsData, isLoading: recordingsLoading } = useQuery({
    queryKey: ["recordings", listParams],
    queryFn: () => getRecordings(listParams),
    enabled: viewMode === "list",
  });

  const recordings = recordingsData?.recordings ?? recordingsData?.items ?? [];
  const totalPages = recordingsData?.total_pages ?? 1;

  // Effects
  useEffect(() => {
    if (recordingDates?.dates) {
      setAvailableDates(recordingDates.dates.map((d) => new Date(d)));
    }
  }, [recordingDates]);

  // Seek handler
  const handleSeek = useCallback(
    async (timestamp) => {
      try {
        const info = await getPlaybackInfo(cameraId, {
          timestamp: new Date(timestamp).toISOString(),
        });
        playerRef.current?.seekTo?.(info);
      } catch {
        /* ignore */
      }
    },
    [cameraId],
  );

  // Export
  const exportMutation = useMutation({
    mutationFn: (data) => exportClip(data),
    onSuccess: (result) =>
      toast.success(`Export started — ${result.export_id || "processing"}`),
    onError: (e) => toast.error(e.response?.data?.detail || "Export failed"),
  });

  const handleExport = () => {
    const start = startOfDay(selectedDate);
    const end = new Date(start);
    end.setHours(23, 59, 59, 999);
    exportMutation.mutate({
      camera_id: cameraId,
      start_time: start.toISOString(),
      end_time: end.toISOString(),
    });
  };

  // Bookmark
  const bookmarkMutation = useMutation({
    mutationFn: (data) => createBookmark(data),
    onSuccess: () => toast.success("Bookmark saved"),
    onError: (e) => toast.error(e.response?.data?.detail || "Bookmark failed"),
  });

  const handleBookmark = useCallback(
    (timestamp) => {
      if (!cameraId) return;
      bookmarkMutation.mutate({
        camera_id: cameraId,
        timestamp: timestamp ?? 0,
      });
    },
    [cameraId, bookmarkMutation],
  );

  // Delete mutations
  const deleteMut = useMutation({
    mutationFn: deleteRecording,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recordings"] });
      toast.success("Recording deleted");
      setDeleteTarget(null);
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Delete failed"),
  });

  const bulkDeleteMut = useMutation({
    mutationFn: bulkDeleteRecordings,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recordings"] });
      toast.success(`${selected.size} recordings deleted`);
      setSelected(new Set());
      setShowBulkDelete(false);
    },
    onError: (e) =>
      toast.error(e.response?.data?.detail || "Bulk delete failed"),
  });

  // Date navigation
  const handlePrevDay = () => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() - 1);
    setSelectedDate(startOfDay(d));
  };
  const handleNextDay = () => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + 1);
    if (d <= new Date()) setSelectedDate(startOfDay(d));
  };

  const hasRecordings = (date) =>
    availableDates.some((d) => d.toDateString() === date.toDateString());

  // Selection helpers
  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };
  const toggleSelectAll = () => {
    if (selected.size === recordings.length) setSelected(new Set());
    else setSelected(new Set(recordings.map((r) => r.id)));
  };

  const handleDownload = async (rec) => {
    try {
      const url = await getRecordingDownloadUrl(rec.id);
      const link = document.createElement("a");
      link.href = typeof url === "string" ? url : url.url;
      link.download = rec.filename || `recording_${rec.id}.mp4`;
      link.click();
    } catch {
      toast.error("Download failed");
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-4">
      {/* View mode toggle */}
      <div className="flex items-center gap-2">
        <Button
          variant={viewMode === "playback" ? "default" : "outline"}
          size="sm"
          onClick={() => setViewMode("playback")}
        >
          <Play className="h-4 w-4 mr-1" />
          Timeline Playback
        </Button>
        <Button
          variant={viewMode === "list" ? "default" : "outline"}
          size="sm"
          onClick={() => setViewMode("list")}
        >
          <Film className="h-4 w-4 mr-1" />
          Recording Files
        </Button>
      </div>

      {viewMode === "playback" ? (
        /* ---- Timeline Playback ---- */
        <div className="space-y-4">
          {/* Date controls */}
          <div className="flex items-center gap-2 flex-wrap">
            <Button variant="outline" size="icon" onClick={handlePrevDay}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  className="w-40 sm:w-48 justify-start text-sm"
                >
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
                  modifiers={{ hasRecording: availableDates }}
                  modifiersStyles={{
                    hasRecording: {
                      fontWeight: "bold",
                      backgroundColor: "rgb(236, 253, 245)",
                      color: "rgb(5, 150, 105)",
                    },
                  }}
                  initialFocus
                />
              </PopoverContent>
            </Popover>
            <Button
              variant="outline"
              size="icon"
              onClick={handleNextDay}
              disabled={
                selectedDate.toDateString() === new Date().toDateString()
              }
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={timeline.length === 0 || exportMutation.isPending}
            >
              <Download className="h-4 w-4 mr-2" />
              Export Day
            </Button>
          </div>

          {/* Player + sidebar */}
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="flex-1 min-w-0">
              <TimelinePlayer
                ref={playerRef}
                cameraId={cameraId}
                recordings={timeline}
                selectedDate={selectedDate}
                onDateChange={(d) => setSelectedDate(startOfDay(d))}
                onSeek={handleSeek}
                onExport={handleExport}
                onBookmark={handleBookmark}
                isLoading={timelineLoading}
              />
            </div>
            <div className="lg:w-64 flex-shrink-0 space-y-4">
              <RecordingCalendar
                cameraId={cameraId}
                selectedDate={selectedDate}
                onSelectDate={(d) => setSelectedDate(startOfDay(d))}
              />
              <ClipBuilder cameraId={cameraId} currentTime={selectedDate} />
            </div>
          </div>
        </div>
      ) : (
        /* ---- Recording Files List ---- */
        <div className="space-y-4">
          {/* Filters */}
          <div className="flex flex-wrap items-end gap-3">
            <div className="relative w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search recordings…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                className="pl-10"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">From</label>
              <Input
                type="date"
                value={startDateFilter}
                onChange={(e) => {
                  setStartDateFilter(e.target.value);
                  setPage(1);
                }}
                className="w-40"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground block mb-1">To</label>
              <Input
                type="date"
                value={endDateFilter}
                onChange={(e) => {
                  setEndDateFilter(e.target.value);
                  setPage(1);
                }}
                className="w-40"
              />
            </div>
          </div>

          {/* Bulk actions */}
          {selected.size > 0 && (
            <div className="flex items-center gap-3 bg-card/40 dark:bg-primary/60 rounded-lg p-3">
              <span className="text-sm text-zinc-400 ">
                {selected.size} selected
              </span>
              <Button
                variant="destructive"
                size="sm"
                onClick={() => setShowBulkDelete(true)}
              >
                <Trash2 className="h-4 w-4 mr-1" />
                Delete Selected
              </Button>
            </div>
          )}

          {/* Table */}
          <div className="bg-card dark:bg-primary border border-border  rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-card/40 dark:bg-primary/60 border-b border-border ">
                <tr>
                  <th className="w-10 px-3 py-3">
                    <button
                      onClick={toggleSelectAll}
                      className="text-muted-foreground hover:text-zinc-400"
                    >
                      {selected.size === recordings.length &&
                      recordings.length > 0 ? (
                        <CheckSquare className="h-4 w-4" />
                      ) : (
                        <SquareIcon className="h-4 w-4" />
                      )}
                    </button>
                  </th>
                  <th className="text-left px-3 py-3 text-zinc-400  font-medium">
                    Date
                  </th>
                  <th className="text-left px-3 py-3 text-zinc-400  font-medium">
                    Duration
                  </th>
                  <th className="text-left px-3 py-3 text-zinc-400  font-medium hidden md:table-cell">
                    Size
                  </th>
                  <th className="text-right px-3 py-3 text-zinc-400  font-medium">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {recordingsLoading ? (
                  <tr>
                    <td
                      colSpan={5}
                      className="text-center py-12 text-muted-foreground"
                    >
                      Loading…
                    </td>
                  </tr>
                ) : recordings.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="text-center py-12">
                      <HardDrive className="h-10 w-10 text-slate-300 mx-auto mb-3" />
                      <p className="text-muted-foreground">No recordings found</p>
                    </td>
                  </tr>
                ) : (
                  recordings.map((rec) => (
                    <tr
                      key={rec.id}
                      className="border-b border-slate-100  last:border-0 hover:bg-card/40/50 dark:hover:bg-primary/60/50"
                    >
                      <td className="px-3 py-3">
                        <button
                          onClick={() => toggleSelect(rec.id)}
                          className="text-muted-foreground hover:text-zinc-400"
                        >
                          {selected.has(rec.id) ? (
                            <CheckSquare className="h-4 w-4 text-white" />
                          ) : (
                            <SquareIcon className="h-4 w-4" />
                          )}
                        </button>
                      </td>
                      <td className="px-3 py-3 text-white ">
                        {rec.start_time
                          ? format(
                              new Date(rec.start_time),
                              "MMM d, yyyy HH:mm:ss",
                            )
                          : "-"}
                      </td>
                      <td className="px-3 py-3 text-zinc-400 ">
                        {formatDuration(rec.duration)}
                      </td>
                      <td className="px-3 py-3 text-zinc-400  hidden md:table-cell">
                        {formatBytes(rec.file_size)}
                      </td>
                      <td className="px-3 py-3 text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => handleDownload(rec)}
                          >
                            <Download className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-red-500"
                            onClick={() => setDeleteTarget(rec)}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Page {page} of {totalPages}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  <ChevronLeft className="h-4 w-4 mr-1" /> Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage(page + 1)}
                >
                  Next <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            </div>
          )}

          {/* Delete confirmation */}
          <AlertDialog
            open={!!deleteTarget}
            onOpenChange={() => setDeleteTarget(null)}
          >
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Delete Recording</AlertDialogTitle>
                <AlertDialogDescription>
                  This will permanently delete this recording file. This action
                  cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => deleteMut.mutate(deleteTarget?.id)}
                  className="bg-destructive hover:bg-destructive/90"
                >
                  Delete
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>

          {/* Bulk delete confirmation */}
          <AlertDialog open={showBulkDelete} onOpenChange={setShowBulkDelete}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>
                  Delete {selected.size} Recordings
                </AlertDialogTitle>
                <AlertDialogDescription>
                  This will permanently delete the selected recordings. This
                  action cannot be undone.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => bulkDeleteMut.mutate({ ids: [...selected] })}
                  className="bg-destructive hover:bg-destructive/90"
                >
                  Delete All
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// Config Tab — Camera settings + linkage rules
// =============================================================================

const ConfigTab = ({ cameraId }) => {
  const { canManage } = usePermissions();
  const GO2RTC_URL = process.env.REACT_APP_GO2RTC_URL || "http://localhost:1984";
  const snapshotUrl = `${GO2RTC_URL}/api/frame.jpeg?src=${encodeURIComponent(cameraId)}`;

  return (
    <div className="p-4 md:p-6 space-y-8 max-w-4xl">
      {canManage ? (
        <>
          <CameraSettingsPanel cameraId={cameraId} snapshotUrl={snapshotUrl} />
          <div className="border-t border-border  pt-6">
            <LinkageRuleBuilder />
          </div>
        </>
      ) : (
        <div className="text-center py-12">
          <SlidersHorizontal className="h-10 w-10 text-slate-300 mx-auto mb-3" />
          <p className="text-muted-foreground">
            You don't have permission to configure cameras.
          </p>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// Snapshots Tab — Browse periodic and event-triggered snapshots
// =============================================================================

const SnapshotsTab = ({ cameraId }) => {
  const [trigger, setTrigger] = useState("all");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 24;

  const { data, isLoading } = useQuery({
    queryKey: ["snapshots", cameraId, trigger, page],
    queryFn: () =>
      getCameraSnapshots(cameraId, {
        trigger: trigger === "all" ? undefined : trigger,
        page,
        page_size: PAGE_SIZE,
      }),
    keepPreviousData: true,
  });

  const snapshots = data?.snapshots ?? data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  const BACKEND_URL = process.env.REACT_APP_API_URL || "http://localhost:8000";

  const getImageUrl = (filePath) => {
    if (!filePath) return null;
    // file_path is an absolute server path; serve via /thumbnails/ static mount
    const filename = filePath.split("/").pop();
    return `${BACKEND_URL}/thumbnails/${filename}`;
  };

  return (
    <div className="p-4 md:p-6 space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1 bg-card/60 dark:bg-primary/60 rounded-lg p-1">
          {["all", "periodic", "event"].map((t) => (
            <button
              key={t}
              onClick={() => { setTrigger(t); setPage(1); }}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors capitalize ${
                trigger === t
                  ? "bg-card  text-white  shadow-sm"
                  : "text-muted-foreground hover:text-zinc-200"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        {total > 0 && (
          <span className="text-sm text-muted-foreground">{total} snapshots</span>
        )}
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <RefreshCw className="h-8 w-8 animate-spin text-slate-300" />
        </div>
      ) : snapshots.length === 0 ? (
        <div className="text-center py-16">
          <ImageIcon className="h-12 w-12 text-slate-200 mx-auto mb-3" />
          <p className="text-muted-foreground text-sm">No snapshots found</p>
          <p className="text-slate-300 text-xs mt-1">
            Snapshots are captured automatically every 5 minutes when recording
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3">
          {snapshots.map((snap) => {
            const imgUrl = getImageUrl(snap.file_path);
            return (
              <div
                key={snap.id}
                className="group relative bg-card/60 dark:bg-primary/60 rounded-lg overflow-hidden aspect-video cursor-pointer hover:ring-2 hover:ring-slate-400 transition-all"
                onClick={() => imgUrl && window.open(imgUrl, "_blank")}
              >
                {imgUrl ? (
                  <img
                    src={imgUrl}
                    alt={`Snapshot ${snap.id}`}
                    className="w-full h-full object-cover"
                    loading="lazy"
                    onError={(e) => { e.target.style.display = "none"; }}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <ImageIcon className="h-6 w-6 text-slate-300" />
                  </div>
                )}

                {/* Overlay */}
                <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                <div className="absolute bottom-0 left-0 right-0 p-2 opacity-0 group-hover:opacity-100 transition-opacity">
                  <p className="text-white text-xs font-medium leading-tight">
                    {snap.captured_at
                      ? format(new Date(snap.captured_at), "MMM d, HH:mm:ss")
                      : "—"}
                  </p>
                </div>

                {/* Trigger badge */}
                {snap.trigger && snap.trigger !== "periodic" && (
                  <div className="absolute top-1.5 right-1.5">
                    <span className="text-xs bg-red-500 text-white px-1.5 py-0.5 rounded-full font-medium capitalize">
                      {snap.trigger}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              <ChevronLeft className="h-4 w-4 mr-1" /> Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              Next <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

export default CameraDetail;
