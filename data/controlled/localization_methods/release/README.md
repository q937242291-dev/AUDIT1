# PinAI Luna Pro-Python260 model-only release

This package contains real PinAI provider-returned records from `pinai_pro_python260_full_20260909_v1` using only `gpt-5.6-luna`.

- Expected cases: 260
- Valid provider-backed common cases: 260
- Valid method rows: 1300 / 1300
- Provider usage events: 1734
- Annotation disclosure label: `人工+大模型辅助标注（模拟人工）`
- Real human annotation: 0; no human agreement is claimed.

The public package retains the normalized case-level results, method summaries,
repository summaries, and valid completed rows. Original provider payloads and
retry logs are not redistributed here; their acquisition boundary is recorded
in `release_metadata.json`. The complete method-level row/event logs are
organized separately under `data/logs/localization_methods/`.

The tables are descriptive model-only data with post-hoc gold scoring. They are not formal causal, robustness, semantic-human, or survival results.
