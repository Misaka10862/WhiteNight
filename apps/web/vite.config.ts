import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期把 /api 与 /ws 代理到本机 WhiteNight 后端（含 WebSocket 升级）。
export default defineConfig(({ mode }) => {
  const apiUrl = loadEnv(mode, '.', '').WHITENIGHT_API_URL || 'http://127.0.0.1:8765'
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/api': {
          target: apiUrl,
          ws: true,
        },
        '/ws': {
          target: apiUrl.replace(/^http/, 'ws'),
          ws: true,
        },
      },
    },
  }
})
