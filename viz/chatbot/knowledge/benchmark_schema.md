# Benchmark output schema

This file describes columns and fields the code writes. It is not a scored result. No `benchmark_table.csv` or `metrics.json` is part of the git tree. When someone runs the scripts locally, `viz/chatbot/build_collection.py` can upload those files beside this note. Until then, do not invent values for these columns.

## `scripts/benchmark_skill.py`

The script writes `benchmark_table.csv` and `benchmark_summary.json` in the output directory (default `benchmark_results`).

`benchmark_table.csv` columns, from the script:

- `model`
- `track` (`baseline`, `climate`, or `nowcast`)
- `test_rmse`
- `skill_vs_constant` (1 minus test RMSE divided by the constant-prediction RMSE)
- `skill_ci_low`
- `skill_ci_high`
- `roc_auc`
- `pr_auc`
- `pr_auc_ci_low`
- `pr_auc_ci_high`
- `pr_auc_vs_no_skill`

The climate track is climate covariates, location, and season only. The nowcast track may use lagged krill in the same 5-degree sector. The script says nowcast skill does not carry to a 2040 projection.

`benchmark_summary.json` keys written by the script:

- `test_rows`
- `test_years`
- `n_test_years`
- `hotspot_prevalence`
- `constant_rmse`
- `feature_importance`

Confidence intervals come from a year-block bootstrap. The default bootstrap count in the script is 1000. This file does not report a bootstrap result.

## Training `metrics.json`

`fishcast/training/gp.py` writes `metrics.json` for a GP run. Fields that matter for a policy question, from that file:

- `model_name`
- `test_metrics`, which includes `rmse`, `mae`, `f1`, `threshold`, `auc`, `pr_auc`, `hotspot_prevalence`, and `rmse_skill_vs_constant` when a held-out test split exists
- `test_baseline`, which includes `constant_prediction`, `constant_rmse`, `constant_mae`, `no_skill_pr_auc`, and `no_skill_auc` (the code sets `no_skill_auc` to 0.5)
- `data`, which includes `preprocessing_version` for runs saved after preprocessing v2

`docs/CHANGES_preprocessing_v2.md` says runs trained before that change have no `preprocessing_version` in `metrics.json`. Those runs are not comparable with v2 runs.

Do not fill these fields from memory. If a number is not in an uploaded `metrics.json` or `benchmark_table.csv`, it is not a FishCast result.
