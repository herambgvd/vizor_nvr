// =============================================================================
// RecordingCalendar — Monthly calendar with recording density indicators
// =============================================================================

import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  format,
  startOfMonth,
  endOfMonth,
  eachDayOfInterval,
  isSameMonth,
  isSameDay,
  addMonths,
  subMonths,
  startOfWeek,
  endOfWeek,
  isAfter,
} from "date-fns";
import { ChevronLeft, ChevronRight, Calendar } from "lucide-react";
import { getRecordingDates } from "../../api/recordings";
import { Button } from "../ui/button";
import { cn } from "../../lib/utils";

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * RecordingCalendar — Shows monthly calendar with recording availability.
 *
 * @param {string}   cameraId  - Camera to show recordings for
 * @param {Date}     selectedDate - Currently selected date
 * @param {Function} onSelectDate - Callback when a day is clicked
 */
export const RecordingCalendar = ({
  cameraId,
  selectedDate,
  onSelectDate,
  className,
}) => {
  const [viewMonth, setViewMonth] = useState(
    startOfMonth(selectedDate || new Date()),
  );

  // Fetch recording dates for this camera
  const { data: recordingDates = {} } = useQuery({
    queryKey: ["recordingDates", cameraId],
    queryFn: () => getRecordingDates(cameraId),
    enabled: !!cameraId,
    staleTime: 60000,
  });

  // Parse dates into a lookup map: "YYYY-MM-DD" → true
  const dateSet = useMemo(() => {
    const set = new Set();
    (recordingDates.dates || []).forEach((d) => {
      set.add(typeof d === "string" ? d.slice(0, 10) : format(new Date(d), "yyyy-MM-dd"));
    });
    return set;
  }, [recordingDates]);

  // Build calendar grid (6 weeks x 7 days)
  const calendarDays = useMemo(() => {
    const monthStart = startOfMonth(viewMonth);
    const monthEnd = endOfMonth(viewMonth);
    const gridStart = startOfWeek(monthStart); // Sunday-based
    const gridEnd = endOfWeek(monthEnd);
    return eachDayOfInterval({ start: gridStart, end: gridEnd });
  }, [viewMonth]);

  const prevMonth = () => setViewMonth(subMonths(viewMonth, 1));
  const nextMonth = () => setViewMonth(addMonths(viewMonth, 1));
  const today = new Date();

  return (
    <div
      className={cn(
        "bg-zinc-950 border border-white/10 rounded-lg p-4",
        className,
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <Button variant="ghost" size="icon" onClick={prevMonth}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <h3 className="text-sm font-semibold text-white">
          {format(viewMonth, "MMMM yyyy")}
        </h3>
        <Button
          variant="ghost"
          size="icon"
          onClick={nextMonth}
          disabled={isAfter(addMonths(viewMonth, 1), today)}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      {/* Weekday labels */}
      <div className="grid grid-cols-7 gap-1 mb-1">
        {WEEKDAYS.map((d) => (
          <div
            key={d}
            className="text-center text-[10px] font-medium text-zinc-500 uppercase"
          >
            {d}
          </div>
        ))}
      </div>

      {/* Day cells */}
      <div className="grid grid-cols-7 gap-1">
        {calendarDays.map((day) => {
          const key = format(day, "yyyy-MM-dd");
          const inMonth = isSameMonth(day, viewMonth);
          const isToday = isSameDay(day, today);
          const isSelected = selectedDate && isSameDay(day, selectedDate);
          const hasRecording = dateSet.has(key);
          const isFuture = isAfter(day, today);

          return (
            <button
              key={key}
              disabled={isFuture || !inMonth}
              onClick={() => onSelectDate?.(day)}
              className={cn(
                "relative h-9 w-full rounded-md text-xs font-medium transition-colors",
                !inMonth && "text-slate-300 cursor-default",
                inMonth && !isFuture && "hover:bg-white/[0.04] cursor-pointer",
                isFuture && "text-slate-300 cursor-not-allowed",
                isToday && "ring-1 ring-slate-400",
                isSelected &&
                  "bg-zinc-900 text-white hover:bg-zinc-900/60",
                hasRecording &&
                  !isSelected &&
                  inMonth &&
                  "bg-emerald-50 text-emerald-700 font-semibold",
              )}
            >
              {format(day, "d")}
              {/* Recording dot */}
              {hasRecording && inMonth && (
                <span
                  className={cn(
                    "absolute bottom-0.5 left-1/2 -translate-x-1/2 h-1 w-1 rounded-full",
                    isSelected ? "bg-zinc-950" : "bg-emerald-500",
                  )}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3 pt-3 border-t border-slate-100 text-[10px] text-zinc-500">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          Has recordings
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded border border-slate-400" />
          Today
        </span>
      </div>

      {!cameraId && (
        <div className="mt-3 text-center text-xs text-zinc-500">
          <Calendar className="h-5 w-5 mx-auto mb-1 opacity-50" />
          Select a camera to view recording dates
        </div>
      )}
    </div>
  );
};

export default RecordingCalendar;
