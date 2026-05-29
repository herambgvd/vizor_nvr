// Cluster (N+1 hot standby) API client.
// NOTE: /cluster/status is admin-only on the backend; /cluster/nodes is
// available to any authenticated user, so the StatusBar uses getClusterNodes.
import client from "./client";

export const getClusterNodes = async () => {
  const res = await client.get("/cluster/nodes");
  return res.data; // [{ node_id, hostname, role, is_leader, ... }]
};

export const getClusterStatus = async () => {
  const res = await client.get("/cluster/status");
  return res.data; // admin only
};

// Derive the local node's role label from the nodes list.
export const localNodeRole = (nodes) => {
  if (!Array.isArray(nodes) || nodes.length === 0) return "unknown";
  const leader = nodes.find((n) => n.is_leader);
  return leader ? "active" : "standby";
};
