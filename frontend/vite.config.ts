import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Vite server forwards /api to the gateway, so the browser talks to one
// origin, exactly like production, where nginx does the same job (nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.API_URL ?? "http://localhost:8000", changeOrigin: true },
    },
  },
});
