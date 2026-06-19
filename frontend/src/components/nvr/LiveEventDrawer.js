// =============================================================================
// LiveEventDrawer — persistent right-side panel for real-time events
// =============================================================================
// Subscribes to the `events` WebSocket channel. Drawer is a fixed panel
// docked to the right edge — no backdrop overlay, no blur, background
// stays interactive (operators can still click cameras / nav while it's
// open). Auto-opens on alarm/critical when enabled. Suppressed on
// /events route (page already shows live feed).
//
// Two exported components share state via context:
//   <LiveEventProvider>      mount once near the root
//     <LiveEventBell />      bell trigger — put in sidebar header
//     <LiveEventDrawer />    the actual right-side panel
//   </LiveEventProvider>
// =============================================================================

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Bell,
  BellRing,
  AlertTriangle,
  Shield,
  Activity,
  Video,
  VideoOff,
  XCircle,
  Check,
  Trash2,
  ArrowUpRight,
  VolumeX,
  Volume2,
  X,
} from "lucide-react";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { cn } from "../../lib/utils";
import { useWebSocket } from "../../hooks/useWebSocket";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getAllCameras } from "../../api/cameras";
import { acknowledgeEvent } from "../../api/events";
import { format } from "date-fns";
import { toast } from "sonner";

const MAX_BUFFER = 50;
// Routes where the floating drawer is suppressed — Events page has its
// own live feed, Dashboard hosts an inline events panel.
const SUPPRESS_ROUTES = ["/events", "/"];
const SOUND_KEY = "nvr.events.drawer.sound";
const AUTO_OPEN_KEY = "nvr.events.drawer.autoopen";

const SEVERITY_STYLE = {
  info: {
    bar: "bg-blue-500",
    badge: "bg-blue-500/15 text-blue-300 border border-blue-500/30",
    label: "Info",
  },
  warning: {
    bar: "bg-amber-500",
    badge: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
    label: "Warning",
  },
  critical: {
    bar: "bg-rose-500",
    badge: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
    label: "Critical",
  },
  alarm: {
    bar: "bg-rose-600 animate-pulse",
    badge: "bg-rose-500/25 text-rose-200 border border-rose-500/50",
    label: "Alarm",
  },
};

const ICON_FOR_TYPE = (type) => {
  if (!type) return Bell;
  if (type.startsWith("motion")) return Activity;
  if (type.includes("tamper")) return Shield;
  if (type === "video_loss" || type === "camera_offline") return VideoOff;
  if (type === "camera_online") return Video;
  if (type.includes("error") || type.includes("disk")) return XCircle;
  return AlertTriangle;
};

// Short WebAudio chirp on alarm/critical. No asset dependency.
const playChirp = (severity) => {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const beep = (offsetSec, freq) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, ctx.currentTime + offsetSec);
      gain.gain.setValueAtTime(0.0001, ctx.currentTime + offsetSec);
      gain.gain.exponentialRampToValueAtTime(
        0.18,
        ctx.currentTime + offsetSec + 0.02,
      );
      gain.gain.exponentialRampToValueAtTime(
        0.0001,
        ctx.currentTime + offsetSec + 0.22,
      );
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + offsetSec);
      osc.stop(ctx.currentTime + offsetSec + 0.25);
    };
    if (severity === "alarm" || severity === "critical") {
      beep(0, 880);
      beep(0.18, 660);
    } else {
      beep(0, 660);
    }
    setTimeout(() => ctx.close(), 700);
  } catch {
    // No audio context — silent
  }
};

// ----------------------------------------------------------------------------
// Context
// ----------------------------------------------------------------------------

const LiveEventCtx = createContext(null);

const useLiveEvent = () => {
  const ctx = useContext(LiveEventCtx);
  if (!ctx) {
    throw new Error("useLiveEvent must be used inside <LiveEventProvider>");
  }
  return ctx;
};

// Safe read-only accessor for consumers that only need the event buffer
// (e.g. AlarmDock). Falls back to an empty list outside the provider so it
// never throws.
export const useLiveEvents = () => {
  const ctx = useContext(LiveEventCtx);
  return ctx || { events: [], isConnected: false, connectionState: "disconnected" };
};

