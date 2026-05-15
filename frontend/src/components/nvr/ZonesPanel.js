// =============================================================================
// ZonesPanel — list/create/delete counting zones for a camera
// =============================================================================
// Embeds in CameraScenarioConfig for People Counting. New zone dialog
// uses ROICanvas; choose line (in/out) or polygon (crowd) with threshold.
// =============================================================================

import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Trash2,
  Pencil,
  ArrowRightLeft,
  Users,
  Activity,
} from "lucide-react";
import { toast } from "sonner";
import {
  listZones,
  createZone,
  updateZone,
  deleteZone,
} from "../../api/people";
import ROICanvas from "./ROICanvas";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "../ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";

const SCENARIO_META = {
  in_out: {
    icon: ArrowRightLeft,
    label: "In/Out Line",
    pill: "bg-blue-500/15 text-blue-300 border-blue-500/30",
  },
  crowd: {
    icon: Users,
    label: "Crowd Polygon",
    pill: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  },
};

const SEVERITY_META = {
  info: {
    label: "Info",
    pill: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    color: "#38bdf8",
  },
  warning: {
    label: "Warning",
    pill: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    color: "#fbbf24",
  },
  critical: {
    label: "Critical",
    pill: "bg-rose-500/15 text-rose-300 border-rose-500/30",
    color: "#f43f5e",
  },
};

