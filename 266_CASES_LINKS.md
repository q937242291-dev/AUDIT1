# 266个Python案例：官方入口

[打开SWE-bench Pro官方数据集](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro)

[打开固定版本的Pro V1数据文件](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro/tree/2d52cb3df914a3fcf80c7f66738b3a88ae37fc50/data/v1)

| 项目 | 对应值 |
|---|---|
| 数据集 | ScaleAI/SWE-bench_Pro |
| 版本配置 | v1 |
| split | test |
| 语言筛选字段 | repo_language |
| 语言筛选值 | python |
| 主实验任务数 | 266个不同instance_id |
| 固定revision | 2d52cb3df914a3fcf80c7f66738b3a88ae37fc50 |
| 五方法比较 | 266×5=1330条任务/方法记录 |
| 原/精简工作流 | 266×2=532个计划运行 |

193个成功样本采用这266任务范围内的随机Luna成功子集；统计口径见[193_SUCCESS_SAMPLE.md](193_SUCCESS_SAMPLE.md)。

官方案例使用上面的V1配置和Python筛选条件。代码在`src/audit_framework/experiments/benchmarks.py`中固定上述口径，任务注册入口为`scripts/prepare_task_registration.py`。

```sh
python scripts/prepare_task_registration.py --links
```
