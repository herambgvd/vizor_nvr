// =============================================================================
// AI · Attendance tab (FRS only).
//
// Two views:
//   • Log   — daily sighting records (GET /api/ai/frs/attendance) joined to
//             person names: person, day, check-in, check-out, camera.
//   • Report— per-person aggregate over a date range
//             (GET /api/ai/frs/attendance/report): days present, first/last seen.
//
// Client-side CSV export for whichever view is active.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Download,
  ImageOff,
  Loader2,
  Users,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { format } from "date-fns";

import {
  listAttendance,
  attendanceReport,
  getScenarioCameras,
} from "../../../../api/frs";
import { scenarioSnapshotUrl } from "../../../../api/ai";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { cn } from "../../../../lib/utils";
import { cameraNameMap } from "./frsShared";

const PAGE_SIZE = 25;

function todayKey() {
  return format(new Date(), "yyyy-MM-dd");
}
function daysAgoKey(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return format(d, "yyyy-MM-dd");
}

function fmtClock(iso) {
  if (!iso) return "—";
  try {
    return format(new Date(iso), "HH:mm:ss");
  } catch {
    return iso;
  }
}
function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return format(new Date(iso), "MMM d, HH:mm");
  } catch {
    return iso;
  }
}

// Quote a CSV cell, escaping embedded quotes.
function csvCell(v) {
  const s = v == null ? "" : String(v);
  return `"${s.replace(/"/g, '""')}"`;
}

