// =============================================================================
// Cameras — table with thumbnails, search, sort, filter, drag-reorder,
// bulk actions, inline recording toggle, right-click context menu, health
// =============================================================================

import React, { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient, useMutation, useQuery } from "@tanstack/react-query";
import {
  Camera,
  Plus,
  Search,
  MoreVertical,
  Play,
  Square,
  RefreshCw,
  Trash2,
  ExternalLink,
  Pencil,
  Wifi,
  WifiOff,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronDown,
  ArrowUpDown,
  GripVertical,
  Power,
  PowerOff,
  Activity,
} from "lucide-react";
import { toast } from "sonner";
import { useCamerasQuery, useCameraMutations } from "../hooks";
import { usePermissions } from "../hooks/usePermissions";
import useLicense from "../hooks/useLicense";
import {
  StatusBadge,
  RecordingIndicator,
  CameraFormDialog,
  ONVIFDiscovery,
} from "../components/nvr";
import CameraThumbnail from "../components/nvr/CameraThumbnail";
import {
  bulkDeleteCameras,
  bulkStartRecording,
  bulkStopRecording,
  bulkTestConnection,
  bulkSetEnabled,
  reorderCameras,
  getLatestHealth,
  getCameraGroups,
} from "../api/cameras";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../components/ui/alert-dialog";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { cn } from "../lib/utils";

const PAGE_SIZES = [10, 25, 50, 100];

// Health pill helpers — green if both kbps & fps healthy, amber if degraded
const healthTone = (h) => {
  if (!h) return null;
  const k = h.bitrate_kbps;
  const f = h.fps_actual;
  if (k == null && f == null) return "muted";
  if ((k != null && k < 64) || (f != null && f < 5)) return "amber";
  return "ok";
};

const HealthCell = ({ data }) => {
  if (!data) return <span className="text-xs text-muted-foreground">—</span>;
  const tone = healthTone(data);
  const toneCls =
    tone === "ok"
      ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/20"
      : tone === "amber"
        ? "bg-amber-500/10 text-amber-300 border-amber-500/20"
        : "bg-card/60 text-muted-foreground border-border";
  const kbps = data.bitrate_kbps != null ? `${data.bitrate_kbps} kbps` : "—";
  const fps = data.fps_actual != null ? `${Math.round(data.fps_actual)} fps` : "—";
  const loss = data.packet_loss_percent != null
    ? `${data.packet_loss_percent.toFixed(1)}%`
    : null;
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[11px] font-mono",
        toneCls,
      )}
      title={data.captured_at ? `Captured ${new Date(data.captured_at).toLocaleString()}` : ""}
    >
      <Activity className="h-3 w-3" />
      <span>{kbps}</span>
      <span className="opacity-50">·</span>
      <span>{fps}</span>
      {loss && (
        <>
          <span className="opacity-50">·</span>
          <span>{loss} loss</span>
        </>
      )}
    </div>
  );
};

// Sortable header
const SortHeader = ({ label, field, sort, setSort, className }) => {
  const active = sort.field === field;
  const dir = active ? sort.dir : null;
  return (
    <button
      type="button"
      onClick={() =>
        setSort((s) =>
          s.field === field
            ? { field, dir: s.dir === "asc" ? "desc" : "asc" }
            : { field, dir: "asc" },
        )
      }
      className={cn(
        "inline-flex items-center gap-1 text-left hover:text-white transition-colors",
        active ? "text-white" : "text-muted-foreground",
        className,
      )}
    >
      {label}
      {dir === "asc" ? (
        <ChevronUp className="h-3 w-3" />
      ) : dir === "desc" ? (
        <ChevronDown className="h-3 w-3" />
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-40" />
      )}
    </button>
  );
};

