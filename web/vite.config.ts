import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Développement : l'API FastAPI tourne sur :8000 (python -m agentkit.server), relayée ici.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        // API éteinte : message clair au lieu d'une erreur 500 anonyme
        configure: (proxy) => {
          proxy.on("error", (_err, _req, res) => {
            const r = res as import("node:http").ServerResponse;
            if (r.headersSent) return;
            r.writeHead(502, { "Content-Type": "application/json" });
            r.end(JSON.stringify({ detail: "The API server is not running. Start it in another terminal: python -m agentkit.server" }));
          });
        },
      },
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
