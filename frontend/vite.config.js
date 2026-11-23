import { defineConfig } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'

export default defineConfig(({ mode }) => ({
  plugins: [uni()],
  build: { minify: mode === 'development' ? false : 'esbuild' }
}))
