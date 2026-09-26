import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    include: ['src/**/*.test.{js,jsx,ts,tsx}'],
    // Dots. is PC-only; retained pre-pivot mobile tests are historical, not release gates.
    exclude: ['docs/inherited/**', 'src/viewport.test.js', 'src/issue-56-profile-mobile-visual-regression.test.jsx'],
  },
});
