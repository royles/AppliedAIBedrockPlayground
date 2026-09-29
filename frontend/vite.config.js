import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Cloudera AI (CAI) layout
 * ------------------------
 * - Frontend listens on 127.0.0.1:CDSW_APP_PORT (set by the platform).
 * - Backend API runs on 127.0.0.1:8000 (internal loopback only).
 * - start.py sets BACKEND_PROXY_TARGET before launching Vite.
 *
 * Do NOT proxy to CDSW_READONLY_PORT — that port is for external readonly
 * URLs and is not reachable via loopback inside the workload.
 */
const isClouderaAI = Boolean(process.env.CDSW_APP_PORT);
const internalApiPort = process.env.BACKEND_PROXY_PORT || "8000";
const backendTarget =
  process.env.BACKEND_PROXY_TARGET || `http://127.0.0.1:${internalApiPort}`;
const frontendPort = parseInt(process.env.CDSW_APP_PORT || "5173", 10);
const frontendHost = process.env.CDSW_APP_HOST || "127.0.0.1";

const allowedHosts = [".cloudera.site", ".cloudera.com", "localhost", "127.0.0.1"];
if (process.env.CDSW_DOMAIN) {
  allowedHosts.push(process.env.CDSW_DOMAIN);
}
if (process.env.CDSW_PUBLIC_URL) {
  try {
    allowedHosts.push(new URL(process.env.CDSW_PUBLIC_URL).hostname);
  } catch {
    // ignore invalid URL
  }
}

const proxyOptions = {
  target: backendTarget,
  changeOrigin: true,
};

if (isClouderaAI) {
  console.log(
    `[vite] Cloudera AI: frontend ${frontendHost}:${frontendPort}, api proxy -> ${backendTarget}`,
  );
}

export default defineConfig({
  // Relative asset URLs so CSS/JS load under Cloudera AI path prefixes.
  base: "./",
  plugins: [react()],
  build: {
    // Avoid crossorigin on stylesheet links; some static hosts block them without CORS.
    modulePreload: { polyfill: false },
  },
  server: {
    host: frontendHost,
    port: frontendPort,
    strictPort: isClouderaAI,
    allowedHosts,
    proxy: {
      "/api": proxyOptions,
      "/docs": proxyOptions,
      "/openapi.json": proxyOptions,
      "/redoc": proxyOptions,
    },
  },
});
