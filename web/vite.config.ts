import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { VitePWA } from "vite-plugin-pwa";

// During development the API runs separately (heos-home on :8080); Vite proxies to it.
const api = process.env.HEOS_API ?? "http://localhost:8080";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "HEOS Home",
        short_name: "HEOS Home",
        description: "Local controller for HEOS devices",
        display: "fullscreen",
        orientation: "any",
        background_color: "#121212",
        theme_color: "#121212",
        icons: [{ src: "icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any maskable" }],
      },
      workbox: {
        // API calls and cached device images must always go to the service.
        navigateFallbackDenylist: [/^\/api\//, /^\/docs/],
        runtimeCaching: [],
      },
    }),
  ],
  server: {
    host: true,
    proxy: {
      "/api": { target: api, ws: true, changeOrigin: true },
    },
  },
  test: {
    environment: "node",
  },
});
