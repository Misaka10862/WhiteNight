import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期把 /api 与 /ws 代理到本机 WhiteNight 后端；生产由后端同源托管（阶段 6）。
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
      },
    },
  },
})
