# Data Visualization

This folder will hold the FishCast web app and the static figure pipeline.

Planned layout (settle in weeks 1-2):

- `viz/app/` front end (TypeScript, D3 geographic projections for the south-polar map)
- `viz/api/` data API (FastAPI) serving predictions, time series and benchmark tables
- `viz/figures/` scripts that regenerate every static figure with one command
- `viz/STYLE_GUIDE.md` projection, colour maps, fonts, units

Before choosing a map library, build a small prototype that draws the Antarctic coastline in a south-polar stereographic projection. Leaflet and MapLibre use Web Mercator and are poor fits for the Southern Ocean.

## Policy chatbot

`viz/api/` stays the data API for predictions, time series, and benchmark tables. The policy chatbot is a different service (its own process, API keys, and document collection), so it lives in `viz/chatbot/` and can be called from `viz/app/` later. See `viz/chatbot/README.md`.