export const LiveEventProvider = ({ children }) => {
  const location = useLocation();
  const qc = useQueryClient();
  const suppressed = SUPPRESS_ROUTES.some((r) =>
    r === "/" ? location.pathname === "/" : location.pathname.startsWith(r),
  );
  // Keep prop name for backward compatibility with existing consumers
  const onEventsPage = suppressed;

  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState([]);
  const [unseen, setUnseen] = useState(0);
  const [soundOn, setSoundOn] = useState(() => {
    try {
      return localStorage.getItem(SOUND_KEY) !== "off";
    } catch {
      return true;
    }
  });
  const [autoOpen, setAutoOpen] = useState(() => {
    try {
      return localStorage.getItem(AUTO_OPEN_KEY) !== "off";
    } catch {
      return true;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(SOUND_KEY, soundOn ? "on" : "off");
    } catch {}
  }, [soundOn]);
  useEffect(() => {
    try {
      localStorage.setItem(AUTO_OPEN_KEY, autoOpen ? "on" : "off");
    } catch {}
  }, [autoOpen]);

  useEffect(() => {
    if (open) setUnseen(0);
  }, [open]);

  // Auto-close drawer when navigating to Events page
  useEffect(() => {
    if (onEventsPage) setOpen(false);
  }, [onEventsPage]);

  const stateRef = useRef({ onEventsPage, autoOpen, soundOn, open });
  stateRef.current = { onEventsPage, autoOpen, soundOn, open };

  const handleNewEvent = useCallback(
    (payload) => {
      if (!payload) return;
      const { onEventsPage, autoOpen, soundOn, open } = stateRef.current;

      setEvents((prev) => {
        if (prev.some((e) => e.id === payload.id)) return prev;
        const next = [payload, ...prev];
        return next.length > MAX_BUFFER ? next.slice(0, MAX_BUFFER) : next;
      });

      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["events-unack-count"] });
      qc.invalidateQueries({ queryKey: ["event-stats"] });

      if (onEventsPage) return;

      if (!open) setUnseen((c) => c + 1);

      const sev = payload.severity;
      const escalating = sev === "alarm" || sev === "critical";
      if (autoOpen && escalating) setOpen(true);
      if (soundOn) playChirp(sev);
    },
    [qc],
  );

  const { isConnected, connectionState } = useWebSocket({
    channels: ["events", "system"],
    onNewEvent: handleNewEvent,
  });

  const value = useMemo(
    () => ({
      open,
      setOpen,
      events,
      setEvents,
      unseen,
      soundOn,
      setSoundOn,
      autoOpen,
      setAutoOpen,
      onEventsPage,
      isConnected,
      connectionState,
    }),
    [open, events, unseen, soundOn, autoOpen, onEventsPage, isConnected, connectionState],
  );

  return <LiveEventCtx.Provider value={value}>{children}</LiveEventCtx.Provider>;
};

// ----------------------------------------------------------------------------
// Bell trigger — mount inside the sidebar header
// ----------------------------------------------------------------------------

export const LiveEventBell = ({ compact = false }) => {
  const location = useLocation();
  const { open, setOpen, unseen, onEventsPage } = useLiveEvent();
  if (onEventsPage) return null;
  // Bell only on Dashboard route
  if (location.pathname !== "/") return null;

  return (
    <button
      type="button"
      aria-label="Open live events"
      onClick={() => setOpen((v) => !v)}
      className={cn(
        "relative inline-flex items-center justify-center rounded-lg",
        "border border-white/10 bg-card/60 hover:bg-card transition-colors",
        compact ? "h-9 w-9" : "h-10 w-10",
        unseen > 0 && "ring-2 ring-rose-500/40",
        open && "bg-card",
      )}
    >
      {unseen > 0 ? (
        <BellRing className="h-[18px] w-[18px] text-rose-300" />
      ) : (
        <Bell className="h-[18px] w-[18px] text-muted-foreground" />
      )}
      {unseen > 0 && (
        <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-white text-[10px] font-semibold flex items-center justify-center">
          {unseen > 99 ? "99+" : unseen}
        </span>
      )}
    </button>
  );
};

// ----------------------------------------------------------------------------
// Drawer — persistent right-side panel, no overlay
// ----------------------------------------------------------------------------

