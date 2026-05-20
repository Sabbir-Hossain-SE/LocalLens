import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#10b981',
          dark: '#059669',
          light: '#34d399',
        },
        surface: {
          DEFAULT: '#0f172a',
          card: '#1e293b',
          hover: '#253347',
          border: '#334155',
          deep: '#0a0f1a',
        },
        score: {
          high: '#10b981',
          mid: '#f59e0b',
          low: '#ef4444',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        'pulse-green': 'pulse-green 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fade-in 0.4s ease-out forwards',
        'slide-up': 'slide-up 0.3s ease-out forwards',
        'slide-in-right': 'slide-in-right 0.4s ease-out forwards',
        'spin-slow': 'spin 3s linear infinite',
        'bounce-once': 'bounce 0.6s ease-out',
      },
      keyframes: {
        'pulse-green': {
          '0%, 100%': { opacity: '1', boxShadow: '0 0 0 0 rgba(16, 185, 129, 0.4)' },
          '50%': { opacity: '0.7', boxShadow: '0 0 0 8px rgba(16, 185, 129, 0)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(16px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-in-right': {
          from: { opacity: '0', transform: 'translateX(16px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
      },
      backgroundImage: {
        'gradient-brand': 'linear-gradient(135deg, #10b981, #059669)',
        'gradient-card': 'linear-gradient(145deg, #1e293b, #0f172a)',
        'gradient-rank': 'linear-gradient(135deg, #10b981, #0d9488)',
      },
    },
  },
  plugins: [],
};

export default config;
