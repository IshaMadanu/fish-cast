# Limitations of FishCast for policy use

This note is the collection's statement of what the repository itself currently supports. It does not add results that are not already written down in the repository. No scored `benchmark_table.csv` or training `metrics.json` is committed in git, so this file does not quote a leaderboard and does not invent scores.

Where this file disagrees with `docs/FishCastMethodology.md`, use this file. That methodology document is marked Draft and describes intended behaviour, not a measured forecast skill.

## Climate-only models show no skill yet

From the repository README, section "Key results so far":

> Only models that use recent krill catches currently beat a constant prediction on the test years (about 5% lower error). No climate-only model shows skill yet. All runs from before 27 September 2026 are invalid; see `docs/CHANGES_preprocessing_v2.md`.

A climate-only model uses climate, place, and season. It does not use recent krill catches. `scripts/benchmark_skill.py` defines that track as the one a climate-driven projection, including a spillover map, depends on. The same script says skill on the nowcast track, which may use krill observed earlier in the same 5-degree sector, does not carry to a 2040 projection, where no krill has been observed.

Do not claim predictive skill for climate-only future projections. The README says no climate-only model shows skill yet. The "about 5% lower error" figure is the README's description of models that use recent catches, on the test years. It is not a climate-only skill score.

## The climate-only GP ranks hotspots backwards

From `docs/week1_issues.md`, issue 5:

> Why does the climate-only GP rank hotspots backwards? Its test ROC-AUC is about 0.35.

The issue asks for a note in `analysis/experiments/` with a likely explanation or ruled-out causes. That note is not in the repository. Until it exists, and until a benchmark run after the data rebuild says otherwise, do not use climate-only GP hotspot maps as evidence for an MPA decision.

In this project a hotspot is a haul whose krill density is at or above the historical 90th percentile for its sector. After the 27 September 2026 change, a hotspot must also contain krill. `docs/CHANGES_preprocessing_v2.md` records that the old rule labelled empty hauls as hotspots because many sectors had a 90th percentile of 0.

`fishcast/training/gp.py` states that PR-AUC is the more honest ranking score when hotspots are uncommon, and that the no-skill PR-AUC equals the hotspot prevalence. This file does not quote a measured PR-AUC.

## Longitude bug: fixed in code, the merged file has not been rebuilt

From `docs/CHANGES_preprocessing_v2.md` (found 3 October 2026), `data/README.md`, and `scripts/data/README.md`:

The current `krillcast_merged.csv` was built by a notebook that matched KRILLBASE longitudes (from -180 to 180) to a climate grid stored as 0 to 360 without converting them. Every haul west of Greenwich (77% of hauls) received the environmental values of the 0.5 degree E grid column at its latitude and date. Checked directly: among hauls on the same date and latitude row but at three or more different longitudes, 474 of 610 groups west of Greenwich have identical SST, against 0 of 178 east of Greenwich. The change note says this likely explains much of the missing climate-only skill.

`scripts/data/build_dataset.py` fixes the longitude match. The shared `krillcast_merged.csv` has not been rebuilt with that script. Rebuild the file and rerun the benchmark before drawing conclusions about climate predictors.

`data/README.md` publishes a SHA-256 for `krillcast_merged.csv` (v1). That checksum is for the file with this bug.

## Other caveats stated in the repository

- Runs from before 27 September 2026 are not comparable with preprocessing v2. `docs/CHANGES_preprocessing_v2.md` says any run from before that change is not comparable, and that all previous lag-model results are invalid, including `FishCast_LatentStateGP_v1`.
- The v2 chronological split, from that same note, is train 1926–1998, validation 1998–2004, and test 2004–2016: 8,766 / 1,896 / 1,882 hauls. Validation still picks the checkpoint and the hotspot threshold. The test years are scored once.
- The sequence and ConvLSTM loaders received the sea-ice fix only. They still fit scaling and hotspot cut-offs on all years and have no test split. The change note leaves that as a follow-up for the Analysis team.
- Skill against a constant prediction is defined in code as one minus the model's RMSE divided by the RMSE of predicting the training-set average (`fishcast/training/gp.py` and `scripts/benchmark_skill.py`). A positive value means lower error than that constant. Benchmark confidence intervals are year-block bootstraps. This collection does not include a filled benchmark table.
- `viz/figures/leaderboard.py` groups models into "climate-only" (the track it describes as usable for 2040) and "nowcast" (uses recent krill catches). That grouping is a chart label, not a new skill result.

## What this collection does not contain

- Official CCAMLR advice. Decision-support tool based on FishCast model outputs and cited literature. Not official advice.
- CCAMLR meeting reports or scientific papers. The team adds those under `viz/chatbot/knowledge/external/` when they have the right to upload them. This repository does not scrape or bundle copyrighted papers.
- A rebuilt haul file or a new benchmark after the longitude fix.

## Terms, as this repository uses them

- Nowcast: a model that may use krill observed earlier in the same 5-degree sector. Skill here does not carry to a future year with no krill observations (`scripts/benchmark_skill.py`).
- Climate-driven forecast: climate covariates, location, and season only. This is the skill a climate projection depends on. No model on this track shows skill yet (README).
- Hotspot: a binary label for a dense haul, at or above the historical 90th percentile in its sector, and, after preprocessing v2, a haul that contains krill (`docs/FishCastMethodology.md`, `docs/CHANGES_preprocessing_v2.md`).
- Spillover: the methodology draft's name for krill populations moving beyond current marine protected area boundaries. The repository does not report a measured spillover rate.
- Skill score: improvement in density error relative to always predicting the training average. See `scripts/benchmark_skill.py`. Do not treat a confidence interval that includes zero as demonstrated skill.
