// =============================================================================
// RecordingsPage — /cameras/:id/recordings (Timeline playback only)
// =============================================================================
// Recording Files list view dropped — the global /playback page already
// covers multi-cam list/scrub. This page is the single-cam scrub timeline
// only, so it doesn't duplicate the global playback UX.
// =============================================================================

import React, { useCallback, useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { format, startOfDay } from "date-fns";
import {
  ChevronLeft,
  ChevronRight,
  Calendar as CalendarIcon,
  Download,
} from "lucide-react";
import { toast } from "sonner";
import {
  getTimeline,
  getRecordingDates,
  getPlaybackInfo,
  exportClip,
} from "../../api/recordings";
import { createBookmark } from "../../api/bookmarks";
import {
  TimelinePlayer,
  RecordingCalendar,
  ClipBuilder,
} from "../../components/nvr";
import { Button } from "../../components/ui/button";
import { getErrorMessage } from "../../lib/utils";
import { Calendar } from "../../components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "../../components/ui/popover";

const RecordingsPage = () => {
  const { cameraId } = useOutletContext();
  const playerRef = useRef(null);

  const [selectedDate, setSelectedDate] = useState(startOfDay(new Date()));
  const [availableDates, setAvailableDates] = useState([]);

  const { data: recordingDates } = useQuery({
    queryKey: ["recordingDates", cameraId],
    queryFn: () => getRecordingDates(cameraId),
    enabled: !!cameraId,
  });

  const { data: timeline = [], isLoading: timelineLoading } = useQuery({
    queryKey: ["timeline", cameraId, selectedDate?.toISOString()],
    queryFn: () => getTimeline(cameraId, selectedDate?.toISOString()),
    enabled: !!cameraId && !!selectedDate,
    staleTime: 30_000,
    select: (data) => {
      const segments = Array.isArray(data) ? data : data?.segments ?? [];
      return segments.map((seg) => ({
        ...seg,
        start_time: seg.start_time || seg.start,
        end_time: seg.end_time || seg.end,
        id: seg.recording_id || seg.id,
      }));
    },
  });

  useEffect(() => {
    if (recordingDates?.dates) {
      const next = recordingDates.dates.map((d) => new Date(d));
      // Only update when content actually changed to avoid Calendar
      // re-render storms.
      setAvailableDates((prev) => {
        if (prev.length === next.length && prev.every((d, i) => d.getTime() === next[i].getTime())) {
          return prev;
        }
        return next;
      });
    }
  }, [recordingDates]);

  const handleSeek = useCallback(
    async (timestamp) => {
      try {
        const info = await getPlaybackInfo(cameraId, {
          timestamp: new Date(timestamp).toISOString(),
        });
        playerRef.current?.seekTo?.(info);
      } catch (e) {
        toast.error("Seek failed");
      }
    },
    [cameraId],
  );

  const exportMutation = useMutation({
    mutationFn: exportClip,
    onSuccess: (res) =>
      toast.success(`Export started — ${res.export_id || "processing"}`),
    onError: (e) => toast.error(getErrorMessage(e, "Export failed")),
  });

  const handleExportDay = () => {
    const start = startOfDay(selectedDate);
    const end = new Date(start);
    end.setHours(23, 59, 59, 999);
    exportMutation.mutate({
      camera_id: cameraId,
      start_time: start.toISOString(),
      end_time: end.toISOString(),
    });
  };

  const bookmarkMutation = useMutation({
    mutationFn: createBookmark,
    onSuccess: () => toast.success("Bookmark saved"),
    onError: (e) => toast.error(getErrorMessage(e, "Bookmark failed")),
  });

  const handleBookmark = useCallback(
    (timestamp) => {
      if (!cameraId || timestamp == null) return;
      bookmarkMutation.mutate({
        camera_id: cameraId,
        timestamp: Number(timestamp) || 0,
      });
    },
    [cameraId, bookmarkMutation],
  );

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

  return (
    <div className="p-4 md:p-6 space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Button variant="outline" size="icon" onClick={handlePrevDay}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <Popover>
          <PopoverTrigger asChild>
            <Button variant="outline" className="w-40 sm:w-48 justify-start text-sm">
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
                  color: "rgb(20, 184, 166)",
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
          disabled={selectedDate.toDateString() === new Date().toDateString()}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleExportDay}
          disabled={timeline.length === 0 || exportMutation.isPending}
        >
          <Download className="h-4 w-4 mr-2" />
          Export Day
        </Button>
      </div>

      <div className="flex flex-col xl:flex-row gap-4">
        <div className="flex-1 min-w-0">
          <TimelinePlayer
            ref={playerRef}
            cameraId={cameraId}
            recordings={timeline}
            selectedDate={selectedDate}
            onDateChange={(d) => setSelectedDate(startOfDay(d))}
            onSeek={handleSeek}
            onExport={handleExportDay}
            onBookmark={handleBookmark}
            isLoading={timelineLoading}
          />
        </div>
        <div className="xl:w-64 flex-shrink-0 space-y-4">
          <RecordingCalendar
            cameraId={cameraId}
            selectedDate={selectedDate}
            onSelectDate={(d) => setSelectedDate(startOfDay(d))}
          />
          <ClipBuilder cameraId={cameraId} currentTime={selectedDate} />
        </div>
      </div>
    </div>
  );
};

export default RecordingsPage;
