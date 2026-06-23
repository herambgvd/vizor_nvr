// =============================================================================
// Cameras — dense console device manager.
// Table view (sortable, drag-reorder, bulk actions) +
// Grid/card view toggle (persisted via useUiPrefs camerasView pref).
// ALL existing functionality preserved: search, sort, filter, drag-reorder,
// bulk actions, inline recording toggle, right-click context menu, health
// indicators, ONVIF discovery, camera form dialog, preview modal.
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
  AlertTriangle,
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
  FolderInput,
  Timer,
  CalendarClock,
  LayoutGrid,
  List,
  FolderPlus,
} from "lucide-react";
import { toast } from "sonner";
import { useCamerasQuery, useCameraMutations } from "../hooks";
import { useUiPrefs } from "../hooks/useUiPrefs";
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
  createCameraGroup,
  updateCameraGroup,
  deleteCameraGroup,
  bulkCameraAction,
} from "../api/cameras";
import {
  listScheduleTemplates,
  applyScheduleTemplate,
} from "../api/scheduleTemplates";
import { verifyPassword } from "../api/auth";
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
import { cn, friendlyError } from "../lib/utils";
import { formatDateTime } from "../lib/datetime";

const PAGE_SIZES = [10, 25, 50, 100];
const DEFAULT_GROUP_COLOR = "#228B22";
const HEX_COLOR_RE = /^#[0-9a-fA-F]{6}$/;
const safeGroupColor = (value) => (
  HEX_COLOR_RE.test(value || "") ? value : DEFAULT_GROUP_COLOR
);

// ── Health helpers ────────────────────────────────────────────────────────────
const healthTone = (h) => {
  if (!h) return null;
  const k = h.bitrate_kbps;
  const f = h.fps_actual;
  if (k == null && f == null) return "muted";
  if ((k != null && k < 64) || (f != null && f < 5)) return "amber";
  return "ok";
};

const HealthCell = ({ data }) => {
  if (!data) return <span className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>—</span>;
  const tone = healthTone(data);
  const color =
    tone === "ok" ? "var(--console-online)"
    : tone === "amber" ? "var(--console-alarm)"
    : "var(--console-muted)";
  const kbps = data.bitrate_kbps != null ? `${data.bitrate_kbps} kbps` : "—";
  const fps = data.fps_actual != null ? `${Math.round(data.fps_actual)} fps` : "—";
  const loss = data.packet_loss_percent != null
    ? `${data.packet_loss_percent.toFixed(1)}%`
    : null;
  return (
    <div
      className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded font-telemetry text-[11px] border"
      style={{
        color,
        borderColor: "var(--console-border)",
        background: "var(--console-raised)",
      }}
      title={data.captured_at ? `Captured ${formatDateTime(data.captured_at)}` : ""}
    >
      <Activity className="h-3 w-3" />
      <span>{kbps}</span>
      <span style={{ opacity: 0.4 }}>·</span>
      <span>{fps}</span>
      {loss && (
        <>
          <span style={{ opacity: 0.4 }}>·</span>
          <span>{loss} loss</span>
        </>
      )}
    </div>
  );
};

// ── Sortable header ───────────────────────────────────────────────────────────
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
        "inline-flex items-center gap-1 text-left transition-colors font-telemetry text-[11px] uppercase tracking-wide",
        active ? "" : "",
        className,
      )}
      style={{ color: active ? "var(--console-accent)" : "var(--console-muted)" }}
    >
      {label}
      {dir === "asc" ? (
        <ChevronUp className="h-3 w-3" />
      ) : dir === "desc" ? (
        <ChevronDown className="h-3 w-3" />
      ) : (
        <ArrowUpDown className="h-3 w-3" style={{ opacity: 0.4 }} />
      )}
    </button>
  );
};

// ── Status dot (compact, used in grid cards) ──────────────────────────────────
const StatusDot = ({ status }) => {
  const color =
    status === "online" ? "var(--console-online)"
    : status === "offline" ? "var(--console-offline)"
    : "var(--console-alarm)";
  return (
    <span
      className="inline-block w-2 h-2 rounded-full flex-shrink-0"
      style={{ background: color }}
      title={status}
    />
  );
};

// ── Recording dot (compact for card overlay) ──────────────────────────────────
const RecDot = () => (
  <span
    className="inline-flex items-center gap-1 font-telemetry text-[10px] px-1 py-0.5 rounded"
    style={{ background: "var(--console-rec)", color: "#fff" }}
  >
    ● REC
  </span>
);

