// =============================================================================
// AI · Transit tab (FRS) — entry→exit dwell-time tracking for recognized faces.
// =============================================================================
// Mirrors the vizor-app Transit layout: a single page with two sub-tabs.
//
//   SESSIONS  — KPI cards (open / overdue / closed) + a table of transit
//               sessions (person, rule, status badge, opened, closed, duration)
//               with a status filter.
//   RULES     — a "create rule" form (name, entry camera, exit cameras, window
//               minutes, enabled) + a table of existing rules with edit/delete.
//
// NVR stays thin — rules + sessions live in the FRS scenario db, reached through
// the scenario proxy (api/ai). Rule shape per scenarios/frs/routers/transit.py:
//   rule    = { id, name, config, enabled }  (camera pairing lives in config)
//   session = { id, rule_id, person_id, status, started_at, ended_at, attributes }
// Camera ids are NVR camera ids (the bridge maps cameras↔streams by id).
// =============================================================================

import React, { useMemo, useState, useEffect } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import {
  ArrowLeftRight,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  X,
  Power,
  PowerOff,
  ListChecks,
  Clock,
  ImageOff,
} from "lucide-react";
import { toast } from "sonner";
import { friendlyError } from "../../../../lib/utils";
import { formatDateTime } from "../../../../lib/datetime";

import {
  listTransitRules,
  createTransitRule,
  updateTransitRule,
  deleteTransitRule,
  listTransitSessions,
  scenarioSnapshotUrl,
} from "../../../../api/ai";
import { useConfirm } from "../../../../components/ui/confirm";
import { getAllCameras } from "../../../../api/cameras";

const FRS_SLUG = "frs";

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};
const inputCls = "w-full rounded px-2.5 py-1.5 font-telemetry text-[12px] outline-none";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
  { value: "overdue", label: "Overdue" },
];

const STATUS_COLOR = {
  open: "var(--console-accent)",
  closed: "var(--console-muted)",
  overdue: "var(--console-rec)",
};

// The backend nests the camera pairing inside `config`; older rows may have the
// fields flat. Read defensively from either place.
const ruleCfg = (rule) => ({ ...(rule || {}), ...((rule && rule.config) || {}) });

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return formatDateTime(iso);
  } catch {
    return iso;
  }
}

function fmtDuration(startedAt, endedAt) {
  if (!startedAt) return "—";
  const start = new Date(startedAt).getTime();
  const end = endedAt ? new Date(endedAt).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "—";
  const secs = Math.floor((end - start) / 1000);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

// Authenticated snapshot thumbnail — <img src> can't send the bearer token, so
// fetch the bytes via scenarioSnapshotUrl and render an object URL (revoked on
// unmount). Mirrors the Investigate tab's HitThumb.
function AuthImg({ snapshotKey, label }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    if (!snapshotKey) { setUrl(null); return undefined; }
    let active = true;
    let obj = null;
    scenarioSnapshotUrl(FRS_SLUG, snapshotKey).then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      obj = u;
      setUrl(u);
    });
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
  }, [snapshotKey]);
  return (
    <div className="flex flex-col gap-1.5">
      <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        {label}
      </span>
      <div
        className="w-full aspect-video rounded flex items-center justify-center overflow-hidden"
        style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
      >
        {url ? (
          <img src={url} alt={label} className="w-full h-full object-cover" />
        ) : (
          <ImageOff className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
        )}
      </div>
    </div>
  );
}

