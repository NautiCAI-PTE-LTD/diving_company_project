# NautiCAI — Marine Inspection Suite (Frontend)

Production-ready React + Vite + TailwindCSS UI for an AI-powered diving / marine
inspection company. The UI is built around the three trained models in
`../Models/`:

| Model file                               | Role                          | Used by UI in              |
|------------------------------------------|-------------------------------|----------------------------|
| `Ship_classification_v2.pth`             | Hull-region classifier (11)   | Image Studio auto-routing  |
| `Before_and_after_v2.keras`              | Before / after cleaning (2)   | Per-image AI overlay       |
| `species_classifier_bundle.pt`           | Fouling species (5)           | Per-image AI overlay       |

## Quick start (Windows / PowerShell)

```powershell
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The dev server proxies `/api/*` to `http://localhost:8000` (set in
`vite.config.js`) — that's where your Python backend will live.

While the backend is offline, the UI runs in **mock mode** (set in
`.env.example` → copy to `.env`) so every page is fully clickable.

## Build for production

```powershell
npm run build        # outputs to ./dist
npm run preview      # serve the build locally
```

## Stack

- **React 18** + **Vite 5**
- **TailwindCSS 3** (custom marine theme, glassmorphism, ocean gradient)
- **React Router 6** (sidebar nav)
- **Zustand** (report wizard state)
- **Framer Motion** (page transitions)
- **Recharts** (dashboard charts)
- **react-dropzone** (image uploads)
- **react-hot-toast** (notifications)
- **lucide-react** (icons)

## Layout

```
src/
├── App.jsx                 ← shell + routing
├── main.jsx                ← entry, toaster
├── index.css               ← Tailwind + design tokens
├── components/
│   ├── Logo.jsx            ← NautiCAI brand mark + wordmark
│   ├── Sidebar.jsx         ← left nav
│   ├── Topbar.jsx          ← search + profile
│   ├── Stepper.jsx         ← multi-step wizard
│   ├── StatCard.jsx        ← KPI tiles
│   ├── ImageDropzone.jsx   ← drag/drop with bubble FX
│   └── RegionTile.jsx      ← per-hull-region uploader
├── pages/
│   ├── Dashboard.jsx       ← hero + KPIs + charts + recent
│   ├── NewReport.jsx       ← 3-step wizard
│   ├── UploadImages.jsx    ← auto-routing image studio
│   ├── Analysis.jsx        ← fleet-wide insights
│   ├── Reports.jsx         ← searchable archive
│   └── Settings.jsx        ← API & branding
├── lib/
│   ├── constants.js        ← class names from the .pth/.h5 bundles
│   └── api.js              ← axios client (mock fallback)
└── store/reportStore.js    ← zustand state for wizard
```

## When you wire the backend

1. Copy `.env.example → .env` and set `VITE_USE_MOCK=false`.
2. Implement these endpoints (the UI already calls them):
   - `POST /api/analyze`     — multipart `image` + `region_hint?` → `{ region, stage, species, fouling_pct, severity }`
   - `POST /api/reports`     — JSON body `{ vessel, results }` → `{ id, pdfUrl, ... }`
   - `GET  /api/reports`     — list of reports
3. Done — everything lights up.
