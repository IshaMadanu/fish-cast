# Data Visualization

This folder holds the FishCast map prototype and static figure pipeline.

## Local map and historical-data chat

The prototype at `prototype/polar_map.html` includes a chat panel that answers questions
from summaries of the historical haul observations in `data/krillcast_merged.csv`. It does
not use or claim to show model predictions. The API key stays in the local Python server;
it is never sent to the browser.

From the repository root, stop any existing `python -m http.server` process with Ctrl+C,
set `XAI_API_KEY` in the same terminal, then start:

```bash
python scripts/chat_server.py
```

Open <http://127.0.0.1:8000/viz/prototype/polar_map.html>. The chat reads
`data/krillcast_merged.csv`, which is also the historical haul data drawn on the map. To use
a different haul CSV, set `FISHCAST_HAUL_DATA` to its path before starting the server. The
CSV must contain `DATE` and `NUMBER_OF_KRILL_UNDER_1M2`; annual summaries include available
environment columns. Set `FISHCAST_GROK_MODEL` to override the default `grok-3-mini` model
name if needed. Answers are based on data summaries, so questions needing details outside
those summaries may not be answerable.

Planned layout (settle in weeks 1-2):

- `viz/app/` front end (TypeScript, D3 geographic projections for the south-polar map)
- `viz/api/` data API (FastAPI) serving predictions, time series and benchmark tables
- `viz/figures/` scripts that regenerate every static figure with one command
- `viz/STYLE_GUIDE.md` projection, colour maps, fonts, units

Before choosing a map library, build a small prototype that draws the Antarctic coastline in a south-polar stereographic projection. Leaflet and MapLibre use Web Mercator and are poor fits for the Southern Ocean.
