// =============================================================================
// AI · FRS · Reports — the four operator reports + CSV/Excel export + scheduling.
//   1. Attendance        : First-In, Last-Out, Duration (per person/day)
//   2. Group             : Headcount, Attendance Compliance %
//   3. Entry/Exit Mismatch: Unpaired vs Resolved transit sessions
//   4. Unknown Attempts   : count + snapshots of face_unknown events
// Each can be exported (CSV/XLSX) and scheduled (email + in-system download).
// =============================================================================

import React, { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import {
  CalendarClock, Download, FileSpreadsheet, FileText, Loader2, Mail,
  Play, Plus, Trash2, Users, UserX, ArrowLeftRight, ClipboardList,
} from "lucide-react";

import {
  frsReport, frsReportExportUrl, listReportSchedules, createReportSchedule,
  deleteReportSchedule, runReportSchedule, listReportRuns, reportRunDownloadUrl,
} from "../../../../api/ai";

const REPORTS = [
  { key: "attendance", label: "Attendance", icon: ClipboardList,
    desc: "First-In, Last-Out, Duration" },
  { key: "group", label: "Group", icon: Users,
    desc: "Headcount, Attendance Compliance" },
  { key: "mismatch", label: "Entry / Exit Mismatch", icon: ArrowLeftRight,
    desc: "Unpaired vs Resolved" },
  { key: "unknown", label: "Unknown Attempts", icon: UserX,
    desc: "Count + Snapshots" },
];

function todayISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function saveBlobUrl(url, name) {
  if (!url) return;
  const a = document.createElement("a");
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

// Render an ISO timestamp as a short local time; pass other cells through.
const ISO_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;
function renderCell(col, val) {
  if (val == null || val === "") return "—";
  if (typeof val === "string" && ISO_RE.test(val)) {
    const d = new Date(val);
    if (!isNaN(d)) return d.toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  if (col === "compliance_pct") return `${val}%`;
  return String(val);
}

export default function ReportsTab() {
  const qc = useQueryClient();
  const [active, setActive] = useState("attendance");
  const [dayFrom, setDayFrom] = useState(todayISO(-6));
  const [dayTo, setDayTo] = useState(todayISO(0));

  const { data, isFetching } = useQuery({
    queryKey: ["frs", "report", active, dayFrom, dayTo],
    queryFn: () => frsReport(active, { day_from: dayFrom, day_to: dayTo }),
    placeholderData: keepPreviousData,
  });
  const columns = data?.columns || [];
  const rows = data?.items || [];

  const doExport = async (format) => {
    const url = await frsReportExportUrl(active, { day_from: dayFrom, day_to: dayTo, format });
    saveBlobUrl(url, `${active}_${dayFrom}_${dayTo}.${format === "csv" ? "csv" : "xlsx"}`);
  };

  return (
    <div className="h-full overflow-y-auto px-4 py-4 md:px-6 space-y-4">
      {/* Report selector */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {REPORTS.map((r) => {
          const Icon = r.icon;
          const on = active === r.key;
          return (
            <button key={r.key} type="button" onClick={() => setActive(r.key)}
              className="rounded-lg border p-3 text-left transition-colors"
              style={{
                borderColor: on ? "var(--console-accent)" : "var(--console-border)",
                background: on ? "var(--console-raised)" : "var(--console-panel)",
              }}>
              <div className="flex items-center gap-2">
                <Icon className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
                <span className="text-sm font-medium">{r.label}</span>
              </div>
              <p className="text-[11px] mt-1" style={{ color: "var(--console-muted)" }}>{r.desc}</p>
            </button>
          );
        })}
      </div>

      {/* Date range + export */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border p-3"
        style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
        <div>
          <label className="block text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--console-muted)" }}>From</label>
          <input type="date" value={dayFrom} max={dayTo} onChange={(e) => setDayFrom(e.target.value)}
            className="rounded-md border px-2 py-1.5 text-sm bg-transparent"
            style={{ borderColor: "var(--console-border)", colorScheme: "dark" }} />
        </div>
        <div>
          <label className="block text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--console-muted)" }}>To</label>
          <input type="date" value={dayTo} min={dayFrom} max={todayISO(0)} onChange={(e) => setDayTo(e.target.value)}
            className="rounded-md border px-2 py-1.5 text-sm bg-transparent"
            style={{ borderColor: "var(--console-border)", colorScheme: "dark" }} />
        </div>
        <div className="flex-1" />
        <button type="button" onClick={() => doExport("csv")}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-white/[0.04]"
          style={{ borderColor: "var(--console-border)" }}>
          <FileText className="h-4 w-4" /> CSV
        </button>
        <button type="button" onClick={() => doExport("xlsx")}
          className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm hover:bg-white/[0.04]"
          style={{ borderColor: "var(--console-border)" }}>
          <FileSpreadsheet className="h-4 w-4" /> Excel
        </button>
      </div>

      {/* Table */}
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
        <div className="px-3 py-2 flex items-center justify-between" style={{ background: "var(--console-raised)" }}>
          <span className="text-xs font-telemetry uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            {REPORTS.find((r) => r.key === active)?.label} · {rows.length} rows
          </span>
          {isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin" style={{ color: "var(--console-muted)" }} />}
        </div>
        <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0" style={{ background: "var(--console-panel)" }}>
              <tr>
                {columns.map((c) => (
                  <th key={c} className="px-3 py-2 text-left text-[10px] uppercase tracking-widest font-telemetry"
                    style={{ color: "var(--console-muted)", borderBottom: "1px solid var(--console-border)" }}>
                    {c.replace(/_/g, " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr><td colSpan={columns.length || 1} className="px-3 py-8 text-center text-sm"
                  style={{ color: "var(--console-muted)" }}>No data for this range.</td></tr>
              ) : rows.map((row, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                  {columns.map((c) => (
                    <td key={c} className="px-3 py-2 whitespace-nowrap" style={{ color: "var(--console-text)" }}>
                      {c === "snapshot"
                        ? (row[c]
                          ? <span className="text-[11px] inline-flex items-center gap-1" style={{ color: "var(--console-accent)" }}>● captured</span>
                          : <span className="text-[11px]" style={{ color: "var(--console-muted)" }}>—</span>)
                        : renderCell(c, row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <SchedulesPanel qc={qc} />
    </div>
  );
}

// ── Scheduling: create/list/run/delete + recent generated files ────────────
function SchedulesPanel({ qc }) {
  const [form, setForm] = useState({
    name: "", report: "attendance", fmt: "xlsx", frequency: "daily",
    at_time: "08:00", range_days: 7, recipients: "",
  });
  const { data: schedules } = useQuery({ queryKey: ["frs", "report-schedules"], queryFn: listReportSchedules });
  const { data: runs } = useQuery({ queryKey: ["frs", "report-runs"], queryFn: () => listReportRuns(20) });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["frs", "report-schedules"] });
    qc.invalidateQueries({ queryKey: ["frs", "report-runs"] });
  };
  const createM = useMutation({ mutationFn: createReportSchedule, onSuccess: refresh });
  const delM = useMutation({ mutationFn: deleteReportSchedule, onSuccess: refresh });
  const runM = useMutation({ mutationFn: runReportSchedule, onSuccess: refresh });

  const downloadRun = async (r) => {
    const url = await reportRunDownloadUrl(r.id, r.fmt);
    saveBlobUrl(url, r.filename);
  };

  return (
    <div className="rounded-lg border p-4 space-y-4" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
      <div className="flex items-center gap-2">
        <CalendarClock className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
        <span className="text-sm font-medium">Scheduled reports</span>
        <span className="text-[11px]" style={{ color: "var(--console-muted)" }}>email at the set time + download here</span>
      </div>

      {/* Create form */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 items-end">
        <Field label="Name"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Daily attendance" className="w-full rounded border px-2 py-1.5 text-sm bg-transparent" style={{ borderColor: "var(--console-border)" }} /></Field>
        <Field label="Report"><select value={form.report} onChange={(e) => setForm({ ...form, report: e.target.value })}
          className="w-full rounded border px-2 py-1.5 text-sm bg-transparent" style={{ borderColor: "var(--console-border)", colorScheme: "dark" }}>
          {REPORTS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
        </select></Field>
        <Field label="Format"><select value={form.fmt} onChange={(e) => setForm({ ...form, fmt: e.target.value })}
          className="w-full rounded border px-2 py-1.5 text-sm bg-transparent" style={{ borderColor: "var(--console-border)", colorScheme: "dark" }}>
          <option value="xlsx">Excel</option><option value="csv">CSV</option>
        </select></Field>
        <Field label="Frequency"><select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })}
          className="w-full rounded border px-2 py-1.5 text-sm bg-transparent" style={{ borderColor: "var(--console-border)", colorScheme: "dark" }}>
          <option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option>
        </select></Field>
        <Field label="Time"><input type="time" value={form.at_time} onChange={(e) => setForm({ ...form, at_time: e.target.value })}
          className="w-full rounded border px-2 py-1.5 text-sm bg-transparent" style={{ borderColor: "var(--console-border)", colorScheme: "dark" }} /></Field>
        <Field label="Range (days)"><input type="number" min={1} value={form.range_days} onChange={(e) => setForm({ ...form, range_days: Number(e.target.value) })}
          className="w-full rounded border px-2 py-1.5 text-sm bg-transparent" style={{ borderColor: "var(--console-border)" }} /></Field>
        <Field label="Recipients"><input value={form.recipients} onChange={(e) => setForm({ ...form, recipients: e.target.value })}
          placeholder="a@x.com, b@y.com" className="w-full rounded border px-2 py-1.5 text-sm bg-transparent" style={{ borderColor: "var(--console-border)" }} /></Field>
      </div>
      <button type="button" disabled={createM.isPending || !form.name}
        onClick={() => createM.mutate(form)}
        className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
        style={{ background: "var(--console-accent)", color: "#fff" }}>
        <Plus className="h-4 w-4" /> Add schedule
      </button>

      {/* Existing schedules */}
      <div className="space-y-1.5">
        {(schedules?.items || []).map((s) => (
          <div key={s.id} className="flex items-center gap-3 rounded border px-3 py-2 text-sm" style={{ borderColor: "var(--console-border)" }}>
            <span className="font-medium">{s.name}</span>
            <span className="text-[11px]" style={{ color: "var(--console-muted)" }}>{s.report} · {s.frequency} {s.at_time} · {s.fmt}</span>
            {s.recipients && <span className="text-[11px] inline-flex items-center gap-1" style={{ color: "var(--console-muted)" }}><Mail className="h-3 w-3" />{s.recipients}</span>}
            <span className="flex-1" />
            <span className="text-[11px]" style={{ color: "var(--console-muted)" }}>next {s.next_run_at ? new Date(s.next_run_at).toLocaleString() : "—"}</span>
            <button type="button" title="Run now" onClick={() => runM.mutate(s.id)} className="p-1 hover:opacity-70"><Play className="h-4 w-4" /></button>
            <button type="button" title="Delete" onClick={() => delM.mutate(s.id)} className="p-1 hover:opacity-70"><Trash2 className="h-4 w-4" style={{ color: "#f87171" }} /></button>
          </div>
        ))}
        {(schedules?.items || []).length === 0 && <p className="text-[11px]" style={{ color: "var(--console-muted)" }}>No schedules yet.</p>}
      </div>

      {/* Recent generated files */}
      {(runs?.items || []).length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-widest mb-1.5" style={{ color: "var(--console-muted)" }}>Recent files</div>
          <div className="space-y-1">
            {(runs.items || []).map((r) => (
              <div key={r.id} className="flex items-center gap-3 text-sm">
                <span>{r.report}</span>
                <span className="text-[11px]" style={{ color: "var(--console-muted)" }}>{r.rows} rows · {new Date(r.created_at).toLocaleString()}</span>
                {r.emailed_to && <span className="text-[11px] inline-flex items-center gap-1" style={{ color: r.email_ok ? "#34d399" : "#fbbf24" }}><Mail className="h-3 w-3" />{r.email_ok ? "sent" : "email off"}</span>}
                <span className="flex-1" />
                <button type="button" onClick={() => downloadRun(r)} className="inline-flex items-center gap-1 text-[12px] hover:opacity-70" style={{ color: "var(--console-accent)" }}>
                  <Download className="h-3.5 w-3.5" /> download
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-widest mb-1" style={{ color: "var(--console-muted)" }}>{label}</label>
      {children}
    </div>
  );
}