// Session detail modal — who, the rule, entry/exit time + camera, duration, and
// the entry/exit snapshots. Mirrors vizor-app's SessionDetailModal.
const SessionDetailModal = ({ session: s, ruleName, camName, onClose }) => {
  const personLabel =
    s.person_name || (s.person_id ? `Person ${String(s.person_id).slice(0, 8)}` : "—");
  const dur = s.duration_seconds != null
    ? fmtDuration(s.started_at, s.ended_at || (s.started_at && new Date(new Date(s.started_at).getTime() + s.duration_seconds * 1000).toISOString()))
    : fmtDuration(s.started_at, s.ended_at);
  const Row = ({ label, value, mono }) => (
    <div className="flex items-center justify-between gap-3">
      <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
        {label}
      </span>
      <span
        className={`font-telemetry text-[12px] truncate ${mono ? "tabular-nums" : ""}`}
        style={{ color: "var(--console-text)" }}
      >
        {value}
      </span>
    </div>
  );
  return (
    <Modal title="Transit session" onClose={onClose}>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="flex flex-col gap-2.5">
          <Row label="Person" value={personLabel} />
          <Row label="Person ID" value={s.person_id || "—"} mono />
          <Row label="Rule" value={ruleName(s.rule_id) || s.rule_name || "—"} />
          <Row label="Status" value={<StatusBadge status={s.status} />} />
          <Row label="Duration" value={dur} />
          <Row label="Entry camera" value={camName ? camName(s.entry_camera) : (s.entry_camera || "—")} />
          <Row label="Entry time" value={fmtTime(s.started_at)} />
          <Row label="Exit camera" value={s.exit_camera ? (camName ? camName(s.exit_camera) : s.exit_camera) : "— (no exit)"} />
          <Row label="Exit time" value={fmtTime(s.ended_at)} />
        </div>
        <div className="flex flex-col gap-3">
          <AuthImg snapshotKey={s.entry_snapshot} label="Entry snapshot" />
          <AuthImg snapshotKey={s.exit_snapshot} label="Exit snapshot" />
        </div>
      </div>
    </Modal>
  );
};

// ---------------------------------------------------------------------------
// shared primitives
// ---------------------------------------------------------------------------

const Field = ({ label, children }) => (
  <div className="flex flex-col gap-1.5">
    <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
      {label}
    </label>
    {children}
  </div>
);

const Modal = ({ title, onClose, children }) => (
  <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }}>
    <div
      className="w-full max-w-md rounded p-5 flex flex-col gap-4"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      <div className="flex items-center justify-between">
        <h3 className="font-telemetry text-[13px] font-semibold uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
          {title}
        </h3>
        <button type="button" onClick={onClose} className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70" style={{ color: "var(--console-muted)" }}>
          <X className="h-4 w-4" />
        </button>
      </div>
      {children}
    </div>
  </div>
);

const StatusBadge = ({ status }) => {
  const color = STATUS_COLOR[status] || "var(--console-muted)";
  return (
    <span
      className="inline-flex items-center font-telemetry text-[10px] uppercase tracking-widest px-1.5 py-0.5 rounded border"
      style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color }}
    >
      {status || "—"}
    </span>
  );
};

const SubTab = ({ active, onClick, icon: Icon, label, count }) => (
  <button
    type="button"
    onClick={onClick}
    className="inline-flex items-center gap-1.5 font-telemetry text-[11px] uppercase tracking-widest px-3 py-2 border-b-2 -mb-px transition-colors"
    style={{
      borderColor: active ? "var(--console-accent)" : "transparent",
      color: active ? "var(--console-text)" : "var(--console-muted)",
    }}
  >
    <Icon className="h-3.5 w-3.5" />
    {label}
    {typeof count === "number" && (
      <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>· {count}</span>
    )}
  </button>
);

// ---------------------------------------------------------------------------
// rule create / edit form (modal)
// ---------------------------------------------------------------------------

