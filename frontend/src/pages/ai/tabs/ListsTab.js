// =============================================================================
// AI · ANPR Lists tab — user-defined plate lists (categories) + their entries.
//
// (A) Lists management: the operator's own named lists (GET /lists/defs), each
//     with an action (alert / allow / log), colour swatch + entry count. "New
//     list" opens a MODAL; edit + delete (cascade) per list.
// (B) Entries table (GET /lists, unified envelope): plate, the owning list shown
//     as a coloured badge, label, validity window, created. "+ Add plate" opens a
//     MODAL (plate, list select, label, validity); per-row delete with confirm.
//     CSV bulk import targets a chosen list. The lists are global to the ANPR
//     scenario.
// =============================================================================

import React, { useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  ListChecks,
  Loader2,
  Pencil,
  Plus,
  Search,
  ShieldAlert,
  ShieldCheck,
  Tag,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { friendlyError } from "../../../lib/utils";
import { formatDateTime } from "../../../lib/datetime";

import {
  listAnprListDefs,
  createAnprListDef,
  updateAnprListDef,
  deleteAnprListDef,
  listAnprLists,
  addAnprListEntry,
  deleteAnprListEntry,
  importAnprList,
} from "../../../api/ai";
import { useConfirm } from "../../../components/ui/confirm";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../../../components/ui/select";

const PAGE_SIZE = 25;
const ALL = "__all__";

// Action vocabulary — friendly labels + the badge accent for each.
const ACTIONS = [
  { value: "alert", label: "Alert on match", hint: "Raise a high-severity event", icon: ShieldAlert, color: "#ef4444" },
  { value: "allow", label: "Allow / log only", hint: "Positive match, info event", icon: ShieldCheck, color: "#22c55e" },
  { value: "log", label: "Log only", hint: "Just tag the read", icon: Tag, color: "#64748b" },
];
const ACTION_META = Object.fromEntries(ACTIONS.map((a) => [a.value, a]));
const SWATCHES = ["#ef4444", "#22c55e", "#3b82f6", "#f59e0b", "#a855f7", "#14b8a6", "#64748b"];

function fmtTime(iso) {
  if (!iso) return "—";
  try { return formatDateTime(iso); } catch { return iso; }
}

// ---------------------------------------------------------------------------
// shared modal shell + form primitives (console-token styled)
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

const ModalActions = ({ onClose, onSubmit, pending, submitLabel }) => (
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
      onClick={onSubmit}
      disabled={pending}
      className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded disabled:opacity-50"
      style={{ background: "var(--console-accent)", color: "#fff" }}
    >
      {pending && <Loader2 className="h-3 w-3 animate-spin" />}
      {submitLabel}
    </button>
  </div>
);

// ---------------------------------------------------------------------------
// badges
// ---------------------------------------------------------------------------

// The list a plate belongs to — coloured by the list's own colour.
function ListBadge({ name, color }) {
  const c = color || "var(--console-muted)";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] font-medium"
      style={{ borderColor: `${c}66`, background: `${c}22`, color: c }}
    >
      <span className="h-2 w-2 rounded-full" style={{ background: c }} />
      {name || "—"}
    </span>
  );
}

// A list's action — alert / allow / log.
function ActionBadge({ action }) {
  const meta = ACTION_META[action] || ACTION_META.log;
  const Icon = meta.icon;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide"
      style={{ borderColor: `${meta.color}55`, background: `${meta.color}1f`, color: meta.color }}
    >
      <Icon className="h-3 w-3" /> {meta.value}
    </span>
  );
}

// ---------------------------------------------------------------------------
// (A) list-definition modal (create / edit)
// ---------------------------------------------------------------------------

