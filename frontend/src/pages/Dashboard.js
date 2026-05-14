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
    <div className="p-4 md:p-6 h-full flex flex-col min-h-0">
      {/* Header: title + stat-pills + actions on one row */}
      <div className="flex flex-wrap items-center gap-3 mb-4 flex-shrink-0">
        <div className="flex-shrink-0">
          <h1
            className="text-xl md:text-2xl font-bold text-white tracking-tight leading-none"
            style={{ fontFamily: "Manrope, sans-serif" }}
          >
            Dashboard
          </h1>
        </div>

        {/* Stat badges — compact, color-coded */}
        <div className="flex items-center gap-2 flex-wrap">
          <StatBadge
            icon={Video}
            label="Total"
            value={cameras.length}
            tone="slate"
          />
          <StatBadge
            icon={Wifi}
            label="Online"
            value={onlineCount}
            tone="emerald"
          />
          <StatBadge
            icon={Video}
            label="Recording"
            value={recordingCount}
            tone="red"
            pulse={recordingCount > 0}
          />
          <StatBadge
            icon={WifiOff}
            label="Offline"
            value={offlineCount}
            tone="zinc"
          />
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <Button
            variant="outline"
            onClick={() => refetch()}
            disabled={isLoading}
            size="sm"
          >
            <RefreshCw
              className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`}
            />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
          {canManage && (
            <Button
              onClick={openAdd}
              className="bg-primary hover:bg-primary/60"
              size="sm"
            >
              <Plus className="h-4 w-4 sm:mr-2" />
              <span className="hidden sm:inline">Add Camera</span>
            </Button>
          )}
        </div>
      </div>

      {/* Grid: fills remaining viewport, NO scroll — tiles auto-shrink
          to fit the N×M layout. Matches Hikvision/Dahua NVR behavior. */}
      <div className="flex-1 min-h-0">
        <CameraGrid
          cameras={cameras}
          isLoading={isLoading}
          loadingCameras={[]}
          maxCameras={128}
          onCameraClick={(cam) => navigate(`/playback?camera=${cam.id}`)}
          onStartRecording={(cam) =>
            canOperate && mutations.start.mutate(cam.id)
          }
          onStopRecording={(cam) =>
            canOperate && mutations.stop.mutate(cam.id)
          }
          onTestConnection={(cam) =>
            canOperate && mutations.test.mutate(cam.id)
          }
          onCameraSettings={canManage ? openEdit : undefined}
          onCameraFullscreen={(cam) => navigate(`/live/${cam.id}`)}
          onAddCamera={canManage ? openAdd : undefined}
        />
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
              className="bg-destructive hover:bg-destructive/90"
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
  slate: { bg: "bg-card/60", text: "text-zinc-400" },
  emerald: { bg: "bg-emerald-50", text: "text-emerald-600" },
  red: { bg: "bg-red-50", text: "text-red-600" },
};

const StatCard = ({ label, value, icon: Icon, color, sub, pulse }) => {
  const c = colorMap[color] || colorMap.slate;
  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className={`text-2xl font-bold ${c.text}`}>{value}</p>
        </div>
        <div className={`p-3 ${c.bg} rounded-lg relative`}>
          <Icon className={`h-6 w-6 ${c.text}`} />
          {pulse && (
            <span className="absolute -top-1 -right-1 h-2 w-2 bg-destructive rounded-full animate-pulse" />
          )}
        </div>
      </div>
      <p className="text-xs text-muted-foreground mt-2">{sub}</p>
    </div>
  );
};


// Compact stat badge — inline pill replaces the old 4-card stat grid so
// the camera grid gets the whole viewport.
const BADGE_TONES = {
  slate: "bg-card/60 text-zinc-300 border-border",
  emerald: "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
  red: "bg-rose-500/10 text-rose-300 border-rose-500/20",
  zinc: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
};

const StatBadge = ({ icon: Icon, label, value, tone = "slate", pulse }) => {
  const klass = BADGE_TONES[tone] || BADGE_TONES.slate;
  return (
    <div
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-xs font-medium ${klass}`}
    >
      <span className="relative inline-flex">
        <Icon className="h-3.5 w-3.5" />
        {pulse && (
          <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 bg-rose-500 rounded-full animate-pulse" />
        )}
      </span>
      <span className="text-muted-foreground">{label}</span>
      <span className="font-bold tabular-nums">{value}</span>
    </div>
  );
};

export default Dashboard;
