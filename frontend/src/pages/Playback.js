// =============================================================================
// Playback — Recording timeline & video playback + Bookmarks
// =============================================================================

import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format, startOfDay } from "date-fns";
import {
  Play,
  Calendar as CalendarIcon,
  Camera,
  ChevronLeft,
  ChevronRight,
  Download,
  Bookmark,
  Search,
  Trash2,
  Edit2,
  Check,
  X,
  Clock,
} from "lucide-react";
import { getAllCameras } from "../api/cameras";
import {
  getTimeline,
  getRecordingDates,
  exportClip,
  getPlaybackInfo,
} from "../api/recordings";
import {
  createBookmark,
  getBookmarks,
  updateBookmark,
  deleteBookmark,
} from "../api/bookmarks";
import {
  TimelinePlayer,
  RecordingCalendar,
  ClipBuilder,
} from "../components/nvr";
import AIEventTimeline from "../components/camera/AIEventTimeline";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Badge } from "../components/ui/badge";
import { Calendar } from "../components/ui/calendar";
import { Textarea } from "../components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "../components/ui/popover";
import { cn } from "../lib/utils";
import { toast } from "sonner";

const Playback = () => {
  const [searchParams, setSearchParams] = useSearchParams();

  // State
  const [selectedCameraId, setSelectedCameraId] = useState(
    searchParams.get("camera") || "",
  );
  const [selectedDate, setSelectedDate] = useState(startOfDay(new Date()));
  const [availableDates, setAvailableDates] = useState([]);

  // Player ref for programmatic seeking
  const playerRef = useRef(null);

  // Queries
  const { data: cameras = [] } = useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
  });

  const { data: recordingDates } = useQuery({
    queryKey: ["recordingDates", selectedCameraId],
    queryFn: () => getRecordingDates(selectedCameraId),
    enabled: !!selectedCameraId,
  });

  const { data: timeline = [], isLoading: timelineLoading } = useQuery({
    queryKey: ["timeline", selectedCameraId, selectedDate?.toISOString()],
    queryFn: () => getTimeline(selectedCameraId, selectedDate?.toISOString()),
    enabled: !!selectedCameraId && !!selectedDate,
    staleTime: 30000,
    refetchOnWindowFocus: false,
    // Transform API segments (start/end) to format expected by TimelinePlayer (start_time/end_time)
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

  // Export mutation
  const exportMutation = useMutation({
    mutationFn: (data) => exportClip(data),
    onSuccess: (result) =>
      toast.success(`Export started — ${result.export_id || "processing"}`),
    onError: (e) => toast.error(e.response?.data?.detail || "Export failed"),
  });

  // Available dates from API
  useEffect(() => {
    if (recordingDates?.dates) {
      setAvailableDates(recordingDates.dates.map((d) => new Date(d)));
    }
  }, [recordingDates]);

  // Auto-select first camera from URL or list
  useEffect(() => {
    if (!selectedCameraId && cameras.length > 0) {
      const urlCam = searchParams.get("camera");
      if (urlCam && cameras.find((c) => c.id === urlCam)) {
        setSelectedCameraId(urlCam);
      } else {
        setSelectedCameraId(cameras[0].id);
      }
    }
  }, [cameras, selectedCameraId, searchParams]);

  // Sync URL
  useEffect(() => {
    if (selectedCameraId) {
      setSearchParams({ camera: selectedCameraId }, { replace: true });
    }
  }, [selectedCameraId, setSearchParams]);

  // ---- seek handler (actually controls the TimelinePlayer) ----
  const handleSeek = useCallback(
    async (timestamp) => {
      try {
        // Ask backend for the recording file & byte-offset
        const info = await getPlaybackInfo(selectedCameraId, {
          timestamp: new Date(timestamp).toISOString(),
        });
        // TimelinePlayer exposes an imperative seekTo method
        playerRef.current?.seekTo?.(info);
      } catch {
        // Silently ignore seek failures - user will see "no recording" state
      }
    },
    [selectedCameraId],
  );

  // ---- date navigation ----
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

  // ---- export ----
  const handleExport = () => {
    const start = startOfDay(selectedDate);
    const end = new Date(start);
    end.setHours(23, 59, 59, 999);
    exportMutation.mutate({
      camera_id: selectedCameraId,
      start_time: start.toISOString(),
      end_time: end.toISOString(),
    });
  };

  // ---- bookmark ----
  const bookmarkMutation = useMutation({
    mutationFn: (data) => createBookmark(data),
    onSuccess: () => toast.success("Bookmark saved"),
    onError: (e) => toast.error(e.response?.data?.detail || "Bookmark failed"),
  });

  const handleBookmark = useCallback(
    (timestamp) => {
      if (!selectedCameraId) return;
      bookmarkMutation.mutate({
        camera_id: selectedCameraId,
        timestamp: timestamp ?? 0,
      });
    },
    [selectedCameraId, bookmarkMutation],
  );

  const hasRecordings = (date) =>
    availableDates.some((d) => d.toDateString() === date.toDateString());

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-4 md:px-8 pt-4 md:pt-6 pb-3 md:pb-4 border-b border-border ">
        <h1
          className="text-2xl md:text-3xl font-bold text-white  tracking-tight"
          style={{ fontFamily: "Manrope, sans-serif" }}
        >
          Playback
        </h1>
        <p className="text-muted-foreground dark:text-muted-foreground mt-1 text-sm md:text-base">
          Review and export recorded footage
        </p>
      </div>

      <Tabs
        defaultValue="timeline"
        className="flex-1 flex flex-col overflow-hidden"
      >
        <div className="flex-shrink-0 px-4 md:px-8 border-b border-border ">
          <TabsList className="h-auto bg-transparent gap-0 p-0">
            <TabsTrigger
              value="timeline"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <Play className="h-4 w-4" />
              Timeline
            </TabsTrigger>
            <TabsTrigger
              value="bookmarks"
              className="gap-2 rounded-none border-b-2 border-transparent data-[state=active]:border-slate-900 data-[state=active]:bg-transparent data-[state=active]:shadow-none px-4 py-3"
            >
              <Bookmark className="h-4 w-4" />
              Bookmarks
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent
          value="timeline"
          className="flex-1 flex flex-col overflow-hidden m-0"
        >
          {/* Controls */}
          <div className="flex-shrink-0 px-4 md:px-8 py-3 md:py-4 border-b border-slate-100  flex flex-col sm:flex-row flex-wrap items-start sm:items-center gap-3 md:gap-4">
            {/* Camera select */}
            <div className="flex items-center gap-2 w-full sm:w-auto">
              <Camera className="h-5 w-5 text-muted-foreground hidden sm:block" />
              <Select
                value={selectedCameraId}
                onValueChange={setSelectedCameraId}
              >
                <SelectTrigger className="w-full sm:w-64">
                  <SelectValue placeholder="Select camera" />
                </SelectTrigger>
                <SelectContent>
                  {cameras.map((cam) => (
                    <SelectItem key={cam.id} value={cam.id}>
                      <div className="flex items-center gap-2">
                        <span
                          className={cn(
                            "h-2 w-2 rounded-full",
                            cam.status === "online"
                              ? "bg-emerald-500"
                              : "bg-slate-400",
                          )}
                        />
                        {cam.name}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Date nav */}
            <div className="flex items-center gap-2">
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
            </div>

            {/* Export */}
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={
                !selectedCameraId ||
                timeline.length === 0 ||
                exportMutation.isPending
              }
              className="w-full sm:w-auto"
            >
              <Download className="h-4 w-4 mr-2" />
              Export Day
            </Button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-4 md:px-8 py-3 md:py-4">
            {selectedCameraId ? (
              <div className="flex flex-col lg:flex-row gap-4">
                <div className="flex-1 min-w-0">
                  <TimelinePlayer
                    ref={playerRef}
                    cameraId={selectedCameraId}
                    recordings={timeline}
                    selectedDate={selectedDate}
                    onDateChange={(d) => setSelectedDate(startOfDay(d))}
                    onSeek={handleSeek}
                    onExport={handleExport}
                    onBookmark={handleBookmark}
                    isLoading={timelineLoading}
                  />
                  <AIEventTimeline
                    cameraId={selectedCameraId}
                    windowStart={startOfDay(selectedDate)}
                    windowEnd={new Date(startOfDay(selectedDate).getTime() + 86400000)}
                    onSeek={(ts) => handleSeek(ts)}
                  />
                </div>
                <div className="lg:w-64 flex-shrink-0 space-y-4">
                  <RecordingCalendar
                    cameraId={selectedCameraId}
                    selectedDate={selectedDate}
                    onSelectDate={(d) => setSelectedDate(startOfDay(d))}
                  />
                  <ClipBuilder
                    cameraId={selectedCameraId}
                    currentTime={selectedDate}
                  />
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-16 px-4 bg-card/40 rounded-lg border border-dashed border-border">
                <Play className="h-12 w-12 text-muted-foreground mb-4" />
                <h3 className="text-lg font-medium text-white mb-2">
                  Select a Camera
                </h3>
                <p className="text-muted-foreground text-center max-w-md">
                  Choose a camera from the dropdown above to view recorded
                  footage.
                </p>
              </div>
            )}
          </div>
        </TabsContent>

        <TabsContent value="bookmarks" className="flex-1 overflow-y-auto m-0">
          <BookmarksPanel cameras={cameras} />
        </TabsContent>
      </Tabs>
    </div>
  );
};

// =============================================================================
// Bookmarks Panel — embedded in Playback page
// =============================================================================

const BOOKMARK_PAGE_SIZE = 20;

const BookmarksPanel = ({ cameras }) => {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const [page, setPage] = useState(1);
  const [cameraId, setCameraId] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [editingBookmark, setEditingBookmark] = useState(null);
  const [editNote, setEditNote] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  const params = useMemo(() => {
    const p = {
      limit: BOOKMARK_PAGE_SIZE,
      offset: (page - 1) * BOOKMARK_PAGE_SIZE,
    };
    if (cameraId !== "all") p.camera_id = cameraId;
    if (searchQuery.trim()) p.search = searchQuery.trim();
    return p;
  }, [page, cameraId, searchQuery]);

  const {
    data: bookmarks = [],
    isLoading,
    isFetching,
  } = useQuery({
    queryKey: ["bookmarks", params],
    queryFn: () => getBookmarks(params),
    staleTime: 30000,
  });

  const cameraMap = useMemo(() => {
    return cameras.reduce((acc, cam) => {
      acc[cam.id] = cam;
      return acc;
    }, {});
  }, [cameras]);

  const updateMut = useMutation({
    mutationFn: ({ id, data }) => updateBookmark(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bookmarks"] });
      setEditingBookmark(null);
      toast.success("Bookmark updated");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Update failed"),
  });

  const deleteMut = useMutation({
    mutationFn: deleteBookmark,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["bookmarks"] });
      setDeleteConfirm(null);
      toast.success("Bookmark deleted");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Delete failed"),
  });

  const handlePlay = (bm) => {
    navigate(`/playback?camera=${bm.camera_id}&t=${bm.timestamp}`);
  };

  const bookmarkList = Array.isArray(bookmarks)
    ? bookmarks
    : (bookmarks?.items ?? []);
  const hasMore = bookmarkList.length === BOOKMARK_PAGE_SIZE;

  return (
    <div className="p-4 md:p-8 space-y-6">
      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative w-64">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search bookmarks…"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(1);
            }}
            className="pl-10"
          />
        </div>
        <Select
          value={cameraId}
          onValueChange={(v) => {
            setCameraId(v);
            setPage(1);
          }}
        >
          <SelectTrigger className="w-48">
            <SelectValue placeholder="All cameras" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All cameras</SelectItem>
            {cameras.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Bookmark cards */}
      {isLoading ? (
        <div className="text-center py-12 text-muted-foreground">
          Loading bookmarks…
        </div>
      ) : bookmarkList.length === 0 ? (
        <div className="text-center py-12">
          <Bookmark className="h-10 w-10 text-slate-300 mx-auto mb-3" />
          <p className="text-muted-foreground">No bookmarks found</p>
          <p className="text-muted-foreground text-sm mt-1">
            Create bookmarks during playback to save important moments
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {bookmarkList.map((bm) => {
            const cam = cameraMap[bm.camera_id];
            return (
              <div
                key={bm.id}
                className="bg-card dark:bg-primary/60 border border-border  rounded-lg p-4 flex items-start gap-4 hover:border-border transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="outline" className="text-xs">
                      <Camera className="h-3 w-3 mr-1" />
                      {cam?.name || "Unknown"}
                    </Badge>
                    <span className="text-xs text-muted-foreground flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {bm.created_at
                        ? format(new Date(bm.created_at), "MMM d, yyyy HH:mm")
                        : "-"}
                    </span>
                  </div>
                  <p className="text-sm text-zinc-200  line-clamp-2">
                    {bm.note || bm.label || "No description"}
                  </p>
                  {bm.timestamp != null && (
                    <p className="text-xs text-muted-foreground mt-1">
                      Timestamp:{" "}
                      {typeof bm.timestamp === "number"
                        ? `${Math.floor(bm.timestamp)}s`
                        : bm.timestamp}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => handlePlay(bm)}
                    title="Play"
                  >
                    <Play className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => {
                      setEditingBookmark(bm);
                      setEditNote(bm.note || bm.label || "");
                    }}
                    title="Edit"
                  >
                    <Edit2 className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-red-500"
                    onClick={() => setDeleteConfirm(bm)}
                    title="Delete"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {(page > 1 || hasMore) && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            <ChevronLeft className="h-4 w-4 mr-1" /> Previous
          </Button>
          <span className="text-sm text-muted-foreground">Page {page}</span>
          <Button
            variant="outline"
            size="sm"
            disabled={!hasMore}
            onClick={() => setPage(page + 1)}
          >
            Next <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        </div>
      )}

      {/* Edit dialog */}
      <Dialog
        open={!!editingBookmark}
        onOpenChange={() => setEditingBookmark(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit Bookmark</DialogTitle>
            <DialogDescription>
              Update the note for this bookmark
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={editNote}
            onChange={(e) => setEditNote(e.target.value)}
            placeholder="Add a note…"
            rows={3}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditingBookmark(null)}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                updateMut.mutate({
                  id: editingBookmark.id,
                  data: { note: editNote },
                })
              }
              disabled={updateMut.isPending}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete dialog */}
      <Dialog
        open={!!deleteConfirm}
        onOpenChange={() => setDeleteConfirm(null)}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete Bookmark</DialogTitle>
            <DialogDescription>This action cannot be undone.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteMut.mutate(deleteConfirm.id)}
              disabled={deleteMut.isPending}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Playback;
