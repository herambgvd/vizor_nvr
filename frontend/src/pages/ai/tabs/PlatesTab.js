// =============================================================================
// AI · ANPR Plates tab — the plate-reads browser (primary Detect/Search view).
//
// Searchable, filterable, paginated table of plate reads from the ANPR plugin
// (GET /plates, unified {items,total,limit,offset} envelope). Filters: camera,
// plate text, list-hit, date range. Each read shows plate (big mono), vehicle
// type, direction, speed, watchlist badge, confidence, snapshot, time. Clicking
// a row opens a detail modal with the full-frame plate crop.
// =============================================================================

import React, { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import {
  Car,
  ChevronLeft,
  ChevronRight,
  Filter,
  ImageOff,
  Loader2,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { formatDateTime } from "../../../lib/datetime";

import { getScenarioCameras } from "../../../api/frs";
import {
  listScenarioPluginEvents,
  deleteScenarioPluginEvent,
  bulkDeleteScenarioPluginEvents,
  scenarioSnapshotUrl,
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
import { confidenceBadgeClass, fmtConfidence, fmtBbox, cameraNameMap } from "./frsShared";

const PAGE_SIZE = 25;
const ALL = "__all__";

function fmtTime(iso) {
  if (!iso) return "—";
  try { return formatDateTime(iso); } catch { return iso; }
}

// Authenticated <img> for the plate-crop snapshot (service-token gated proxy).
function SnapshotThumb({ ev, slug, big }) {
  const [blobUrl, setBlobUrl] = useState(null);
  const path = ev.snapshot_path;
  const isPluginSnap = typeof path === "string" && path.startsWith("/snapshot");

  useEffect(() => {
    if (!isPluginSnap || !slug || !path) return undefined;
    let active = true;
    let obj = null;
    scenarioSnapshotUrl(slug, path).then((u) => {
      if (!active) { if (u) URL.revokeObjectURL(u); return; }
      obj = u;
      setBlobUrl(u);
    });
    return () => { active = false; if (obj) URL.revokeObjectURL(obj); };
  }, [isPluginSnap, slug, path]);

  const sizeCls = big ? "w-full aspect-video" : "h-10 w-16";
  if (!path || (isPluginSnap && !blobUrl)) {
    return (
      <div
        className={`${sizeCls} rounded flex items-center justify-center border`}
        style={{ borderColor: "var(--console-border)", background: "var(--console-raised)" }}
      >
        {isPluginSnap && path ? (
          <Loader2 className="h-4 w-4 animate-spin text-zinc-500" />
        ) : (
          <ImageOff className="h-4 w-4 text-zinc-600" />
        )}
      </div>
    );
  }
  return (
    <img
      src={blobUrl}
      alt="plate"
      loading="lazy"
      className={`${sizeCls} rounded object-cover border`}
      style={{ borderColor: "var(--console-border)" }}
    />
  );
}

function ListHitBadge({ hit, label }) {
  if (!hit) return <span className="text-zinc-600 text-xs">—</span>;
  const isBlack = hit === "blacklist";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
        isBlack
          ? "border-rose-500/40 bg-rose-500/15 text-rose-300"
          : "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
      )}
      title={label || hit}
    >
      {isBlack ? "Blacklist" : "Whitelist"}
    </span>
  );
}

