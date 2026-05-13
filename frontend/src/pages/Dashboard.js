// =============================================================================
// Dashboard — Camera grid with status cards
// =============================================================================

import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Video, Plus, RefreshCw, Wifi, WifiOff } from "lucide-react";
import { useCamerasQuery, useCameraMutations } from "../hooks";
import { usePermissions } from "../hooks/usePermissions";
import { CameraGrid, CameraFormDialog } from "../components/nvr";
import { Button } from "../components/ui/button";
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

const Dashboard = () => {
  const navigate = useNavigate();
  const { canOperate, canManage } = usePermissions();

  // Shared camera data & mutations
  const { data: cameras = [], isLoading, refetch } = useCamerasQuery();
  const mutations = useCameraMutations();

  // Dialog state
  const [showForm, setShowForm] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [selected, setSelected] = useState(null);

  // Handlers
  const openAdd = () => {
    setSelected(null);
    setShowForm(true);
  };
  const openEdit = (cam) => {
    setSelected(cam);
    setShowForm(true);
  };
  const openDelete = (cam) => {
    setSelected(cam);
    setShowForm(false);
    setShowDelete(true);
  };

  const handleSubmit = (data) => {
    const onSuccess = () => {
      setShowForm(false);
      setSelected(null);
    };
    if (selected) {
      mutations.update.mutate({ id: selected.id, data }, { onSuccess });
    } else {
      mutations.create.mutate(data, { onSuccess });
    }
  };

  const handleDelete = () => {
    mutations.remove.mutate(selected?.id, {
      onSuccess: () => {
        setShowDelete(false);
        setSelected(null);
      },
    });
  };

  // Stats
  const onlineCount = cameras.filter((c) => c.status === "online").length;
  const recordingCount = cameras.filter((c) => c.is_recording).length;
  const offlineCount = cameras.filter((c) => c.status === "offline").length;

  return (
    <div className="p-4 md:p-8 h-full overflow-y-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6 md:mb-8">
        <div>
          <h1
            className="text-2xl md:text-3xl font-bold text-white  tracking-tight"
            style={{ fontFamily: "Manrope, sans-serif" }}
          >
            Dashboard
          </h1>
          <p className="text-zinc-500 mt-1 text-sm md:text-base">
            Monitor and manage your camera network
          </p>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          <Button
            variant="outline"
            onClick={() => refetch()}
            disabled={isLoading}
            size="sm"
            className="flex-1 sm:flex-none"
          >
            <RefreshCw
              className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
          {canManage && (
            <Button
              onClick={openAdd}
              className="bg-zinc-900 hover:bg-zinc-900/60 flex-1 sm:flex-none"
              size="sm"
            >
              <Plus className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Add Camera</span>
            </Button>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-4 mb-6 md:mb-8">
        <StatCard
          label="Total Cameras"
          value={cameras.length}
          icon={Video}
          color="slate"
          sub={`${cameras.length} registered`}
        />
        <StatCard
          label="Online"
          value={onlineCount}
          icon={Wifi}
          color="emerald"
          sub="Connected cameras"
        />
        <StatCard
          label="Recording"
          value={recordingCount}
          icon={Video}
          color="red"
          sub="Active recordings"
          pulse={recordingCount > 0}
        />
        <StatCard
          label="Offline"
          value={offlineCount}
          icon={WifiOff}
          color="slate"
          sub="Disconnected cameras"
        />
      </div>

      {/* Grid */}
      <CameraGrid
        cameras={cameras}
        isLoading={isLoading}
        loadingCameras={[]}
        maxCameras={128}
        onCameraClick={(cam) => navigate(`/playback?camera=${cam.id}`)}
        onStartRecording={(cam) => canOperate && mutations.start.mutate(cam.id)}
        onStopRecording={(cam) => canOperate && mutations.stop.mutate(cam.id)}
        onTestConnection={(cam) => canOperate && mutations.test.mutate(cam.id)}
        onCameraSettings={canManage ? openEdit : undefined}
        onCameraFullscreen={(cam) => navigate(`/live/${cam.id}`)}
        onAddCamera={canManage ? openAdd : undefined}
      />

      {/* Form dialog */}
      <CameraFormDialog
        open={showForm}
        onOpenChange={(open) => {
          setShowForm(open);
          if (!open) setSelected(null);
        }}
        camera={selected}
        onSubmit={handleSubmit}
        onDelete={openDelete}
        isPending={mutations.create.isPending || mutations.update.isPending}
      />

      {/* Delete confirmation */}
      <AlertDialog open={showDelete} onOpenChange={setShowDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Camera</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete "{selected?.name}"? This will stop
              any active recordings and cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              className="bg-red-600 hover:bg-red-700"
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

// ---------- stat card ----------

const colorMap = {
  slate: { bg: "bg-white/[0.04]", text: "text-zinc-400" },
  emerald: { bg: "bg-emerald-50", text: "text-emerald-600" },
  red: { bg: "bg-red-50", text: "text-red-600" },
};

const StatCard = ({ label, value, icon: Icon, color, sub, pulse }) => {
  const c = colorMap[color] || colorMap.slate;
  return (
    <div className="bg-zinc-950 border border-white/10 rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-zinc-500">{label}</p>
          <p className={`text-2xl font-bold ${c.text}`}>{value}</p>
        </div>
        <div className={`p-3 ${c.bg} rounded-lg relative`}>
          <Icon className={`h-6 w-6 ${c.text}`} />
          {pulse && (
            <span className="absolute -top-1 -right-1 h-2 w-2 bg-red-600 rounded-full animate-pulse" />
          )}
        </div>
      </div>
      <p className="text-xs text-zinc-500 mt-2">{sub}</p>
    </div>
  );
};

export default Dashboard;
