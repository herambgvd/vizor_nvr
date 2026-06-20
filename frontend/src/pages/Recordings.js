// =============================================================================
// Recordings — Browse, search, download, and delete recordings
// =============================================================================

import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  Film,
  Search,
  Download,
  Trash2,
  ChevronLeft,
  ChevronRight,
  CheckSquare,
  Square,
  Camera,
  HardDrive,
} from "lucide-react";
import {
  getRecordings,
  deleteRecording,
  bulkDeleteRecordings,
  getRecordingDownloadUrl,
} from "../api/recordings";
import { getAllCameras } from "../api/cameras";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
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
import { toast } from "sonner";
import { friendlyError } from "../lib/utils";

const PAGE_SIZE = 25;

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
};

const formatDuration = (seconds) => {
  if (!seconds) return "-";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
};

const Recordings = () => {
  const qc = useQueryClient();

  // Filters
  const [page, setPage] = useState(1);
  const [cameraFilter, setCameraFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // Selection
  const [selected, setSelected] = useState(new Set());
  const [deleteTarget, setDeleteTarget] = useState(null); // single delete
  const [showBulkDelete, setShowBulkDelete] = useState(false);

  // Build query params — unified pagination contract: limit + offset.
  // The recordings list endpoint filters on start_after / end_before.
  const params = useMemo(() => {
    const p = { limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE };
    if (cameraFilter && cameraFilter !== "all") p.camera_id = cameraFilter;
    if (search.trim()) p.search = search.trim();
    if (startDate) p.start_after = `${startDate}T00:00:00`;
    if (endDate) p.end_before = `${endDate}T23:59:59`;
    return p;
  }, [page, cameraFilter, search, startDate, endDate]);

  // Queries
  const { data, isLoading } = useQuery({
    queryKey: ["recordings", params],
    queryFn: () => getRecordings(params),
  });

  const { data: cameras = [] } = useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
  });

  const recordings = Array.isArray(data) ? data : (data?.items ?? []);
  const total = data?.total ?? recordings.length;
  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  // Mutations
  const deleteMut = useMutation({
    mutationFn: deleteRecording,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recordings"] });
      toast.success("Recording deleted");
      setDeleteTarget(null);
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't delete the recording")),
  });

  const bulkDeleteMut = useMutation({
    mutationFn: (ids) => bulkDeleteRecordings(ids),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["recordings"] });
      toast.success(`Deleted ${res?.deleted ?? selected.size} recordings`);
      setSelected(new Set());
      setShowBulkDelete(false);
    },
    onError: (e) => toast.error(friendlyError(e, "Couldn't delete the selected recordings")),
  });

  // Camera name lookup
  const cameraMap = useMemo(() => {
    const m = {};
    cameras.forEach((c) => {
      m[c.id] = c.name;
    });
    return m;
  }, [cameras]);

  // Selection helpers
  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === recordings.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(recordings.map((r) => r.id)));
    }
  };

  const handleDownload = (id) => {
    const url = getRecordingDownloadUrl(id);
    window.open(url, "_blank");
  };

  return (
    <div className="p-4 md:p-8 h-full overflow-y-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6 md:mb-8">
        <div>
          <h1
            className="text-2xl md:text-3xl font-bold text-white tracking-tight"
            style={{ fontFamily: "Manrope, sans-serif" }}
          >
            Recordings
          </h1>
          <p className="text-muted-foreground mt-1 text-sm md:text-base">
            Browse, download, and manage recorded footage
          </p>
        </div>
        {selected.size > 0 && (
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setShowBulkDelete(true)}
          >
            <Trash2 className="h-4 w-4 mr-1" />
            Delete {selected.size} Selected
          </Button>
        )}
      </div>

      {/* Filters */}
      <div className="border border-[var(--console-border)] rounded-lg p-3 md:p-4 mb-4 md:mb-6" style={{ backgroundColor: 'var(--console-panel)' }}>
        <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-5 gap-3 md:gap-4">
          <div>
            <Label className="text-xs">Camera</Label>
            <Select
              value={cameraFilter}
              onValueChange={(v) => {
                setCameraFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="All cameras" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All cameras</SelectItem>
                {cameras.map((c) => (
                  <SelectItem key={c.id} value={c.id}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Search</Label>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                className="pl-8"
                placeholder="Search…"
              />
            </div>
          </div>
          <div>
            <Label className="text-xs">From</Label>
            <Input
              type="date"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div>
            <Label className="text-xs">To</Label>
            <Input
              type="date"
              value={endDate}
              onChange={(e) => {
                setEndDate(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <div className="flex items-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setCameraFilter("all");
                setSearch("");
                setStartDate("");
                setEndDate("");
                setPage(1);
              }}
            >
              Clear Filters
            </Button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="border border-[var(--console-border)] rounded-lg overflow-hidden" style={{ backgroundColor: 'var(--console-panel)' }}>
        {isLoading ? (
          <div className="p-10 text-center text-muted-foreground">Loading…</div>
        ) : recordings.length === 0 ? (
          <div className="p-10 text-center text-muted-foreground">
            <Film className="h-10 w-10 mx-auto mb-3 opacity-50" />
            <p>No recordings found</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-[var(--console-border)]" style={{ backgroundColor: 'var(--console-raised)' }}>
              <tr>
                <th className="w-10 px-4 py-3">
                  <button onClick={toggleSelectAll}>
                    {selected.size === recordings.length ? (
                      <CheckSquare className="h-4 w-4 text-white" />
                    ) : (
                      <Square className="h-4 w-4 text-muted-foreground" />
                    )}
                  </button>
                </th>
                <th className="text-left px-4 py-3 text-[var(--console-muted)] font-medium">
                  Camera
                </th>
                <th className="text-left px-4 py-3 text-[var(--console-muted)] font-medium">
                  Start Time
                </th>
                <th className="text-left px-4 py-3 text-[var(--console-muted)] font-medium">
                  Duration
                </th>
                <th className="text-left px-4 py-3 text-[var(--console-muted)] font-medium">
                  Size
                </th>
                <th className="text-right px-4 py-3 text-[var(--console-muted)] font-medium">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {recordings.map((rec) => (
                <tr
                  key={rec.id}
                  className="border-b border-[var(--console-border)] last:border-0 hover:bg-[var(--console-raised)]"
                >
                  <td className="px-4 py-3">
                    <button onClick={() => toggleSelect(rec.id)}>
                      {selected.has(rec.id) ? (
                        <CheckSquare className="h-4 w-4 text-white" />
                      ) : (
                        <Square className="h-4 w-4 text-muted-foreground" />
                      )}
                    </button>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Camera className="h-4 w-4 text-muted-foreground" />
                      <span className="font-medium text-white">
                        {cameraMap[rec.camera_id] ||
                          rec.camera_id?.substring(0, 8)}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-[var(--console-muted)]">
                    {rec.start_time
                      ? format(new Date(rec.start_time), "MMM d, yyyy HH:mm:ss")
                      : "-"}
                  </td>
                  <td className="px-4 py-3 text-[var(--console-muted)]">
                    {rec.duration
                      ? formatDuration(rec.duration)
                      : rec.start_time && rec.end_time
                        ? formatDuration(
                            (new Date(rec.end_time) -
                              new Date(rec.start_time)) /
                              1000,
                          )
                        : "-"}
                  </td>
                  <td className="px-4 py-3 text-[var(--console-muted)]">
                    <div className="flex items-center gap-1">
                      <HardDrive className="h-3 w-3 text-muted-foreground" />
                      {formatBytes(rec.file_size)}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => handleDownload(rec.id)}
                        title="Download"
                      >
                        <Download className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 hover:opacity-80"
                        style={{ color: 'var(--console-rec)' }}
                        onClick={() => setDeleteTarget(rec)}
                        title="Delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-muted-foreground">
            Page {page} of {totalPages} ({total} total)
          </p>
          <div className="flex gap-2">
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
      )}

      {/* Single Delete Confirm */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={() => setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Recording</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete the recording file. This action
              cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive hover:bg-destructive/90"
              onClick={() => deleteMut.mutate(deleteTarget.id)}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Bulk Delete Confirm */}
      <AlertDialog open={showBulkDelete} onOpenChange={setShowBulkDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {selected.size} Recordings
            </AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete {selected.size} recording files. This
              cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive hover:bg-destructive/90"
              onClick={() => bulkDeleteMut.mutate([...selected])}
            >
              Delete All
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default Recordings;
