import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "../api/client";

const DEFAULT_BRANDING = {
  system_name: "Vizor NVR",
  logo_url: "",
  favicon_url: "",
  background_color: "#000000",
  button_color: "#228B22",
};

const HEX_COLOR = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

const normalizeHex = (value, fallback) => {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!HEX_COLOR.test(raw)) return fallback;
  if (raw.length === 4) {
    const [, r, g, b] = raw;
    return `#${r}${r}${g}${g}${b}${b}`.toUpperCase();
  }
  return raw.toUpperCase();
};

const hexToRgb = (hex) => {
  const clean = hex.replace("#", "");
  return {
    r: parseInt(clean.slice(0, 2), 16),
    g: parseInt(clean.slice(2, 4), 16),
    b: parseInt(clean.slice(4, 6), 16),
  };
};

const hexToHslToken = (hex) => {
  const { r, g, b } = hexToRgb(hex);
  const rp = r / 255;
  const gp = g / 255;
  const bp = b / 255;
  const max = Math.max(rp, gp, bp);
  const min = Math.min(rp, gp, bp);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;

  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === rp) h = (gp - bp) / d + (gp < bp ? 6 : 0);
    if (max === gp) h = (bp - rp) / d + 2;
    if (max === bp) h = (rp - gp) / d + 4;
    h *= 60;
  }

  return `${Math.round(h)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
};

const readableTextFor = (hex) => {
  const { r, g, b } = hexToRgb(hex);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.58 ? "#06120A" : "#FFFFFF";
};

export const getBranding = async () => {
  const response = await apiClient.get("/settings/public/branding");
  return { ...DEFAULT_BRANDING, ...(response.data || {}) };
};

export default function useBranding() {
  const { data } = useQuery({
    queryKey: ["public-branding"],
    queryFn: getBranding,
    staleTime: 60_000,
  });

  const branding = { ...DEFAULT_BRANDING, ...(data || {}) };

  useEffect(() => {
    document.title = branding.system_name || DEFAULT_BRANDING.system_name;

    const faviconUrl = branding.favicon_url;
    let link = document.querySelector("link[rel='icon']");
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = faviconUrl || "/favicon.ico";

    const backgroundColor = normalizeHex(
      branding.background_color,
      DEFAULT_BRANDING.background_color,
    );
    const buttonColor = normalizeHex(
      branding.button_color,
      DEFAULT_BRANDING.button_color,
    );
    const root = document.documentElement;
    const bgHsl = hexToHslToken(backgroundColor);
    const buttonHsl = hexToHslToken(buttonColor);
    const buttonText = readableTextFor(buttonColor);

    root.style.setProperty("--background", bgHsl);
    root.style.setProperty("--sidebar", bgHsl);
    root.style.setProperty("--console-bg", backgroundColor);
    root.style.setProperty("--primary", buttonHsl);
    root.style.setProperty("--secondary", buttonHsl);
    root.style.setProperty("--accent", buttonHsl);
    root.style.setProperty("--success", buttonHsl);
    root.style.setProperty("--ring", buttonHsl);
    root.style.setProperty("--console-accent", buttonColor);
    root.style.setProperty("--console-accent-blue", buttonColor);
    root.style.setProperty("--console-online", buttonColor);
    root.style.setProperty("--console-accent-foreground", buttonText);
  }, [
    branding.system_name,
    branding.favicon_url,
    branding.background_color,
    branding.button_color,
  ]);

  return branding;
}
