# M3-CMR GPT-4.1 Model-Swap Validation Report

Status: `PASS`

Scope: non paper-facing robustness evidence for file localization only. The M3-CMR method, scoring rules, official baselines, and CommonN case sets were kept fixed; only the path-audit model was changed.

Provider path: Huiyan OpenAI-compatible gateway, `https://api.huiyan-ai.cn/v1`. API keys were supplied only through process environment variables and are not written into artifacts or reports.

Run label: `m3_model_swap_openai_gpt41_huiyan_mt420_c3_20260515`

| CommonN | Status | RCR@1 | RCR@3 | Hit@1 | Hit@3 | FalseCredit | Avg tokens | Accepted avg | Lowest live avg | Path ok |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Common50 | passed | 0.76 | 0.92 | 0.76 | 0.92 | 0.24 | 3157.94 | 3336.54 | 4097.8 | 26 |
| Common100 | passed | 0.74 | 0.89 | 0.74 | 0.89 | 0.26 | 1861.95 | 2035.21 | 4186.35 | 51 |
| Common150 | passed | 0.773333 | 0.9 | 0.773333 | 0.9 | 0.226667 | 1428.233333 | 1596.173333 | 4260.92 | 74 |
| Common200 | passed | 0.795 | 0.91 | 0.795 | 0.91 | 0.205 | 1256.225 | 1428.65 | 4468.58 | 103 |
| Common300 | passed | 0.833333 | 0.943333 | 0.833333 | 0.943333 | 0.166667 | 921.553333 | 1061.353333 | 4754.217 | 128 |

## Interpretation

GPT-4.1 passes the same staged model-swap gate. On Common200, RCR@1/Hit@1 rises from 0.785 to 0.795, the complementary Top1MissRate changes from 0.215 to 0.205, and avg tokens fall from 1428.65 to 1256.225.

The Common200 comparison against completed official 2025-2026 baselines remains favorable: the best official baseline has RCR@1/Hit@1 0.745, and the lowest live-token baseline average is 4468.58. Artifact-only `tokens=0` rows still mean no released usage log and are not token-efficiency wins. Top1MissRate is not reported as independent false-credit evidence.

## Notes

- The model channel was probed before Common50 and passed.
- All stages reused cached no-path artifacts to avoid redundant deterministic work; live calls were used for the path-audit branch.
- This report does not alter the three paper-facing M3 tables.
- The 2026-only official baseline gate remains `INSUFFICIENT_EVIDENCE`; this run does not claim ten pure-2026 complete official localization baselines.
