import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const api = process.env.API_PROXY || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/health": api,
      "/api": api,
      "/auth": api,
      "/twitch": api,
    },
  },
});