const RuleForm = ({ initial, cameras, onClose, qc }) => {
  const editing = !!initial;
  const cfg = ruleCfg(initial);
  const [form, setForm] = useState({
    name: cfg.name || "",
    entry_camera: cfg.entry_camera || "",
    exit_cameras: cfg.exit_cameras || [],
    window_minutes: cfg.window_minutes ?? 15,
    enabled: initial?.enabled ?? true,
  });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const toggleExit = (id) =>
    setForm((f) => ({
      ...f,
      exit_cameras: f.exit_cameras.includes(id)
        ? f.exit_cameras.filter((x) => x !== id)
        : [...f.exit_cameras, id],
    }));

  const mut = useMutation({
    mutationFn: () => {
      const config = {
        entry_camera: form.entry_camera,
        exit_cameras: form.exit_cameras,
        window_minutes: Number(form.window_minutes) || 0,
      };
      const payload = {
        name: form.name.trim(),
        enabled: !!form.enabled,
        config,
      };
      return editing ? updateTransitRule(initial.id, payload) : createTransitRule(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-transit-rules"] });
      toast.success(editing ? "Rule updated" : "Rule created");
      onClose();
    },
    onError: (e) => toast.error(friendlyError(e, "Failed to save rule")),
  });

  const submit = () => {
    if (!form.name.trim()) return toast.error("Rule name is required");
    if (!form.entry_camera) return toast.error("Entry camera is required");
    if (form.exit_cameras.length === 0) return toast.error("Pick at least one exit camera");
    mut.mutate();
  };

  const exitCandidates = cameras.filter((c) => c.id !== form.entry_camera);

  return (
    <Modal title={editing ? "Edit transit rule" : "New transit rule"} onClose={onClose}>
      <Field label="Rule name">
        <input className={inputCls} style={inputStyle} placeholder="Gate A → Gate B transit" value={form.name} onChange={(e) => set("name", e.target.value)} autoFocus />
      </Field>
      <Field label="Entry camera">
        <select className={inputCls} style={inputStyle} value={form.entry_camera} onChange={(e) => set("entry_camera", e.target.value)}>
          <option value="">— select —</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name || c.id}
            </option>
          ))}
        </select>
      </Field>
      <Field label={`Exit cameras (any of) · selected ${form.exit_cameras.length}`}>
        <div
          className="rounded p-2 max-h-40 overflow-auto flex flex-col gap-1"
          style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
        >
          {exitCandidates.length === 0 ? (
            <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
              No cameras available
            </span>
          ) : (
            exitCandidates.map((c) => {
              const checked = form.exit_cameras.includes(c.id);
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => toggleExit(c.id)}
                  className="flex items-center gap-2 text-left rounded px-2 py-1 font-telemetry text-[12px] transition-colors hover:brightness-125"
                  style={{ color: checked ? "var(--console-text)" : "var(--console-muted)" }}
                >
                  <span
                    className="h-3.5 w-3.5 rounded-sm shrink-0 inline-flex items-center justify-center"
                    style={{
                      border: "1px solid var(--console-border)",
                      background: checked ? "var(--console-accent)" : "transparent",
                    }}
                  >
                    {checked && <span className="h-1.5 w-1.5 rounded-sm" style={{ background: "#fff" }} />}
                  </span>
                  {c.name || c.id}
                </button>
              );
            })
          )}
        </div>
      </Field>
      <div className="grid grid-cols-2 gap-3 items-end">
        <Field label="Deadline (minutes)">
          <input type="number" min={1} max={1440} className={inputCls} style={inputStyle} value={form.window_minutes} onChange={(e) => set("window_minutes", e.target.value)} />
        </Field>
        <button
          type="button"
          onClick={() => set("enabled", !form.enabled)}
          className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-2 rounded border"
          style={{
            background: "var(--console-raised)",
            borderColor: "var(--console-border)",
            color: form.enabled ? "var(--console-accent)" : "var(--console-muted)",
          }}
        >
          {form.enabled ? <Power className="h-3.5 w-3.5" /> : <PowerOff className="h-3.5 w-3.5" />}
          {form.enabled ? "Enabled" : "Disabled"}
        </button>
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onClose} className="font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}>
          Cancel
        </button>
        <button type="button" onClick={submit} disabled={mut.isPending} className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded disabled:opacity-50" style={{ background: "var(--console-accent)", color: "#fff" }}>
          {mut.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
          {editing ? "Save" : "Create"}
        </button>
      </div>
    </Modal>
  );
};

