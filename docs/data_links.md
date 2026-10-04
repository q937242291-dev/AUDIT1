# 官方数据链接及统计口径

| 用途 | 官方链接 | 选择条件 |
|---|---|---|
| 主实验Python266 | [SWE-bench Pro](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro) | v1、test、repo_language=python、266个不同instance_id |
| Pro V1固定版本 | [V1数据文件](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro/tree/2d52cb3df914a3fcf80c7f66738b3a88ae37fc50/data/v1) | revision=2d52cb3df914a3fcf80c7f66738b3a88ae37fc50 |
| 官方Pro评测代码 | [SWE-bench_Pro-os](https://github.com/scaleapi/SWE-bench_Pro-os) | V1评测适配器；代码pin见third_party/sources.lock.json |
| 补充实验Verified200 | [SWE-bench Verified](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified) | 官方test集500任务中的随机200任务 |
| 补充实验Lite300与切片 | [SWE-bench Lite](https://huggingface.co/datasets/SWE-bench/SWE-bench_Lite) | test集300任务；50/100/150/200/300切片跨模型使用相同任务名单 |

主实验采用固定V1版本。193成功样本是266任务范围内的随机Luna成功子集，Figure6使用两个工作流均成功的配对样本。

项目根目录的`266_CASES_LINKS.md`提供266案例入口、选择条件和任务网格；`193_SUCCESS_SAMPLE.md`汇总193样本的论文统计。
