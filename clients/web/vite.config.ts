import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server binds localhost only — the client, like the API, is on-device.
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173 },
});
