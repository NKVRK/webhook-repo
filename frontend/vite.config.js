import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],

  // Proxy API requests to the Flask backend during development
  server: {
    proxy: {
      "/webhook": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
      },
    },
  },
});
