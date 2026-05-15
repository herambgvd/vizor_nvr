// =============================================================================
// FRS · Investigate — /ai/modules/frs/investigate
// =============================================================================
// Upload a photo → embed → Qdrant cosine search → optionally filter by
// time range + camera list against events table. Results show snapshot
// + camera + click-through to Playback at the event timestamp.
// =============================================================================

import React, { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Upload,
  Search,
  ImageIcon,
  Clock,
  Camera as CameraIcon,
  PlayCircle,
} from "lucide-react";
import { format, subHours, startOfDay, endOfDay } from "date-fns";
import { toast } from "sonner";
import apiClient, { BACKEND_URL, getAccessToken } from "../../../../api/client";
import { getAllCameras } from "../../../../api/cameras";
import { Button } from "../../../../components/ui/button";
import { Input } from "../../../../components/ui/input";
import { Label } from "../../../../components/ui/label";
import { Badge } from "../../../../components/ui/badge";

const PRESETS = [
  { label: "Last 1h", fn: () => ({ since: subHours(new Date(), 1), until: new Date() }) },
  { label: "Last 6h", fn: () => ({ since: subHours(new Date(), 6), until: new Date() }) },
  { label: "Today", fn: () => ({ since: startOfDay(new Date()), until: new Date() }) },
  { label: "Yesterday", fn: () => {
      const d = subHours(startOfDay(new Date()), 24);
      return { since: d, until: endOfDay(d) };
    },
  },
  { label: "Last 7d", fn: () => ({ since: subHours(new Date(), 168), until: new Date() }) },
];

const fmtLocal = (d) => format(d, "yyyy-MM-dd'T'HH:mm");

const submitInvestigation = async ({ file, since, until, cameraIds }) => {
  const form = new FormData();
  form.append("file", file);
  if (since) form.append("since", new Date(since).toISOString());
  if (until) form.append("until", new Date(until).toISOString());
  if (cameraIds && cameraIds.length) form.append("camera_ids", cameraIds.join(","));
  const r = await apiClient.post("/ai/frs/investigate", form, {
    headers: { "Content-Type": "multipart/form-data" },
    timeout: 60_000,
  });
  return r.data;
};

