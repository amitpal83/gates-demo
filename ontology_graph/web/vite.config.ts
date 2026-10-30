import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, forward /api to the FastAPI container; in production FastAPI serves the built files itself.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8504" } },
});
