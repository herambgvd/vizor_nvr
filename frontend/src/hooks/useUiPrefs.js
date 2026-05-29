import { useCallback, useSyncExternalStore } from "react";

const KEY = "nvr_ui_prefs";

const DEFAULTS = {
  railCollapsed: false,
  treeCollapsed: false,
  dockOpen: true,
  wallLayout: 4,
  // wallTiles: array of cameraId|null, indexed by slot
  wallTiles: [],
};

function read() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS };
  } catch {
    return { ...DEFAULTS };
  }
}

// Module-level shared store so every useUiPrefs consumer (e.g. the camera tree
// in the shell and the video wall) reads and writes the SAME state and stays in
// sync. A plain per-component useState would give each consumer an independent
// copy, so a write from one component would never reach the others.
let state = read();
const listeners = new Set();

function getSnapshot() {
  return state;
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function write(patch) {
  state = { ...state, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* ignore quota errors */
  }
  listeners.forEach((l) => l());
}

export function useUiPrefs() {
  const prefs = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const update = useCallback((patch) => write(patch), []);
  return [prefs, update];
}
