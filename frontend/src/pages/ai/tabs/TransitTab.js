// =============================================================================
// AI · Transit tab (FRS) — transit rules (CRUD) + transit sessions.
// =============================================================================
// Rules: name, entry camera, one-or-more exit cameras, window (minutes), enabled
// toggle. CRUD proxies through /api/ai/frs/transit/rules to the FRS scenario.
// Sessions: a read-only table of open/closed/overdue transit sessions with a
// status filter, fed by /api/ai/frs/transit/sessions.
//
// NVR stays thin — rules + sessions live in the FRS scenario db. Camera ids are
// NVR camera ids (the bridge maps cameras↔streams by id).
// =============================================================================

import React, { useMemo, useState } from "react";
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
} from "lucide-react";
import { toast } from "sonner";
import { format } from "date-fns";

import {
  listTransitRules,
  createTransitRule,
  updateTransitRule,
  deleteTransitRule,
  listTransitSessions,
} from "../../../api/ai";
import { useConfirm } from "../../../components/ui/confirm";
import { getAllCameras } from "../../../api/cameras";

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

function fmtTime(iso) {
  if (!iso) return "—";
  try {
    return format(new Date(iso), "MMM d, HH:mm:ss");
  } catch {
    return iso;
  }
}

function fmtDuration(openedAt, closedAt) {
  if (!openedAt) return "—";
  const start = new Date(openedAt).getTime();
  const end = closedAt ? new Date(closedAt).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "—";
  const secs = Math.floor((end - start) / 1000);
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

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

// ---------------------------------------------------------------------------
// rule create / edit form
// ---------------------------------------------------------------------------

const RuleForm = ({ initial, cameras, onClose, qc }) => {
  const editing = !!initial;
  const [form, setForm] = useState({
    name: initial?.name || "",
    entry_camera: initial?.entry_camera || "",
    exit_cameras: initial?.exit_cameras || [],
    window_minutes: initial?.window_minutes ?? 15,
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
      const payload = {
        name: form.name.trim(),
        entry_camera: form.entry_camera,
        exit_cameras: form.exit_cameras,
        window_minutes: Number(form.window_minutes) || 0,
        enabled: !!form.enabled,
      };
      return editing ? updateTransitRule(initial.id, payload) : createTransitRule(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-transit-rules"] });
      toast.success(editing ? "Rule updated" : "Rule created");
      onClose();
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to save rule"),
  });

  const submit = () => {
    if (!form.name.trim()) return toast.error("Rule name is required");
    if (!form.entry_camera) return toast.error("Entry camera is required");
    if (form.exit_cameras.length === 0) return toast.error("Pick at least one exit camera");
    mut.mutate();
  };

  return (
    <Modal title={editing ? "Edit transit rule" : "Add transit rule"} onClose={onClose}>
      <Field label="Name">
        <input className={inputCls} style={inputStyle} value={form.name} onChange={(e) => set("name", e.target.value)} autoFocus />
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
      <Field label="Exit cameras">
        <div
          className="rounded p-2 max-h-40 overflow-auto flex flex-col gap-1"
          style={{ background: "var(--console-raised)", border: "1px solid var(--console-border)" }}
        >
          {cameras.length === 0 ? (
            <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>
              No cameras
            </span>
          ) : (
            cameras.map((c) => {
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
        <Field label="Window (minutes)">
          <input type="number" min={1} className={inputCls} style={inputStyle} value={form.window_minutes} onChange={(e) => set("window_minutes", e.target.value)} />
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
// rule row
// ---------------------------------------------------------------------------

const RuleRow = ({ rule, camName, onEdit, qc }) => {
  const confirm = useConfirm();
  const delMut = useMutation({
    mutationFn: () => deleteTransitRule(rule.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-transit-rules"] });
      toast.success("Rule deleted");
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Failed to delete rule"),
  });

  const onDelete = () => {
    confirm({ title: `Delete transit rule "${rule.name}"?`, confirmText: "Delete", danger: true })
      .then((ok) => { if (ok) delMut.mutate(); });
  };

  return (
    <div
      className="rounded p-3 flex items-center gap-3"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-telemetry text-[12px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
            {rule.name}
          </span>
          <span
            className="font-telemetry text-[9px] uppercase tracking-widest px-1.5 py-0.5 rounded border"
            style={{
              background: "var(--console-raised)",
              borderColor: "var(--console-border)",
              color: rule.enabled ? "var(--console-accent)" : "var(--console-muted)",
            }}
          >
            {rule.enabled ? "Enabled" : "Disabled"}
          </span>
        </div>
        <div className="font-telemetry text-[10px] uppercase tracking-widest mt-0.5 truncate" style={{ color: "var(--console-muted)" }}>
          {camName(rule.entry_camera)} → {(rule.exit_cameras || []).map(camName).join(", ") || "—"} · {rule.window_minutes}m
        </div>
      </div>
      <button type="button" onClick={() => onEdit(rule)} className="h-7 w-7 inline-flex items-center justify-center rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }} title="Edit">
        <Pencil className="h-3.5 w-3.5" />
      </button>
      <button type="button" onClick={onDelete} disabled={delMut.isPending} className="h-7 w-7 inline-flex items-center justify-center rounded border disabled:opacity-50" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-rec)" }} title="Delete">
        {delMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
};

// ---------------------------------------------------------------------------
// tab
// ---------------------------------------------------------------------------

const TransitTab = () => {
  const qc = useQueryClient();
  const [showAdd, setShowAdd] = useState(false);
  const [editRule, setEditRule] = useState(null);
  const [statusFilter, setStatusFilter] = useState("");

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

  const sessionParams = useMemo(() => {
    const p = { limit: 100, offset: 0 };
    if (statusFilter) p.status = statusFilter;
    return p;
  }, [statusFilter]);

  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: ["frs-transit-sessions", sessionParams],
    queryFn: () => listTransitSessions(sessionParams),
    placeholderData: keepPreviousData,
  });
  const sessions = sessionsData?.sessions || [];
  const ruleName = (id) => rules.find((r) => r.id === id)?.name || id || "—";

  const sessionStats = useMemo(() => {
    const s = { open: 0, overdue: 0, closed: 0 };
    sessions.forEach((sess) => {
      if (sess.status in s) s[sess.status] += 1;
    });
    return s;
  }, [sessions]);

  const KPI_CARDS = [
    { key: "open", label: "Open", value: sessionStats.open, color: "var(--console-accent)" },
    { key: "overdue", label: "Overdue", value: sessionStats.overdue, color: "var(--console-rec)" },
    { key: "closed", label: "Closed", value: sessionStats.closed, color: "var(--console-online)" },
  ];

  return (
    <div className="p-6 flex flex-col gap-6">
      {/* Rules section */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <ArrowLeftRight className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
            <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              Transit Rules · {rules.length}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setShowAdd(true)}
            className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded"
            style={{ background: "var(--console-accent)", color: "#fff" }}
          >
            <Plus className="h-3.5 w-3.5" />
            Add rule
          </button>
        </div>

        {rulesLoading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
          </div>
        ) : rules.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
            <ArrowLeftRight className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
            <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              No transit rules
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
            {rules.map((r) => (
              <RuleRow key={r.id} rule={r} camName={camName} onEdit={setEditRule} qc={qc} />
            ))}
          </div>
        )}
      </div>

      {/* Sessions section */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <ListChecks className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
            <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              Transit Sessions · {sessionsData?.total ?? sessions.length}
            </span>
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded px-2.5 py-1.5 font-telemetry text-[12px] outline-none"
            style={inputStyle}
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

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
                  </td>
                </tr>
              ) : (
                sessions.map((s) => (
                  <tr key={s.id} className="border-t hover:bg-white/[0.02] transition-colors" style={{ borderColor: "var(--console-border)" }}>
                    <td className="px-3 py-2 font-telemetry text-[12px] truncate max-w-[160px]" style={{ color: "var(--console-text)" }}>
                      {s.person_id ? `Person ${String(s.person_id).slice(0, 8)}` : "—"}
                    </td>
                    <td className="px-3 py-2 font-telemetry text-[12px] truncate max-w-[160px]" style={{ color: "var(--console-text)" }}>
                      {ruleName(s.rule_id)}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={s.status} />
                    </td>
                    <td className="px-3 py-2 font-telemetry text-[11px] whitespace-nowrap" style={{ color: "var(--console-muted)" }}>
                      {fmtTime(s.opened_at)}
                    </td>
                    <td className="px-3 py-2 font-telemetry text-[11px] whitespace-nowrap" style={{ color: "var(--console-muted)" }}>
                      {fmtTime(s.closed_at)}
                    </td>
                    <td className="px-3 py-2 font-telemetry text-[11px] whitespace-nowrap" style={{ color: "var(--console-muted)" }}>
                      {fmtDuration(s.opened_at, s.closed_at)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showAdd && <RuleForm cameras={cameras} qc={qc} onClose={() => setShowAdd(false)} />}
      {editRule && <RuleForm initial={editRule} cameras={cameras} qc={qc} onClose={() => setEditRule(null)} />}
    </div>
  );
};

export default TransitTab;
