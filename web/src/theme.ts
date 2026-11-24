// Material 3 flavoured MUI theme: tonal surfaces, rounded shapes, 48 dp touch targets.

import { createTheme, type Theme } from "@mui/material/styles";

export function makeTheme(mode: "dark" | "light"): Theme {
  const dark = mode === "dark";
  return createTheme({
    palette: {
      mode,
      primary: { main: dark ? "#8ab4f8" : "#1a5fb4" },
      secondary: { main: dark ? "#c4c7f5" : "#5b5d8f" },
      background: dark
        ? { default: "#111318", paper: "#1b1e24" }
        : { default: "#f7f9ff", paper: "#ffffff" },
      error: { main: dark ? "#ffb4ab" : "#ba1a1a" },
      success: { main: dark ? "#7dd99a" : "#1b6d3a" },
    },
    shape: { borderRadius: 16 },
    typography: {
      fontFamily: "Roboto, system-ui, sans-serif",
      button: { textTransform: "none", fontWeight: 500 },
    },
    components: {
      MuiButtonBase: { defaultProps: { disableRipple: false } },
      MuiIconButton: { styleOverrides: { root: { minWidth: 48, minHeight: 48 } } },
      MuiButton: { styleOverrides: { root: { borderRadius: 24, minHeight: 44, paddingInline: 20 } } },
      MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
      MuiSlider: { styleOverrides: { root: { height: 6 } } },
      MuiListItemButton: { styleOverrides: { root: { borderRadius: 12, minHeight: 48 } } },
    },
  });
}

export function formatTime(ms: number): string {
  if (!ms || ms < 0) return "0:00";
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}
