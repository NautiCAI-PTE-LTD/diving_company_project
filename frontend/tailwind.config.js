/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['"Plus Jakarta Sans"', 'Inter', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        // NautiCAI brand — deep ocean navy + cyan accent
        ink: {
          950: '#070d1a',
          900: '#0a1429',
          800: '#0f1d3a',
          700: '#152748',
          600: '#1e355f',
          500: '#2a4575',
        },
        brand: {
          50:  '#ecfeff',
          100: '#cffafe',
          200: '#a5f3fc',
          300: '#67e8f9',
          400: '#22d3ee',
          500: '#06b6d4',
          600: '#0891b2',
          700: '#0e7490',
          800: '#155e75',
          900: '#164e63',
        },
        accent: {
          400: '#7dd3fc',
          500: '#38bdf8',
          600: '#0284c7',
        },
        success: { 500: '#10b981' },
        warning: { 500: '#f59e0b' },
        danger:  { 500: '#ef4444' },
      },
      backgroundImage: {
        'ocean-gradient':
          'radial-gradient(1200px 600px at 0% 0%, rgba(34,211,238,0.18) 0%, transparent 50%), radial-gradient(900px 500px at 100% 0%, rgba(56,189,248,0.16) 0%, transparent 60%), linear-gradient(180deg, #070d1a 0%, #0a1429 100%)',
        'wave-pattern':
          "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='200' viewBox='0 0 1600 200'><path d='M0 100 C 200 40, 400 160, 600 100 S 1000 40, 1200 100 S 1600 160, 1600 100' stroke='%2322d3ee' stroke-opacity='0.15' fill='none' stroke-width='2'/></svg>\")",
        'grid-faint':
          "linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
      },
      backgroundSize: {
        'grid-faint': '40px 40px',
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(34,211,238,0.25), 0 10px 40px -10px rgba(34,211,238,0.45)',
        card: '0 10px 30px -12px rgba(2, 8, 23, 0.6)',
        inset: 'inset 0 1px 0 rgba(255,255,255,0.06)',
      },
      keyframes: {
        float: { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-6px)' } },
        shimmer: {
          '0%':   { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        bubble: {
          '0%':   { transform: 'translateY(0) scale(1)',    opacity: '0' },
          '20%':  { opacity: '0.7' },
          '100%': { transform: 'translateY(-120px) scale(1.6)', opacity: '0' },
        },
      },
      animation: {
        float: 'float 4s ease-in-out infinite',
        shimmer: 'shimmer 2.6s linear infinite',
        bubble: 'bubble 6s ease-in infinite',
      },
    },
  },
  plugins: [],
}
