import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期把 /api 与 /ws 代理到本机 WhiteNight 后端（含 WebSocket 升级）。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        ws: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
    },
  },
})