// ---------------------------------------------------------------------------
// RULES sub-tab
// ---------------------------------------------------------------------------

const RulesPanel = ({ rules, rulesLoading, cameras, camName, qc }) => {
  const confirm = useConfirm();
  const [modal, setModal] = useState(null); // null | "create" | rule

  const delMut = useMutation({
    mutationFn: (id) => deleteTransitRule(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-transit-rules"] });
      toast.success("Rule deleted");
    },
    onError: (e) => toast.error(friendlyError(e, "Failed to delete rule")),
  });

  const onDelete = (rule) => {
    confirm({
      title: "Delete rule?",
      description: `"${rule.name}" — open sessions stay until they close.`,
      confirmText: "Delete",
      danger: true,
    }).then((ok) => { if (ok) delMut.mutate(rule.id); });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <p className="font-telemetry text-[11px] max-w-2xl leading-relaxed" style={{ color: "var(--console-muted)" }}>
          Define entry→exit camera pairs with a deadline. A person recognized at the entry camera
          must reach any exit camera within the window — otherwise the session goes overdue.
        </p>
        <button
          type="button"
          onClick={() => setModal("create")}
          className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded shrink-0"
          style={{ background: "var(--console-accent)", color: "#fff" }}
        >
          <Plus className="h-3.5 w-3.5" />
          New rule
        </button>
      </div>

      {rulesLoading ? (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
        </div>
      ) : rules.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-12 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
          <ArrowLeftRight className="h-7 w-7" style={{ color: "var(--console-muted)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            No transit rules yet
          </span>
          <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
            Create one to enforce entry→exit dwell time for recognized faces.
          </span>
        </div>
      ) : (
        <div className="rounded overflow-hidden" style={{ border: "1px solid var(--console-border)" }}>
          <table className="w-full text-left">
            <thead>
              <tr
                className="font-telemetry text-[10px] uppercase tracking-wider"
                style={{ background: "var(--console-raised)", color: "var(--console-muted)" }}
              >
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Entry</th>
                <th className="px-3 py-2 font-medium">Exits</th>
                <th className="px-3 py-2 font-medium">Window</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => {
                const cfg = ruleCfg(r);
                return (
                  <tr key={r.id} className="border-t hover:bg-white/[0.02] transition-colors" style={{ borderColor: "var(--console-border)" }}>
                    <td className="px-3 py-2 font-telemetry text-[12px] font-semibold truncate max-w-[160px]" style={{ color: "var(--console-text)" }}>
                      {r.name}
                    </td>
                    <td className="px-3 py-2 font-telemetry text-[12px] truncate max-w-[140px]" style={{ color: "var(--console-muted)" }}>
                      {camName(cfg.entry_camera)}
                    </td>
                    <td className="px-3 py-2 font-telemetry text-[12px] truncate max-w-[180px]" style={{ color: "var(--console-muted)" }}>
                      {(cfg.exit_cameras || []).map(camName).join(", ") || "—"}
                    </td>
                    <td className="px-3 py-2 font-telemetry text-[12px] tabular-nums whitespace-nowrap" style={{ color: "var(--console-text)" }}>
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" style={{ color: "var(--console-muted)" }} />
                        {cfg.window_minutes ?? "—"}m
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className="font-telemetry text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded border"
                        style={{
                          background: "var(--console-raised)",
                          borderColor: "var(--console-border)",
                          color: r.enabled ? "var(--console-accent)" : "var(--console-muted)",
                        }}
                      >
                        {r.enabled ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right whitespace-nowrap">
                      <button type="button" onClick={() => setModal(r)} className="h-7 w-7 inline-flex items-center justify-center rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }} title="Edit">
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" onClick={() => onDelete(r)} disabled={delMut.isPending} className="h-7 w-7 ml-1.5 inline-flex items-center justify-center rounded border disabled:opacity-50" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-rec)" }} title="Delete">
                        {delMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {modal && (
        <RuleForm
          initial={modal === "create" ? null : modal}
          cameras={cameras}
          qc={qc}
          onClose={() => setModal(null)}
        />
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// SESSIONS sub-tab
// ---------------------------------------------------------------------------

const SessionsPanel = ({ ruleName }) => {
  const [statusFilter, setStatusFilter] = useState("");
  const [detail, setDetail] = useState(null);

  const sessionParams = useMemo(() => {
    const p = { limit: 200, offset: 0 };
    if (statusFilter) p.status = statusFilter;
    return p;
  }, [statusFilter]);

  // KPI cards always reflect totals across all statuses, independent of the
  // active filter — so fetch an unfiltered set for the counts.
  const { data: allData } = useQuery({
    queryKey: ["frs-transit-sessions", { limit: 500, offset: 0 }],
    queryFn: () => listTransitSessions({ limit: 500, offset: 0 }),
    placeholderData: keepPreviousData,
  });
  const allSessions = allData?.sessions || [];

  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ["frs-transit-sessions", sessionParams],
    queryFn: () => listTransitSessions(sessionParams),
    placeholderData: keepPreviousData,
  });
  const sessions = sessionsData?.sessions || [];

  const stats = useMemo(() => {
    const s = { open: 0, overdue: 0, closed: 0 };
    allSessions.forEach((sess) => {
      if (sess.status in s) s[sess.status] += 1;
    });
    return s;
  }, [allSessions]);

  const KPI_CARDS = [
    { key: "open", label: "Open", value: stats.open, color: "var(--console-accent)" },
    { key: "overdue", label: "Overdue", value: stats.overdue, color: "var(--console-rec)" },
    { key: "closed", label: "Closed", value: stats.closed, color: "var(--console-online)" },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* KPI cards */}
      <div className="grid grid-cols-3 gap-3">
        {KPI_CARDS.map((kpi) => (
          <div
            key={kpi.key}
            className="rounded-lg p-3 flex flex-col gap-1"
            style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
          >
            <div className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              {kpi.label}
            </div>
            <div className="font-telemetry text-2xl font-semibold tabular-nums" style={{ color: kpi.color }}>
              {kpi.value}
            </div>
          </div>
        ))}
      </div>

      {/* Status filter */}
      <div className="flex items-center gap-2 flex-wrap">
        {STATUS_OPTIONS.map((o) => {
          const active = statusFilter === o.value;
          return (
            <button
              key={o.value || "all"}
              type="button"
              onClick={() => setStatusFilter(o.value)}
              className="font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded border transition-colors"
              style={{
                background: active ? "var(--console-accent)" : "var(--console-raised)",
                borderColor: active ? "var(--console-accent)" : "var(--console-border)",
                color: active ? "#fff" : "var(--console-muted)",
              }}
            >
              {o.label}
            </button>
          );
        })}
        <span className="ml-auto font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
          {sessionsData?.total ?? sessions.length} session{(sessionsData?.total ?? sessions.length) === 1 ? "" : "s"}
        </span>
      </div>

      {/* Sessions table */}
      <div className="rounded overflow-hidden" style={{ border: "1px solid var(--console-border)" }}>
        <table className="w-full text-left">
          <thead>
            <tr
              className="font-telemetry text-[10px] uppercase tracking-wider"
              style={{ background: "var(--console-raised)", color: "var(--console-muted)" }}
            >
              <th className="px-3 py-2 font-medium">Person</th>
              <th className="px-3 py-2 font-medium">Rule</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Opened</th>
              <th className="px-3 py-2 font-medium">Closed</th>
              <th className="px-3 py-2 font-medium">Duration</th>
            </tr>
          </thead>
          <tbody>
            {sessionsLoading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                  <td colSpan={6} className="px-3 py-3">
                    <div className="h-5 rounded animate-pulse bg-zinc-800/60" />
                  </td>
                </tr>
              ))
            ) : sessions.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-12 text-center">
                  <ListChecks className="h-8 w-8 mx-auto mb-2" style={{ color: "var(--console-muted)" }} />
                  <p className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
                    No transit sessions
                  </p>
                  <p className="font-telemetry text-[10px] mt-1" style={{ color: "var(--console-muted)" }}>
                    Sessions appear as recognized faces hit configured entry cameras.
                  </p>
                </td>
              </tr>
            ) : (
              sessions.map((s) => (
                <tr
                  key={s.id}
                  onClick={() => setDetail(s)}
                  className="border-t hover:bg-white/[0.02] transition-colors cursor-pointer"
                  style={{ borderColor: "var(--console-border)" }}
                >
                  <td className="px-3 py-2 font-telemetry text-[12px] truncate max-w-[160px]" style={{ color: "var(--console-text)" }}>
                    {s.person_name
                      || s.attributes?.person_name
                      || (s.person_id ? `Person ${String(s.person_id).slice(0, 8)}` : "—")}
                  </td>
                  <td className="px-3 py-2 font-telemetry text-[12px] truncate max-w-[160px]" style={{ color: "var(--console-text)" }}>
                    {ruleName(s.rule_id)}
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge status={s.status} />
                  </td>
                  <td className="px-3 py-2 font-telemetry text-[11px] whitespace-nowrap" style={{ color: "var(--console-muted)" }}>
                    {fmtTime(s.started_at)}
                  </td>
                  <td className="px-3 py-2 font-telemetry text-[11px] whitespace-nowrap" style={{ color: "var(--console-muted)" }}>
                    {fmtTime(s.ended_at)}
                  </td>
                  <td className="px-3 py-2 font-telemetry text-[11px] whitespace-nowrap" style={{ color: "var(--console-muted)" }}>
                    {fmtDuration(s.started_at, s.ended_at)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {detail && (
        <SessionDetailModal
          session={detail}
          ruleName={ruleName}
          onClose={() => setDetail(null)}
        />
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// tab shell
// ---------------------------------------------------------------------------

const TransitTab = () => {
  const qc = useQueryClient();
  const [sub, setSub] = useState("sessions"); // "sessions" | "rules"

  const { data: cameras = [] } = useQuery({
    queryKey: ["cameras", "all"],
    queryFn: getAllCameras,
  });
  const camNameMap = useMemo(() => {
    const m = {};
    (cameras || []).forEach((c) => {
      m[c.id] = c.name || c.id;
    });
    return m;
  }, [cameras]);
  const camName = (id) => camNameMap[id] || id || "—";

  const { data: rulesData, isLoading: rulesLoading } = useQuery({
    queryKey: ["frs-transit-rules"],
    queryFn: listTransitRules,
  });
  const rules = rulesData?.rules || [];
  const ruleName = (id) => rules.find((r) => r.id === id)?.name || id || "—";

  return (
    <div className="p-6 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center gap-2">
        <ArrowLeftRight className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
        <span className="font-telemetry text-[13px] font-semibold uppercase tracking-widest" style={{ color: "var(--console-text)" }}>
          Transit
        </span>
        <span className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          · Entry→exit dwell-time tracking
        </span>
      </div>

      {/* Sub-tab switch */}
      <div className="flex items-center gap-1 border-b" style={{ borderColor: "var(--console-border)" }}>
        <SubTab active={sub === "sessions"} onClick={() => setSub("sessions")} icon={ListChecks} label="Sessions" />
        <SubTab active={sub === "rules"} onClick={() => setSub("rules")} icon={ArrowLeftRight} label="Rules" count={rules.length} />
      </div>

      {sub === "sessions" ? (
        <SessionsPanel ruleName={ruleName} />
      ) : (
        <RulesPanel
          rules={rules}
          rulesLoading={rulesLoading}
          cameras={cameras}
          camName={camName}
          qc={qc}
        />
      )}
    </div>
  );
};

export default TransitTab;
