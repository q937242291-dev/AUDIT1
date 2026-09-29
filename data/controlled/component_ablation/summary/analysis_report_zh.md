# Causal60 描述性统计附录

来源为最终 canonical ledger：540 行、9 个变体、每变体 60 行；completed=537，error=3。

`component_ablation_metric_summary.csv` 同时给出 completed-row conditional mean 与 60-case coverage-normalized mean；错误行不被当作成功，也不进行插补。FileHit@1 提供 completed 分母 Wilson 95% 区间。

`component_ablation_paired_bootstrap.csv` 给出各变体相对 full_v5 的 FileHit/MRR 配对差值、5000 次 bootstrap 95% 区间，以及 FileHit@1 的 McNemar exact p。它们是 post-hoc descriptive statistics，不是 formal causal correctness 或 benchmark outcome。
