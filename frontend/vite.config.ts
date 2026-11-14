import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
    // Canonical snapshots live beside frontend/, independently of workspace detection.
    fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] },
  },
});