function ListDefForm({ initial, onClose, qc }) {
  const editing = !!initial;
  const [form, setForm] = useState({
    name: initial?.name || "",
    action: initial?.action || "alert",
    color: initial?.color || SWATCHES[0],
    description: initial?.description || "",
  });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const mut = useMutation({
    mutationFn: () => (editing ? updateAnprListDef(initial.id, form) : createAnprListDef(form)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["anpr-list-defs"] });
      qc.invalidateQueries({ queryKey: ["anpr-lists"] });
      toast.success(editing ? "List updated" : "List created");
      onClose();
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't save list")),
  });

  const submit = () => {
    if (!form.name.trim()) { toast.error("Name is required"); return; }
    mut.mutate();
  };

  return (
    <Modal title={editing ? "Edit list" : "New list"} onClose={onClose}>
      <Field label="Name">
        <input className={inputCls} style={inputStyle} value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="e.g. VIP, Staff, Stolen Vehicles" autoFocus />
      </Field>

      <Field label="Action on match">
        <select className={inputCls} style={inputStyle} value={form.action} onChange={(e) => set("action", e.target.value)}>
          {ACTIONS.map((a) => (
            <option key={a.value} value={a.value}>{a.label}</option>
          ))}
        </select>
        <span className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
          {ACTION_META[form.action]?.hint}
        </span>
      </Field>

      <Field label="Colour">
        <div className="flex items-center gap-2 flex-wrap">
          {SWATCHES.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => set("color", c)}
              className="h-6 w-6 rounded-full border-2 transition-transform"
              style={{ background: c, borderColor: form.color === c ? "var(--console-text)" : "transparent" }}
            />
          ))}
          <input type="color" value={form.color} onChange={(e) => set("color", e.target.value)} className="h-6 w-8 rounded bg-transparent cursor-pointer" />
        </div>
      </Field>

      <Field label="Description">
        <textarea className={inputCls} style={inputStyle} rows={2} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Optional note" />
      </Field>

      <ModalActions onClose={onClose} onSubmit={submit} pending={mut.isPending} submitLabel={editing ? "Save" : "Create"} />
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// (A) list card
// ---------------------------------------------------------------------------

