import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Cpu, MemoryStick, HardDrive, Server, Circle } from "lucide-react";
import { getResources } from "../../api/monitoring";
import { getClusterNodes, localNodeRole } from "../../api/cluster";
import { useCamerasQuery } from "../../hooks";
import { fmtPct } from "../../lib/telemetry";

function Metric({ icon: Icon, label, value, tone }) {
  return (
    <div className="flex items-center gap-1.5 px-2.5 border-r" style={{ borderColor: "var(--console-border)" }}>
      <Icon className="h-3.5 w-3.5 text-zinc-500" />
      <span className="text-zinc-500">{label}</span>
      <span className="font-telemetry" style={{ color: tone || "var(--console-text)" }}>{value}</span>
    </div>
  );
}

export default function StatusBar() {
  const { data: cameras = [] } = useCamerasQuery();
  const { data: resources } = useQuery({
    queryKey: ["resources"],
    queryFn: getResources,
    refetchInterval: 5000,
  });
  const { data: nodes = [] } = useQuery({
    queryKey: ["cluster-nodes"],
    queryFn: getClusterNodes,
    refetchInterval: 5000,
    retry: false,
  });
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const online = cameras.filter((c) => c.status === "online").length;
  const offline = cameras.length - online;
  const recording = cameras.filter((c) => c.is_recording).length;
  const role = localNodeRole(nodes);

  const cpu = resources?.cpu_percent ?? resources?.cpu;
  const mem = resources?.memory_percent ?? resources?.memory;
  const disk = resources?.disk_percent ?? resources?.disk;

  return (
    <div
      className="flex items-center text-[11px] console-panel border-t select-none"
      style={{ height: "var(--console-statusbar-h)", borderColor: "var(--console-border)" }}
    >
      <Metric icon={Cpu} label="CPU" value={fmtPct(cpu)} />
      <Metric icon={MemoryStick} label="MEM" value={fmtPct(mem)} />
      <Metric icon={HardDrive} label="DISK" value={fmtPct(disk)} />
      <Metric
        icon={Circle}
        label="REC"
        value={String(recording)}
        tone={recording > 0 ? "var(--console-rec)" : undefined}
      />
      <div className="flex items-center gap-2 px-2.5 border-r" style={{ borderColor: "var(--console-border)" }}>
        <span className="text-zinc-500">CAMS</span>
        <span className="font-telemetry" style={{ color: "var(--console-online)" }}>{online}↑</span>
        <span className="font-telemetry" style={{ color: "var(--console-offline)" }}>{offline}↓</span>
      </div>
      <Metric
        icon={Server}
        label="NODE"
        value={role}
        tone={role === "active" ? "var(--console-online)" : "var(--console-muted)"}
      />
      <div className="ml-auto px-3 font-telemetry text-zinc-400">
        {now.toLocaleString()}
      </div>
    </div>
  );
}