const Cameras = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { canOperate, canManage } = usePermissions();
  const { cameraCap: licenseCap } = useLicense();
  const { data: cameras = [], isLoading } = useCamerasQuery();
  const mutations = useCameraMutations();

  // Health snapshot map { camera_id: {...} }
  const { data: healthMap = {} } = useQuery({
    queryKey: ["camera-health-latest"],
    queryFn: getLatestHealth,
    refetchInterval: 15_000,
  });

  // Camera groups for filter
  const { data: groups = [] } = useQuery({
    queryKey: ["camera-groups"],
    queryFn: getCameraGroups,
    staleTime: 60_000,
  });

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [groupFilter, setGroupFilter] = useState("all");
  const [sort, setSort] = useState({ field: "order", dir: "asc" }); // 'order' = display_order
  const [showForm, setShowForm] = useState(false);
  const [showOnvif, setShowOnvif] = useState(false);
  const [selected, setSelected] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [contextMenu, setContextMenu] = useState(null); // {x,y,camera}
  const [previewCamera, setPreviewCamera] = useState(null); // camera obj

  // Selection
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Local reorder buffer — patched immediately on drop, then persisted
  const [orderOverride, setOrderOverride] = useState(null);
  const dragIndexRef = useRef(null);

  // Build the working list: server cameras + any local reorder buffer
  const orderedCameras = useMemo(() => {
    if (!orderOverride) return cameras;
    const byId = new Map(cameras.map((c) => [c.id, c]));
    const ordered = orderOverride.map((id) => byId.get(id)).filter(Boolean);
    // Append any cameras the override didn't include (added since)
    cameras.forEach((c) => {
      if (!orderOverride.includes(c.id)) ordered.push(c);
    });
    return ordered;
  }, [cameras, orderOverride]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return orderedCameras.filter((c) => {
      if (q && !(
        c.name.toLowerCase().includes(q) ||
        c.main_stream_url?.toLowerCase().includes(q)
      )) return false;
      if (statusFilter !== "all" && c.status !== statusFilter) return false;
      if (groupFilter !== "all") {
        const ids = c.group_ids || [];
        if (!ids.includes(groupFilter)) return false;
      }
      return true;
    });
  }, [orderedCameras, search, statusFilter, groupFilter]);

  // Apply sort (default = preserve display_order)
  const sorted = useMemo(() => {
    if (sort.field === "order") return filtered;
    const compare = (a, b) => {
      let av, bv;
      switch (sort.field) {
        case "name":
          av = a.name?.toLowerCase() || "";
          bv = b.name?.toLowerCase() || "";
          break;
        case "status":
          av = a.status || "";
          bv = b.status || "";
          break;
        case "recording":
          av = a.is_recording ? 1 : 0;
          bv = b.is_recording ? 1 : 0;
          break;
        case "resolution":
          av = a.resolution || "";
          bv = b.resolution || "";
          break;
        case "last_online":
          av = a.last_online_at ? new Date(a.last_online_at).getTime() : 0;
          bv = b.last_online_at ? new Date(b.last_online_at).getTime() : 0;
          break;
        case "health": {
          const ha = healthMap[a.id];
          const hb = healthMap[b.id];
          av = ha?.bitrate_kbps ?? -1;
          bv = hb?.bitrate_kbps ?? -1;
          break;
        }
        default:
          return 0;
      }
      if (av < bv) return sort.dir === "asc" ? -1 : 1;
      if (av > bv) return sort.dir === "asc" ? 1 : -1;
      return 0;
    };
    return [...filtered].sort(compare);
  }, [filtered, sort, healthMap]);

  const total = sorted.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);
  const paginated = useMemo(
    () => sorted.slice((page - 1) * pageSize, page * pageSize),
    [sorted, page, pageSize],
  );

  // Drop selections no longer visible
  useEffect(() => {
    if (!selectedIds.size) return;
    const visible = new Set(filtered.map((c) => c.id));
    let changed = false;
    const next = new Set();
    selectedIds.forEach((id) => {
      if (visible.has(id)) next.add(id);
      else changed = true;
    });
    if (changed) setSelectedIds(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtered]);

  const allOnPageSelected =
    paginated.length > 0 && paginated.every((c) => selectedIds.has(c.id));
  const someSelected = selectedIds.size > 0;

  const toggleSelect = (id) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleSelectAllOnPage = () =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allOnPageSelected) paginated.forEach((c) => next.delete(c.id));
      else paginated.forEach((c) => next.add(c.id));
      return next;
    });

  // ── Mutations ───────────────────────────────────────────────────────────
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["cameras"] });

  const bulkDeleteMutation = useMutation({
    mutationFn: (ids) => bulkDeleteCameras(ids),
    onSuccess: (res) => {
      toast.success(`${res?.deleted ?? 0} cameras deleted`);
      setSelectedIds(new Set());
      setBulkConfirm(false);
      invalidate();
    },
    onError: () => toast.error("Bulk delete failed"),
  });

  const bulkStartMutation = useMutation({
    mutationFn: (ids) => bulkStartRecording(ids),
    onSuccess: (res) => {
      toast.success(`${res?.started?.length ?? 0} cameras started`);
      invalidate();
    },
    onError: () => toast.error("Bulk start failed"),
  });

  const bulkStopMutation = useMutation({
    mutationFn: (ids) => bulkStopRecording(ids),
    onSuccess: (res) => {
      toast.success(`${res?.stopped?.length ?? 0} cameras stopped`);
      invalidate();
    },
    onError: () => toast.error("Bulk stop failed"),
  });

  const bulkTestMutation = useMutation({
    mutationFn: (ids) => bulkTestConnection(ids),
    onSuccess: () => {
      toast.success("Connections tested");
      invalidate();
    },
    onError: () => toast.error("Bulk test failed"),
  });

  const bulkEnableMutation = useMutation({
    mutationFn: ({ ids, enabled }) => bulkSetEnabled(ids, enabled),
    onSuccess: (res) => {
      toast.success(`${res?.updated?.length ?? 0} cameras ${res?.enabled ? "enabled" : "disabled"}`);
      invalidate();
    },
    onError: () => toast.error("Bulk enable/disable failed"),
  });

  const reorderMutation = useMutation({
    mutationFn: (ids) => reorderCameras(ids),
    onSuccess: () => {
      invalidate();
      // Server now reflects order; clear local override
      setOrderOverride(null);
    },
    onError: () => {
      toast.error("Reorder failed");
      setOrderOverride(null);
    },
  });

  // ── Drag & drop reorder ─────────────────────────────────────────────────
  const handleDragStart = (idx) => {
    dragIndexRef.current = idx;
  };
  const handleDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };
  const handleDrop = (targetIdx) => {
    const src = dragIndexRef.current;
    dragIndexRef.current = null;
    if (src == null || src === targetIdx) return;

    // Build full ordered id list (entire dataset, not just current page),
    // moving the dragged item to the new position.
    const ids = orderedCameras.map((c) => c.id);
    const fromGlobalIdx = (page - 1) * pageSize + src;
    const toGlobalIdx = (page - 1) * pageSize + targetIdx;
    const [moved] = ids.splice(fromGlobalIdx, 1);
    ids.splice(toGlobalIdx, 0, moved);

    setOrderOverride(ids);
    reorderMutation.mutate(ids);
  };

  // ── Right-click context menu ────────────────────────────────────────────
  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener("click", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [contextMenu]);

  // ── Inline start/stop ──────────────────────────────────────────────────
  const inlineToggle = useCallback(
    (camera) => {
      if (!canOperate) return;
      if (camera.is_recording) {
        mutations.stop.mutate(camera.id);
      } else if (camera.status === "online") {
        mutations.start.mutate(camera.id);
      } else {
        toast.error("Camera is offline");
      }
    },
    [canOperate, mutations],
  );

  // ── Dialog helpers ─────────────────────────────────────────────────────
  const openAdd = () => {
    setSelected(null);
    setShowForm(true);
  };
  const openEdit = (cam) => {
    setSelected(cam);
    setShowForm(true);
  };

  const handleSubmit = (data) => {
    const onSuccess = () => {
      setShowForm(false);
      setSelected(null);
    };
    if (selected?.id) {
      mutations.update.mutate({ id: selected.id, data }, { onSuccess });
    } else {
      mutations.create.mutate(data, { onSuccess });
    }
  };

  const sortAllowsDrag = sort.field === "order" && !search && statusFilter === "all" && groupFilter === "all";

  return (
    <div className="p-4 md:p-6 h-full overflow-y-auto">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative flex-1 min-w-[240px] max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search cameras…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="pl-10 h-9"
          />
        </div>

        <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1); }}>
          <SelectTrigger className="h-9 w-[130px]">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All status</SelectItem>
            <SelectItem value="online">Online</SelectItem>
            <SelectItem value="offline">Offline</SelectItem>
            <SelectItem value="error">Error</SelectItem>
          </SelectContent>
        </Select>

        {groups.length > 0 && (
          <Select value={groupFilter} onValueChange={(v) => { setGroupFilter(v); setPage(1); }}>
            <SelectTrigger className="h-9 w-[160px]">
              <SelectValue placeholder="Group" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All groups</SelectItem>
              {groups.map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {someSelected && canOperate && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline">
                Bulk actions ({selectedIds.size})
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onClick={() => bulkStartMutation.mutate(Array.from(selectedIds))}
              >
                <Play className="h-4 w-4 mr-2" /> Start Recording
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => bulkStopMutation.mutate(Array.from(selectedIds))}
              >
                <Square className="h-4 w-4 mr-2" /> Stop Recording
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => bulkTestMutation.mutate(Array.from(selectedIds))}
              >
                <RefreshCw className="h-4 w-4 mr-2" /> Test Connection
              </DropdownMenuItem>
              {canManage && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() =>
                      bulkEnableMutation.mutate({ ids: Array.from(selectedIds), enabled: true })
                    }
                  >
                    <Power className="h-4 w-4 mr-2" /> Enable
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() =>
                      bulkEnableMutation.mutate({ ids: Array.from(selectedIds), enabled: false })
                    }
                  >
                    <PowerOff className="h-4 w-4 mr-2" /> Disable
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onClick={() => setBulkConfirm(true)}
                    className="text-red-600 focus:text-red-600"
                  >
                    <Trash2 className="h-4 w-4 mr-2" /> Delete
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground hidden md:inline">
            {total} camera{total !== 1 ? "s" : ""}
          </span>
          {canManage && (
            <>
              <Button variant="outline" size="sm" onClick={() => setShowOnvif(true)}>
                <Wifi className="h-4 w-4 sm:mr-2" />
                <span className="hidden sm:inline">Discover</span>
              </Button>
              {(() => {
                const cap = licenseCap;
                const atCap = cap && cap.limit > 0 && cap.used >= cap.limit;
                return (
                  <Button
                    onClick={openAdd}
                    className="bg-primary hover:bg-primary/60"
                    size="sm"
                    disabled={atCap}
                    title={atCap ? `License cap: ${cap.used}/${cap.limit}` : undefined}
                  >
                    <Plus className="h-4 w-4 sm:mr-2" />
                    <span className="hidden sm:inline">
                      {atCap ? "License full" : "Add Camera"}
                    </span>
                  </Button>
                );
              })()}
            </>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden overflow-x-auto">
        <Table className="min-w-[1100px]">
          <TableHeader>
            <TableRow className="bg-card/40">
              {sortAllowsDrag && canManage && <TableHead className="w-[32px]" />}
              <TableHead className="w-[40px]">
                <input
                  type="checkbox"
                  aria-label="Select all on page"
                  className="accent-teal-400 cursor-pointer"
                  checked={allOnPageSelected}
                  onChange={toggleSelectAllOnPage}
                />
              </TableHead>
              <TableHead className="w-[80px]">Preview</TableHead>
              <TableHead className="w-[240px]">
                <SortHeader label="Camera" field="name" sort={sort} setSort={setSort} />
              </TableHead>
              <TableHead>
                <SortHeader label="Status" field="status" sort={sort} setSort={setSort} />
              </TableHead>
              <TableHead className="w-[120px]">Recording</TableHead>
              <TableHead className="hidden lg:table-cell">
                <SortHeader label="Health" field="health" sort={sort} setSort={setSort} />
              </TableHead>
              <TableHead className="hidden xl:table-cell">
                <SortHeader label="Resolution" field="resolution" sort={sort} setSort={setSort} />
              </TableHead>
              <TableHead className="hidden md:table-cell">
                <SortHeader label="Last Online" field="last_online" sort={sort} setSort={setSort} />
              </TableHead>
              <TableHead className="w-[50px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {paginated.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={sortAllowsDrag && canManage ? 10 : 9}
                  className="text-center py-12"
                >
                  <Camera className="h-12 w-12 text-slate-300 mx-auto mb-4" />
                  <p className="text-muted-foreground">
                    {isLoading
                      ? "Loading cameras…"
                      : search || statusFilter !== "all" || groupFilter !== "all"
                        ? "No cameras match the current filters"
                        : "No cameras added yet"}
                  </p>
                  {!search && statusFilter === "all" && groupFilter === "all" && !isLoading && canManage && (
                    <Button onClick={openAdd} variant="outline" className="mt-4">
                      <Plus className="h-4 w-4 mr-2" />
                      Add Your First Camera
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ) : (
              paginated.map((camera, idx) => {
                const health = healthMap[camera.id];
                const isDraggable = sortAllowsDrag && canManage;
                return (
                  <TableRow
                    key={camera.id}
                    className={cn(
                      selectedIds.has(camera.id) && "bg-teal-500/[0.06]",
                      !camera.is_enabled && "opacity-60",
                    )}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setContextMenu({ x: e.clientX, y: e.clientY, camera });
                    }}
                    draggable={isDraggable}
                    onDragStart={() => handleDragStart(idx)}
                    onDragOver={handleDragOver}
                    onDrop={() => handleDrop(idx)}
                  >
                    {isDraggable && (
                      <TableCell className="text-muted-foreground cursor-grab active:cursor-grabbing">
                        <GripVertical className="h-4 w-4" />
                      </TableCell>
                    )}
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${camera.name}`}
                        className="accent-teal-400 cursor-pointer"
                        checked={selectedIds.has(camera.id)}
                        onChange={() => toggleSelect(camera.id)}
                      />
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        onClick={() => setPreviewCamera(camera)}
                        className="rounded-md overflow-hidden ring-1 ring-white/5 hover:ring-teal-400/60 transition"
                        title="Open preview"
                      >
                        <CameraThumbnail cameraId={camera.id} className="w-16 h-10" />
                      </button>
                    </TableCell>
                    <TableCell>
                      <div className="min-w-0">
                        <p
                          className="font-medium text-white hover:text-teal-300 cursor-pointer transition-colors truncate"
                          onClick={() => navigate(`/cameras/${camera.id}`)}
                        >
                          {camera.name}
                        </p>
                        <p className="text-xs text-muted-foreground truncate max-w-[220px]">
                          {camera.main_stream_url}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={camera.status} />
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      {canOperate ? (
                        <button
                          type="button"
                          onClick={() => inlineToggle(camera)}
                          className={cn(
                            "inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium border transition-colors",
                            camera.is_recording
                              ? "bg-rose-500/15 text-rose-300 border-rose-500/30 hover:bg-rose-500/25"
                              : camera.status === "online"
                                ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/20 hover:bg-emerald-500/20"
                                : "bg-card/60 text-muted-foreground border-border cursor-not-allowed",
                          )}
                          disabled={!camera.is_recording && camera.status !== "online"}
                        >
                          {camera.is_recording ? (
                            <>
                              <Square className="h-3 w-3" /> Stop
                            </>
                          ) : (
                            <>
                              <Play className="h-3 w-3" /> Start
                            </>
                          )}
                        </button>
                      ) : camera.is_recording ? (
                        <RecordingIndicator isRecording />
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <HealthCell data={health} />
                    </TableCell>
                    <TableCell className="font-mono text-sm text-zinc-400 hidden xl:table-cell">
                      {camera.resolution || "-"}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground hidden md:table-cell">
                      {camera.last_online_at
                        ? new Date(camera.last_online_at).toLocaleString()
                        : "Never"}
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-8 w-8">
                            <MoreVertical className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {canManage && (
                            <DropdownMenuItem onClick={() => openEdit(camera)}>
                              <Pencil className="h-4 w-4 mr-2" /> Edit Camera
                            </DropdownMenuItem>
                          )}
                          {canOperate && (
                            <DropdownMenuItem
                              onClick={() => mutations.test.mutate(camera.id)}
                            >
                              <RefreshCw className="h-4 w-4 mr-2" /> Test Connection
                            </DropdownMenuItem>
                          )}
                          <DropdownMenuItem onClick={() => navigate(`/cameras/${camera.id}`)}>
                            <ExternalLink className="h-4 w-4 mr-2" /> View Details
                          </DropdownMenuItem>
                          {canManage && (
                            <>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                onClick={() => setDeleteTarget(camera)}
                                className="text-red-600 focus:text-red-600"
                              >
                                <Trash2 className="h-4 w-4 mr-2" /> Delete Camera
                              </DropdownMenuItem>
                            </>
                          )}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      {!sortAllowsDrag && canManage && total > 0 && (
        <p className="mt-2 text-[11px] text-muted-foreground">
          Drag-to-reorder disabled — clear search/filter and sort by default to rearrange.
        </p>
      )}

      {/* Pagination */}
      {total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 mt-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>Rows per page</span>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="bg-card border border-border rounded px-2 py-1 text-foreground"
            >
              {PAGE_SIZES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span>
              {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}
            </span>
            <div className="flex gap-1">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Floating context menu */}
      {contextMenu && (
        <div
          className="fixed z-50 min-w-[180px] rounded-lg border border-white/10 bg-card/95 backdrop-blur-xl shadow-2xl p-1 text-sm"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          {canOperate && (
            <button
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-md hover:bg-white/5"
              onClick={() => {
                inlineToggle(contextMenu.camera);
                setContextMenu(null);
              }}
            >
              {contextMenu.camera.is_recording ? (
                <><Square className="h-4 w-4" /> Stop Recording</>
              ) : (
                <><Play className="h-4 w-4" /> Start Recording</>
              )}
            </button>
          )}
          {canOperate && (
            <button
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-md hover:bg-white/5"
              onClick={() => {
                mutations.test.mutate(contextMenu.camera.id);
                setContextMenu(null);
              }}
            >
              <RefreshCw className="h-4 w-4" /> Test Connection
            </button>
          )}
          <button
            className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-md hover:bg-white/5"
            onClick={() => {
              navigate(`/cameras/${contextMenu.camera.id}`);
              setContextMenu(null);
            }}
          >
            <ExternalLink className="h-4 w-4" /> View Details
          </button>
          {canManage && (
            <button
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-md hover:bg-white/5"
              onClick={() => {
                openEdit(contextMenu.camera);
                setContextMenu(null);
              }}
            >
              <Pencil className="h-4 w-4" /> Edit Camera
            </button>
          )}
          {canManage && (
            <>
              <div className="h-px bg-white/10 my-1" />
              <button
                className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-md hover:bg-rose-500/10 text-rose-300"
                onClick={() => {
                  setDeleteTarget(contextMenu.camera);
                  setContextMenu(null);
                }}
              >
                <Trash2 className="h-4 w-4" /> Delete Camera
              </button>
            </>
          )}
        </div>
      )}

      {/* Form */}
      <CameraFormDialog
        open={showForm}
        onOpenChange={(open) => {
          setShowForm(open);
          if (!open) setSelected(null);
        }}
        camera={selected}
        onSubmit={handleSubmit}
        onDelete={(cam) => {
          setShowForm(false);
          setDeleteTarget(cam);
        }}
        isPending={mutations.create.isPending || mutations.update.isPending}
      />

      {/* Single delete */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={() => setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Camera</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{deleteTarget?.name}"? This will
              stop any active recordings and delete all recording files. This
              action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                mutations.remove.mutate(deleteTarget?.id, {
                  onSuccess: () => setDeleteTarget(null),
                })
              }
              className="bg-destructive hover:bg-destructive/90"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk delete */}
      <AlertDialog open={bulkConfirm} onOpenChange={setBulkConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selectedIds.size} cameras</AlertDialogTitle>
            <AlertDialogDescription>
              Selected cameras will be removed. Active recordings stop, stored
              recording files are deleted. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                bulkDeleteMutation.mutate(Array.from(selectedIds))
              }
              className="bg-destructive hover:bg-destructive/90"
              disabled={bulkDeleteMutation.isPending}
            >
              Delete {selectedIds.size}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Preview modal — bigger snapshot on click. Refreshes every 5s
          via CameraThumbnail interval so operator sees near-live frame. */}
      <Dialog
        open={!!previewCamera}
        onOpenChange={(open) => !open && setPreviewCamera(null)}
      >
        <DialogContent className="!max-w-3xl !p-0 !gap-0 !block overflow-hidden">
          {previewCamera && (
            <>
              <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-white/10">
                <DialogTitle className="flex items-center gap-2 text-sm font-semibold">
                  <Camera className="h-4 w-4 text-teal-300" />
                  {previewCamera.name}
                  <StatusBadge status={previewCamera.status} />
                </DialogTitle>
              </div>
              <div className="bg-black w-full aspect-video flex items-center justify-center overflow-hidden">
                <CameraThumbnail
                  cameraId={previewCamera.id}
                  refreshSec={5}
                  className="w-full h-full object-contain"
                />
              </div>
              <div className="flex items-center justify-between gap-3 px-5 py-3 text-xs text-muted-foreground border-t border-white/10">
                <span className="font-mono truncate flex-1">
                  {previewCamera.main_stream_url}
                </span>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {previewCamera.resolution && (
                    <span>{previewCamera.resolution}</span>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      navigate(`/playback?camera=${previewCamera.id}`);
                      setPreviewCamera(null);
                    }}
                  >
                    Playback
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => {
                      navigate(`/cameras/${previewCamera.id}`);
                      setPreviewCamera(null);
                    }}
                  >
                    Details
                  </Button>
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      <ONVIFDiscovery
        open={showOnvif}
        onOpenChange={setShowOnvif}
        onAdded={() => invalidate()}
      />
    </div>
  );
};

export default Cameras;
