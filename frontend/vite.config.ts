import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const rawBase = process.env.BASE_PATH || "/";
const base = rawBase.endsWith("/") ? rawBase : `${rawBase}/`;

export default defineConfig({
  base,
  plugins: [react()],
  server: {
    port: 3000,
    open: false,
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