// ── Camera grid card ──────────────────────────────────────────────────────────
const CameraGridCard = ({
  camera,
  health,
  selectedIds,
  toggleSelect,
  inlineToggle,
  canOperate,
  canRecord,
  canManage,
  onContextMenu,
  onPreview,
  openEdit,
  setDeleteTarget,
  navigate,
  mutations,
  isDraggable,
  dragIdx,
  handleDragStart,
  handleDragOver,
  handleDrop,
}) => {
  return (
    <div
      className={cn(
        "group relative flex flex-col rounded overflow-hidden border transition-colors cursor-default",
        !camera.is_enabled && "opacity-50",
        selectedIds.has(camera.id) && "ring-1",
      )}
      style={{
        background: "var(--console-raised)",
        borderColor: selectedIds.has(camera.id) ? "var(--console-accent)" : "var(--console-border)",
        boxShadow: selectedIds.has(camera.id) ? "0 0 0 1px var(--console-accent)" : undefined,
      }}
      onContextMenu={onContextMenu}
      draggable={isDraggable}
      onDragStart={() => handleDragStart(dragIdx)}
      onDragOver={handleDragOver}
      onDrop={() => handleDrop(dragIdx)}
    >
      {/* Thumbnail */}
      <div className="relative w-full" style={{ aspectRatio: "16/9", background: "#000" }}>
        <button
          type="button"
          className="w-full h-full block"
          onClick={() => onPreview(camera)}
          title="Open preview"
        >
          <CameraThumbnail cameraId={camera.id} className="w-full h-full object-cover" />
        </button>

        {/* Top-left overlay: status dot + rec */}
        <div className="absolute top-1.5 left-1.5 flex items-center gap-1.5">
          <StatusDot status={camera.status} />
          {camera.is_recording && <RecDot />}
        </div>

        {/* Top-right overlay: checkbox */}
        <div className="absolute top-1.5 right-1.5">
          <input
            type="checkbox"
            aria-label={`Select ${camera.name}`}
            className="cursor-pointer accent-teal-400 w-3.5 h-3.5"
            checked={selectedIds.has(camera.id)}
            onChange={() => toggleSelect(camera.id)}
            onClick={(e) => e.stopPropagation()}
          />
        </div>

        {/* Drag handle — shown on hover when drag enabled */}
        {isDraggable && (
          <div
            className="absolute bottom-1 left-1 opacity-0 group-hover:opacity-60 cursor-grab active:cursor-grabbing"
            style={{ color: "var(--console-muted)" }}
          >
            <GripVertical className="h-3.5 w-3.5" />
          </div>
        )}
      </div>

      {/* Card footer */}
      <div
        className="flex items-center gap-1 px-2 py-1.5 border-t"
        style={{
          background: "var(--console-panel)",
          borderColor: "var(--console-border)",
        }}
      >
        {/* Name + health */}
        <div className="flex-1 min-w-0">
          <p
            className="text-xs font-medium truncate cursor-pointer hover:underline"
            style={{ color: "var(--console-text)" }}
            onClick={() => navigate(`/cameras/${camera.id}`)}
            title={camera.name}
          >
            {camera.name}
          </p>
          {health ? (
            <p className="font-telemetry text-[10px] truncate mt-0.5" style={{ color: "var(--console-muted)" }}>
              {health.bitrate_kbps != null ? `${health.bitrate_kbps} kbps` : ""}
              {health.bitrate_kbps != null && health.fps_actual != null ? " · " : ""}
              {health.fps_actual != null ? `${Math.round(health.fps_actual)} fps` : ""}
            </p>
          ) : (
            <p className="font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
              {camera.resolution || "—"}
            </p>
          )}
        </div>

        {/* Actions dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex-shrink-0 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-white/10 transition"
              style={{ color: "var(--console-muted)" }}
            >
              <MoreVertical className="h-3.5 w-3.5" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {canRecord && (
              <DropdownMenuItem onClick={() => inlineToggle(camera)}>
                {camera.is_recording ? (
                  <><Square className="h-4 w-4 mr-2" /> Stop Recording</>
                ) : (
                  <><Play className="h-4 w-4 mr-2" /> Start Recording</>
                )}
              </DropdownMenuItem>
            )}
            {canOperate && (
              <DropdownMenuItem onClick={() => mutations.test.mutate(camera.id)}>
                <RefreshCw className="h-4 w-4 mr-2" /> Test Connection
              </DropdownMenuItem>
            )}
            <DropdownMenuItem onClick={() => navigate(`/cameras/${camera.id}`)}>
              <ExternalLink className="h-4 w-4 mr-2" /> View Details
            </DropdownMenuItem>
            {canManage && (
              <DropdownMenuItem onClick={() => openEdit(camera)}>
                <Pencil className="h-4 w-4 mr-2" /> Edit Camera
              </DropdownMenuItem>
            )}
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
      </div>
    </div>
  );
};

// ── Main page component ───────────────────────────────────────────────────────
const Cameras = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { canOperate, canManage } = usePermissions();
  const { cameraCap: licenseCap, hasFeature } = useLicense();
  const canRecord = canOperate && hasFeature("recording");
  const canPlayback = hasFeature("playback");
  const { data: cameras = [], isLoading, isError: camerasError, refetch: refetchCameras } = useCamerasQuery();
  const mutations = useCameraMutations();
  const [prefs, setPrefs] = useUiPrefs();
  const camerasView = prefs.camerasView || "table";

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
  // Password-confirmation gate for irreversible camera deletes.
  const [deletePwd, setDeletePwd] = useState("");
  const [bulkPwd, setBulkPwd] = useState("");
  const [deleteVerifying, setDeleteVerifying] = useState(false);
  const [deletePwdError, setDeletePwdError] = useState("");
  const [contextMenu, setContextMenu] = useState(null); // {x,y,camera}
  const [previewCamera, setPreviewCamera] = useState(null); // camera obj

  // Template dialogs
  const [showApplyTemplate, setShowApplyTemplate] = useState(false);
  const [showSetRetention, setShowSetRetention] = useState(false);
  const [retentionInput, setRetentionInput] = useState("");
  const [showMoveToGroup, setShowMoveToGroup] = useState(false);
  const [moveGroupId, setMoveGroupId] = useState("");
  const [showGroupManager, setShowGroupManager] = useState(false);
  const [editingGroup, setEditingGroup] = useState(null);
  const [groupForm, setGroupForm] = useState({
    name: "",
    description: "",
    color: DEFAULT_GROUP_COLOR,
  });

  // Fetch schedule templates for bulk apply
  const { data: scheduleTemplates = [] } = useQuery({
    queryKey: ["schedule-templates"],
    queryFn: listScheduleTemplates,
    staleTime: 60_000,
  });
  const [selectedTemplateId, setSelectedTemplateId] = useState("");

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

  const cameraCountByGroupId = useMemo(() => {
    const counts = new Map();
    cameras.forEach((camera) => {
      (camera.group_ids || []).forEach((groupId) => {
        counts.set(groupId, (counts.get(groupId) || 0) + 1);
      });
    });
    return counts;
  }, [cameras]);

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

  // ── Mutations ────────────────────────────────────────────────────────────
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["cameras"] });
  const invalidateGroups = () => {
    invalidate();
    queryClient.invalidateQueries({ queryKey: ["camera-groups"] });
  };

  const resetGroupForm = () => {
    setEditingGroup(null);
    setGroupForm({ name: "", description: "", color: DEFAULT_GROUP_COLOR });
  };

  const openGroupEditor = (group = null) => {
    setEditingGroup(group);
    setGroupForm({
      name: group?.name || "",
      description: group?.description || "",
      color: group?.color || DEFAULT_GROUP_COLOR,
    });
    setShowGroupManager(true);
  };

  const groupSaveMutation = useMutation({
    mutationFn: (payload) => (
      editingGroup
        ? updateCameraGroup(editingGroup.id, payload)
        : createCameraGroup(payload)
    ),
    onSuccess: () => {
      toast.success(editingGroup ? "Group updated" : "Group created");
      resetGroupForm();
      invalidateGroups();
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't save the group")),
  });

  const groupDeleteMutation = useMutation({
    mutationFn: (groupId) => deleteCameraGroup(groupId),
    onSuccess: () => {
      toast.success("Group deleted");
      resetGroupForm();
      if (groupFilter !== "all") setGroupFilter("all");
      if (moveGroupId) setMoveGroupId("");
      invalidateGroups();
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't delete the group")),
  });

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

  // Verify the operator's password before running an irreversible delete.
  // Keeps the dialog open (and shows an inline error) on a wrong password.
  const confirmSingleDelete = async () => {
    if (!deletePwd) {
      setDeletePwdError("Password is required");
      return;
    }
    setDeleteVerifying(true);
    setDeletePwdError("");
    try {
      await verifyPassword(deletePwd);
    } catch (e) {
      setDeleteVerifying(false);
      setDeletePwdError(
        e.response?.status === 401
          ? "Incorrect password"
          : friendlyError(e, "Verification failed"),
      );
      return;
    }
    setDeleteVerifying(false);
    mutations.remove.mutate(deleteTarget?.id, {
      onSuccess: () => setDeleteTarget(null),
    });
  };

  const confirmBulkDelete = async () => {
    if (!bulkPwd) {
      setDeletePwdError("Password is required");
      return;
    }
    setDeleteVerifying(true);
    setDeletePwdError("");
    try {
      await verifyPassword(bulkPwd);
    } catch (e) {
      setDeleteVerifying(false);
      setDeletePwdError(
        e.response?.status === 401
          ? "Incorrect password"
          : friendlyError(e, "Verification failed"),
      );
      return;
    }
    setDeleteVerifying(false);
    bulkDeleteMutation.mutate(Array.from(selectedIds));
  };

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

  const bulkMoveGroupMutation = useMutation({
    mutationFn: ({ ids, groupId }) =>
      bulkCameraAction("move_to_group", ids, { group_id: groupId }),
    onSuccess: (res) => {
      toast.success(`Moved ${res?.succeeded?.length ?? 0} cameras to group`);
      setShowMoveToGroup(false);
      setMoveGroupId("");
      invalidateGroups();
    },
    onError: () => toast.error("Move to group failed"),
  });

  const bulkSetRetentionMutation = useMutation({
    mutationFn: ({ ids, days }) =>
      bulkCameraAction("set_retention", ids, { retention_days: days }),
    onSuccess: (res) => {
      toast.success(`Updated retention for ${res?.succeeded?.length ?? 0} cameras`);
      setShowSetRetention(false);
      setRetentionInput("");
      invalidate();
    },
    onError: () => toast.error("Set retention failed"),
  });

  const applyTemplateMutation = useMutation({
    mutationFn: ({ templateId, ids }) => applyScheduleTemplate(templateId, ids),
    onSuccess: (res) => {
      toast.success(`Applied template to ${res?.applied ?? 0} cameras`);
      setShowApplyTemplate(false);
      setSelectedTemplateId("");
      invalidate();
    },
    onError: () => toast.error("Apply template failed"),
  });

  const reorderMutation = useMutation({
    mutationFn: (ids) => reorderCameras(ids),
    onSuccess: () => {
      invalidate();
      setOrderOverride(null);
    },
    onError: () => {
      toast.error("Reorder failed");
      setOrderOverride(null);
    },
  });

  // ── Drag & drop reorder ──────────────────────────────────────────────────
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

    const ids = orderedCameras.map((c) => c.id);
    const fromGlobalIdx = (page - 1) * pageSize + src;
    const toGlobalIdx = (page - 1) * pageSize + targetIdx;
    const [moved] = ids.splice(fromGlobalIdx, 1);
    ids.splice(toGlobalIdx, 0, moved);

    setOrderOverride(ids);
    reorderMutation.mutate(ids);
  };

  // ── Right-click context menu ─────────────────────────────────────────────
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

  // ── Inline start/stop ────────────────────────────────────────────────────
  const inlineToggle = useCallback(
    (camera) => {
      if (!canRecord) return;
      if (camera.is_recording) {
        mutations.stop.mutate(camera.id);
      } else if (camera.status === "online") {
        mutations.start.mutate(camera.id);
      } else {
        toast.error("Camera is offline");
      }
    },
    [canRecord, mutations],
  );

  // ── Dialog helpers ───────────────────────────────────────────────────────
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

  // ── Shared input / select console style props ────────────────────────────
  const inputStyle = {
    background: "var(--console-raised)",
    borderColor: "var(--console-border)",
    color: "var(--console-text)",
  };

  return (
    <div
      className="h-full overflow-y-auto flex flex-col"
      style={{ background: "var(--console-bg)", color: "var(--console-text)" }}
    >
      {/* ── Page header ──────────────────────────────────────────────────── */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b flex-shrink-0"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <div className="flex items-center gap-2">
          <span
            className="w-0.5 h-4 rounded-full flex-shrink-0"
            style={{ background: "var(--console-accent)" }}
          />
          <span
            className="font-telemetry text-xs font-semibold uppercase tracking-widest"
            style={{ color: "var(--console-text)" }}
          >
            Cameras
          </span>
          {!isLoading && (
            <span
              className="font-telemetry text-[11px] px-1.5 py-0.5 rounded"
              style={{
                background: "var(--console-raised)",
                color: "var(--console-muted)",
                border: "1px solid var(--console-border)",
              }}
            >
              {total}
            </span>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* View toggle */}
        <div
          className="flex items-center rounded overflow-hidden border"
          style={{ borderColor: "var(--console-border)" }}
        >
          <button
            type="button"
            className="p-1.5 transition-colors"
            style={{
              background: camerasView === "table" ? "var(--console-accent)" : "var(--console-raised)",
              color: camerasView === "table" ? "#06231f" : "var(--console-muted)",
            }}
            title="Table view"
            onClick={() => setPrefs({ camerasView: "table" })}
          >
            <List className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            className="p-1.5 transition-colors"
            style={{
              background: camerasView === "grid" ? "var(--console-accent)" : "var(--console-raised)",
              color: camerasView === "grid" ? "#06231f" : "var(--console-muted)",
            }}
            title="Grid view"
            onClick={() => setPrefs({ camerasView: "grid" })}
          >
            <LayoutGrid className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div
        className="flex flex-wrap items-center gap-2 px-4 py-2 border-b flex-shrink-0"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        <div className="relative flex-1 min-w-[200px] max-w-md">
          <Search
            className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5"
            style={{ color: "var(--console-muted)" }}
          />
          <input
            type="text"
            placeholder="Search cameras…"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            className="w-full pl-8 pr-3 py-1.5 rounded text-xs border outline-none focus:ring-1 font-telemetry"
            style={{
              ...inputStyle,
              "--tw-ring-color": "var(--console-accent)",
            }}
          />
        </div>

        <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1); }}>
          <SelectTrigger
            className="h-[30px] w-[120px] text-xs font-telemetry"
            style={inputStyle}
          >
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
            <SelectTrigger
              className="h-[30px] w-[140px] text-xs font-telemetry"
              style={inputStyle}
            >
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

        {canManage && (
          <button
            type="button"
            className="h-[30px] px-3 rounded text-xs border font-telemetry inline-flex items-center gap-1.5 transition-colors hover:bg-[var(--console-hover)]"
            style={{
              borderColor: "var(--console-border)",
              color: "var(--console-text)",
              background: "var(--console-raised)",
            }}
            onClick={() => openGroupEditor()}
          >
            <FolderPlus className="h-3.5 w-3.5" />
            Groups
          </button>
        )}

        {someSelected && canOperate && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="h-[30px] px-3 rounded text-xs border font-telemetry transition-colors hover:bg-[var(--console-hover)]"
                style={{
                  borderColor: "var(--console-accent)",
                  color: "var(--console-accent)",
                  background: "transparent",
                }}
              >
                Bulk ({selectedIds.size}) ▾
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {canRecord && (
                <>
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
                </>
              )}
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
                  <DropdownMenuItem onClick={() => setShowMoveToGroup(true)}>
                    <FolderInput className="h-4 w-4 mr-2" /> Move to group…
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setShowApplyTemplate(true)}>
                    <CalendarClock className="h-4 w-4 mr-2" /> Apply schedule template…
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setShowSetRetention(true)}>
                    <Timer className="h-4 w-4 mr-2" /> Set retention…
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
          {canManage && (
            <>
              <button
                type="button"
                className="h-[30px] px-3 rounded text-xs border font-telemetry inline-flex items-center gap-1.5 transition-colors hover:bg-[var(--console-hover)]"
                style={{
                  borderColor: "var(--console-border)",
                  color: "var(--console-muted)",
                  background: "var(--console-raised)",
                }}
                onClick={() => setShowOnvif(true)}
              >
                <Wifi className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Discover</span>
              </button>
              {(() => {
                const cap = licenseCap;
                const atCap = cap && cap.limit > 0 && cap.used >= cap.limit;
                return (
                  <button
                    type="button"
                    onClick={openAdd}
                    disabled={atCap}
                    title={atCap ? `License cap: ${cap.used}/${cap.limit}` : undefined}
                    className="h-[30px] px-3 rounded text-xs font-telemetry inline-flex items-center gap-1.5 transition-colors disabled:opacity-50"
                    style={{
                      background: "var(--console-accent)",
                      color: "#06231f",
                    }}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    <span className="hidden sm:inline">
                      {atCap ? "License full" : "Add Camera"}
                    </span>
                  </button>
                );
              })()}
            </>
          )}
        </div>
      </div>

      {/* ── Main content area ─────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3">

        {/* Mobile card list — visible below md, hidden above */}
        <div className="md:hidden space-y-1.5 mb-3">
          {isLoading ? (
            <div
              className="text-center py-10 text-xs font-telemetry"
              style={{ color: "var(--console-muted)" }}
            >
              Loading cameras…
            </div>
          ) : camerasError && cameras.length === 0 ? (
            <div className="text-center py-10 flex flex-col items-center gap-3">
              <AlertTriangle className="h-8 w-8" style={{ color: "var(--console-rec)" }} />
              <p className="text-xs font-telemetry" style={{ color: "var(--console-rec)" }}>
                Couldn't load cameras
              </p>
              <button
                type="button"
                onClick={() => refetchCameras()}
                className="px-3 py-1.5 rounded text-xs font-telemetry border"
                style={{ borderColor: "var(--console-border)", color: "var(--console-text)", background: "var(--console-raised)" }}
              >
                <RefreshCw className="h-3.5 w-3.5 inline mr-1" /> Retry
              </button>
            </div>
          ) : paginated.length === 0 ? (
            <div className="text-center py-10">
              <Camera className="h-10 w-10 mx-auto mb-3" style={{ color: "var(--console-muted)" }} />
              <p className="text-xs font-telemetry" style={{ color: "var(--console-muted)" }}>
                {search || statusFilter !== "all" || groupFilter !== "all"
                  ? "No cameras match the current filters"
                  : "No cameras added yet"}
              </p>
              {!search && statusFilter === "all" && groupFilter === "all" && canManage && (
                <button
                  type="button"
                  onClick={openAdd}
                  className="mt-4 px-3 py-1.5 rounded text-xs font-telemetry border"
                  style={{
                    borderColor: "var(--console-border)",
                    color: "var(--console-muted)",
                    background: "var(--console-raised)",
                  }}
                >
                  <Plus className="h-3.5 w-3.5 inline mr-1" /> Add Your First Camera
                </button>
              )}
            </div>
          ) : (
            paginated.map((camera) => (
              <div
                key={camera.id}
                className={cn(
                  "rounded border p-2.5 flex items-center gap-2.5",
                  !camera.is_enabled && "opacity-60",
                )}
                style={{
                  background: selectedIds.has(camera.id) ? "rgba(20,184,166,0.06)" : "var(--console-raised)",
                  borderColor: selectedIds.has(camera.id) ? "var(--console-accent)" : "var(--console-border)",
                }}
              >
                <input
                  type="checkbox"
                  aria-label={`Select ${camera.name}`}
                  className="accent-teal-400 cursor-pointer flex-shrink-0"
                  checked={selectedIds.has(camera.id)}
                  onChange={() => toggleSelect(camera.id)}
                />
                <button
                  type="button"
                  onClick={() => setPreviewCamera(camera)}
                  className="rounded overflow-hidden flex-shrink-0"
                  style={{ border: "1px solid var(--console-border)" }}
                >
                  <CameraThumbnail cameraId={camera.id} className="w-16 h-10" />
                </button>
                <div className="flex-1 min-w-0">
                  <p
                    className="text-xs font-medium truncate cursor-pointer hover:underline"
                    style={{ color: "var(--console-text)" }}
                    onClick={() => navigate(`/cameras/${camera.id}`)}
                  >
                    {camera.name}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <StatusBadge status={camera.status} />
                    {camera.is_recording && <RecordingIndicator isRecording />}
                  </div>
                </div>
                <div className="flex-shrink-0">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="h-8 w-8">
                        <MoreVertical className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {canRecord && (
                        <DropdownMenuItem onClick={() => inlineToggle(camera)}>
                          {camera.is_recording ? (
                            <><Square className="h-4 w-4 mr-2" /> Stop Recording</>
                          ) : (
                            <><Play className="h-4 w-4 mr-2" /> Start Recording</>
                          )}
                        </DropdownMenuItem>
                      )}
                      {canManage && (
                        <DropdownMenuItem onClick={() => openEdit(camera)}>
                          <Pencil className="h-4 w-4 mr-2" /> Edit Camera
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
                </div>
              </div>
            ))
          )}
        </div>

        {/* ── Desktop views: table or grid ─────────────────────────────── */}
        <div className="hidden md:block">

          {/* === TABLE VIEW === */}
          {camerasView === "table" && (
            <div
              className="rounded overflow-hidden overflow-x-auto border"
              style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
            >
              <table className="min-w-[1100px] w-full text-xs" style={{ color: "var(--console-text)" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--console-border)", background: "var(--console-raised)" }}>
                    {sortAllowsDrag && canManage && <th className="w-[32px] px-2 py-2 align-middle" />}
                    <th className="w-[36px] px-2 py-2 text-left align-middle">
                      <input
                        type="checkbox"
                        aria-label="Select all on page"
                        className="accent-teal-400 cursor-pointer"
                        checked={allOnPageSelected}
                        onChange={toggleSelectAllOnPage}
                      />
                    </th>
                    <th className="w-[76px] px-2 py-2 text-left align-middle" style={{ color: "var(--console-muted)" }}>
                      <span className="font-telemetry uppercase tracking-wide text-[10px]">Preview</span>
                    </th>
                    <th className="w-[220px] px-2 py-2 text-left align-middle">
                      <SortHeader label="Camera" field="name" sort={sort} setSort={setSort} />
                    </th>
                    <th className="px-2 py-2 text-left align-middle">
                      <SortHeader label="Status" field="status" sort={sort} setSort={setSort} />
                    </th>
                    <th className="w-[110px] px-2 py-2 text-left align-middle">
                      <SortHeader label="Recording" field="recording" sort={sort} setSort={setSort} />
                    </th>
                    <th className="hidden lg:table-cell px-2 py-2 text-left align-middle">
                      <SortHeader label="Health" field="health" sort={sort} setSort={setSort} />
                    </th>
                    <th className="hidden xl:table-cell px-2 py-2 text-left align-middle">
                      <SortHeader label="Resolution" field="resolution" sort={sort} setSort={setSort} />
                    </th>
                    <th className="hidden md:table-cell px-2 py-2 text-left align-middle">
                      <SortHeader label="Last Online" field="last_online" sort={sort} setSort={setSort} />
                    </th>
                    <th className="w-[44px] px-2 py-2 align-middle" />
                  </tr>
                </thead>
                <tbody>
                  {paginated.length === 0 ? (
                    <tr>
                      <td
                        colSpan={sortAllowsDrag && canManage ? 10 : 9}
                        className="text-center py-12"
                      >
                        {!isLoading && camerasError && cameras.length === 0 ? (
                          <>
                            <AlertTriangle className="h-10 w-10 mx-auto mb-3" style={{ color: "var(--console-rec)" }} />
                            <p className="font-telemetry text-xs" style={{ color: "var(--console-rec)" }}>
                              Couldn't load cameras
                            </p>
                            <button
                              type="button"
                              onClick={() => refetchCameras()}
                              className="mt-4 px-3 py-1.5 rounded text-xs font-telemetry border"
                              style={{ borderColor: "var(--console-border)", color: "var(--console-text)", background: "var(--console-raised)" }}
                            >
                              <RefreshCw className="h-3.5 w-3.5 inline mr-1" /> Retry
                            </button>
                          </>
                        ) : (
                        <>
                        <Camera className="h-10 w-10 mx-auto mb-3" style={{ color: "var(--console-muted)" }} />
                        <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
                          {isLoading
                            ? "Loading cameras…"
                            : search || statusFilter !== "all" || groupFilter !== "all"
                              ? "No cameras match the current filters"
                              : "No cameras added yet"}
                        </p>
                        {!search && statusFilter === "all" && groupFilter === "all" && !isLoading && canManage && (
                          <button
                            type="button"
                            onClick={openAdd}
                            className="mt-4 px-3 py-1.5 rounded text-xs font-telemetry border"
                            style={{
                              borderColor: "var(--console-border)",
                              color: "var(--console-muted)",
                              background: "var(--console-raised)",
                            }}
                          >
                            <Plus className="h-3.5 w-3.5 inline mr-1" />
                            Add Your First Camera
                          </button>
                        )}
                        </>
                        )}
                      </td>
                    </tr>
                  ) : (
                    paginated.map((camera, idx) => {
                      const health = healthMap[camera.id];
                      const isDraggable = sortAllowsDrag && canManage;
                      return (
                        <tr
                          key={camera.id}
                          className="transition-colors"
                          style={{
                            borderBottom: "1px solid var(--console-border)",
                            background: selectedIds.has(camera.id)
                              ? "rgba(20,184,166,0.05)"
                              : "transparent",
                            opacity: !camera.is_enabled ? 0.5 : 1,
                          }}
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
                            <td className="px-2 py-2 align-middle cursor-grab active:cursor-grabbing" style={{ color: "var(--console-muted)" }}>
                              <GripVertical className="h-3.5 w-3.5" />
                            </td>
                          )}
                          <td className="px-2 py-2 align-middle" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              aria-label={`Select ${camera.name}`}
                              className="accent-teal-400 cursor-pointer"
                              checked={selectedIds.has(camera.id)}
                              onChange={() => toggleSelect(camera.id)}
                            />
                          </td>
                          <td className="px-2 py-2 align-middle" onClick={(e) => e.stopPropagation()}>
                            <button
                              type="button"
                              onClick={() => setPreviewCamera(camera)}
                              className="rounded overflow-hidden transition"
                              style={{ border: "1px solid var(--console-border)" }}
                              title="Open preview"
                            >
                              <CameraThumbnail cameraId={camera.id} className="w-16 h-10" />
                            </button>
                          </td>
                          <td className="px-2 py-2 align-middle">
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <p
                                  className="font-medium cursor-pointer hover:underline truncate"
                                  style={{ color: "var(--console-text)" }}
                                  onClick={() => navigate(`/cameras/${camera.id}`)}
                                >
                                  {camera.name}
                                </p>
                                {camera.retention_days != null && (
                                  <span
                                    className="font-telemetry text-[10px] px-1 py-0.5 rounded border flex-shrink-0"
                                    style={{
                                      color: "#c4b5fd",
                                      borderColor: "rgba(139,92,246,0.3)",
                                      background: "rgba(139,92,246,0.1)",
                                    }}
                                  >
                                    Ret: {camera.retention_days}d
                                  </span>
                                )}
                              </div>
                              <p
                                className="font-telemetry text-[10px] truncate max-w-[200px] mt-0.5"
                                style={{ color: "var(--console-muted)" }}
                              >
                                {camera.main_stream_url ? "Stream configured ✓" : "No stream configured"}
                              </p>
                            </div>
                          </td>
                          <td className="px-2 py-2 align-middle">
                            <div className="flex flex-col gap-1">
                              <StatusBadge status={camera.status} />
                              {camera.credentials_status === "unauthorized" && (
                                <a
                                  href={`/cameras/${camera.id}/settings#credentials`}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    navigate(`/cameras/${camera.id}/settings`);
                                    e.preventDefault();
                                  }}
                                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border hover:opacity-80 transition-opacity whitespace-nowrap font-telemetry"
                                  style={{
                                    color: "var(--console-alarm)",
                                    borderColor: "rgba(245,158,11,0.3)",
                                    background: "rgba(245,158,11,0.1)",
                                  }}
                                  title="ONVIF credentials invalid — click to update"
                                >
                                  Credentials invalid
                                </a>
                              )}
                            </div>
                          </td>
                          <td className="px-2 py-2 align-middle" onClick={(e) => e.stopPropagation()}>
                            {canRecord ? (
                              <button
                                type="button"
                                onClick={() => inlineToggle(camera)}
                                className="inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium border transition-colors font-telemetry"
                                style={
                                  camera.is_recording
                                    ? {
                                        background: "rgba(239,68,68,0.15)",
                                        color: "var(--console-rec)",
                                        borderColor: "rgba(239,68,68,0.3)",
                                      }
                                    : camera.status === "online"
                                      ? {
                                          background: "hsl(var(--ring) / 0.1)",
                                          color: "var(--console-online)",
                                          borderColor: "hsl(var(--ring) / 0.2)",
                                        }
                                      : {
                                          background: "var(--console-raised)",
                                          color: "var(--console-muted)",
                                          borderColor: "var(--console-border)",
                                          cursor: "not-allowed",
                                        }
                                }
                                disabled={!camera.is_recording && camera.status !== "online"}
                              >
                                {camera.is_recording ? (
                                  <><Square className="h-3 w-3" /> Stop</>
                                ) : (
                                  <><Play className="h-3 w-3" /> Start</>
                                )}
                              </button>
                            ) : camera.is_recording ? (
                              <RecordingIndicator isRecording />
                            ) : (
                              <span className="font-telemetry text-[11px]" style={{ color: "var(--console-muted)" }}>—</span>
                            )}
                          </td>
                          <td className="hidden lg:table-cell px-2 py-2 align-middle">
                            <HealthCell data={health} />
                          </td>
                          <td className="font-telemetry text-[11px] hidden xl:table-cell px-2 py-2 align-middle" style={{ color: "var(--console-muted)" }}>
                            {camera.resolution || "—"}
                          </td>
                          <td className="font-telemetry text-[11px] hidden md:table-cell px-2 py-2 align-middle" style={{ color: "var(--console-muted)" }}>
                            {camera.last_online_at
                              ? formatDateTime(camera.last_online_at)
                              : "Never"}
                          </td>
                          <td className="px-2 py-2 align-middle" onClick={(e) => e.stopPropagation()}>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <button
                                  type="button"
                                  className="p-1.5 rounded hover:bg-[var(--console-hover)] transition"
                                  style={{ color: "var(--console-muted)" }}
                                >
                                  <MoreVertical className="h-3.5 w-3.5" />
                                </button>
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
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* === GRID VIEW === */}
          {camerasView === "grid" && (
            <>
              {isLoading ? (
                <div
                  className="text-center py-16 font-telemetry text-xs"
                  style={{ color: "var(--console-muted)" }}
                >
                  Loading cameras…
                </div>
              ) : camerasError && cameras.length === 0 ? (
                <div className="text-center py-16 flex flex-col items-center gap-3">
                  <AlertTriangle className="h-12 w-12" style={{ color: "var(--console-rec)" }} />
                  <p className="font-telemetry text-xs" style={{ color: "var(--console-rec)" }}>
                    Couldn't load cameras
                  </p>
                  <button
                    type="button"
                    onClick={() => refetchCameras()}
                    className="px-3 py-1.5 rounded text-xs font-telemetry border"
                    style={{ borderColor: "var(--console-border)", color: "var(--console-text)", background: "var(--console-raised)" }}
                  >
                    <RefreshCw className="h-3.5 w-3.5 inline mr-1" /> Retry
                  </button>
                </div>
              ) : paginated.length === 0 ? (
                <div className="text-center py-16">
                  <Camera className="h-12 w-12 mx-auto mb-4" style={{ color: "var(--console-muted)" }} />
                  <p className="font-telemetry text-xs" style={{ color: "var(--console-muted)" }}>
                    {search || statusFilter !== "all" || groupFilter !== "all"
                      ? "No cameras match the current filters"
                      : "No cameras added yet"}
                  </p>
                  {!search && statusFilter === "all" && groupFilter === "all" && canManage && (
                    <button
                      type="button"
                      onClick={openAdd}
                      className="mt-4 px-3 py-1.5 rounded text-xs font-telemetry border"
                      style={{
                        borderColor: "var(--console-border)",
                        color: "var(--console-muted)",
                        background: "var(--console-raised)",
                      }}
                    >
                      <Plus className="h-3.5 w-3.5 inline mr-1" /> Add Your First Camera
                    </button>
                  )}
                </div>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
                  {paginated.map((camera, idx) => {
                    const isDraggable = sortAllowsDrag && canManage;
                    return (
                      <CameraGridCard
                        key={camera.id}
                        camera={camera}
                        health={healthMap[camera.id]}
                        selectedIds={selectedIds}
                        toggleSelect={toggleSelect}
                        inlineToggle={inlineToggle}
                        canOperate={canOperate}
                        canRecord={canRecord}
                        canManage={canManage}
                        onContextMenu={(e) => {
                          e.preventDefault();
                          setContextMenu({ x: e.clientX, y: e.clientY, camera });
                        }}
                        onPreview={setPreviewCamera}
                        openEdit={openEdit}
                        setDeleteTarget={setDeleteTarget}
                        navigate={navigate}
                        mutations={mutations}
                        isDraggable={isDraggable}
                        dragIdx={idx}
                        handleDragStart={handleDragStart}
                        handleDragOver={handleDragOver}
                        handleDrop={handleDrop}
                      />
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>

        {/* Drag hint */}
        {!sortAllowsDrag && canManage && total > 0 && (
          <p className="mt-2 font-telemetry text-[10px]" style={{ color: "var(--console-muted)" }}>
            Drag-to-reorder disabled — clear search/filter and sort by default order to rearrange.
          </p>
        )}

        {/* ── Pagination ───────────────────────────────────────────────── */}
        {total > 0 && (
          <div
            className="flex flex-wrap items-center justify-between gap-2 mt-3 font-telemetry text-[11px]"
            style={{ color: "var(--console-muted)" }}
          >
            <div className="flex items-center gap-2">
              <span>Rows per page</span>
              <select
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className="rounded px-2 py-0.5 border"
                style={{
                  background: "var(--console-raised)",
                  borderColor: "var(--console-border)",
                  color: "var(--console-text)",
                }}
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
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="px-2 py-1 rounded border disabled:opacity-30 hover:bg-[var(--console-hover)] transition"
                  style={{
                    borderColor: "var(--console-border)",
                    color: "var(--console-muted)",
                    background: "var(--console-raised)",
                  }}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  className="px-2 py-1 rounded border disabled:opacity-30 hover:bg-[var(--console-hover)] transition"
                  style={{
                    borderColor: "var(--console-border)",
                    color: "var(--console-muted)",
                    background: "var(--console-raised)",
                  }}
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Floating context menu ─────────────────────────────────────────── */}
      {contextMenu && (
        <div
          className="fixed z-50 min-w-[180px] rounded border shadow-2xl p-1 text-xs"
          style={{
            left: contextMenu.x,
            top: contextMenu.y,
            background: "var(--console-raised)",
            borderColor: "var(--console-border)",
            color: "var(--console-text)",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {canRecord && (
            <button
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded hover:bg-[var(--console-hover)]"
              onClick={() => {
                inlineToggle(contextMenu.camera);
                setContextMenu(null);
              }}
            >
              {contextMenu.camera.is_recording ? (
                <><Square className="h-3.5 w-3.5" /> Stop Recording</>
              ) : (
                <><Play className="h-3.5 w-3.5" /> Start Recording</>
              )}
            </button>
          )}
          {canOperate && (
            <button
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded hover:bg-[var(--console-hover)]"
              onClick={() => {
                mutations.test.mutate(contextMenu.camera.id);
                setContextMenu(null);
              }}
            >
              <RefreshCw className="h-3.5 w-3.5" /> Test Connection
            </button>
          )}
          <button
            className="w-full text-left flex items-center gap-2 px-3 py-2 rounded hover:bg-[var(--console-hover)]"
            onClick={() => {
              navigate(`/cameras/${contextMenu.camera.id}`);
              setContextMenu(null);
            }}
          >
            <ExternalLink className="h-3.5 w-3.5" /> View Details
          </button>
          {canManage && (
            <button
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded hover:bg-[var(--console-hover)]"
              onClick={() => {
                openEdit(contextMenu.camera);
                setContextMenu(null);
              }}
            >
              <Pencil className="h-3.5 w-3.5" /> Edit Camera
            </button>
          )}
          {canManage && (
            <>
              <div className="h-px my-1" style={{ background: "var(--console-border)" }} />
              <button
                className="w-full text-left flex items-center gap-2 px-3 py-2 rounded hover:bg-rose-500/10"
                style={{ color: "var(--console-rec)" }}
                onClick={() => {
                  setDeleteTarget(contextMenu.camera);
                  setContextMenu(null);
                }}
              >
                <Trash2 className="h-3.5 w-3.5" /> Delete Camera
              </button>
            </>
          )}
        </div>
      )}

      {/* ── Camera group manager ─────────────────────────────────────────── */}
      <Dialog
        open={showGroupManager}
        onOpenChange={(open) => {
          setShowGroupManager(open);
          if (!open) resetGroupForm();
        }}
      >
        <DialogContent className="w-[min(900px,calc(100vw-32px))] max-w-none">
          <DialogHeader>
            <DialogTitle>Camera Groups</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-4">
            <div
              className="rounded border overflow-hidden"
              style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
            >
              <div
                className="px-3 py-2 border-b font-telemetry text-[11px] uppercase tracking-wide"
                style={{ borderColor: "var(--console-border)", color: "var(--console-muted)" }}
              >
                Existing groups
              </div>
              <div className="max-h-[360px] overflow-y-auto">
                {groups.length === 0 ? (
                  <div className="p-6 text-sm" style={{ color: "var(--console-muted)" }}>
                    No groups created yet. Create a group to organize cameras.
                  </div>
                ) : (
                  groups.map((group) => {
                    const active = editingGroup?.id === group.id;
                    return (
                      <div
                        key={group.id}
                        className="flex items-center gap-3 px-3 py-2 border-b last:border-b-0"
                        style={{
                          borderColor: "var(--console-border)",
                          background: active ? "var(--console-hover)" : "transparent",
                        }}
                      >
                        <span
                          className="h-3 w-3 rounded-full shrink-0"
                          style={{ background: safeGroupColor(group.color) }}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium truncate" style={{ color: "var(--console-text)" }}>
                            {group.name}
                          </p>
                          <p className="text-[11px] truncate" style={{ color: "var(--console-muted)" }}>
                            {(cameraCountByGroupId.get(group.id) || 0)} camera{(cameraCountByGroupId.get(group.id) || 0) === 1 ? "" : "s"}
                            {group.description ? ` · ${group.description}` : ""}
                          </p>
                        </div>
                        <button
                          type="button"
                          className="h-7 px-2 rounded text-[11px] border hover:bg-[var(--console-hover)]"
                          style={{ borderColor: "var(--console-border)", color: "var(--console-text)" }}
                          onClick={() => openGroupEditor(group)}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="h-7 px-2 rounded text-[11px] border hover:bg-rose-500/10"
                          style={{ borderColor: "var(--console-border)", color: "var(--console-rec)" }}
                          disabled={groupDeleteMutation.isPending}
                          onClick={() => {
                            if (window.confirm(`Delete group "${group.name}"? Cameras will not be deleted.`)) {
                              groupDeleteMutation.mutate(group.id);
                            }
                          }}
                        >
                          Delete
                        </button>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            <div
              className="rounded border p-4 space-y-3"
              style={{ borderColor: "var(--console-border)", background: "var(--console-panel)" }}
            >
              <div>
                <p className="font-telemetry text-[11px] uppercase tracking-wide" style={{ color: "var(--console-text)" }}>
                  {editingGroup ? "Edit group" : "New group"}
                </p>
                <p className="text-[12px]" style={{ color: "var(--console-muted)" }}>
                  Use groups for filtering, permissions and bulk movement.
                </p>
              </div>
              <div className="space-y-1.5">
                <label className="text-[11px] uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
                  Group name
                </label>
                <Input
                  value={groupForm.name}
                  onChange={(e) => setGroupForm((prev) => ({ ...prev, name: e.target.value }))}
                  placeholder="Example: Ground Floor"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-[11px] uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
                  Description
                </label>
                <Input
                  value={groupForm.description}
                  onChange={(e) => setGroupForm((prev) => ({ ...prev, description: e.target.value }))}
                  placeholder="Optional"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-[11px] uppercase tracking-wide" style={{ color: "var(--console-muted)" }}>
                  Color
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={safeGroupColor(groupForm.color)}
                    onChange={(e) => setGroupForm((prev) => ({ ...prev, color: e.target.value }))}
                    className="h-9 w-12 rounded border bg-transparent"
                    style={{ borderColor: "var(--console-border)" }}
                  />
                  <Input
                    value={groupForm.color}
                    onChange={(e) => setGroupForm((prev) => ({ ...prev, color: e.target.value }))}
                    placeholder="#228B22"
                  />
                </div>
              </div>
              <div className="flex justify-between gap-2 pt-2">
                <Button variant="outline" onClick={resetGroupForm}>
                  Clear
                </Button>
                <Button
                  disabled={!groupForm.name.trim() || groupSaveMutation.isPending}
                  onClick={() =>
                    groupSaveMutation.mutate({
                      name: groupForm.name.trim(),
                      description: groupForm.description.trim() || null,
                      color: safeGroupColor(groupForm.color),
                    })
                  }
                >
                  {editingGroup ? "Update Group" : "Create Group"}
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Move to group dialog ──────────────────────────────────────────── */}
      <Dialog open={showMoveToGroup} onOpenChange={setShowMoveToGroup}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Move {selectedIds.size} camera{selectedIds.size !== 1 ? "s" : ""} to group</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            {groups.length === 0 ? (
              <div
                className="rounded border p-3 text-sm"
                style={{ borderColor: "var(--console-border)", color: "var(--console-muted)" }}
              >
                No groups available. Create a group first.
              </div>
            ) : (
              <Select value={moveGroupId} onValueChange={setMoveGroupId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a group…" />
                </SelectTrigger>
                <SelectContent>
                  {groups.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      {g.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>
          <div className="flex justify-end gap-2 mt-2">
            <Button
              variant="ghost"
              onClick={() => {
                setShowMoveToGroup(false);
                openGroupEditor();
              }}
            >
              Manage Groups
            </Button>
            <Button variant="outline" onClick={() => setShowMoveToGroup(false)}>Cancel</Button>
            <Button
              disabled={!moveGroupId || bulkMoveGroupMutation.isPending}
              onClick={() =>
                bulkMoveGroupMutation.mutate({
                  ids: Array.from(selectedIds),
                  groupId: moveGroupId,
                })
              }
            >
              Move
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Set retention dialog ──────────────────────────────────────────── */}
      <Dialog open={showSetRetention} onOpenChange={setShowSetRetention}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Set retention for {selectedIds.size} camera{selectedIds.size !== 1 ? "s" : ""}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-sm text-muted-foreground">
              Enter the number of days to keep recordings for the selected cameras.
              Leave blank to inherit the global retention setting.
            </p>
            <Input
              type="number"
              min={1}
              placeholder="Days (blank = global default)"
              value={retentionInput}
              onChange={(e) => setRetentionInput(e.target.value)}
            />
          </div>
          <div className="flex justify-end gap-2 mt-2">
            <Button variant="outline" onClick={() => setShowSetRetention(false)}>Cancel</Button>
            <Button
              disabled={bulkSetRetentionMutation.isPending}
              onClick={() =>
                bulkSetRetentionMutation.mutate({
                  ids: Array.from(selectedIds),
                  days: retentionInput === "" ? null : parseInt(retentionInput, 10),
                })
              }
            >
              Apply
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Apply schedule template dialog ───────────────────────────────── */}
      <Dialog open={showApplyTemplate} onOpenChange={setShowApplyTemplate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Apply schedule template to {selectedIds.size} camera{selectedIds.size !== 1 ? "s" : ""}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Select value={selectedTemplateId} onValueChange={setSelectedTemplateId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a template…" />
              </SelectTrigger>
              <SelectContent>
                {scheduleTemplates.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    <span>{t.name}</span>
                    {t.description && (
                      <span className="ml-2 text-xs text-muted-foreground">{t.description}</span>
                    )}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex justify-end gap-2 mt-2">
            <Button variant="outline" onClick={() => setShowApplyTemplate(false)}>Cancel</Button>
            <Button
              disabled={!selectedTemplateId || applyTemplateMutation.isPending}
              onClick={() =>
                applyTemplateMutation.mutate({
                  templateId: selectedTemplateId,
                  ids: Array.from(selectedIds),
                })
              }
            >
              Apply Template
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* ── Form dialog ───────────────────────────────────────────────────── */}
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

      {/* ── Single delete confirmation ─────────────────────────────────────── */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) {
            setDeleteTarget(null);
            setDeletePwd("");
            setDeletePwdError("");
          }
        }}
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
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">
              Confirm with your account password
            </label>
            <Input
              type="password"
              autoComplete="current-password"
              placeholder="Account password"
              value={deletePwd}
              onChange={(e) => {
                setDeletePwd(e.target.value);
                if (deletePwdError) setDeletePwdError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") confirmSingleDelete();
              }}
            />
            {deletePwdError && (
              <p className="text-xs text-rose-400">{deletePwdError}</p>
            )}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                confirmSingleDelete();
              }}
              className="bg-destructive hover:bg-destructive/90"
              disabled={deleteVerifying || mutations.remove.isPending}
            >
              {deleteVerifying || mutations.remove.isPending
                ? "Deleting…"
                : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ── Bulk delete confirmation ───────────────────────────────────────── */}
      <AlertDialog
        open={bulkConfirm}
        onOpenChange={(open) => {
          setBulkConfirm(open);
          if (!open) {
            setBulkPwd("");
            setDeletePwdError("");
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {selectedIds.size} cameras</AlertDialogTitle>
            <AlertDialogDescription>
              Selected cameras will be removed. Active recordings stop, stored
              recording files are deleted. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">
              Confirm with your account password
            </label>
            <Input
              type="password"
              autoComplete="current-password"
              placeholder="Account password"
              value={bulkPwd}
              onChange={(e) => {
                setBulkPwd(e.target.value);
                if (deletePwdError) setDeletePwdError("");
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") confirmBulkDelete();
              }}
            />
            {deletePwdError && (
              <p className="text-xs text-rose-400">{deletePwdError}</p>
            )}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                confirmBulkDelete();
              }}
              className="bg-destructive hover:bg-destructive/90"
              disabled={deleteVerifying || bulkDeleteMutation.isPending}
            >
              {deleteVerifying || bulkDeleteMutation.isPending
                ? "Deleting…"
                : `Delete ${selectedIds.size}`}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ── Preview modal ─────────────────────────────────────────────────── */}
      <Dialog
        open={!!previewCamera}
        onOpenChange={(open) => !open && setPreviewCamera(null)}
      >
        <DialogContent className="!max-w-3xl !p-0 !gap-0 !block overflow-hidden">
          {previewCamera && (
            <>
              <div
                className="flex items-center justify-between gap-3 px-5 py-3 border-b"
                style={{ borderColor: "var(--console-border)" }}
              >
                <DialogTitle className="flex items-center gap-2 text-sm font-semibold" style={{ color: "var(--console-text)" }}>
                  <Camera className="h-4 w-4" style={{ color: "var(--console-accent)" }} />
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
              <div
                className="flex items-center justify-between gap-3 px-5 py-3 border-t font-telemetry text-xs"
                style={{ borderColor: "var(--console-border)", color: "var(--console-muted)" }}
              >
                <span className="truncate flex-1">
                  {previewCamera.name}
                </span>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {previewCamera.resolution && (
                    <span>{previewCamera.resolution}</span>
                  )}
                  {canPlayback && (
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
                  )}
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

      {/* ── ONVIF Discovery ───────────────────────────────────────────────── */}
      <ONVIFDiscovery
        open={showOnvif}
        onOpenChange={setShowOnvif}
        onAdded={() => invalidate()}
      />
    </div>
  );
};

export default Cameras;