const InvestigatePage = () => {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [selectedCams, setSelectedCams] = useState([]);
  const [results, setResults] = useState([]);

  const { data: cameras = [] } = useQuery({
    queryKey: ["all-cameras"],
    queryFn: getAllCameras,
  });

  const mut = useMutation({
    mutationFn: submitInvestigation,
    onSuccess: (r) => {
      setResults(r?.results || []);
      toast.success(
        `${r?.matches || 0} match${r?.matches === 1 ? "" : "es"}`,
      );
    },
    onError: (e) => {
      toast.error(
        e?.response?.data?.detail ||
          "Investigation failed (Triton/Qdrant may be offline)",
      );
    },
  });

  const onFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(f));
  };

  const applyPreset = (p) => {
    const { since: s, until: u } = p.fn();
    setSince(fmtLocal(s));
    setUntil(fmtLocal(u));
  };

  const toggleCam = (id) => {
    setSelectedCams((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id],
    );
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!file) return toast.error("Pick a photo first");
    mut.mutate({ file, since, until, cameraIds: selectedCams });
  };

  const openInPlayback = (hit) => {
    if (!hit.camera_id || !hit.ts) {
      toast.error("No camera/timestamp for this hit");
      return;
    }
    const t = new Date(hit.ts).getTime();
    navigate(`/playback?camera=${hit.camera_id}&t=${t}`);
  };

  const snapshotSrc = (snapshotPath) => {
    if (!snapshotPath) return null;
    const token = getAccessToken();
    const sep = snapshotPath.includes("?") ? "&" : "?";
    return `${BACKEND_URL}${snapshotPath}${sep}token=${token || ""}`;
  };

  const camMap = useMemo(() => {
    const m = {};
    cameras.forEach((c) => { m[c.id] = c.name; });
    return m;
  }, [cameras]);

  return (
    <div className="p-4 md:p-6 max-w-6xl space-y-5">
      <form onSubmit={handleSubmit} className="grid lg:grid-cols-[1fr_1.8fr] gap-4">
        <div className="space-y-3">
          <div>
            <Label>Query photo</Label>
            <div className="mt-2 rounded-lg border border-dashed border-white/15 bg-card/40 p-4 flex flex-col items-center gap-2">
              {previewUrl ? (
                <img
                  src={previewUrl}
                  alt="query"
                  className="w-full h-48 object-contain rounded"
                />
              ) : (
                <div className="h-48 w-full flex items-center justify-center text-muted-foreground">
                  <ImageIcon className="h-10 w-10 opacity-30" />
                </div>
              )}
              <Input
                type="file"
                accept="image/jpeg,image/png"
                onChange={onFile}
                className="text-xs"
              />
            </div>
          </div>

          <div>
            <Label>Time window</Label>
            <div className="grid grid-cols-2 gap-2 mt-1">
              <Input
                type="datetime-local"
                value={since}
                onChange={(e) => setSince(e.target.value)}
                aria-label="from"
              />
              <Input
                type="datetime-local"
                value={until}
                onChange={(e) => setUntil(e.target.value)}
                aria-label="to"
              />
            </div>
            <div className="flex flex-wrap gap-1 mt-2">
              {PRESETS.map((p) => (
                <Button
                  type="button"
                  key={p.label}
                  variant="outline"
                  size="sm"
                  onClick={() => applyPreset(p)}
                  className="h-7 px-2 text-[11px]"
                >
                  {p.label}
                </Button>
              ))}
              {(since || until) && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => { setSince(""); setUntil(""); }}
                  className="h-7 px-2 text-[11px]"
                >
                  Clear
                </Button>
              )}
            </div>
          </div>

          <div>
            <Label>Cameras (optional)</Label>
            <div className="mt-1 max-h-40 overflow-y-auto rounded-md border border-white/10 bg-card/40 p-2 space-y-1">
              {cameras.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  No cameras
                </p>
              ) : (
                cameras.map((c) => {
                  const on = selectedCams.includes(c.id);
                  return (
                    <button
                      type="button"
                      key={c.id}
                      onClick={() => toggleCam(c.id)}
                      className={`w-full flex items-center gap-2 px-2 py-1 rounded text-left text-xs ${
                        on
                          ? "bg-teal-500/15 text-teal-200"
                          : "hover:bg-white/5 text-muted-foreground"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        readOnly
                        className="h-3 w-3"
                      />
                      <CameraIcon className="h-3 w-3" />
                      <span className="truncate">{c.name}</span>
                    </button>
                  );
                })
              )}
            </div>
            {selectedCams.length > 0 && (
              <p className="text-[11px] text-muted-foreground mt-1">
                {selectedCams.length} selected
              </p>
            )}
          </div>

          <Button type="submit" disabled={mut.isPending} className="w-full">
            <Search className="h-4 w-4 mr-1" />
            {mut.isPending ? "Searching…" : "Search"}
          </Button>
        </div>

        <div className="space-y-2 min-h-0">
          <div className="flex items-center justify-between">
            <Label>Results</Label>
            <span className="text-[11px] text-muted-foreground">
              {results.length} hit{results.length === 1 ? "" : "s"}
            </span>
          </div>
          <div className="rounded-lg border border-border bg-card/40 overflow-hidden">
            {results.length === 0 ? (
              <p className="px-4 py-12 text-sm text-center text-muted-foreground">
                {mut.isPending
                  ? "Searching…"
                  : "Upload a face + Search to investigate"}
              </p>
            ) : (
              <div className="divide-y divide-white/5 max-h-[70vh] overflow-y-auto">
                {results.map((r, i) => {
                  const snap = snapshotSrc(r.snapshot_path);
                  return (
                    <div
                      key={r.event_id || `${r.person_id}-${i}`}
                      className="p-3 flex items-center gap-3 text-sm hover:bg-card/50"
                    >
                      {snap ? (
                        <img
                          src={snap}
                          alt="snap"
                          className="h-14 w-20 object-cover rounded border border-white/10"
                        />
                      ) : (
                        <div className="h-14 w-20 flex items-center justify-center rounded border border-white/10 bg-card/60">
                          <Upload className="h-4 w-4 text-muted-foreground" />
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs">
                            {r.person_id?.slice(0, 8) || "unknown"}
                          </span>
                          <Badge variant="outline" className="text-[10px]">
                            {(r.score * 100).toFixed(0)}%
                          </Badge>
                          {r.camera_id && (
                            <Badge
                              variant="outline"
                              className="text-[10px] bg-blue-500/10 border-blue-500/30 text-blue-300"
                            >
                              <CameraIcon className="h-3 w-3 mr-1" />
                              {camMap[r.camera_id] || r.camera_id.slice(0, 8)}
                            </Badge>
                          )}
                        </div>
                        {r.ts && (
                          <div className="text-[11px] text-muted-foreground font-mono mt-0.5">
                            <Clock className="h-3 w-3 inline mr-1" />
                            {format(new Date(r.ts), "MMM dd, HH:mm:ss")}
                          </div>
                        )}
                      </div>
                      {r.event_id && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          title="Open in playback"
                          onClick={() => openInPlayback(r)}
                        >
                          <PlayCircle className="h-4 w-4 text-teal-300" />
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </form>
    </div>
  );
};

export default InvestigatePage;
