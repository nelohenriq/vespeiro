import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3001,
    open: false,
    proxy: {
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
        timeout: 60000,
        configure: (proxy) => {
          proxy.on("error", (err, _req, res) => {
            console.error("[proxy] API server not reachable:", err.message);
            if (!res.headersSent) {
              res.writeHead(502, { "Content-Type": "application/json" });
            }
            res.end(JSON.stringify({
              error: "API server not running",
              detail: "Start the API server: cd docs/analisa-pt/tools && python api_server.py --port 8080",
            }));
          });
        },
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
