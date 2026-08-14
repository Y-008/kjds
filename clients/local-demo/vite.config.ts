import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  build: {
    assetsInlineLimit: 0,
    cssCodeSplit: false,
    emptyOutDir: true,
    modulePreload: false,
    outDir: "dist",
    rollupOptions: {
      output: {
        assetFileNames: (assetInfo) =>
          assetInfo.names.some((name) => name.endsWith(".css"))
            ? "assets/app.css"
            : "assets/[name][extname]",
        chunkFileNames: "assets/[name].js",
        entryFileNames: "assets/app.js",
      },
    },
    sourcemap: false,
    target: "es2022",
  },
  preview: {
    host: "127.0.0.1",
    port: 43190,
    strictPort: true,
  },
  server: {
    host: "127.0.0.1",
    port: 43190,
    strictPort: true,
  },
});