export const LiveEventDrawer = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const {
    open,
    setOpen,
    events,
    setEvents,
    soundOn,
    setSoundOn,
    autoOpen,
    setAutoOpen,
    onEventsPage,
  } = useLiveEvent();

  const { data: cameras } = useQuery({
    queryKey: ["cameras"],
    queryFn: getAllCameras,
    staleTime: 60_000,
  });

  const cameraNameById = useMemo(() => {
    const m = new Map();
    (cameras || []).forEach((c) => m.set(c.id, c.name));
    return m;
  }, [cameras]);

  // Esc closes
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  const handleAck = async (id) => {
    try {
      await acknowledgeEvent(id, null);
      setEvents((prev) =>
        prev.map((e) => (e.id === id ? { ...e, _acked: true } : e)),
      );
      qc.invalidateQueries({ queryKey: ["events"] });
      qc.invalidateQueries({ queryKey: ["events-unack-count"] });
    } catch {
      toast.error("Acknowledge failed");
    }
  };

  const handleDismiss = (id) => {
    setEvents((prev) => prev.filter((e) => e.id !== id));
  };

  const handleClearAll = () => {
    setEvents([]);
  };

  // Render even when closed so the slide animation works on mount
  return (
    <aside
      aria-hidden={!open}
      className={cn(
        // Stuck to right edge, full-height, above main content
        "fixed top-0 right-0 z-30 h-screen",
        "w-full sm:w-[380px] md:w-[400px]",
        "border-l border-white/10 bg-card/95 backdrop-blur-xl shadow-2xl",
        "flex flex-col",
        "transition-transform duration-300 ease-out",
        open ? "translate-x-0" : "translate-x-full",
        onEventsPage && "hidden",
      )}
    >
      <header className="px-5 py-4 border-b border-white/10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-base font-semibold">
            <BellRing className="h-4 w-4 text-teal-300" />
            Live Events
            <Badge variant="outline" className="ml-1 text-[10px]">
              {events.length}
            </Badge>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              title={soundOn ? "Mute alerts" : "Enable alert sound"}
              onClick={() => setSoundOn((v) => !v)}
              className="h-7 w-7 inline-flex items-center justify-center rounded-md hover:bg-white/5"
            >
              {soundOn ? (
                <Volume2 className="h-4 w-4 text-muted-foreground" />
              ) : (
                <VolumeX className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
            <button
              type="button"
              title="Close"
              onClick={() => setOpen(false)}
              className="h-7 w-7 inline-flex items-center justify-center rounded-md hover:bg-white/5"
            >
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
          <label className="inline-flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              className="accent-teal-400"
              checked={autoOpen}
              onChange={(e) => setAutoOpen(e.target.checked)}
            />
            Auto-open on alarm
          </label>
          {events.length > 0 && (
            <button
              type="button"
              onClick={handleClearAll}
              className="text-xs text-muted-foreground hover:text-rose-300"
            >
              Clear all
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
        {events.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center text-muted-foreground py-16">
            <Bell className="h-8 w-8 mb-3 opacity-40" />
            <p className="text-sm">No live events yet</p>
            <p className="text-xs mt-1 opacity-70">
              New alarms appear here in real time
            </p>
          </div>
        ) : (
          events.map((evt) => {
            const sev = SEVERITY_STYLE[evt.severity] || SEVERITY_STYLE.info;
            const Icon = ICON_FOR_TYPE(evt.event_type);
            const camName =
              cameraNameById.get(evt.camera_id) ||
              (evt.camera_id ? evt.camera_id.slice(0, 8) : "System");
            return (
              <div
                key={evt.id}
                className={cn(
                  "relative rounded-lg border border-white/10 bg-card/60 overflow-hidden",
                  evt._acked && "opacity-60",
                )}
              >
                <div className={cn("absolute left-0 top-0 bottom-0 w-1", sev.bar)} />
                <div className="pl-3 pr-3 py-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="text-sm font-medium truncate">
                        {evt.title || evt.event_type}
                      </span>
                    </div>
                    <Badge className={cn("shrink-0 text-[10px]", sev.badge)}>
                      {sev.label}
                    </Badge>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="truncate">{camName}</span>
                    <span>·</span>
                    <span>
                      {evt.triggered_at
                        ? format(new Date(evt.triggered_at), "HH:mm:ss")
                        : "now"}
                    </span>
                  </div>
                  {evt.description && (
                    <p className="mt-2 text-xs text-muted-foreground line-clamp-2">
                      {evt.description}
                    </p>
                  )}
                  <div className="mt-3 flex items-center gap-1.5">
                    {!evt._acked && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-xs"
                        onClick={() => handleAck(evt.id)}
                      >
                        <Check className="h-3.5 w-3.5 mr-1" />
                        Ack
                      </Button>
                    )}
                    {evt.camera_id && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 px-2 text-xs"
                        onClick={() => {
                          setOpen(false);
                          navigate(`/playback?camera=${evt.camera_id}`);
                        }}
                      >
                        <ArrowUpRight className="h-3.5 w-3.5 mr-1" />
                        Playback
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2 text-xs ml-auto text-muted-foreground hover:text-rose-300"
                      onClick={() => handleDismiss(evt.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="border-t border-white/10 p-3">
        <Button
          variant="outline"
          size="sm"
          className="w-full"
          onClick={() => {
            setOpen(false);
            navigate("/events");
          }}
        >
          Open full Events & Alarms
          <ArrowUpRight className="h-4 w-4 ml-1" />
        </Button>
      </div>
    </aside>
  );
};

export default LiveEventDrawer;
