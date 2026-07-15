import path from 'path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/transactions': 'http://localhost:8000',
      '/accounts': 'http://localhost:8000',
      '/insights': 'http://localhost:8000',
      '/categories': 'http://localhost:8000',
      '/import': 'http://localhost:8000',
      '/backup': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  build: { outDir: 'dist' },
})
