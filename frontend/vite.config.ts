import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  define: { __APP_BUILD_SHA__: JSON.stringify("test-build") },
  // Vite is retained only as the Vitest transform pipeline.
});
