// =============================================================================
// Bookmarks — List, search, and jump to bookmarked recording timestamps
// =============================================================================

import React, { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Bookmark,
  Camera,
  ChevronLeft,
  ChevronRight,
  Clock,
  Play,
  Search,
  Trash2,
  Edit2,
  Check,
  X,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";
import { getBookmarks, updateBookmark, deleteBookmark } from "../api/bookmarks";
import { getAllCameras } from "../api/cameras";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { toast } from "sonner";
import { format } from "date-fns";

const PAGE_SIZE = 20;

const inputStyle = {
  background: "var(--console-raised)",
  border: "1px solid var(--console-border)",
  color: "var(--console-text)",
};

const Bookmarks = () => {
  const qc = useQueryClient();
  const navigate = useNavigate();

  // Filters
  const [page, setPage] = useState(1);
  const [cameraId, setCameraId] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Edit dialog
  const [editingBookmark, setEditingBookmark] = useState(null);
  const [editNote, setEditNote] = useState("");

  // Delete confirmation
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  // Build query params
  const params = useMemo(() => {
    const p = {
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    };
    if (cameraId !== "all") p.camera_id = cameraId;
    if (searchQuery.trim()) p.search = searchQuery.trim();
    return p;
  }, [page, cameraId, searchQuery]);

  // Fetch bookmarks
  const {
    data: bookmarks = [],
    isLoading,
    isFetching,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["bookmarks", params],
    queryFn: () => getBookmarks(params),
    staleTime: 30000,
  });

  // Fetch cameras for filter dropdown and name lookup
  const { data: cameras = [] } = useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
    staleTime: 60000,
  });

  // Camera lookup map
  const cameraMap = useMemo(() => {
    return cameras.reduce((acc, cam) => {
      acc[cam.id] = cam;
      return acc;
    }, {});
  }, [cameras]);

  // Update bookmark mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }) => updateBookmark(id, data),
    onSuccess: () => {
      toast.success("Bookmark updated");
      qc.invalidateQueries({ queryKey: ["bookmarks"] });
      setEditingBookmark(null);
    },
    onError: () => toast.error("Failed to update bookmark"),
  });

  // Delete bookmark mutation
  const deleteMutation = useMutation({
    mutationFn: deleteBookmark,
    onSuccess: () => {
      toast.success("Bookmark deleted");
      qc.invalidateQueries({ queryKey: ["bookmarks"] });
      setDeleteConfirm(null);
    },
    onError: () => toast.error("Failed to delete bookmark"),
  });

  // Format timestamp for display
  const formatTimestamp = (seconds) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
    }
    return `${minutes}:${secs.toString().padStart(2, "0")}`;
  };

  // Handle play bookmark - navigate to playback page
  const handlePlayBookmark = (bookmark) => {
    // Navigate to playback page with camera selected and timestamp
    const camera = cameraMap[bookmark.camera_id];
    if (camera) {
      // Extract date from created_at for the playback page
      const bookmarkDate = new Date(bookmark.created_at);
      const dateStr = format(bookmarkDate, "yyyy-MM-dd");

      // Navigate to playback with query params
      navigate(
        `/playback?camera=${bookmark.camera_id}&date=${dateStr}&t=${bookmark.timestamp}`,
      );
    } else {
      toast.error("Camera not found");
    }
  };

  // Open edit dialog
  const handleEditClick = (bookmark) => {
    setEditingBookmark(bookmark);
    setEditNote(bookmark.note || "");
  };

  // Save edit
  const handleSaveEdit = () => {
    if (editingBookmark) {
      updateMutation.mutate({
        id: editingBookmark.id,
        data: { note: editNote },
      });
    }
  };

  // Pagination
  const hasMore = bookmarks.length === PAGE_SIZE;
  const hasPrev = page > 1;

  return (
    <div
      className="h-full flex flex-col overflow-hidden"
      style={{ background: "var(--console-bg)", color: "var(--console-text)" }}
    >
      {/* Page header bar */}
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
            Bookmarks
          </span>
        </div>
        <div className="flex-1" />
      </div>

      {/* Toolbar / filter row */}
      <div
        className="flex flex-wrap items-center gap-2 px-4 py-2 border-b flex-shrink-0"
        style={{ background: "var(--console-panel)", borderColor: "var(--console-border)" }}
      >
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search
            className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5"
            style={{ color: "var(--console-muted)" }}
          />
          <input
            type="text"
            placeholder="Search bookmarks…"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(1);
            }}
            className="w-full pl-8 pr-3 rounded text-xs border outline-none focus:ring-1 font-telemetry h-[30px]"
            style={{
              ...inputStyle,
              "--tw-ring-color": "var(--console-accent)",
            }}
          />
        </div>

        {/* Camera filter */}
        <Select
          value={cameraId}
          onValueChange={(v) => {
            setCameraId(v);
            setPage(1);
          }}
        >
          <SelectTrigger
            className="h-[30px] w-48 text-xs font-telemetry"
            style={inputStyle}
          >
            <Camera className="h-3.5 w-3.5 mr-2 flex-shrink-0" style={{ color: "var(--console-muted)" }} />
            <SelectValue placeholder="All Cameras" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Cameras</SelectItem>
            {cameras.map((cam) => (
              <SelectItem key={cam.id} value={cam.id}>
                {cam.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Bookmarks list */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div
          className="rounded-none border-0"
          style={{ background: "var(--console-bg)" }}
        >
          {isLoading ? (
            <div
              className="p-8 text-center font-telemetry text-xs"
              style={{ color: "var(--console-muted)" }}
            >
              Loading bookmarks…
            </div>
          ) : isError ? (
            <div className="p-8 text-center">
              <AlertTriangle
                className="h-10 w-10 mx-auto mb-3"
                style={{ color: "var(--console-rec)" }}
              />
              <p
                className="font-telemetry text-xs mb-3"
                style={{ color: "var(--console-rec)" }}
              >
                Failed to load bookmarks
              </p>
              <button
                type="button"
                onClick={() => refetch()}
                className="inline-flex items-center gap-1.5 h-[28px] px-3 rounded font-telemetry text-xs border transition-colors hover:bg-white/5"
                style={{
                  background: "var(--console-raised)",
                  borderColor: "var(--console-border)",
                  color: "var(--console-text)",
                }}
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Retry
              </button>
            </div>
          ) : bookmarks.length === 0 ? (
            <div className="p-8 text-center">
              <Bookmark
                className="h-10 w-10 mx-auto mb-3 opacity-30"
                style={{ color: "var(--console-muted)" }}
              />
              <p
                className="font-telemetry text-xs"
                style={{ color: "var(--console-muted)" }}
              >
                {searchQuery || cameraId !== "all"
                  ? "No bookmarks match your filters"
                  : "No bookmarks yet. Create one while viewing a recording."}
              </p>
            </div>
          ) : (
            <div>
              {bookmarks.map((bookmark) => {
                const camera = cameraMap[bookmark.camera_id];
                return (
                  <div
                    key={bookmark.id}
                    className="flex items-start gap-3 px-4 py-3 border-b transition-colors"
                    style={{
                      borderColor: "var(--console-border)",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = "var(--console-panel)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "transparent";
                    }}
                  >
                    {/* Camera icon */}
                    <div
                      className="p-1.5 rounded flex-shrink-0 mt-0.5"
                      style={{
                        background: "var(--console-raised)",
                        border: "1px solid var(--console-border)",
                      }}
                    >
                      <Camera className="h-4 w-4" style={{ color: "var(--console-muted)" }} />
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span
                          className="font-telemetry text-xs font-semibold truncate"
                          style={{ color: "var(--console-text)" }}
                        >
                          {camera?.name || "Unknown Camera"}
                        </span>
                        <span
                          className="inline-flex items-center gap-1 font-telemetry text-[10px] px-1.5 py-0.5 rounded flex-shrink-0"
                          style={{
                            background: "var(--console-raised)",
                            border: "1px solid var(--console-border)",
                            color: "var(--console-accent)",
                          }}
                        >
                          <Clock className="h-2.5 w-2.5" />
                          {formatTimestamp(bookmark.timestamp)}
                        </span>
                      </div>
                      {bookmark.note && (
                        <p
                          className="font-telemetry text-xs line-clamp-2 mb-0.5"
                          style={{ color: "var(--console-muted)" }}
                        >
                          {bookmark.note}
                        </p>
                      )}
                      <p
                        className="font-telemetry text-[10px]"
                        style={{ color: "var(--console-muted)" }}
                      >
                        {format(new Date(bookmark.created_at), "PPp")}
                      </p>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <button
                        type="button"
                        onClick={() => handlePlayBookmark(bookmark)}
                        title="Play from bookmark"
                        className="p-1.5 rounded transition-colors hover:bg-white/5"
                        style={{ color: "var(--console-accent)" }}
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleEditClick(bookmark)}
                        title="Edit note"
                        className="p-1.5 rounded transition-colors hover:bg-white/5"
                        style={{ color: "var(--console-muted)" }}
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeleteConfirm(bookmark)}
                        title="Delete bookmark"
                        className="p-1.5 rounded transition-colors hover:bg-white/5"
                        style={{ color: "var(--console-rec)" }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Pagination */}
          {(hasMore || hasPrev) && (
            <div
              className="flex items-center justify-between px-4 py-2.5 border-t"
              style={{
                background: "var(--console-panel)",
                borderColor: "var(--console-border)",
              }}
            >
              <span
                className="font-telemetry text-xs"
                style={{ color: "var(--console-muted)" }}
              >
                PAGE {page}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => p - 1)}
                  disabled={!hasPrev || isFetching}
                  className="h-[28px] px-3 rounded font-telemetry text-xs border transition-colors disabled:opacity-40 flex items-center gap-1 hover:bg-white/5"
                  style={{
                    background: "var(--console-raised)",
                    borderColor: "var(--console-border)",
                    color: "var(--console-muted)",
                  }}
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  Prev
                </button>
                <button
                  type="button"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={!hasMore || isFetching}
                  className="h-[28px] px-3 rounded font-telemetry text-xs border transition-colors disabled:opacity-40 flex items-center gap-1 hover:bg-white/5"
                  style={{
                    background: "var(--console-raised)",
                    borderColor: "var(--console-border)",
                    color: "var(--console-muted)",
                  }}
                >
                  Next
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Edit Dialog */}
      <Dialog
        open={!!editingBookmark}
        onOpenChange={(open) => !open && setEditingBookmark(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Bookmark</DialogTitle>
            <DialogDescription>
              Update the note for this bookmark.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="Add a note..."
            value={editNote}
            onChange={(e) => setEditNote(e.target.value)}
            rows={3}
          />
          <DialogFooter>
            <button
              type="button"
              onClick={() => setEditingBookmark(null)}
              className="h-[30px] px-3 rounded font-telemetry text-xs border transition-colors hover:bg-white/5"
              style={{
                background: "var(--console-raised)",
                borderColor: "var(--console-border)",
                color: "var(--console-muted)",
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSaveEdit}
              disabled={updateMutation.isPending}
              className="h-[30px] px-3 rounded font-telemetry text-xs transition-colors flex items-center gap-1.5 disabled:opacity-50"
              style={{
                background: "var(--console-accent)",
                color: "#06231f",
              }}
            >
              <Check className="h-3.5 w-3.5" />
              Save
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={!!deleteConfirm}
        onOpenChange={(open) => !open && setDeleteConfirm(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Bookmark?</DialogTitle>
            <DialogDescription>
              This action cannot be undone. The bookmark will be permanently
              deleted.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setDeleteConfirm(null)}
              className="h-[30px] px-3 rounded font-telemetry text-xs border transition-colors hover:bg-white/5"
              style={{
                background: "var(--console-raised)",
                borderColor: "var(--console-border)",
                color: "var(--console-muted)",
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => deleteMutation.mutate(deleteConfirm.id)}
              disabled={deleteMutation.isPending}
              className="h-[30px] px-3 rounded font-telemetry text-xs transition-colors flex items-center gap-1.5 disabled:opacity-50"
              style={{
                background: "var(--console-rec)",
                color: "#fff",
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Bookmarks;
