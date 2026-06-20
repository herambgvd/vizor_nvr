// =============================================================================
// AI · ANPR Lists tab — whitelist / blacklist manager.
//
// A table of plate-list entries (GET /lists, unified envelope). Columns: plate,
// list type (whitelist green / blacklist red), label, valid from/to, created.
// Add-entry form (plate, type, label, optional validity). Per-row delete with
// confirm. CSV bulk import (POST /lists/import — multipart `file`, list_type
// query as the per-row fallback). The list is global to the ANPR scenario.
// =============================================================================

import React, { useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  ListChecks,
  Loader2,
  Plus,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { friendlyError } from "../../../lib/utils";
import { formatDateTime } from "../../../lib/datetime";

import {
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
import { cn } from "../../../lib/utils";

const PAGE_SIZE = 25;
const ALL = "__all__";

function fmtTime(iso) {
  if (!iso) return "—";
  try { return formatDateTime(iso); } catch { return iso; }
}

function ListTypeBadge({ type }) {
  const isBlack = type === "blacklist";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium capitalize",
        isBlack
          ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
          : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
      )}
    >
      {type || "—"}
    </span>
  );
}

// Add-entry form — plate + type + label + optional validity window.
function AddEntryForm({ onAdd, pending }) {
  const [plate, setPlate] = useState("");
  const [listType, setListType] = useState("blacklist");
  const [label, setLabel] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [validTo, setValidTo] = useState("");

  const submit = () => {
    if (!plate.trim()) {
      toast.error("Enter a plate first");
      return;
    }
    onAdd(
      {
        plate: plate.trim(),
        list_type: listType,
        label: label.trim() || undefined,
        valid_from: validFrom ? new Date(validFrom).toISOString() : undefined,
        valid_to: validTo ? new Date(validTo).toISOString() : undefined,
      },
      () => { setPlate(""); setLabel(""); setValidFrom(""); setValidTo(""); },
    );
  };

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border p-3" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry mr-1">
        <Plus className="h-3.5 w-3.5" /> Add entry
      </div>
      <div className="w-44">
        <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">Plate</label>
        <Input
          className="h-8 text-xs font-mono uppercase"
          placeholder="e.g. MH12AB1234"
          value={plate}
          onChange={(e) => setPlate(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
        />
      </div>
      <div className="w-36">
        <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">List</label>
        <Select value={listType} onValueChange={setListType}>
          <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="blacklist">Blacklist</SelectItem>
            <SelectItem value="whitelist">Whitelist</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="w-44">
        <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">Label (optional)</label>
        <Input className="h-8 text-xs" placeholder="e.g. Stolen vehicle" value={label} onChange={(e) => setLabel(e.target.value)} />
      </div>
      <div>
        <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">Valid from</label>
        <Input type="datetime-local" className="h-8 text-xs" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
      </div>
      <div>
        <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">Valid to</label>
        <Input type="datetime-local" className="h-8 text-xs" value={validTo} onChange={(e) => setValidTo(e.target.value)} />
      </div>
      <Button size="sm" className="h-8 text-xs" disabled={pending} onClick={submit}>
        {pending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Plus className="h-3.5 w-3.5 mr-1" />}
        Add
      </Button>
    </div>
  );
}

export default function ListsTab({ scenario }) {
  const slug = scenario?.slug || "anpr";
  const qc = useQueryClient();
  const confirm = useConfirm();
  const fileRef = useRef(null);
  const [importType, setImportType] = useState("blacklist");

  const [page, setPage] = useState(0);
  const [listType, setListTypeFilter] = useState(ALL);
  const [plate, setPlate] = useState("");

  const params = useMemo(() => {
    const p = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
    if (listType !== ALL) p.list_type = listType;
    if (plate.trim()) p.plate = plate.trim();
    return p;
  }, [page, listType, plate]);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["anpr-lists", slug, params],
    queryFn: () => listAnprLists(params),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const refresh = () => qc.invalidateQueries({ queryKey: ["anpr-lists", slug] });

  const addMutation = useMutation({
    mutationFn: (payload) => addAnprListEntry(payload),
    onError: (e) => toast.error(friendlyError(e, "Couldn't add entry")),
  });

  const addEntry = (payload, onDone) => {
    addMutation.mutate(payload, {
      onSuccess: () => { toast.success("Entry added"); refresh(); onDone?.(); },
    });
  };

  const delMutation = useMutation({
    mutationFn: (id) => deleteAnprListEntry(id),
    onSuccess: () => { toast.success("Entry removed"); refresh(); },
    onError: (e) => toast.error(friendlyError(e, "Couldn't remove entry")),
  });

  const importMutation = useMutation({
    mutationFn: (file) => importAnprList(file, importType),
    onSuccess: (r) => {
      toast.success(`Imported ${r?.imported ?? 0} entries${r?.skipped ? ` · ${r.skipped} skipped` : ""}`);
      refresh();
    },
    onError: (e) => toast.error(friendlyError(e, "Import failed")),
  });

  const onPickFile = (e) => {
    const f = e.target.files?.[0];
    if (f) importMutation.mutate(f);
    e.target.value = "";
  };

  const resetFilters = () => { setListTypeFilter(ALL); setPlate(""); setPage(0); };
  const hasFilters = listType !== ALL || plate.trim();

  return (
    <div className="p-4 space-y-3">
      {/* Add-entry form */}
      <AddEntryForm onAdd={addEntry} pending={addMutation.isPending} />

      {/* Filter + import bar */}
      <div className="flex flex-wrap items-end gap-2 rounded-lg border p-3" style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}>
        <div className="relative w-52">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
          <Input className="h-8 text-xs pl-7" placeholder="Search plate…" value={plate} onChange={(e) => { setPlate(e.target.value); setPage(0); }} />
        </div>
        <div className="w-36">
          <Select value={listType} onValueChange={(v) => { setListTypeFilter(v); setPage(0); }}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="List type" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All lists</SelectItem>
              <SelectItem value="blacklist">Blacklist</SelectItem>
              <SelectItem value="whitelist">Whitelist</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {hasFilters ? (
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={resetFilters}>
            <X className="h-3.5 w-3.5 mr-1" /> Clear
          </Button>
        ) : null}

        {/* CSV import — type picker + upload */}
        <div className="ml-auto flex items-end gap-2">
          <div className="w-32">
            <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">Import as</label>
            <Select value={importType} onValueChange={setImportType}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="blacklist">Blacklist</SelectItem>
                <SelectItem value="whitelist">Whitelist</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={onPickFile} />
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            disabled={importMutation.isPending}
            onClick={() => fileRef.current?.click()}
            title="CSV columns: plate, list_type, label, valid_from, valid_to (header optional)"
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
                  <p className="text-sm text-zinc-300">No list entries yet</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    {hasFilters ? "Try widening your filters." : "Add a plate above, or import a CSV to build your watchlist."}
                  </p>
                </td>
              </tr>
            ) : (
              items.map((row) => (
                <tr key={row.id} className="border-t hover:bg-white/[0.04] transition-colors" style={{ borderColor: "var(--console-border)" }}>
                  <td className="px-3 py-2">
                    <span className="font-mono text-[14px] font-semibold tracking-wider text-zinc-100">{row.plate || "—"}</span>
                  </td>
                  <td className="px-3 py-2"><ListTypeBadge type={row.list_type} /></td>
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
                          title: `Remove ${row.plate} from the ${row.list_type}?`,
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
              ))
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
    </div>
  );
}
