import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The built app is served by pywebview from src/portfolio_ledger/ui (relative asset paths).
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../src/portfolio_ledger/ui',
    emptyOutDir: true,
  },
  server: { port: 5175, strictPort: true },
});
