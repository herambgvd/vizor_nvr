import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "../api/client";

const DEFAULT_BRANDING = {
  system_name: "Vizor NVR",
  logo_url: "",
  favicon_url: "",
  theme_mode: "dark",
  background_color: "#000000",
  button_color: "#228B22",
  text_color: "#E2E8F0",
  font_size: "14",
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

const clampFontSize = (value) => {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return 14;
  return Math.min(18, Math.max(12, parsed));
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

    const themeMode = branding.theme_mode === "light" ? "light" : "dark";
    const palette = themeMode === "light"
      ? {
          bg: "#FFFFFF",
          panel: "#FFFFFF",
          raised: "#F5F7FA",
          border: "#D7DEE8",
          muted: "#64748B",
          input: "#FFFFFF",
          popover: "#FFFFFF",
          hover: "#EEF2F7",
          active: "#E4EAF2",
        }
      : {
          bg: "#000000",
          panel: "#000000",
          raised: "#050505",
          border: "#202020",
          muted: "#8A8F98",
          input: "#050505",
          popover: "#000000",
          hover: "#101010",
          active: "#171717",
        };
    const buttonColor = normalizeHex(
      branding.button_color,
      DEFAULT_BRANDING.button_color,
    );
    const textColor = normalizeHex(
      branding.text_color,
      themeMode === "light" ? "#111827" : DEFAULT_BRANDING.text_color,
    );
    const root = document.documentElement;
    const bgHsl = hexToHslToken(palette.bg);
    const buttonHsl = hexToHslToken(buttonColor);
    const buttonText = readableTextFor(buttonColor);
    const fontSize = clampFontSize(branding.font_size);

    root.classList.toggle("light", themeMode === "light");
    root.classList.toggle("dark", themeMode === "dark");
    root.style.setProperty("--console-font-size", `${fontSize}px`);
    root.style.fontSize = `${fontSize}px`;
    root.style.setProperty("--background", bgHsl);
    root.style.setProperty("--sidebar", bgHsl);
    root.style.setProperty("--foreground", hexToHslToken(textColor));
    root.style.setProperty("--card", hexToHslToken(palette.panel));
    root.style.setProperty("--card-foreground", hexToHslToken(textColor));
    root.style.setProperty("--popover", hexToHslToken(palette.popover));
    root.style.setProperty("--popover-foreground", hexToHslToken(textColor));
    root.style.setProperty("--muted", hexToHslToken(palette.raised));
    root.style.setProperty("--muted-foreground", hexToHslToken(palette.muted));
    root.style.setProperty("--border", hexToHslToken(palette.border));
    root.style.setProperty("--input", hexToHslToken(palette.input));
    root.style.setProperty("--console-bg", palette.bg);
    root.style.setProperty("--console-panel", palette.panel);
    root.style.setProperty("--console-raised", palette.raised);
    root.style.setProperty("--console-border", palette.border);
    root.style.setProperty("--console-hover", palette.hover);
    root.style.setProperty("--console-active", palette.active);
    root.style.setProperty("--console-text", textColor);
    root.style.setProperty("--console-muted", palette.muted);
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
    branding.theme_mode,
    branding.button_color,
    branding.text_color,
    branding.font_size,
  ]);

  return branding;
}
