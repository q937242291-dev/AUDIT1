# M3-CMR GPT Model-Swap Validation Report

Status: `PASS`

Scope: non paper-facing model-swap robustness evidence for file localization only. The agent method stayed fixed; only the path-audit LLM was changed.

Provider facts:

- Official OpenAI endpoint: prior probe returned `401 invalid_api_key`, so it was not used for accepted GPT evaluation.
- Huiyan OpenAI-compatible gateway: usable for GPT-compatible evaluation through `https://api.huiyan-ai.cn/v1`.
- `gpt-5-mini`: probe reached the gateway, but path-audit returned empty `raw_text`; it is not counted as a passed path-audit model.
- Counted GPT-compatible models: `gpt-4.1-mini`, `gpt-4.1`, and `gpt-5.1`.

## Passed GPT-Compatible Runs

| Model | CommonN | Status | RCR@1 | RCR@3 | Hit@1 | Hit@3 | FalseCredit | Avg tokens | Path ok |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| gpt-4.1-mini | Common50 | passed | 0.76 | 0.92 | 0.76 | 0.92 | 0.24 | 3161.78 | 26 |
| gpt-4.1-mini | Common100 | passed | 0.74 | 0.89 | 0.74 | 0.89 | 0.26 | 1866.89 | 51 |
| gpt-4.1-mini | Common150 | passed | 0.773333 | 0.9 | 0.773333 | 0.9 | 0.226667 | 1432.2 | 74 |
| gpt-4.1-mini | Common200 | passed | 0.785 | 0.91 | 0.785 | 0.91 | 0.215 | 1257.525 | 103 |
| gpt-4.1-mini | Common300 | passed | 0.833333 | 0.943333 | 0.833333 | 0.943333 | 0.166667 | 922.206667 | 128 |
| gpt-4.1 | Common50 | passed | 0.76 | 0.92 | 0.76 | 0.92 | 0.24 | 3157.94 | 26 |
| gpt-4.1 | Common100 | passed | 0.74 | 0.89 | 0.74 | 0.89 | 0.26 | 1861.95 | 51 |
| gpt-4.1 | Common150 | passed | 0.773333 | 0.9 | 0.773333 | 0.9 | 0.226667 | 1428.233333 | 74 |
| gpt-4.1 | Common200 | passed | 0.795 | 0.91 | 0.795 | 0.91 | 0.205 | 1256.225 | 103 |
| gpt-4.1 | Common300 | passed | 0.833333 | 0.943333 | 0.833333 | 0.943333 | 0.166667 | 921.553333 | 128 |
| gpt-5.1 | Common50 | passed | 0.76 | 0.92 | 0.76 | 0.92 | 0.24 | 3164.9 | 26 |
| gpt-5.1 | Common100 | passed | 0.74 | 0.89 | 0.74 | 0.89 | 0.26 | 1870.2 | 51 |
| gpt-5.1 | Common150 | passed | 0.793333 | 0.9 | 0.793333 | 0.9 | 0.206667 | 1435.546667 | 74 |
| gpt-5.1 | Common200 | passed | 0.795 | 0.91 | 0.795 | 0.91 | 0.205 | 1264.165 | 103 |
| gpt-5.1 | Common300 | passed | 0.833333 | 0.943333 | 0.833333 | 0.943333 | 0.166667 | 927.59 | 128 |

## Main Takeaway

With the M3-CMR agent method unchanged, GPT-compatible `gpt-4.1-mini`, `gpt-4.1`, and `gpt-5.1` all pass Common50/100/150/200/300. On Common200, `gpt-4.1` reaches RCR@1/Hit@1 0.795, Top1MissRate 0.205, and avg tokens 1256.225; `gpt-5.1` reaches the same accuracy/miss rate at avg tokens 1264.165. The best completed official 2025-2026 baseline in the local Common200 table has RCR@1/Hit@1 0.745. The legacy field is not an independent unsupported-hit metric.

## Claim Boundaries

- This is a localization-only claim, not repair performance or human trajectory faithfulness.
- SWE-agent and other artifact-only `tokens=0` rows mean no released usage log; they do not count as token-efficiency wins.
- The paper-facing result still uses exactly three M3 tables.
- The pure 2026 official baseline gate remains `INSUFFICIENT_EVIDENCE`; candidate-only 2026 methods are not mixed into the main result.
- API keys are accepted only through process environment variables and are not written into this report.
