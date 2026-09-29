# Work2 leakage90 model-only probe：统计结果

90/90 个 PinAI/gpt-5.6-luna model-only cells 完成：6 tasks × O/C/P/L/D 五类 condition × 3 seeds；每类 condition 各 18 个，seed-01/02/03 各 30。运行时没有发送 future/location/diff payload、code、gold、tests、evaluator、human labels 或其他模型预测。

FileHit 是执行后的 post-hoc gold-file diagnostic，不是运行时输入，也不是修复正确率。O/C/P/L/D 对照只能作为描述性模型输出差异；由于真实 payload 未经独立 review 且没有重放 checkpoint，不能叫 leakage causal effect。

## 条件汇总

| condition | n | complete | nonempty | confidence | FileHit@1 | FileHit@3 | FileHit@5 | tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C_future_scrubbed | 18 | 18 | 1.0000 | 0.8294 | 0.8889 | 1.0000 | 1.0000 | 1206.2778 |
| D_diff_only | 18 | 18 | 0.0000 | 0.2778 | 0.0000 | 0.0000 | 0.0000 | 440.9444 |
| L_location_only | 18 | 18 | 0.0000 | 0.1111 | 0.0000 | 0.0000 | 0.0000 | 442.8889 |
| O_original_future_info | 18 | 18 | 0.9444 | 0.8217 | 0.8889 | 0.9444 | 0.9444 | 1200.3889 |
| P_equal_length_legal_history | 18 | 18 | 0.8889 | 0.7511 | 0.8333 | 0.8889 | 0.8889 | 1157.0000 |

## 相对 O 的描述性配对对照

| comparison | paired tasks | delta FileHit@1 | bootstrap 95% |
|---|---:|---:|---:|
| C_future_scrubbed - O_original_future_info | 6 | 0.0000 | [-0.1667, 0.1667] |
| D_diff_only - O_original_future_info | 6 | -0.8889 | [-1.0000, -0.7778] |
| L_location_only - O_original_future_info | 6 | -0.8889 | [-1.0000, -0.7778] |
| P_equal_length_legal_history - O_original_future_info | 6 | -0.0556 | [-0.3333, 0.1667] |

## 边界

- 该补充关闭的是 leakage90 的 provider-backed model-output coverage，不是正式 leakage gate。
- `leakage_dependence=NA`、runtime correctness=NA、formal promotion=0。
- 正式目标仍需要独立 payload review、同 checkpoint intervention、robust evaluator/patch/test、human review 及 formal inference。
