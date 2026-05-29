import { useCallback, useState } from "react";

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

export function useUiPrefs() {
  const [prefs, setPrefs] = useState(read);

  const update = useCallback((patch) => {
    setPrefs((prev) => {
      const next = { ...prev, ...patch };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        /* ignore quota errors */
      }
      return next;
    });
  }, []);

  return [prefs, update];
}
