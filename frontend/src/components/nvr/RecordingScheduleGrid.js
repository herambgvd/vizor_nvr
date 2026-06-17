// =============================================================================
// RecordingScheduleGrid — Weekly 24h × 7-day visual recording schedule
// =============================================================================

import React, { useState, useRef, useCallback } from "react";
import { Clock, Save, Eraser, ChevronDown, BookTemplate, Plus } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "../ui/button";
import { Label } from "../ui/label";
import { Input } from "../ui/input";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../ui/dialog";
import {
  listScheduleTemplates,
  createScheduleTemplate,
} from "../../api/scheduleTemplates";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, i) => i);

const MODES = {
  continuous: { label: "Continuous", color: "bg-blue-500" },
  motion: { label: "Motion Only", color: "bg-[var(--console-accent)]" },
  off: { label: "Off", color: "bg-gray-300 dark:bg-gray-600" },
};

/**
 * Props:
 *  - schedule: { [day]: Array<"continuous"|"motion"|"off"> }  (24 entries per day)
 *  - onChange(schedule): called when schedule changes
 *  - onSave(schedule): called on save click
 *  - saving: boolean
 *  - canManage: boolean — show template save/apply controls
 */
export const RecordingScheduleGrid = ({
  schedule: externalSchedule,
  onChange,
  onSave,
  saving = false,
  canManage = false,
}) => {
  const defaultSchedule = () =>
    Object.fromEntries(DAYS.map((d) => [d, Array(24).fill("continuous")]));

  const [schedule, setSchedule] = useState(
    externalSchedule || defaultSchedule(),
  );
  const [paintMode, setPaintMode] = useState("continuous");
  const [painting, setPainting] = useState(false);
  const gridRef = useRef(null);

  // Templates
  const queryClient = useQueryClient();
  const { data: templates = [] } = useQuery({
    queryKey: ["schedule-templates"],
    queryFn: listScheduleTemplates,
    staleTime: 30_000,
  });
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [tplName, setTplName] = useState("");
  const [tplDesc, setTplDesc] = useState("");
  const saveTplMutation = useMutation({
    mutationFn: (data) => createScheduleTemplate(data),
    onSuccess: () => {
      toast.success("Template saved");
      queryClient.invalidateQueries({ queryKey: ["schedule-templates"] });
      setShowSaveDialog(false);
      setTplName("");
      setTplDesc("");
    },
    onError: (err) => toast.error(err?.response?.data?.detail || "Failed to save template"),
  });

  // Sync with external prop changes
  React.useEffect(() => {
    if (externalSchedule) setSchedule(externalSchedule);
  }, [externalSchedule]);

  const update = useCallback(
    (newSched) => {
      setSchedule(newSched);
      onChange?.(newSched);
    },
    [onChange],
  );

  const setCellMode = (day, hour) => {
    const newSched = {
      ...schedule,
      [day]: schedule[day].map((v, i) => (i === hour ? paintMode : v)),
    };
    update(newSched);
  };

  const handleMouseDown = (day, hour) => {
    setPainting(true);
    setCellMode(day, hour);
  };

  const handleMouseEnter = (day, hour) => {
    if (painting) setCellMode(day, hour);
  };

  const handleMouseUp = () => setPainting(false);

  const fillAll = (mode) => {
    update(Object.fromEntries(DAYS.map((d) => [d, Array(24).fill(mode)])));
  };

  return (
    <div
      className="space-y-4"
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <div className="flex items-center gap-2">
        <Clock className="h-5 w-5" />
        <h3 className="font-semibold">Recording Schedule</h3>
      </div>

      {/* Templates row */}
      {canManage && (
        <div className="flex items-center gap-2 flex-wrap">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="text-xs h-7">
                <BookTemplate className="h-3 w-3 mr-1" /> Templates
                <ChevronDown className="h-3 w-3 ml-1" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {templates.length === 0 && (
                <DropdownMenuItem disabled>No templates</DropdownMenuItem>
              )}
              {templates.map((t) => (
                <DropdownMenuItem
                  key={t.id}
                  onClick={() => {
                    update(t.grid);
                    toast.success(`Applied "${t.name}"`);
                  }}
                >
                  {t.name}
                  {t.description && (
                    <span className="ml-2 text-xs text-muted-foreground truncate max-w-[180px]">
                      {t.description}
                    </span>
                  )}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => setShowSaveDialog(true)}>
                <Plus className="h-3 w-3 mr-1" /> Save current as template…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

      {/* Legend & paint mode selector */}
      <div className="flex items-center gap-4 flex-wrap">
        <Label className="text-xs text-muted-foreground">Paint mode:</Label>
        {Object.entries(MODES).map(([key, { label, color }]) => (
          <button
            key={key}
            type="button"
            onClick={() => setPaintMode(key)}
            className={`flex items-center gap-1.5 px-2 py-1 rounded border text-xs ${
              paintMode === key
                ? "ring-2 ring-primary border-primary"
                : "border-border"
            }`}
          >
            <span className={`inline-block w-3 h-3 rounded-sm ${color}`} />
            {label}
          </button>
        ))}
        <div className="ml-auto flex gap-1">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fillAll("continuous")}
            className="text-xs h-7"
          >
            All Continuous
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => fillAll("motion")}
            className="text-xs h-7"
          >
            All Motion
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => fillAll("off")}
            className="text-xs h-7"
          >
            <Eraser className="h-3 w-3 mr-1" /> Clear
          </Button>
        </div>
      </div>

      {/* Grid */}
      <div className="overflow-x-auto" ref={gridRef}>
        <table
          className="border-collapse select-none"
          style={{ minWidth: 650 }}
        >
          <thead>
            <tr>
              <th className="w-10" />
              {HOURS.map((h) => (
                <th
                  key={h}
                  className="text-[10px] text-muted-foreground font-normal px-0 text-center"
                  style={{ width: 24 }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DAYS.map((day) => (
              <tr key={day}>
                <td className="text-xs font-medium pr-2 text-right">{day}</td>
                {HOURS.map((h) => {
                  const mode = schedule[day]?.[h] || "off";
                  return (
                    <td
                      key={h}
                      className={`border border-background cursor-pointer ${MODES[mode]?.color || MODES.off.color}`}
                      style={{ width: 24, height: 22 }}
                      onMouseDown={() => handleMouseDown(day, h)}
                      onMouseEnter={() => handleMouseEnter(day, h)}
                      title={`${day} ${h}:00 — ${MODES[mode]?.label || mode}`}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {onSave && (
        <Button size="sm" onClick={() => onSave(schedule)} disabled={saving}>
          <Save className="h-4 w-4 mr-1" /> Save Schedule
        </Button>
      )}

      {/* Save-as-template dialog */}
      <Dialog open={showSaveDialog} onOpenChange={setShowSaveDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save as Template</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <Label className="text-sm">Template name *</Label>
              <Input
                value={tplName}
                onChange={(e) => setTplName(e.target.value)}
                placeholder="e.g. Weekday Nights"
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-sm">Description (optional)</Label>
              <Input
                value={tplDesc}
                onChange={(e) => setTplDesc(e.target.value)}
                placeholder="Brief description…"
                className="mt-1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowSaveDialog(false)}>
              Cancel
            </Button>
            <Button
              disabled={!tplName.trim() || saveTplMutation.isPending}
              onClick={() =>
                saveTplMutation.mutate({
                  name: tplName.trim(),
                  description: tplDesc.trim() || undefined,
                  grid: schedule,
                })
              }
            >
              Save Template
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};
