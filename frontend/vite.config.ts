import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API URL comes from VITE_API_URL: .env.local (dev) or .env.production (Vercel build).
export default defineConfig({
  plugins: [react(), tailwindcss()],
})
