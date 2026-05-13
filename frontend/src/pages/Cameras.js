// =============================================================================
// Cameras — Table-based camera management
// =============================================================================

import React, { useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Camera,
  Plus,
  Search,
  MoreVertical,
  Play,
  Square,
  RefreshCw,
  Trash2,
  Video,
  ExternalLink,
  Pencil,
  Wifi,
} from "lucide-react";
import { useCamerasQuery, useCameraMutations } from "../hooks";
import { usePermissions } from "../hooks/usePermissions";
import {
  StatusBadge,
  RecordingIndicator,
  CameraFormDialog,
  ONVIFDiscovery,
} from "../components/nvr";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
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

const Cameras = () => {
  const navigate = useNavigate();
  const { canOperate, canManage } = usePermissions();
  const { data: cameras = [], isLoading } = useCamerasQuery();
  const mutations = useCameraMutations();

  // Local state
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [showOnvif, setShowOnvif] = useState(false);
  const [selected, setSelected] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    if (!q) return cameras;
    return cameras.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.location?.toLowerCase().includes(q) ||
        c.main_stream_url?.toLowerCase().includes(q),
    );
  }, [cameras, search]);

  // Dialog helpers
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

  return (
    <div className="p-4 md:p-8 h-full overflow-y-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6 md:mb-8">
        <div>
          <h1
            className="text-2xl md:text-3xl font-bold text-white tracking-tight"
            style={{ fontFamily: "Manrope, sans-serif" }}
          >
            Cameras
          </h1>
          <p className="text-zinc-500 mt-1 text-sm md:text-base">
            Manage your camera network ({cameras.length} cameras)
          </p>
        </div>
        {canManage && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowOnvif(true)}
              className="flex-1 sm:flex-none"
            >
              <Wifi className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Discover ONVIF</span>
            </Button>
            <Button
              onClick={openAdd}
              className="bg-zinc-900 hover:bg-zinc-900/60 flex-1 sm:flex-none"
              size="sm"
            >
              <Plus className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Add Camera</span>
            </Button>
          </div>
        )}
      </div>

      {/* Search */}
      <div className="mb-4 md:mb-6 relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500" />
        <Input
          placeholder="Search cameras…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-10"
        />
      </div>

      {/* Table */}
      <div className="bg-zinc-950 border border-white/10 rounded-lg overflow-hidden overflow-x-auto">
        <Table className="min-w-[800px]">
          <TableHeader>
            <TableRow className="bg-zinc-950/40">
              <TableHead className="w-[250px]">Camera</TableHead>
              <TableHead className="hidden md:table-cell">Location</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Recording</TableHead>
              <TableHead className="hidden lg:table-cell">Resolution</TableHead>
              <TableHead className="hidden md:table-cell">
                Last Online
              </TableHead>
              <TableHead className="w-[50px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-12">
                  <Camera className="h-12 w-12 text-slate-300 mx-auto mb-4" />
                  <p className="text-zinc-500">
                    {search
                      ? "No cameras match your search"
                      : "No cameras added yet"}
                  </p>
                  {!search && canManage && (
                    <Button
                      onClick={openAdd}
                      variant="outline"
                      className="mt-4"
                    >
                      <Plus className="h-4 w-4 mr-2" />
                      Add Your First Camera
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ) : (
              filtered.map((camera) => (
                <TableRow key={camera.id}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div
                        className={`p-2 rounded-lg ${camera.is_enabled ? "bg-white/[0.04]" : "bg-zinc-950/40"}`}
                      >
                        <Video
                          className={`h-5 w-5 ${camera.is_enabled ? "text-zinc-400" : "text-zinc-500"}`}
                        />
                      </div>
                      <div>
                        <p
                          className="font-medium text-white hover:text-blue-600 cursor-pointer transition-colors"
                          onClick={() => navigate(`/cameras/${camera.id}`)}
                        >
                          {camera.name}
                        </p>
                        <p className="text-xs text-zinc-500 truncate max-w-[180px]">
                          {camera.main_stream_url}
                        </p>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-zinc-400 hidden md:table-cell">
                    {camera.location || "-"}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={camera.status} />
                  </TableCell>
                  <TableCell>
                    {camera.is_recording ? (
                      <RecordingIndicator isRecording />
                    ) : (
                      <span className="text-sm text-zinc-500">
                        Not recording
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-sm text-zinc-400 hidden lg:table-cell">
                    {camera.resolution || "-"}
                  </TableCell>
                  <TableCell className="text-sm text-zinc-500 hidden md:table-cell">
                    {camera.last_online_at
                      ? new Date(camera.last_online_at).toLocaleString()
                      : "Never"}
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" className="h-8 w-8">
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {canManage && (
                          <DropdownMenuItem onClick={() => openEdit(camera)}>
                            <Pencil className="h-4 w-4 mr-2" />
                            Edit Camera
                          </DropdownMenuItem>
                        )}
                        {canOperate &&
                          (camera.is_recording ? (
                            <DropdownMenuItem
                              onClick={() => mutations.stop.mutate(camera.id)}
                            >
                              <Square className="h-4 w-4 mr-2" />
                              Stop Recording
                            </DropdownMenuItem>
                          ) : (
                            <DropdownMenuItem
                              onClick={() => mutations.start.mutate(camera.id)}
                              disabled={camera.status !== "online"}
                            >
                              <Play className="h-4 w-4 mr-2" />
                              Start Recording
                            </DropdownMenuItem>
                          ))}
                        {canOperate && (
                          <DropdownMenuItem
                            onClick={() => mutations.test.mutate(camera.id)}
                          >
                            <RefreshCw className="h-4 w-4 mr-2" />
                            Test Connection
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                          onClick={() => navigate(`/cameras/${camera.id}`)}
                        >
                          <ExternalLink className="h-4 w-4 mr-2" />
                          View Details
                        </DropdownMenuItem>
                        {canManage && (
                          <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={() => setDeleteTarget(camera)}
                              className="text-red-600 focus:text-red-600"
                            >
                              <Trash2 className="h-4 w-4 mr-2" />
                              Delete Camera
                            </DropdownMenuItem>
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Form dialog */}
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

      {/* Delete confirmation */}
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
              className="bg-red-600 hover:bg-red-700"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* ONVIF Discovery */}
      <ONVIFDiscovery
        open={showOnvif}
        onOpenChange={setShowOnvif}
        onSelect={(cameraData) => {
          setSelected(cameraData);
          setShowForm(true);
        }}
      />
    </div>
  );
};

export default Cameras;