function ListDefCard({ def, onEdit, qc }) {
  const confirm = useConfirm();
  const delMut = useMutation({
    mutationFn: () => deleteAnprListDef(def.id),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["anpr-list-defs"] });
      qc.invalidateQueries({ queryKey: ["anpr-lists"] });
      const n = r?.deleted_entries ?? 0;
      toast.success(`List deleted${n ? ` · ${n} entr${n === 1 ? "y" : "ies"} removed` : ""}`);
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't delete list")),
  });

  const onDelete = async () => {
    const n = def.entry_count ?? 0;
    if (await confirm({
      title: `Delete list "${def.name}"?`,
      description: n ? `This also removes ${n} plate entr${n === 1 ? "y" : "ies"} in this list.` : undefined,
      confirmText: "Delete",
      danger: true,
    })) {
      delMut.mutate();
    }
  };

  const accent = def.color || "var(--console-accent)";
  return (
    <div className="group/card rounded-lg overflow-hidden flex flex-col" style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }}>
      <div className="h-1.5 w-full" style={{ background: accent }} />
      <div className="p-3.5 flex flex-col gap-2.5 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="font-telemetry text-[13px] font-semibold truncate" style={{ color: "var(--console-text)" }}>
              {def.name}
            </div>
            <div className="mt-1"><ActionBadge action={def.action} /></div>
          </div>
          <div className="flex items-center gap-1 shrink-0 opacity-0 group-hover/card:opacity-100 transition-opacity">
            <button type="button" onClick={() => onEdit(def)} className="h-7 w-7 inline-flex items-center justify-center rounded border" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-muted)" }} title="Edit">
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button type="button" onClick={onDelete} disabled={delMut.isPending} className="h-7 w-7 inline-flex items-center justify-center rounded border disabled:opacity-50" style={{ background: "var(--console-raised)", borderColor: "var(--console-border)", color: "var(--console-rec)" }} title="Delete">
              {delMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
            </button>
          </div>
        </div>

        {def.description && (
          <p className="font-telemetry text-[11px] leading-relaxed line-clamp-2" style={{ color: "var(--console-muted)" }}>
            {def.description}
          </p>
        )}

        <div className="flex items-center justify-between mt-auto pt-2" style={{ borderTop: "1px solid var(--console-border)" }}>
          <span className="inline-flex items-center gap-1.5 font-telemetry text-[12px] font-semibold" style={{ color: "var(--console-text)" }}>
            {def.entry_count ?? 0}
            <span className="font-normal text-[10px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>plates</span>
          </span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// (B) add-entry modal
// ---------------------------------------------------------------------------

function AddEntryForm({ defs, defaultListId, onClose, qc }) {
  const [form, setForm] = useState({
    plate: "",
    list_id: defaultListId || defs[0]?.id || "",
    label: "",
    valid_from: "",
    valid_to: "",
  });
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const mut = useMutation({
    mutationFn: () => addAnprListEntry({
      plate: form.plate.trim(),
      list_id: form.list_id,
      label: form.label.trim() || undefined,
      valid_from: form.valid_from ? new Date(form.valid_from).toISOString() : undefined,
      valid_to: form.valid_to ? new Date(form.valid_to).toISOString() : undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["anpr-lists"] });
      qc.invalidateQueries({ queryKey: ["anpr-list-defs"] });
      toast.success("Plate added");
      onClose();
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't add plate")),
  });

  const submit = () => {
    if (!form.plate.trim()) { toast.error("Enter a plate first"); return; }
    if (!form.list_id) { toast.error("Pick a list"); return; }
    mut.mutate();
  };

  return (
    <Modal title="Add plate" onClose={onClose}>
      <Field label="Plate">
        <input
          className={`${inputCls} font-mono uppercase`}
          style={inputStyle}
          value={form.plate}
          onChange={(e) => set("plate", e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          placeholder="e.g. MH12AB1234"
          autoFocus
        />
      </Field>

      <Field label="List">
        <select className={inputCls} style={inputStyle} value={form.list_id} onChange={(e) => set("list_id", e.target.value)}>
          {defs.length === 0 && <option value="">No lists yet — create one first</option>}
          {defs.map((d) => (
            <option key={d.id} value={d.id}>{d.name} ({d.action})</option>
          ))}
        </select>
      </Field>

      <Field label="Label (optional)">
        <input className={inputCls} style={inputStyle} value={form.label} onChange={(e) => set("label", e.target.value)} placeholder="e.g. Stolen vehicle" />
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Valid from">
          <input type="datetime-local" className={inputCls} style={inputStyle} value={form.valid_from} onChange={(e) => set("valid_from", e.target.value)} />
        </Field>
        <Field label="Valid to">
          <input type="datetime-local" className={inputCls} style={inputStyle} value={form.valid_to} onChange={(e) => set("valid_to", e.target.value)} />
        </Field>
      </div>

      <ModalActions onClose={onClose} onSubmit={submit} pending={mut.isPending} submitLabel="Add" />
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// tab
// ---------------------------------------------------------------------------

export default function ListsTab({ scenario }) {
  const slug = scenario?.slug || "anpr";
  const qc = useQueryClient();
  const confirm = useConfirm();
  const fileRef = useRef(null);

  const [editingDef, setEditingDef] = useState(undefined); // undefined=closed, null=new, obj=edit
  const [addingEntry, setAddingEntry] = useState(false);

  const [page, setPage] = useState(0);
  const [listFilter, setListFilter] = useState(ALL);
  const [plate, setPlate] = useState("");
  const [importListId, setImportListId] = useState("");

  // List definitions.
  const { data: defsData, isLoading: defsLoading } = useQuery({
    queryKey: ["anpr-list-defs", slug],
    queryFn: listAnprListDefs,
  });
  const defs = defsData?.items || [];
  const defById = useMemo(() => Object.fromEntries(defs.map((d) => [d.id, d])), [defs]);

  // Default the CSV-import target + entry filter to the first list once loaded.
  const effectiveImportId = importListId || defs[0]?.id || "";

  const params = useMemo(() => {
    const p = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
    if (listFilter !== ALL) p.list_id = listFilter;
    if (plate.trim()) p.plate = plate.trim();
    return p;
  }, [page, listFilter, plate]);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["anpr-lists", slug, params],
    queryFn: () => listAnprLists(params),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const refresh = () => qc.invalidateQueries({ queryKey: ["anpr-lists", slug] });

  const delMutation = useMutation({
    mutationFn: (id) => deleteAnprListEntry(id),
    onSuccess: () => {
      toast.success("Plate removed");
      refresh();
      qc.invalidateQueries({ queryKey: ["anpr-list-defs", slug] });
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't remove plate")),
  });

  const importMutation = useMutation({
    mutationFn: (file) => importAnprList(file, effectiveImportId),
    onSuccess: (r) => {
      toast.success(`Imported ${r?.imported ?? 0} plates${r?.skipped ? ` · ${r.skipped} skipped` : ""}`);
      refresh();
      qc.invalidateQueries({ queryKey: ["anpr-list-defs", slug] });
    },
    onError: (e) => toast.error(friendlyError(e, "Import failed")),
  });

  const onPickFile = (e) => {
    const f = e.target.files?.[0];
    if (f) {
      if (!effectiveImportId) toast.error("Create a list first");
      else importMutation.mutate(f);
    }
    e.target.value = "";
  };

  const resetFilters = () => { setListFilter(ALL); setPlate(""); setPage(0); };
  const hasFilters = listFilter !== ALL || plate.trim();
  const noLists = defs.length === 0;

  return (
    <div className="p-4 space-y-5">
      {/* ── (A) Lists management ─────────────────────────────────────────── */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ListChecks className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
            <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>
              Lists · {defs.length}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setEditingDef(null)}
            className="inline-flex items-center gap-1.5 font-telemetry text-[10px] uppercase tracking-widest px-3 py-1.5 rounded"
            style={{ background: "var(--console-accent)", color: "#fff" }}
          >
            <Plus className="h-3.5 w-3.5" /> New list
          </button>
        </div>

        {defsLoading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--console-muted)" }} />
          </div>
        ) : noLists ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 rounded" style={{ background: "var(--console-panel)", border: "1px dashed var(--console-border)" }}>
            <ListChecks className="h-6 w-6" style={{ color: "var(--console-muted)" }} />
            <span className="font-telemetry text-[11px] uppercase tracking-widest" style={{ color: "var(--console-muted)" }}>No lists yet</span>
            <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>Create a list (e.g. VIP, Staff, Banned) to start adding plates.</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {defs.map((d) => (
              <ListDefCard key={d.id} def={d} onEdit={setEditingDef} qc={qc} />
            ))}
          </div>
        )}
      </section>

      {/* ── (B) Entries ──────────────────────────────────────────────────── */}
      <section className="space-y-3">
        {/* Filter + add + import bar */}
        <div className="flex flex-wrap items-end gap-2 rounded-lg border p-3" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
          <div className="relative w-52">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
            <Input className="h-8 text-xs pl-7" placeholder="Search plate…" value={plate} onChange={(e) => { setPlate(e.target.value); setPage(0); }} />
          </div>
          <div className="w-44">
            <Select value={listFilter} onValueChange={(v) => { setListFilter(v); setPage(0); }}>
              <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="List" /></SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All lists</SelectItem>
                {defs.map((d) => (
                  <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {hasFilters ? (
            <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={resetFilters}>
              <X className="h-3.5 w-3.5 mr-1" /> Clear
            </Button>
          ) : null}

          <Button size="sm" className="h-8 text-xs" disabled={noLists} onClick={() => setAddingEntry(true)} title={noLists ? "Create a list first" : undefined}>
            <Plus className="h-3.5 w-3.5 mr-1" /> Add plate
          </Button>

          {/* CSV import — target list + upload */}
          <div className="ml-auto flex items-end gap-2">
            <div className="w-40">
              <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">Import into</label>
              <Select value={effectiveImportId} onValueChange={setImportListId} disabled={noLists}>
                <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="List" /></SelectTrigger>
                <SelectContent>
                  {defs.map((d) => (
                    <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={onPickFile} />
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs"
              disabled={importMutation.isPending || noLists}
              onClick={() => fileRef.current?.click()}
              title="CSV columns: plate, label, valid_from, valid_to (header optional)"
            >
              {importMutation.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Upload className="h-3.5 w-3.5 mr-1" />}
              Import CSV
            </Button>
            <div className="text-[11px] text-zinc-500 font-telemetry self-center">
              {total} entr{total === 1 ? "y" : "ies"}
              {isFetching && <Loader2 className="inline h-3 w-3 ml-2 animate-spin text-zinc-400" />}
            </div>
          </div>
        </div>

        {/* Table */}
        <div className="rounded-lg border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
          <table className="w-full text-left">
            <thead>
              <tr className="text-[10px] uppercase tracking-wider text-zinc-500 font-telemetry" style={{ background: "var(--console-raised)" }}>
                <th className="px-3 py-2 font-medium">Plate</th>
                <th className="px-3 py-2 font-medium">List</th>
                <th className="px-3 py-2 font-medium">Label</th>
                <th className="px-3 py-2 font-medium">Valid from</th>
                <th className="px-3 py-2 font-medium">Valid to</th>
                <th className="px-3 py-2 font-medium">Created</th>
                <th className="px-3 py-2 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                    <td colSpan={7} className="px-3 py-3"><div className="h-5 rounded animate-pulse bg-zinc-800/60" /></td>
                  </tr>
                ))
              ) : isError ? (
                <tr><td colSpan={7} className="px-3 py-12 text-center text-sm text-rose-400">Couldn't load list entries.</td></tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-16 text-center">
                    <ListChecks className="h-9 w-9 mx-auto text-zinc-600 mb-2" />
                    <p className="text-sm text-zinc-300">No plates yet</p>
                    <p className="text-xs text-zinc-500 mt-1">
                      {hasFilters ? "Try widening your filters." : noLists ? "Create a list first, then add plates." : "Add a plate, or import a CSV to build your list."}
                    </p>
                  </td>
                </tr>
              ) : (
                items.map((row) => {
                  const def = defById[row.list_id];
                  const name = row.list_name || def?.name;
                  const color = row.list_color || def?.color;
                  return (
                    <tr key={row.id} className="border-t hover:bg-white/[0.04] transition-colors" style={{ borderColor: "var(--console-border)" }}>
                      <td className="px-3 py-2">
                        <span className="font-mono text-[14px] font-semibold tracking-wider text-zinc-100">{row.plate || "—"}</span>
                      </td>
                      <td className="px-3 py-2"><ListBadge name={name} color={color} /></td>
                      <td className="px-3 py-2 text-xs text-zinc-300 max-w-[200px] truncate">{row.label || "—"}</td>
                      <td className="px-3 py-2 text-xs text-zinc-400 font-telemetry whitespace-nowrap">{row.valid_from ? fmtTime(row.valid_from) : "—"}</td>
                      <td className="px-3 py-2 text-xs text-zinc-400 font-telemetry whitespace-nowrap">{row.valid_to ? fmtTime(row.valid_to) : "—"}</td>
                      <td className="px-3 py-2 text-xs text-zinc-400 font-telemetry whitespace-nowrap">{fmtTime(row.created_at)}</td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-rose-400 hover:text-rose-300"
                          disabled={delMutation.isPending}
                          onClick={async () => {
                            if (await confirm({
                              title: `Remove ${row.plate} from ${name || "this list"}?`,
                              confirmText: "Remove",
                              danger: true,
                            })) {
                              delMutation.mutate(row.id);
                            }
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {total > PAGE_SIZE && (
          <div className="flex items-center justify-end gap-2">
            <span className="text-[11px] text-zinc-500 font-telemetry">Page {page + 1} / {totalPages}</span>
            <Button variant="outline" size="sm" className="h-8" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <Button variant="outline" size="sm" className="h-8" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </section>

      {/* Modals */}
      {editingDef !== undefined && (
        <ListDefForm initial={editingDef} qc={qc} onClose={() => setEditingDef(undefined)} />
      )}
      {addingEntry && (
        <AddEntryForm
          defs={defs}
          defaultListId={listFilter !== ALL ? listFilter : undefined}
          qc={qc}
          onClose={() => setAddingEntry(false)}
        />
      )}
    </div>
  );
}
