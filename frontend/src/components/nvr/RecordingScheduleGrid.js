// =============================================================================
// RecordingScheduleGrid — Weekly 24h × 7-day visual recording schedule
// =============================================================================

import React, { useState, useRef, useCallback } from "react";
import { Clock, Save, Eraser } from "lucide-react";
import { Button } from "../ui/button";
import { Label } from "../ui/label";
import { toast } from "sonner";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const HOURS = Array.from({ length: 24 }, (_, i) => i);

const MODES = {
  continuous: { label: "Continuous", color: "bg-blue-500" },
  motion: { label: "Motion Only", color: "bg-green-500" },
  off: { label: "Off", color: "bg-gray-300 dark:bg-gray-600" },
};

/**
 * Props:
 *  - schedule: { [day]: Array<"continuous"|"motion"|"off"> }  (24 entries per day)
 *  - onChange(schedule): called when schedule changes
 *  - onSave(schedule): called on save click
 *  - saving: boolean
 */
export const RecordingScheduleGrid = ({
  schedule: externalSchedule,
  onChange,
  onSave,
  saving = false,
}) => {
  const defaultSchedule = () =>
    Object.fromEntries(DAYS.map((d) => [d, Array(24).fill("continuous")]));

  const [schedule, setSchedule] = useState(
    externalSchedule || defaultSchedule(),
  );
  const [paintMode, setPaintMode] = useState("continuous");
  const [painting, setPainting] = useState(false);
  const gridRef = useRef(null);

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
    </div>
  );
};
