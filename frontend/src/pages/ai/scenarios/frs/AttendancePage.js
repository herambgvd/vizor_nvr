// =============================================================================
// FRS · Attendance — /ai/modules/frs/attendance
// =============================================================================
// Daily attendance log: person | first seen | last seen | total duration |
// late/early flags vs. shift bounds | punches. CSV export.
// Backend endpoint /api/ai/frs/attendance?day=YYYY-MM-DD
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, UserCheck, RefreshCw, Download, Clock } from "lucide-react";
import { format, parse, differenceInMinutes } from "date-fns";
import apiClient from "../../../../api/client";
import { Input } from "../../../../components/ui/input";
import { Button } from "../../../../components/ui/button";
import { Badge } from "../../../../components/ui/badge";
import { cn } from "../../../../lib/utils";

const fetchAttendance = async (day) => {
  try {
    const r = await apiClient.get("/ai/frs/attendance", { params: { day } });
    return r.data;
  } catch (e) {
    if (e?.response?.status === 404) return { rows: [] };
    throw e;
  }
};

const todayKey = () => format(new Date(), "yyyy-MM-dd");

// Persist shift bounds locally — operator preference, not server-side yet.
const LS_SHIFT_START = "frs.shift.start";
const LS_SHIFT_END = "frs.shift.end";
const LS_LATE_GRACE = "frs.shift.lateGrace";

