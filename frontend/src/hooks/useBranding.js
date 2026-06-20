import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "../api/client";
import { setDisplayTimezone } from "../lib/datetime";

const DEFAULT_BRANDING = {
  system_name: "Vizor NVR",
  timezone: "UTC",
  logo_url: "",
  favicon_url: "",
  theme_mode: "dark",
  background_color: "#000000",
  button_color: "#FFFFFF",
  text_color: "#F9FAFB",
  hover_color: "#111111",
  font_size: "14",
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

const clampFontSize = (value) => {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return 14;
  return Math.min(18, Math.max(12, parsed));
};

// Vercel-style palettes. accent = brand GREEN so primary buttons render green +
// white text (previously accent was #FFFFFF/#111827 → white/near-white buttons).
const themePalette = (mode) => (
  mode === "light"
    ? {
        bg: "#FFFFFF",
        panel: "#FFFFFF",
        raised: "#F7F7F8",
        border: "#E5E7EB",
        text: "#0A0A0A",
        muted: "#666666",
        input: "#FFFFFF",
        popover: "#FFFFFF",
        hover: "#F3F4F6",
        active: "#ECECEF",
        accent: "#228B22",
        accentText: "#FFFFFF",
        online: "#16A34A",
      }
    : {
        bg: "#000000",
        panel: "#0A0A0A",
        raised: "#111111",
        border: "#333333",
        text: "#FFFFFF",
        muted: "#888888",
        input: "#111111",
        popover: "#0A0A0A",
        hover: "#171717",
        active: "#1F1F1F",
        accent: "#228B22",
        accentText: "#FFFFFF",
        online: "#22C55E",
      }
);

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

  // Publish the operator display timezone app-wide so lib/datetime formatters
  // render every screen's times in the configured zone.
  useEffect(() => {
    setDisplayTimezone(branding.timezone || null);
  }, [branding.timezone]);

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
    const palette = themePalette(themeMode);
    const buttonColor = palette.accent;
    const textColor = palette.text;
    const hoverColor = palette.hover;
    const root = document.documentElement;
    const bgHsl = hexToHslToken(palette.bg);
    const buttonHsl = hexToHslToken(buttonColor);
    const buttonText = palette.accentText;
    const fontSize = clampFontSize(branding.font_size);

    root.classList.toggle("light", themeMode === "light");
    root.classList.toggle("dark", themeMode === "dark");
    root.dataset.consoleFontSize = String(fontSize);
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
    root.style.setProperty("--console-hover", hoverColor);
    root.style.setProperty("--console-active", palette.active);
    root.style.setProperty("--console-text", textColor);
    root.style.setProperty("--console-muted", palette.muted);
    root.style.setProperty("--primary", buttonHsl);
    root.style.setProperty("--secondary", buttonHsl);
    root.style.setProperty("--accent", buttonHsl);
    root.style.setProperty("--success", buttonHsl);
    root.style.setProperty("--ring", buttonHsl);
    root.style.setProperty("--console-accent", buttonColor);
    root.style.setProperty("--console-accent-blue", "#0070f3");
    root.style.setProperty("--console-online", palette.online);
    root.style.setProperty("--console-raised", palette.raised);
    root.style.setProperty("--console-faint", themeMode === "light" ? "#999999" : "#666666");
    root.style.setProperty("--console-accent-foreground", buttonText);
  }, [
    branding.system_name,
    branding.favicon_url,
    branding.theme_mode,
    branding.font_size,
  ]);

  return branding;
}
