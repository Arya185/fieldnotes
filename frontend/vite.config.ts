import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/index": "http://127.0.0.1:8000",
      "/ask": "http://127.0.0.1:8000",
      "/quiz": "http://127.0.0.1:8000",
      "/notebook": "http://127.0.0.1:8000",
      "/artifact": "http://127.0.0.1:8000",
      "/source": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/openapi.json": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
