// =============================================================================
// AI · Groups tab (FRS) — person groups / watchlists CRUD.
// =============================================================================
// Full CRUD over FRSGroup (name, group_type, color_code, description,
// alert_sound) with live member_count. Reads listGroups; mutations call
// createGroup / updateGroup / deleteGroup and invalidate ["frs-groups"].
// =============================================================================

import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FolderTree,
  Plus,
  Pencil,
  Trash2,
  BellRing,
  BellOff,
  Loader2,
  X,
  Users,
} from "lucide-react";
import { toast } from "sonner";
import { friendlyError } from "../../../../lib/utils";

import { listGroups, createGroup, updateGroup, deleteGroup } from "../../../../api/ai";
import { useConfirm } from "../../../../components/ui/confirm";

const GROUP_TYPES = ["employee", "vip", "watchlist", "banned", "visitor"];
const SWATCHES = ["#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#a855f7", "#14b8a6", "#64748b"];

// ---------------------------------------------------------------------------
// modal shell (console-token styled, self-contained)
// ---------------------------------------------------------------------------

const Modal = ({ title, onClose, children }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }}>
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

const Field = ({ label, children }) => (
  <div className="flex flex-col gap-1.5">
    <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
      {label}
    </label>
    {children}
  </div>
);

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};
const inputCls = "w-full rounded px-2.5 py-1.5 font-telemetry text-[12px] outline-none focus:ring-1";

// ---------------------------------------------------------------------------
// create / edit form
// ---------------------------------------------------------------------------

const GroupForm = ({ initial, onClose, qc }) => {
  const editing = !!initial;
  const [form, setForm] = useState({
    name: initial?.name || "",
    group_type: initial?.group_type || "watchlist",
    color_code: initial?.color_code || SWATCHES[0],
    description: initial?.description || "",
    alert_sound: initial?.alert_sound || false,
  });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const mut = useMutation({
    mutationFn: () => (editing ? updateGroup(initial.id, form) : createGroup(form)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-groups"] });
      toast.success(editing ? "Group updated" : "Group created");
      onClose();
    },
    onError: (e) => toast.error(friendlyError(e, "Failed to save group")),
  });

  const submit = () => {
    if (!form.name.trim()) {
      toast.error("Name is required");
      return;
    }
    mut.mutate();
  };

  return (
    <Modal title={editing ? "Edit group" : "New group"} onClose={onClose}>
      <Field label="Name">
        <input className={inputCls} style={inputStyle} value={form.name} onChange={(e) => set("name", e.target.value)} autoFocus />
      </Field>

      <Field label="Type">
        <select className={inputCls} style={inputStyle} value={form.group_type} onChange={(e) => set("group_type", e.target.value)}>
          {GROUP_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Color">
        <div className="flex items-center gap-2 flex-wrap">
          {SWATCHES.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => set("color_code", c)}
              className="h-6 w-6 rounded-full border-2 transition-transform"
              style={{ background: c, borderColor: form.color_code === c ? "var(--console-text)" : "transparent" }}
            />
          ))}
          <input
            type="color"
            value={form.color_code}
            onChange={(e) => set("color_code", e.target.value)}
            className="h-6 w-8 rounded bg-transparent cursor-pointer"
          />
        </div>
      </Field>

      <Field label="Description">
        <textarea
          className={inputCls}
          style={inputStyle}
          rows={2}
          value={form.description}
          onChange={(e) => set("description", e.target.value)}
        />
      </Field>

      <div className="flex items-center justify-between">
        <label className="font-telemetry text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
          Alert sound
        </label>
        <button
          type="button"
          role="switch"
          aria-checked={form.alert_sound}
          onClick={() => set("alert_sound", !form.alert_sound)}
          className="relative inline-flex h-[20px] w-[36px] items-center rounded-full transition-colors"
          style={{ background: form.alert_sound ? "var(--console-accent)" : "var(--console-border)" }}
        >
          <span
            className="inline-block h-[14px] w-[14px] rounded-full bg-white transition-transform"
            style={{ transform: form.alert_sound ? "translateX(19px)" : "translateX(3px)" }}
          />
        </button>
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <button
          type="button"
          onClick={onClose}
          className="font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded border"
          style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={mut.isPending}
          className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded disabled:opacity-50"
          style={{ background: "var(--console-accent)", color: "#fff" }}
        >
          {mut.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
          {editing ? "Save" : "Create"}
        </button>
      </div>
    </Modal>
  );
};