function downloadCsv(filename, headers, rows) {
  if (!rows.length) {
    toast.error("Nothing to export");
    return;
  }
  const lines = [headers.map(csvCell).join(",")];
  rows.forEach((r) => lines.push(r.map(csvCell).join(",")));
  const blob = new Blob([lines.join("\r\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Authenticated <img> for plugin-relative snapshot paths. `fetcher` returns an
// object URL (revoked on unmount). Mirrors EventsTab's AuthImage.
function AuthImage({ fetcher, deps, className, fallback }) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let active = true;
    let obj = null;
    setUrl(null); setErr(false);
    if (!fetcher) { setErr(true); return undefined; }
    fetcher().then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      if (u) { obj = u; setUrl(u); } else setErr(true);
    }).catch(() => active && setErr(true));
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  if (err) return fallback || null;
  if (!url) {
    return (
      <div className={`${className} flex items-center justify-center`} style={{ background: "var(--console-raised)" }}>
        <Loader2 className="h-3.5 w-3.5 animate-spin text-zinc-500" />
      </div>
    );
  }
  return <img src={url} alt="" className={className} style={{ objectFit: "cover" }} />;
}

// Small attendance face thumbnail (check-in / check-out snapshot) with a muted
// placeholder when no snapshot is available — never breaks the row.
function FaceThumb({ snapshot, slug }) {
  const placeholder = (
    <div
      className="h-9 w-9 rounded flex items-center justify-center border shrink-0"
      style={{
        borderColor: "var(--console-border)",
        background: "var(--console-raised)",
      }}
    >
      <ImageOff className="h-3.5 w-3.5 text-zinc-600" />
    </div>
  );
  if (!snapshot || !slug) return placeholder;
  return (
    <AuthImage
      fetcher={() => scenarioSnapshotUrl(slug, snapshot)}
      deps={[slug, snapshot]}
      className="h-9 w-9 rounded border shrink-0"
      fallback={placeholder}
    />
  );
}

// Theme-aware date field. The native date input's calendar icon is drawn by the
// browser using `color-scheme`; without it the icon is invisible on a dark panel
// (and our previous hardcoded zinc text was invisible on the light theme). We read
// the live --console-text colour to decide light vs dark and set color-scheme so
// the picker icon + popup match the active theme.
function DateField({ label, value, onChange }) {
  const [scheme, setScheme] = useState("dark");
  useEffect(() => {
    try {
      const c = getComputedStyle(document.documentElement)
        .getPropertyValue("--console-text").trim();
      // --console-text is light on dark themes, dark on light themes.
      const m = c.match(/\d+/g);
      if (m && m.length >= 3) {
        const lum = (parseInt(m[0]) * 0.299 + parseInt(m[1]) * 0.587 + parseInt(m[2]) * 0.114);
        setScheme(lum > 140 ? "dark" : "light"); // light text → dark UI
      }
    } catch { /* default dark */ }
  }, []);
  return (
    <div>
      <label
        className="block text-[9px] uppercase tracking-wider font-telemetry mb-0.5"
        style={{ color: "var(--console-muted)" }}
      >
        {label}
      </label>
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 text-xs rounded px-2 outline-none"
        style={{
          background: "var(--console-raised)",
          border: "1px solid var(--console-border)",
          color: "var(--console-text)",
          colorScheme: scheme,
        }}
      />
    </div>
  );
}

function ViewToggle({ view, setView }) {
  const tabs = [
    { id: "log", label: "Log", icon: CalendarDays },
    { id: "report", label: "Report", icon: Users },
  ];
  return (
    <div
      className="inline-flex rounded-lg border p-0.5"
      style={{
        borderColor: "var(--console-border)",
        background: "var(--console-raised)",
      }}
    >
      {tabs.map((t) => {
        const Icon = t.icon;
        const active = view === t.id;
        return (
          <button
            key={t.id}
            onClick={() => setView(t.id)}
            className="flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-colors border"
            style={{
              background: active ? "var(--console-accent)" : "transparent",
              color: active ? "#000" : "var(--console-muted)",
              borderColor: active ? "var(--console-accent)" : "transparent",
            }}
          >
            <Icon className="h-3.5 w-3.5" /> {t.label}
          </button>
        );
      })}
    </div>
  );
}

// Attendance detail modal — full record: person, day, check-in/out time + camera,
// duration, and the captured check-in / check-out snapshots at a readable size.
function AttendanceDetailModal({ record: a, camMap, slug, onClose }) {
  const personLabel = a.person_name || a.person_id || "Unknown";
  const dur = (() => {
    if (!a.check_in_at || !a.check_out_at) return "—";
    const secs = Math.floor((new Date(a.check_out_at).getTime() - new Date(a.check_in_at).getTime()) / 1000);
    if (secs < 0) return "—";
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
    return h ? `${h}h ${m}m` : `${m}m`;
  })();
  const BigSnap = ({ snapshot, label, time, cam }) => (
    <div className="flex flex-col gap-1.5">
      <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        {label}
      </span>
      <div
        className="w-full aspect-video rounded flex items-center justify-center overflow-hidden"
        style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
      >
        {snapshot && slug ? (
          <AuthImage
            fetcher={() => scenarioSnapshotUrl(slug, snapshot)}
            deps={[slug, snapshot]}
            className="w-full h-full"
            fallback={<ImageOff className="h-6 w-6 text-zinc-600" />}
          />
        ) : (
          <ImageOff className="h-6 w-6 text-zinc-600" />
        )}
      </div>
      <span className="font-telemetry text-[11px]" style={{ color: "var(--console-text)" }}>
        {time || "—"}{cam ? ` · ${cam}` : ""}
      </span>
    </div>
  );
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded p-5 flex flex-col gap-4"
        style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="font-telemetry text-[13px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
              {personLabel}
            </div>
            <div className="font-telemetry text-[10px] uppercase tracking-widest mt-0.5" style={{ color: "var(--console-muted)" }}>
              {a.day_key} · duration {dur}
            </div>
          </div>
          <button type="button" onClick={onClose} style={{ color: "var(--console-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <BigSnap
            snapshot={a.check_in_snapshot}
            label="Check-in"
            time={fmtClock(a.check_in_at)}
            cam={camMap[a.check_in_camera_id || a.camera_id] || a.check_in_camera_id || a.camera_id}
          />
          <BigSnap
            snapshot={a.check_out_snapshot}
            label="Check-out"
            time={fmtClock(a.check_out_at)}
            cam={camMap[a.check_out_camera_id] || a.check_out_camera_id}
          />
        </div>
      </div>
    </div>
  );
}

// ── Log view ────────────────────────────────────────────────────────────────

function LogView({ since, until, camMap, slug }) {
  const [page, setPage] = useState(0);
  const [detail, setDetail] = useState(null);

  const params = useMemo(() => {
    const p = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
    if (since) p.since = new Date(`${since}T00:00:00`).toISOString();
    if (until) p.until = new Date(`${until}T23:59:59`).toISOString();
    return p;
  }, [page, since, until]);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["frs", "attendance", params],
    queryFn: () => listAttendance(params),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const exportCsv = () => {
    downloadCsv(
      `attendance_log_${since || "all"}_${until || "all"}.csv`,
      ["Person", "Day", "Check-in", "Check-out", "Camera", "Type"],
      items.map((a) => [
        a.person_name || a.person_id || "Unknown",
        a.day_key,
        fmtClock(a.check_in_at),
        fmtClock(a.check_out_at),
        camMap[a.camera_id] || a.camera_id || "—",
        a.sighting_type || "—",
      ]),
    );
  };

  return (
    <>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] text-zinc-500 font-telemetry">
          {total} record{total === 1 ? "" : "s"}
          {isFetching && (
            <Loader2 className="inline h-3 w-3 ml-2 animate-spin text-zinc-400" />
          )}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          onClick={exportCsv}
          disabled={items.length === 0}
        >
          <Download className="h-3.5 w-3.5 mr-1" /> Export CSV
        </Button>
      </div>

      <div
        className="rounded-lg border overflow-hidden"
        style={{ borderColor: "var(--console-border)" }}
      >
        <table className="w-full text-left">
          <thead>
            <tr
              className="text-[10px] uppercase tracking-wider text-zinc-500 font-telemetry"
              style={{ background: "var(--console-raised)" }}
            >
              <th className="px-3 py-2 font-medium">Person</th>
              <th className="px-3 py-2 font-medium">Day</th>
              <th className="px-3 py-2 font-medium">Check-in</th>
              <th className="px-3 py-2 font-medium">Check-out</th>
              <th className="px-3 py-2 font-medium">Camera</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                  <td colSpan={5} className="px-3 py-3">
                    <div className="h-5 rounded animate-pulse bg-zinc-800/60" />
                  </td>
                </tr>
              ))
            ) : isError ? (
              <tr>
                <td colSpan={5} className="px-3 py-12 text-center text-sm text-rose-400">
                  Couldn't load attendance.
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-16 text-center">
                  <CalendarDays className="h-9 w-9 mx-auto text-zinc-600 mb-2" />
                  <p className="text-sm text-zinc-300">No attendance records</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    Records appear as enrolled people are recognized.
                  </p>
                </td>
              </tr>
            ) : (
              items.map((a) => (
                <tr
                  key={a.id}
                  onClick={() => setDetail(a)}
                  className="border-t hover:bg-white/[0.02] transition-colors cursor-pointer"
                  style={{ borderColor: "var(--console-border)" }}
                >
                  <td className="px-3 py-2 text-xs text-zinc-200">
                    {a.person_name || a.person_id || "Unknown"}
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-300 font-telemetry">
                    {a.day_key}
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-300 font-telemetry">
                    <div className="flex items-center gap-2">
                      <FaceThumb snapshot={a.check_in_snapshot} slug={slug} />
                      <span>{fmtClock(a.check_in_at)}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-300 font-telemetry">
                    <div className="flex items-center gap-2">
                      <FaceThumb snapshot={a.check_out_snapshot} slug={slug} />
                      <span>{fmtClock(a.check_out_at)}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-300 max-w-[160px] truncate">
                    {camMap[a.camera_id] || a.camera_id || "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-end gap-2 mt-3">
          <span className="text-[11px] text-zinc-500 font-telemetry">
            Page {page + 1} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            disabled={page + 1 >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {detail && (
        <AttendanceDetailModal
          record={detail}
          camMap={camMap}
          slug={slug}
          onClose={() => setDetail(null)}
        />
      )}
    </>
  );
}

// ── Report view ───────────────────────────────────────────────────────────────

function ReportView({ since, until }) {
  const day_from = since || daysAgoKey(30);
  const day_to = until || todayKey();

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["frs", "attendance-report", day_from, day_to],
    queryFn: () => attendanceReport({ day_from, day_to }),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];

  // Number of calendar days in the inclusive range (for the days-present grid).
  const totalDays = useMemo(() => {
    try {
      const start = new Date(`${day_from}T00:00:00`);
      const end = new Date(`${day_to}T00:00:00`);
      const diff = Math.round((end - start) / 86400000) + 1;
      return diff > 0 ? diff : 1;
    } catch {
      return 1;
    }
  }, [day_from, day_to]);

  const exportCsv = () => {
    downloadCsv(
      `attendance_report_${day_from}_${day_to}.csv`,
      ["Person", "Days present", "Total days", "First seen", "Last seen"],
      items.map((r) => [
        r.person_name || r.person_id || "Unknown",
        r.days_present,
        totalDays,
        fmtDate(r.first_seen),
        fmtDate(r.last_seen),
      ]),
    );
  };

  return (
    <>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[11px] text-zinc-500 font-telemetry">
          {items.length} person{items.length === 1 ? "" : "s"} · {totalDays} day
          {totalDays === 1 ? "" : "s"} in range
          {isFetching && (
            <Loader2 className="inline h-3 w-3 ml-2 animate-spin text-zinc-400" />
          )}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="h-8 text-xs"
          onClick={exportCsv}
          disabled={items.length === 0}
        >
          <Download className="h-3.5 w-3.5 mr-1" /> Export CSV
        </Button>
      </div>

      <div
        className="rounded-lg border overflow-hidden"
        style={{ borderColor: "var(--console-border)" }}
      >
        <table className="w-full text-left">
          <thead>
            <tr
              className="text-[10px] uppercase tracking-wider text-zinc-500 font-telemetry"
              style={{ background: "var(--console-raised)" }}
            >
              <th className="px-3 py-2 font-medium">Person</th>
              <th className="px-3 py-2 font-medium">Days present</th>
              <th className="px-3 py-2 font-medium">First seen</th>
              <th className="px-3 py-2 font-medium">Last seen</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                  <td colSpan={4} className="px-3 py-3">
                    <div className="h-5 rounded animate-pulse bg-zinc-800/60" />
                  </td>
                </tr>
              ))
            ) : isError ? (
              <tr>
                <td colSpan={4} className="px-3 py-12 text-center text-sm text-rose-400">
                  Couldn't load report.
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-3 py-16 text-center">
                  <Users className="h-9 w-9 mx-auto text-zinc-600 mb-2" />
                  <p className="text-sm text-zinc-300">No attendance in range</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    Adjust the date range above.
                  </p>
                </td>
              </tr>
            ) : (
              items.map((r) => {
                const pct = Math.min(
                  100,
                  Math.round((r.days_present / totalDays) * 100),
                );
                return (
                  <tr
                    key={r.person_id || r.person_name}
                    className="border-t hover:bg-white/[0.02] transition-colors"
                    style={{ borderColor: "var(--console-border)" }}
                  >
                    <td className="px-3 py-2 text-xs text-zinc-200">
                      {r.person_name || r.person_id || "Unknown"}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-24 rounded-full bg-zinc-800 overflow-hidden">
                          <div
                            className="h-full bg-emerald-500/70"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-zinc-300 font-telemetry whitespace-nowrap">
                          {r.days_present} / {totalDays}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs text-zinc-300 font-telemetry">
                      {fmtDate(r.first_seen)}
                    </td>
                    <td className="px-3 py-2 text-xs text-zinc-300 font-telemetry">
                      {fmtDate(r.last_seen)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function AttendanceTab({ scenario }) {
  const scenarioId = scenario?.id;
  const [view, setView] = useState("log");
  const [since, setSince] = useState(daysAgoKey(7));
  const [until, setUntil] = useState(todayKey());

  const { data: cameras = [] } = useQuery({
    queryKey: ["frs", "scenario-cameras", scenarioId],
    queryFn: () => getScenarioCameras(scenarioId),
    enabled: !!scenarioId,
  });
  const camMap = useMemo(() => cameraNameMap(cameras), [cameras]);

  return (
    <div className="p-4 space-y-3">
      <div
        className="flex flex-wrap items-end gap-3 rounded-lg border p-3"
        style={{
          borderColor: "var(--console-border)",
          background: "var(--console-panel)",
        }}
      >
        <ViewToggle view={view} setView={setView} />
        <DateField label="From" value={since} onChange={setSince} />
        <DateField label="To" value={until} onChange={setUntil} />
      </div>

      {view === "log" ? (
        <LogView since={since} until={until} camMap={camMap} slug={scenario?.slug || "frs"} />
      ) : (
        <ReportView since={since} until={until} />
      )}
    </div>
  );
}
