import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Allow /@fs/... loads for VRM and VRMA outside the viewer folder (local dev only).
const fsAllow = [path.resolve(__dirname), path.resolve(__dirname, "..")];
if (process.platform === "win32") {
  for (const letter of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") {
    fsAllow.push(`${letter}:/`);
  }
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    fs: {
      allow: fsAllow,
    },
  },
});
