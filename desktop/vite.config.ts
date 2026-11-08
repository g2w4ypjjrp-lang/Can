import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Tauri geliştirme sunucusu sabit portta çalışır; üretimde dosyalar `dist/` içinden yüklenir.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: { host: "127.0.0.1", port: 1420, strictPort: true },
  build: { target: "es2022", outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
