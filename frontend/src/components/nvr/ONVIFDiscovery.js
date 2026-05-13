// =============================================================================
// ONVIF Discovery Dialog — Scan for ONVIF cameras on the network
// =============================================================================

import React, { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Search,
  Wifi,
  CheckCircle2,
  Loader2,
  Camera,
  Info,
} from "lucide-react";
import { onvifDiscover, onvifProbe } from "../../api/cameras";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "../ui/dialog";
import { cn } from "../../lib/utils";
import { toast } from "sonner";

/**
 * ONVIF Discovery Dialog
 *
 * Usage:
 *   <ONVIFDiscovery
 *     open={showOnvif}
 *     onOpenChange={setShowOnvif}
 *     onSelect={(camera) => {
 *       // camera has { name, main_stream_url, ip, ... }
 *       // open CameraFormDialog with this data pre-filled
 *     }}
 *   />
 */
export const ONVIFDiscovery = ({ open, onOpenChange, onSelect }) => {
  const [devices, setDevices] = useState([]);
  const [selected, setSelected] = useState(null);
  const [credentials, setCredentials] = useState({
    username: "admin",
    password: "",
  });

  // 1 — discover
  const discoverMut = useMutation({
    mutationFn: (params) => onvifDiscover(params),
    onSuccess: (data) => {
      const list = Array.isArray(data) ? data : (data?.devices ?? []);
      setDevices(list);
      setSelected(null);
      if (list.length === 0)
        toast.info("No ONVIF devices found on the network");
    },
    onError: (e) => toast.error(e.response?.data?.detail || "Discovery failed"),
  });

  // 2 — probe (get stream URIs & details)
  const probeMut = useMutation({
    mutationFn: ({ ip, ...rest }) =>
      onvifProbe({
        host: ip,
        ...rest,
        username: credentials.username,
        password: credentials.password,
      }),
    onSuccess: (data) => {
      toast.success("Device probed successfully");
      if (onSelect) {
        onSelect({
          name: data.name || data.model || data.ip || "ONVIF Camera",
          main_stream_url: data.stream_uri || data.main_stream_url || "",
          location: "",
          description: `Model: ${data.model || "-"}, Firmware: ${data.firmware || "-"}`,
          ...(data.ptz_support && { ptz_enabled: true }),
        });
        onOpenChange(false);
      }
    },
    onError: (e) =>
      toast.error(
        e.response?.data?.detail || "Probe failed — check credentials",
      ),
  });

  const handleDiscover = () => {
    discoverMut.mutate({
      timeout: 5,
      username: credentials.username,
      password: credentials.password,
    });
  };

  const handleAdd = () => {
    if (!selected) return;
    probeMut.mutate({
      ip: selected.ip || selected.address,
      port: selected.port || 80,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wifi className="h-5 w-5" />
            ONVIF Discovery
          </DialogTitle>
          <DialogDescription>
            Scan the local network for ONVIF-compatible cameras
          </DialogDescription>
        </DialogHeader>

        {/* Credentials */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">ONVIF Username</Label>
            <Input
              value={credentials.username}
              onChange={(e) =>
                setCredentials((c) => ({ ...c, username: e.target.value }))
              }
              placeholder="admin"
            />
          </div>
          <div>
            <Label className="text-xs">ONVIF Password</Label>
            <Input
              type="password"
              value={credentials.password}
              onChange={(e) =>
                setCredentials((c) => ({ ...c, password: e.target.value }))
              }
              placeholder="••••••"
            />
          </div>
        </div>

        {/* Scan button */}
        <Button
          onClick={handleDiscover}
          disabled={discoverMut.isPending}
          className="w-full"
        >
          {discoverMut.isPending ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Scanning…
            </>
          ) : (
            <>
              <Search className="h-4 w-4 mr-2" />
              Scan Network
            </>
          )}
        </Button>

        {/* Results */}
        {devices.length > 0 && (
          <div className="space-y-2 max-h-60 overflow-y-auto">
            <p className="text-xs text-zinc-500 font-medium">
              {devices.length} device{devices.length !== 1 ? "s" : ""} found
            </p>
            {devices.map((dev, i) => {
              const isSelected = selected === dev;
              return (
                <button
                  key={dev.ip || dev.address || i}
                  className={cn(
                    "w-full text-left p-3 rounded-lg border transition-colors",
                    isSelected
                      ? "border-slate-900 bg-zinc-950/40 ring-1 ring-slate-900"
                      : "border-white/10 hover:border-slate-400",
                  )}
                  onClick={() => setSelected(dev)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Camera className="h-4 w-4 text-zinc-500" />
                      <span className="font-medium text-sm text-white">
                        {dev.name || dev.model || "Unknown Camera"}
                      </span>
                    </div>
                    {isSelected && (
                      <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                    )}
                  </div>
                  <p className="text-xs text-zinc-500 mt-1 font-mono">
                    {dev.ip || dev.address}
                    {dev.port ? `:${dev.port}` : ""}
                  </p>
                  {dev.manufacturer && (
                    <p className="text-xs text-zinc-500 mt-0.5">
                      {dev.manufacturer} {dev.model || ""}
                    </p>
                  )}
                </button>
              );
            })}
          </div>
        )}

        {devices.length === 0 && !discoverMut.isPending && (
          <div className="flex items-center gap-2 text-xs text-zinc-500 py-4 justify-center">
            <Info className="h-4 w-4" />
            Press "Scan Network" to discover cameras
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleAdd}
            disabled={!selected || probeMut.isPending}
          >
            {probeMut.isPending ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Probing…
              </>
            ) : (
              "Add Selected Camera"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default ONVIFDiscovery;
