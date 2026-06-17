// =============================================================================
// PtzTourPanel — Configure and control a per-camera PTZ preset patrol tour
// =============================================================================

import React, { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";
import { GripVertical, Plus, Trash2, Play, Square } from "lucide-react";
import { toast } from "sonner";
import apiClient from "../../api/client";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Switch } from "../ui/switch";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

// ── API helpers ──────────────────────────────────────────────────────────────

const getPtzTour = (cameraId) =>
  apiClient.get(`/cameras/${cameraId}/ptz/tour`).then((r) => r.data);

const putPtzTour = (cameraId, config) =>
  apiClient.put(`/cameras/${cameraId}/ptz/tour`, config).then((r) => r.data);

const startTour = (cameraId) =>
  apiClient.post(`/cameras/${cameraId}/ptz/tour/start`).then((r) => r.data);

const stopTour = (cameraId) =>
  apiClient.post(`/cameras/${cameraId}/ptz/tour/stop`).then((r) => r.data);

const getPresets = (cameraId) =>
  apiClient.get(`/cameras/${cameraId}/ptz/presets`).then((r) => r.data);

// ── Component ────────────────────────────────────────────────────────────────

const PtzTourPanel = ({ cameraId, ptzCapable }) => {
  const qc = useQueryClient();

  const { data: tourData, isLoading } = useQuery({
    queryKey: ["ptz-tour", cameraId],
    queryFn: () => getPtzTour(cameraId),
    enabled: !!cameraId && !!ptzCapable,
    refetchInterval: 8000,
  });

  const { data: presetsData } = useQuery({
    queryKey: ["ptz-presets", cameraId],
    queryFn: () => getPresets(cameraId),
    enabled: !!cameraId && !!ptzCapable,
  });

  const [tourPresets, setTourPresets] = useState([]);
  const [loop, setLoop] = useState(true);

  useEffect(() => {
    if (tourData?.ptz_tour_config?.presets) {
      setTourPresets(tourData.ptz_tour_config.presets);
    }
    if (tourData?.ptz_tour_config?.loop !== undefined) {
      setLoop(tourData.ptz_tour_config.loop);
    }
  }, [tourData]);

  const saveMutation = useMutation({
    mutationFn: () => putPtzTour(cameraId, { presets: tourPresets, loop }),
    onSuccess: () => {
      toast.success("Tour configuration saved");
      qc.invalidateQueries({ queryKey: ["ptz-tour", cameraId] });
    },
    onError: () => toast.error("Failed to save tour config"),
  });

  const startMutation = useMutation({
    mutationFn: () => startTour(cameraId),
    onSuccess: () => {
      toast.success("PTZ tour started");
      qc.invalidateQueries({ queryKey: ["ptz-tour", cameraId] });
    },
    onError: (err) =>
      toast.error(err?.response?.data?.detail || "Failed to start tour"),
  });

  const stopMutation = useMutation({
    mutationFn: () => stopTour(cameraId),
    onSuccess: () => {
      toast.success("PTZ tour stopped");
      qc.invalidateQueries({ queryKey: ["ptz-tour", cameraId] });
    },
    onError: () => toast.error("Failed to stop tour"),
  });

  const handleDragEnd = (result) => {
    if (!result.destination) return;
    const items = Array.from(tourPresets);
    const [moved] = items.splice(result.source.index, 1);
    items.splice(result.destination.index, 0, moved);
    setTourPresets(items);
  };

  const addPreset = (token, name) => {
    if (tourPresets.find((p) => p.token === token)) return;
    setTourPresets([...tourPresets, { token, name, dwell_seconds: 10 }]);
  };

  const removePreset = (token) =>
    setTourPresets(tourPresets.filter((p) => p.token !== token));

  const updateDwell = (token, val) =>
    setTourPresets(
      tourPresets.map((p) =>
        p.token === token
          ? { ...p, dwell_seconds: Math.max(1, parseInt(val) || 1) }
          : p
      )
    );

  const isRunning = tourData?.running && tourData?.ptz_tour_enabled;

  if (!ptzCapable) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">PTZ Tour</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Camera does not support PTZ.
          </p>
        </CardContent>
      </Card>
    );
  }

  const availablePresets = (presetsData || []).filter(
    (p) => !tourPresets.find((tp) => tp.token === p.token)
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm">PTZ Tour / Patrol</CardTitle>
        <div className="flex gap-2">
          {isRunning ? (
            <Button
              size="sm"
              variant="destructive"
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
            >
              <Square className="h-3 w-3 mr-1" /> Stop
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending || tourPresets.length === 0}
            >
              <Play className="h-3 w-3 mr-1" /> Start
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {isRunning && (
          <p className="text-xs text-[var(--console-accent)] font-medium">Tour is running</p>
        )}

        {/* Ordered preset list */}
        <DragDropContext onDragEnd={handleDragEnd}>
          <Droppable droppableId="tour-presets">
            {(provided) => (
              <div
                {...provided.droppableProps}
                ref={provided.innerRef}
                className="space-y-1"
              >
                {tourPresets.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    No presets added. Add from the list below.
                  </p>
                )}
                {tourPresets.map((p, index) => (
                  <Draggable key={p.token} draggableId={p.token} index={index}>
                    {(prov) => (
                      <div
                        ref={prov.innerRef}
                        {...prov.draggableProps}
                        className="flex items-center gap-2 rounded border border-border bg-card/60 px-2 py-1.5"
                      >
                        <span {...prov.dragHandleProps}>
                          <GripVertical className="h-4 w-4 text-muted-foreground cursor-grab" />
                        </span>
                        <span className="text-sm flex-1 truncate">
                          {p.name || p.token}
                        </span>
                        <Label className="text-xs text-muted-foreground">
                          Dwell (s)
                        </Label>
                        <Input
                          type="number"
                          min={1}
                          value={p.dwell_seconds}
                          onChange={(e) => updateDwell(p.token, e.target.value)}
                          className="w-16 h-7 text-xs"
                        />
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7"
                          onClick={() => removePreset(p.token)}
                        >
                          <Trash2 className="h-3 w-3 text-destructive" />
                        </Button>
                      </div>
                    )}
                  </Draggable>
                ))}
                {provided.placeholder}
              </div>
            )}
          </Droppable>
        </DragDropContext>

        {/* Add presets */}
        {availablePresets.length > 0 && (
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">
              Add preset to tour
            </Label>
            <div className="flex flex-wrap gap-1">
              {availablePresets.map((p) => (
                <Button
                  key={p.token}
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  onClick={() => addPreset(p.token, p.name)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  {p.name || p.token}
                </Button>
              ))}
            </div>
          </div>
        )}

        {/* Loop toggle */}
        <div className="flex items-center gap-2">
          <Switch
            id="tour-loop"
            checked={loop}
            onCheckedChange={setLoop}
          />
          <Label htmlFor="tour-loop" className="text-sm cursor-pointer">
            Loop continuously
          </Label>
        </div>

        <Button
          className="w-full"
          size="sm"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
        >
          Save Tour Config
        </Button>
      </CardContent>
    </Card>
  );
};

export default PtzTourPanel;