// ---------------------------------------------------------------------------
// group card
// ---------------------------------------------------------------------------

const GroupCard = ({ group, onEdit, qc }) => {
  const confirm = useConfirm();
  const delMut = useMutation({
    mutationFn: () => deleteGroup(group.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["frs-groups"] });
      toast.success("Group deleted");
    },
    onError: (e) => toast.error(friendlyError(e, "Failed to delete group")),
  });

  const onDelete = () => {
    confirm({ title: `Delete group "${group.name}"?`, confirmText: "Delete", danger: true })
      .then((ok) => { if (ok) delMut.mutate(); });
  };

  const accent = group.color_code || "var(--console-accent)";

  return (
    <div
      className="group/card rounded-lg overflow-hidden flex flex-col transition-transform hover:-translate-y-0.5"
      style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}
    >
      {/* color header strip */}
      <div className="h-1.5 w-full" style={{ background: accent }} />

      <div className="p-3.5 flex flex-col gap-3 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            <span
              className="h-10 w-10 rounded-lg flex items-center justify-center shrink-0"
              style={{ background: accent }}
            >
              <FolderTree className="h-5 w-5 text-white" />
            </span>
            <div className="min-w-0">
              <div className="font-telemetry text-[13px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
                {group.name}
              </div>
              <div className="font-telemetry text-[10px] uppercase tracking-widest truncate" style={{ color: "var(--console-muted)" }}>
                {group.group_type || "group"}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover/card:opacity-100 transition-opacity">
            <button type="button" onClick={() => onEdit(group)} className="h-7 w-7 inline-flex items-center justify-center rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }} title="Edit">
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button type="button" onClick={onDelete} disabled={delMut.isPending} className="h-7 w-7 inline-flex items-center justify-center rounded border disabled:opacity-50" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-rec)" }} title="Delete">
              {delMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>

        {group.description && (
          <p className="font-telemetry text-[11px] leading-relaxed line-clamp-2" style={{ color: "var(--console-muted)" }}>
            {group.description}
          </p>
        )}

        <div className="flex items-center justify-between mt-auto pt-2.5" style={{ borderTop: "1px solid var(--console-border)" }}>
          <span className="inline-flex items-center gap-1.5 font-telemetry text-[12px] font-semibold" style={{ color: "var(--console-text)" }}>
            <Users className="h-4 w-4" style={{ color: accent }} />
            {group.member_count ?? 0}
            <span className="font-normal text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>members</span>
          </span>
          <span className="inline-flex items-center gap-1 font-telemetry text-[10px] uppercase tracking-widest" style={{ color: group.alert_sound ? "var(--console-accent)" : "var(--console-muted)" }}>
            {group.alert_sound ? <BellRing className="h-3 w-3" /> : <BellOff className="h-3 w-3" />}
            {group.alert_sound ? "Alert" : "Silent"}
          </span>
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// tab
// ---------------------------------------------------------------------------

const GroupsTab = () => {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(undefined); // undefined=closed, null=new, obj=edit

  const { data: groups = [], isLoading } = useQuery({
    queryKey: ["frs-groups"],
    queryFn: listGroups,
  });

  return (
    <div className="p-6 flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FolderTree className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            Groups · {groups.length}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setEditing(null)}
          className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded"
          style={{ background: "var(--console-accent)", color: "#fff" }}
        >
          <Plus className="h-3.5 w-3.5" />
          New group
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
        </div>
      ) : groups.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center gap-2 py-16 rounded"
          style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}
        >
          <FolderTree className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
          <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
            No groups yet
          </span>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {groups.map((g) => (
            <GroupCard key={g.id} group={g} onEdit={setEditing} qc={qc} />
          ))}
        </div>
      )}

      {editing !== undefined && (
        <GroupForm initial={editing} qc={qc} onClose={() => setEditing(undefined)} />
      )}
    </div>
  );
};

export default GroupsTab;
