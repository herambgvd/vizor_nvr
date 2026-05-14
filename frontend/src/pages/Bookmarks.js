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
} from "lucide-react";
import { getBookmarks, updateBookmark, deleteBookmark } from "../api/bookmarks";
import { getAllCameras } from "../api/cameras";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
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
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-amber-100 rounded-lg">
            <Bookmark className="h-6 w-6 text-amber-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Bookmarks</h1>
            <p className="text-sm text-muted-foreground">
              View and manage your saved recording bookmarks
            </p>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search bookmarks..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(1);
            }}
            className="pl-9"
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
          <SelectTrigger className="w-48">
            <Camera className="h-4 w-4 mr-2" />
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

      {/* Bookmarks List */}
      <div className="bg-card rounded-lg border">
        {isLoading ? (
          <div className="p-8 text-center text-muted-foreground">
            Loading bookmarks...
          </div>
        ) : bookmarks.length === 0 ? (
          <div className="p-8 text-center">
            <Bookmark className="h-12 w-12 text-muted-foreground mx-auto mb-3 opacity-50" />
            <p className="text-muted-foreground">
              {searchQuery || cameraId !== "all"
                ? "No bookmarks match your filters"
                : "No bookmarks yet. Create one while viewing a recording."}
            </p>
          </div>
        ) : (
          <div className="divide-y">
            {bookmarks.map((bookmark) => {
              const camera = cameraMap[bookmark.camera_id];
              return (
                <div
                  key={bookmark.id}
                  className="p-4 flex items-start gap-4 hover:bg-muted/50 transition-colors"
                >
                  {/* Camera icon */}
                  <div className="p-2 bg-card/60 rounded-lg shrink-0">
                    <Camera className="h-5 w-5 text-zinc-400" />
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium truncate">
                        {camera?.name || "Unknown Camera"}
                      </span>
                      <Badge variant="secondary" className="shrink-0">
                        <Clock className="h-3 w-3 mr-1" />
                        {formatTimestamp(bookmark.timestamp)}
                      </Badge>
                    </div>
                    {bookmark.note && (
                      <p className="text-sm text-muted-foreground line-clamp-2">
                        {bookmark.note}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground mt-1">
                      Created {format(new Date(bookmark.created_at), "PPp")}
                    </p>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 shrink-0">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handlePlayBookmark(bookmark)}
                      title="Play from bookmark"
                    >
                      <Play className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleEditClick(bookmark)}
                      title="Edit note"
                    >
                      <Edit2 className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setDeleteConfirm(bookmark)}
                      title="Delete bookmark"
                      className="text-destructive hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Pagination */}
        {(hasMore || hasPrev) && (
          <div className="flex items-center justify-between p-4 border-t">
            <span className="text-sm text-muted-foreground">Page {page}</span>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p - 1)}
                disabled={!hasPrev || isFetching}
              >
                <ChevronLeft className="h-4 w-4 mr-1" />
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => p + 1)}
                disabled={!hasMore || isFetching}
              >
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </div>
        )}
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
            <Button variant="outline" onClick={() => setEditingBookmark(null)}>
              Cancel
            </Button>
            <Button
              onClick={handleSaveEdit}
              disabled={updateMutation.isPending}
            >
              <Check className="h-4 w-4 mr-2" />
              Save
            </Button>
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
            <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteMutation.mutate(deleteConfirm.id)}
              disabled={deleteMutation.isPending}
            >
              <Trash2 className="h-4 w-4 mr-2" />
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default Bookmarks;
