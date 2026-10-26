import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
const api = { "/api": process.env.API_URL || "http://localhost:8000" };
export default defineConfig({
  plugins: [react()],
  server: { proxy: api },
  preview: { proxy: api },
  build: { chunkSizeWarningLimit: 5000 },
});
