import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = process.env.API_PROXY || "http://localhost:8000";
const hmrPort = Number(process.env.HMR_CLIENT_PORT || "");

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    allowedHosts: ["bot.pangeprime.app"],
    // Behind TLS on 443 the page has no port. An empty port makes the HMR
    // socket URL `wss://host:/`, and Safari tries to parse the error body.
    hmr: hmrPort ? { protocol: "wss", clientPort: hmrPort } : undefined,
    proxy: {
      "/health": api,
      "/api": api,
      "/auth": api,
      "/twitch": api,
    },
  },
});
