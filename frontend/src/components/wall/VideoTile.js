import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera as CamIcon, Circle, Maximize2, Settings, Image, Video, X } from "lucide-react";
import {
  ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger,
} from "../ui/context-menu";
import { WebRTCPlayer } from "../nvr/WebRTCPlayer";
import { getStreamUrls, captureSnapshot, startRecording, stopRecording } from "../../api/cameras";
import { toast } from "sonner";

export default function VideoTile({ camera, onAssign, onClear, onMaximize }) {
  const navigate = useNavigate();
  const [streamId, setStreamId] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    let alive = true;
    setStreamId(null);
    if (camera?.id && camera.status === "online") {
      getStreamUrls(camera.id)
        .then((u) => alive && setStreamId(u.live_stream_id || camera.id))
        .catch(() => {});
    }
    return () => { alive = false; };
  }, [camera?.id, camera?.status]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const id = e.dataTransfer.getData("text/nvr-camera-id");
    if (id) onAssign?.(id);
  };

  if (!camera) {
    return (
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className="relative flex items-center justify-center border border-dashed rounded-sm h-full"
        style={{
          borderColor: dragOver ? "var(--console-accent)" : "var(--console-border)",
          background: dragOver ? "rgba(20,184,166,0.06)" : "transparent",
        }}
      >
        <span className="text-[11px] text-zinc-600">drop camera here</span>
      </div>
    );
  }

  const doSnapshot = async () => {
    try { await captureSnapshot(camera.id); toast.success("Snapshot captured"); }
    catch { toast.error("Snapshot failed"); }
  };
  const doRecord = async () => {
    try {
      if (camera.is_recording) { await stopRecording(camera.id); toast.success("Recording stopped"); }
      else { await startRecording(camera.id); toast.success("Recording started"); }
    } catch { toast.error("Recording toggle failed"); }
  };

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          onDoubleClick={() => onMaximize?.(camera)}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className="group relative bg-black rounded-sm overflow-hidden h-full border"
          style={{ borderColor: dragOver ? "var(--console-accent)" : "var(--console-border)" }}
        >
          {streamId ? (
            <WebRTCPlayer streamId={streamId} cameraId={camera.id} muted className="w-full h-full object-contain" />
          ) : (
            <div className="w-full h-full flex flex-col items-center justify-center text-zinc-600 gap-1">
              <CamIcon className="h-6 w-6" />
              <span className="text-[10px]">{camera.status === "online" ? "connecting…" : "offline"}</span>
            </div>
          )}

          <div className="absolute top-0 inset-x-0 flex items-center gap-1.5 px-2 py-1 bg-gradient-to-b from-black/70 to-transparent">
            <span className="h-2 w-2 rounded-full" style={{ background: camera.status === "online" ? "var(--console-online)" : "var(--console-offline)" }} />
            <span className="text-[11px] text-white truncate">{camera.name}</span>
            {camera.is_recording && <Circle className="h-2.5 w-2.5 ml-auto" style={{ color: "var(--console-rec)", fill: "var(--console-rec)" }} />}
          </div>

          <div className="absolute top-1 right-1 hidden group-hover:flex gap-1">
            <button onClick={doSnapshot} className="p-1 rounded bg-black/60 text-white hover:bg-black/80"><Image className="h-3.5 w-3.5" /></button>
            <button onClick={() => onMaximize?.(camera)} className="p-1 rounded bg-black/60 text-white hover:bg-black/80"><Maximize2 className="h-3.5 w-3.5" /></button>
            <button onClick={() => onClear?.()} className="p-1 rounded bg-black/60 text-white hover:bg-black/80"><X className="h-3.5 w-3.5" /></button>
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent className="console-panel border-border text-zinc-200">
        <ContextMenuItem onClick={doSnapshot}><Image className="h-4 w-4 mr-2" /> Snapshot</ContextMenuItem>
        <ContextMenuItem onClick={doRecord}><Video className="h-4 w-4 mr-2" /> {camera.is_recording ? "Stop recording" : "Start recording"}</ContextMenuItem>
        <ContextMenuItem onClick={() => navigate(`/playback?camera=${camera.id}`)}>Open playback</ContextMenuItem>
        <ContextMenuItem onClick={() => navigate(`/cameras/${camera.id}/settings`)}><Settings className="h-4 w-4 mr-2" /> Camera settings</ContextMenuItem>
        <ContextMenuItem onClick={() => onClear?.()}><X className="h-4 w-4 mr-2" /> Clear tile</ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