function PlateDetailModal({ read, slug, camMap, onClose }) {
  if (!read) return null;
  const r = read;
  const confPct = typeof r.confidence === "number" ? `${(r.confidence * 100).toFixed(1)}%` : "—";
  const rows = [
    ["Time", fmtTime(r.triggered_at)],
    ["Camera", camMap[r.camera_id] || r.camera_id || "—"],
    r.vehicle_type ? ["Vehicle", r.vehicle_type] : null,
    r.direction ? ["Direction", r.direction] : null,
    r.speed_kmh != null ? ["Speed", `${Math.round(r.speed_kmh)} km/h`] : null,
    r.list_hit ? ["Watchlist", `${r.list_hit}${r.list_label ? ` · ${r.list_label}` : ""}`] : null,
    ["Confidence", confPct],
    r.n_frames != null ? ["Frames", r.n_frames] : null,
    ["BBox", fmtBbox(r.bbox)],
  ].filter(Boolean);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.7)" }} onClick={onClose}>
      <div className="w-full max-w-2xl rounded-lg flex flex-col" style={{ background: "var(--console-panel)", border: "1px solid var(--console-border)" }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid var(--console-border)" }}>
          <span className="font-mono text-[16px] font-semibold tracking-wider" style={{ color: "var(--console-text)" }}>{r.plate || "—"}</span>
          <button type="button" onClick={onClose} className="h-7 w-7 inline-flex items-center justify-center rounded hover:opacity-70" style={{ color: "var(--console-muted)" }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
          <div>
            <div className="font-telemetry text-[9px] uppercase tracking-widest mb-1.5" style={{ color: "var(--console-muted)" }}>Plate snapshot</div>
            <SnapshotThumb ev={r} slug={slug} big />
          </div>
          <div className="flex flex-col gap-1.5">
            {rows.map(([k, v]) => (
              <div key={k} className="flex items-start gap-2">
                <div className="w-24 shrink-0 font-telemetry text-[9px] uppercase tracking-widest pt-0.5" style={{ color: "var(--console-muted)" }}>{k}</div>
                <div className="flex-1 min-w-0 font-telemetry text-[11px] break-all capitalize" style={{ color: "var(--console-text)" }}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function PlatesTab({ scenario }) {
  const slug = scenario?.slug || "anpr";
  const scenarioId = scenario?.id;
  const qc = useQueryClient();
  const confirm = useConfirm();
  const [detail, setDetail] = useState(null);

  const [page, setPage] = useState(0);
  const [cameraId, setCameraId] = useState(ALL);
  const [plate, setPlate] = useState("");
  const [listHit, setListHit] = useState(ALL);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

  const { data: cameras = [] } = useQuery({
    queryKey: ["frs", "scenario-cameras", scenarioId],
    queryFn: () => getScenarioCameras(scenarioId),
    enabled: !!scenarioId,
  });
  const camMap = useMemo(() => cameraNameMap(cameras), [cameras]);

  const params = useMemo(() => {
    const p = { limit: PAGE_SIZE, offset: page * PAGE_SIZE };
    if (cameraId !== ALL) p.camera_id = cameraId;
    if (plate.trim()) p.plate = plate.trim();
    if (listHit !== ALL) p.list_hit = listHit;
    if (since) p.since = new Date(since).toISOString();
    if (until) p.until = new Date(until).toISOString();
    return p;
  }, [page, cameraId, plate, listHit, since, until]);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ["anpr-plates", slug, params],
    queryFn: () => listScenarioPluginEvents(slug, params),
    placeholderData: keepPreviousData,
  });

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const [selected, setSelected] = useState(() => new Set());
  const refresh = () => qc.invalidateQueries({ queryKey: ["anpr-plates", slug] });
  const toggleSel = (id) =>
    setSelected((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  const allOnPageSelected = items.length > 0 && items.every((e) => selected.has(e.id));
  const toggleSelAll = () =>
    setSelected((prev) => {
      const n = new Set(prev);
      if (allOnPageSelected) items.forEach((e) => n.delete(e.id));
      else items.forEach((e) => n.add(e.id));
      return n;
    });

  const delMutation = useMutation({
    mutationFn: (id) => deleteScenarioPluginEvent(slug, id),
    onSuccess: () => { toast.success("Plate read deleted"); refresh(); },
    onError: () => toast.error("Couldn't delete plate read"),
  });
  const bulkDelMutation = useMutation({
    mutationFn: (ids) => bulkDeleteScenarioPluginEvents(slug, { ids }),
    onSuccess: (r) => {
      toast.success(`Deleted ${r?.deleted ?? "selected"} plate reads`);
      setSelected(new Set());
      refresh();
    },
    onError: () => toast.error("Bulk delete failed"),
  });

  const resetFilters = () => {
    setCameraId(ALL);
    setPlate("");
    setListHit(ALL);
    setSince("");
    setUntil("");
    setPage(0);
  };
  const onFilterChange = (setter) => (val) => { setter(val); setPage(0); };
  const hasFilters = cameraId !== ALL || plate.trim() || listHit !== ALL || since || until;

  return (
    <div className="p-4 space-y-3">
      {/* Filter bar */}
      <div
        className="flex flex-wrap items-end gap-2 rounded-lg border p-3"
        style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
      >
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-widest text-zinc-500 font-telemetry mr-1">
          <Filter className="h-3.5 w-3.5" /> Filters
        </div>

        <div className="relative w-52">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-500" />
          <Input
            className="h-8 text-xs pl-7"
            placeholder="Search plate…"
            value={plate}
            onChange={(e) => { setPlate(e.target.value); setPage(0); }}
          />
        </div>

        <div className="w-44">
          <Select value={cameraId} onValueChange={onFilterChange(setCameraId)}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Camera" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All cameras</SelectItem>
              {cameras.map((c) => (
                <SelectItem key={c.camera_id} value={c.camera_id}>{c.camera_name || c.camera_id}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="w-36">
          <Select value={listHit} onValueChange={onFilterChange(setListHit)}>
            <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Watchlist" /></SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All reads</SelectItem>
              <SelectItem value="blacklist">Blacklist hits</SelectItem>
              <SelectItem value="whitelist">Whitelist hits</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">From</label>
          <Input type="datetime-local" className="h-8 text-xs" value={since} onChange={(e) => { setSince(e.target.value); setPage(0); }} />
        </div>
        <div>
          <label className="block text-[9px] uppercase tracking-wider text-zinc-500 font-telemetry mb-0.5">To</label>
          <Input type="datetime-local" className="h-8 text-xs" value={until} onChange={(e) => { setUntil(e.target.value); setPage(0); }} />
        </div>

        {hasFilters ? (
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={resetFilters}>
            <X className="h-3.5 w-3.5 mr-1" /> Clear
          </Button>
        ) : null}

        {selected.size > 0 && (
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs text-rose-400 hover:text-rose-300"
            disabled={bulkDelMutation.isPending}
            onClick={async () => {
              if (await confirm({
                title: `Delete ${selected.size} plate read(s)?`,
                description: "This permanently removes the selected reads and their snapshots.",
                confirmText: "Delete",
                danger: true,
              })) {
                bulkDelMutation.mutate(Array.from(selected));
              }
            }}
          >
            {bulkDelMutation.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Trash2 className="h-3.5 w-3.5 mr-1" />}
            Delete {selected.size}
          </Button>
        )}

        <div className="ml-auto text-[11px] text-zinc-500 font-telemetry self-center">
          {total} read{total === 1 ? "" : "s"}
          {isFetching && <Loader2 className="inline h-3 w-3 ml-2 animate-spin text-zinc-400" />}
        </div>
      </div>

      {/* Table */}
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: "var(--console-border)" }}>
        <table className="w-full text-left">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-zinc-500 font-telemetry" style={{ background: "var(--console-raised)" }}>
              <th className="px-3 py-2 w-8">
                <input type="checkbox" checked={allOnPageSelected} onChange={toggleSelAll} className="cursor-pointer" style={{ accentColor: "var(--console-accent)" }} />
              </th>
              <th className="px-3 py-2 font-medium">Time</th>
              <th className="px-3 py-2 font-medium">Camera</th>
              <th className="px-3 py-2 font-medium">Plate</th>
              <th className="px-3 py-2 font-medium">Vehicle</th>
              <th className="px-3 py-2 font-medium">Direction</th>
              <th className="px-3 py-2 font-medium">Speed</th>
              <th className="px-3 py-2 font-medium">List</th>
              <th className="px-3 py-2 font-medium">Conf.</th>
              <th className="px-3 py-2 font-medium">Snapshot</th>
              <th className="px-3 py-2 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <tr key={i} className="border-t" style={{ borderColor: "var(--console-border)" }}>
                  <td colSpan={11} className="px-3 py-3"><div className="h-5 rounded animate-pulse bg-zinc-800/60" /></td>
                </tr>
              ))
            ) : isError ? (
              <tr><td colSpan={11} className="px-3 py-12 text-center text-sm text-rose-400">Couldn't load plate reads.</td></tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={11} className="px-3 py-16 text-center">
                  <Car className="h-9 w-9 mx-auto text-zinc-600 mb-2" />
                  <p className="text-sm text-zinc-300">No plate reads yet</p>
                  <p className="text-xs text-zinc-500 mt-1">
                    {hasFilters ? "Try widening your filters." : "Plate reads appear here as vehicles pass the camera."}
                  </p>
                </td>
              </tr>
            ) : (
              items.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => setDetail(r)}
                  className="border-t hover:bg-white/[0.04] transition-colors cursor-pointer"
                  style={{ borderColor: "var(--console-border)" }}
                >
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(r.id)} onChange={() => toggleSel(r.id)} className="cursor-pointer" style={{ accentColor: "var(--console-accent)" }} />
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-300 font-telemetry whitespace-nowrap">{fmtTime(r.triggered_at)}</td>
                  <td className="px-3 py-2 text-xs text-zinc-300 max-w-[160px] truncate">{camMap[r.camera_id] || r.camera_id || "—"}</td>
                  <td className="px-3 py-2">
                    <span className="font-mono text-[15px] font-semibold tracking-wider text-zinc-100">{r.plate || "—"}</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-300 capitalize">{r.vehicle_type || "—"}</td>
                  <td className="px-3 py-2 text-xs text-zinc-300 capitalize">{r.direction || "—"}</td>
                  <td className="px-3 py-2 text-xs text-zinc-300 font-telemetry whitespace-nowrap">
                    {r.speed_kmh != null ? `${Math.round(r.speed_kmh)} km/h` : "—"}
                  </td>
                  <td className="px-3 py-2"><ListHitBadge hit={r.list_hit} label={r.list_label} /></td>
                  <td className="px-3 py-2">
                    <span className={cn("rounded border px-1.5 text-[10px] font-telemetry", confidenceBadgeClass(r.confidence))}>
                      {fmtConfidence(r.confidence)}
                    </span>
                  </td>
                  <td className="px-3 py-2"><SnapshotThumb ev={r} slug={slug} /></td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 text-xs text-rose-400 hover:text-rose-300"
                      disabled={delMutation.isPending}
                      onClick={async (e) => {
                        e.stopPropagation();
                        if (await confirm({ title: "Delete this plate read?", confirmText: "Delete", danger: true })) {
                          delMutation.mutate(r.id);
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

      {detail && <PlateDetailModal read={detail} slug={slug} camMap={camMap} onClose={() => setDetail(null)} />}
    </div>
  );
}