const csvEscape = (v) => {
  if (v == null) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

const downloadCsv = (filename, rows) => {
  const blob = new Blob([rows.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

const AttendancePage = () => {
  const [day, setDay] = useState(todayKey());
  const [shiftStart, setShiftStart] = useState(
    () => localStorage.getItem(LS_SHIFT_START) || "09:00",
  );
  const [shiftEnd, setShiftEnd] = useState(
    () => localStorage.getItem(LS_SHIFT_END) || "18:00",
  );
  const [lateGrace, setLateGrace] = useState(
    () => Number(localStorage.getItem(LS_LATE_GRACE) || "10"),
  );

  const saveShift = (k, v) => localStorage.setItem(k, v);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["frs-attendance", day],
    queryFn: () => fetchAttendance(day),
    enabled: !!day,
  });
  const rows = data?.rows || [];

  const annotated = useMemo(() => {
    if (!rows.length) return [];
    const start = parse(`${day} ${shiftStart}`, "yyyy-MM-dd HH:mm", new Date());
    const end = parse(`${day} ${shiftEnd}`, "yyyy-MM-dd HH:mm", new Date());
    return rows.map((r) => {
      const firstSeen = r.first_seen ? new Date(r.first_seen) : null;
      const lastSeen = r.last_seen ? new Date(r.last_seen) : null;
      const lateBy = firstSeen
        ? Math.max(0, differenceInMinutes(firstSeen, start) - lateGrace)
        : null;
      const earlyBy = lastSeen
        ? Math.max(0, differenceInMinutes(end, lastSeen))
        : null;
      return { ...r, _lateBy: lateBy, _earlyBy: earlyBy };
    });
  }, [rows, day, shiftStart, shiftEnd, lateGrace]);

  const stats = useMemo(() => {
    const lateCount = annotated.filter((r) => r._lateBy && r._lateBy > 0).length;
    const earlyCount = annotated.filter((r) => r._earlyBy && r._earlyBy > 0).length;
    return { lateCount, earlyCount, total: annotated.length };
  }, [annotated]);

  const exportCsv = () => {
    const header = [
      "person_id",
      "person_name",
      "day",
      "first_seen",
      "last_seen",
      "punches",
      "total_minutes",
      "late_minutes",
      "early_leave_minutes",
    ];
    const lines = [header.join(",")];
    annotated.forEach((r) => {
      lines.push(
        [
          r.person_id,
          r.person_name || "",
          day,
          r.first_seen || "",
          r.last_seen || "",
          (r.punches || []).length,
          r.total_minutes ?? "",
          r._lateBy ?? "",
          r._earlyBy ?? "",
        ]
          .map(csvEscape)
          .join(","),
      );
    });
    downloadCsv(`attendance_${day}.csv`, lines);
  };

  return (
    <div className="p-4 md:p-6 space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="text-xs text-muted-foreground">Day</label>
          <Input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="w-44"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Shift start</label>
          <Input
            type="time"
            value={shiftStart}
            onChange={(e) => {
              setShiftStart(e.target.value);
              saveShift(LS_SHIFT_START, e.target.value);
            }}
            className="w-28"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Shift end</label>
          <Input
            type="time"
            value={shiftEnd}
            onChange={(e) => {
              setShiftEnd(e.target.value);
              saveShift(LS_SHIFT_END, e.target.value);
            }}
            className="w-28"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">Grace (min)</label>
          <Input
            type="number"
            min="0"
            max="120"
            value={lateGrace}
            onChange={(e) => {
              const v = Number(e.target.value || 0);
              setLateGrace(v);
              saveShift(LS_LATE_GRACE, String(v));
            }}
            className="w-20"
          />
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-3.5 w-3.5 mr-1" />
          Refresh
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={exportCsv}
          disabled={!annotated.length}
        >
          <Download className="h-3.5 w-3.5 mr-1" />
          Export CSV
        </Button>
        <span className="ml-auto text-xs text-muted-foreground">
          {stats.total} present · {stats.lateCount} late · {stats.earlyCount} left early
        </span>
      </div>

      <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-card/50 text-zinc-400 uppercase text-[11px] tracking-wider">
              <tr>
                <th className="text-left p-3 font-medium">Person</th>
                <th className="text-left p-3 font-medium">First seen</th>
                <th className="text-left p-3 font-medium">Last seen</th>
                <th className="text-right p-3 font-medium">Punches</th>
                <th className="text-right p-3 font-medium">Late</th>
                <th className="text-right p-3 font-medium">Early leave</th>
                <th className="text-right p-3 font-medium">Total</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              ) : annotated.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-muted-foreground">
                    No attendance for this day
                  </td>
                </tr>
              ) : (
                annotated.map((r) => {
                  const punches = r.punches || [];
                  return (
                    <tr
                      key={r.person_id + day}
                      className="border-t border-white/5 hover:bg-card/50"
                    >
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <UserCheck className="h-4 w-4 text-teal-300" />
                          <span className="font-medium">
                            {r.person_name || r.person_id}
                          </span>
                        </div>
                      </td>
                      <td className="p-3 text-muted-foreground font-mono">
                        {r.first_seen
                          ? format(new Date(r.first_seen), "HH:mm:ss")
                          : "—"}
                      </td>
                      <td className="p-3 text-muted-foreground font-mono">
                        {r.last_seen
                          ? format(new Date(r.last_seen), "HH:mm:ss")
                          : "—"}
                      </td>
                      <td className="p-3 text-right">
                        <Badge variant="outline" className="text-[10px]">
                          {punches.length}
                        </Badge>
                      </td>
                      <td
                        className={cn(
                          "p-3 text-right font-mono",
                          r._lateBy > 0 ? "text-rose-300" : "text-muted-foreground",
                        )}
                      >
                        {r._lateBy > 0 ? `+${r._lateBy}m` : "—"}
                      </td>
                      <td
                        className={cn(
                          "p-3 text-right font-mono",
                          r._earlyBy > 0 ? "text-amber-300" : "text-muted-foreground",
                        )}
                      >
                        {r._earlyBy > 0 ? `-${r._earlyBy}m` : "—"}
                      </td>
                      <td className="p-3 text-right font-mono">
                        {r.total_minutes != null
                          ? `${Math.floor(r.total_minutes / 60)}h ${r.total_minutes % 60}m`
                          : "—"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[11px] text-muted-foreground flex items-center gap-2">
        <Clock className="h-3.5 w-3.5" />
        Late / early calculated against the shift window above. Shift settings
        are stored locally (per browser).
      </p>
    </div>
  );
};

export default AttendancePage;