const ZonesPanel = ({ cameraId }) => {
  const qc = useQueryClient();
  const [showDialog, setShowDialog] = useState(false);
  const [editing, setEditing] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const { data: zones = [], isLoading } = useQuery({
    queryKey: ["zones", cameraId],
    queryFn: () => listZones(cameraId),
    enabled: !!cameraId,
  });

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["zones", cameraId] });

  const createMut = useMutation({
    mutationFn: (body) => createZone(cameraId, body),
    onSuccess: () => {
      invalidate();
      toast.success("Zone created");
      setShowDialog(false);
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Create failed"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }) => updateZone(id, body),
    onSuccess: () => {
      invalidate();
      toast.success("Zone updated");
      setShowDialog(false);
      setEditing(null);
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Update failed"),
  });

  const deleteMut = useMutation({
    mutationFn: (id) => deleteZone(id),
    onSuccess: () => {
      invalidate();
      toast.success("Zone removed");
      setDeleteTarget(null);
    },
  });

  const openCreate = () => {
    setEditing(null);
    setShowDialog(true);
  };
  const openEdit = (zone) => {
    setEditing(zone);
    setShowDialog(true);
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">Counting zones</p>
          <p className="text-[11px] text-muted-foreground">
            Add an In/Out line or a Crowd polygon. Coordinates are stored
            normalized — resolution-independent.
          </p>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-3.5 w-3.5 mr-1" />
          Add zone
        </Button>
      </div>

      {isLoading ? (
        <p className="text-xs text-muted-foreground py-4">Loading…</p>
      ) : zones.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 bg-card/30 p-6 text-center">
          <p className="text-xs text-muted-foreground">No zones yet</p>
        </div>
      ) : (
        <div className="space-y-1.5">
          {zones.map((z) => {
            const meta = SCENARIO_META[z.scenario] || SCENARIO_META.in_out;
            const Icon = meta.icon;
            return (
              <div
                key={z.id}
                className={cn(
                  "flex items-center gap-3 rounded-md border border-white/10 bg-card/40 px-3 py-2",
                  !z.enabled && "opacity-60",
                )}
              >
                <Icon className="h-4 w-4 text-muted-foreground shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">
                      {z.name}
                    </span>
                    <Badge className={cn("text-[10px]", meta.pill)}>
                      {meta.label}
                    </Badge>
                    {(() => {
                      const sev = SEVERITY_META[z.severity || "info"];
                      return (
                        <Badge className={cn("text-[10px]", sev.pill)}>
                          {sev.label}
                        </Badge>
                      );
                    })()}
                  </div>
                  <div className="text-[11px] text-muted-foreground font-mono mt-0.5">
                    {z.geometry?.points?.length || 0} points
                    {z.scenario === "in_out" && (
                      <>
                        {" · "}
                        {z.direction_a_label} → {z.direction_b_label}
                      </>
                    )}
                    {z.scenario === "crowd" && z.threshold && (
                      <> · threshold {z.threshold}</>
                    )}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  onClick={() => openEdit(z)}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-rose-300 hover:text-rose-200 hover:bg-rose-500/10"
                  onClick={() => setDeleteTarget(z)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            );
          })}
        </div>
      )}

      <ZoneFormDialog
        open={showDialog}
        onOpenChange={(v) => {
          setShowDialog(v);
          if (!v) setEditing(null);
        }}
        cameraId={cameraId}
        zone={editing}
        onSubmit={(payload) => {
          if (editing) {
            updateMut.mutate({ id: editing.id, body: payload });
          } else {
            createMut.mutate(payload);
          }
        }}
        pending={createMut.isPending || updateMut.isPending}
      />

      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(v) => !v && setDeleteTarget(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete zone</AlertDialogTitle>
            <AlertDialogDescription>
              Remove "{deleteTarget?.name}"? Future counts won't be recorded
              against this zone. Historical counts remain in the DB.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteMut.mutate(deleteTarget?.id)}
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

const ZoneFormDialog = ({ open, onOpenChange, cameraId, zone, onSubmit, pending }) => {
  const isEdit = !!zone;
  const [form, setForm] = useState(() => ({
    name: zone?.name || "",
    scenario: zone?.scenario || "in_out",
    geometry: zone?.geometry || null,
    threshold: zone?.threshold || 5,
    direction_a_label: zone?.direction_a_label || "in",
    direction_b_label: zone?.direction_b_label || "out",
    severity: zone?.severity || "info",
    enabled: zone?.enabled !== false,
  }));

  React.useEffect(() => {
    if (zone) {
      setForm({
        name: zone.name,
        scenario: zone.scenario,
        geometry: zone.geometry,
        threshold: zone.threshold || 5,
        direction_a_label: zone.direction_a_label,
        direction_b_label: zone.direction_b_label,
        severity: zone.severity || "info",
        enabled: zone.enabled !== false,
      });
    } else {
      setForm({
        name: "",
        scenario: "in_out",
        geometry: null,
        threshold: 5,
        direction_a_label: "in",
        direction_b_label: "out",
        severity: "info",
        enabled: true,
      });
    }
  }, [zone, open]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!form.name?.trim()) return toast.error("Name is required");
    if (!form.geometry?.points?.length) return toast.error("Draw geometry first");
    const required = form.scenario === "line" ? 2 : 3;
    const minPoints = form.scenario === "in_out" ? 2 : 3;
    if (form.geometry.points.length < minPoints) {
      return toast.error(`Geometry needs at least ${minPoints} points`);
    }
    const payload = {
      scenario: form.scenario,
      name: form.name.trim(),
      geometry: {
        kind: form.scenario === "in_out" ? "line" : "polygon",
        points: form.geometry.points,
      },
      threshold: form.scenario === "crowd" ? form.threshold : null,
      direction_a_label: form.direction_a_label,
      direction_b_label: form.direction_b_label,
      severity: form.severity,
      enabled: form.enabled,
    };
    onSubmit(payload);
  };

  const mode = form.scenario === "in_out" ? "line" : "polygon";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit zone" : "Add zone"}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Name</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Entrance line"
                required
              />
            </div>
            <div>
              <Label>Type</Label>
              <Select
                value={form.scenario}
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, scenario: v, geometry: null }))
                }
                disabled={isEdit}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="in_out">In/Out Line</SelectItem>
                  <SelectItem value="crowd">Crowd Polygon</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {form.scenario === "in_out" && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Direction A label</Label>
                <Input
                  value={form.direction_a_label}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, direction_a_label: e.target.value }))
                  }
                />
              </div>
              <div>
                <Label>Direction B label</Label>
                <Input
                  value={form.direction_b_label}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, direction_b_label: e.target.value }))
                  }
                />
              </div>
            </div>
          )}

          {form.scenario === "crowd" && (
            <div>
              <Label>Crowd threshold</Label>
              <Input
                type="number"
                min={1}
                max={10000}
                value={form.threshold}
                onChange={(e) =>
                  setForm((f) => ({ ...f, threshold: Number(e.target.value) }))
                }
              />
              <p className="text-[11px] text-muted-foreground mt-1">
                Crowd alert event fires when people inside polygon ≥ this.
              </p>
            </div>
          )}

          <div>
            <Label>Severity tier</Label>
            <Select
              value={form.severity}
              onValueChange={(v) => setForm((f) => ({ ...f, severity: v }))}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="info">Info (blue)</SelectItem>
                <SelectItem value="warning">Warning (amber)</SelectItem>
                <SelectItem value="critical">Critical (rose)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[11px] text-muted-foreground mt-1">
              Drives overlay color on live tiles + event severity escalation
              when this zone triggers.
            </p>
          </div>

          <ROICanvas
            cameraId={cameraId}
            mode={mode}
            value={form.geometry}
            onChange={(g) => setForm((f) => ({ ...f, geometry: g }))}
            labels={{
              a: form.direction_a_label,
              b: form.direction_b_label,
            }}
            strokeColor={SEVERITY_META[form.severity]?.color}
          />

          <DialogFooter>
            <Button type="submit" disabled={pending}>
              {pending ? "Saving…" : isEdit ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export default ZonesPanel;
