# 修改日志：AUDIT 1.1.2 完整替换包

依据你提供的最新版 fse2027-paper629.pdf，主实验统一为266个 SWE-bench Pro Python任务；193个是该范围内 Luna 成功任务的随机样本，Figure6还要求原/精简两条工作流均成功。数据依照你的要求只给链接。

## 具体修改位置

| 文件 | 修改内容 |
|---|---|
| src/audit_framework/experiments/cohorts.py | 主实验260→266；新增原/精简266任务注册；要求官方身份目录、repo/base_commit和不同任务数；禁止用重复种子补任务 |
| src/audit_framework/experiments/benchmarks.py（新增） | 固定Pro V1版本及Python筛选；身份只保留instance_id/repo/base_commit；Verified/Lite单独核验，导入和规划不下载数据 |
| scripts/prepare_task_registration.py（新增） | 外部实际任务身份注册；提供官方链接；只有明确--fetch才下载，不编造任务名单 |
| src/audit_framework/experiments/catalog.py；configs/experiments/registry.json | 五方法266×5=1330；增加原/精简266×2=532；补全Verified200和Lite50/100/150/200/300的模型切片 |
| src/audit_framework/experiments/workflows.py（新增） | 校验实际原/精简工作流：固定Luna角色、max推理、SWE-agent、prompt/toolset/评测；明确实际删减模块、上下文和内存配置 |
| src/audit_framework/experiments/planning.py；scripts/run_experiments.py | 新增--task-list-root、--workflow-config；注册缺失时明确报错；工作流配置参与计划hash |
| src/audit_framework/experiments/runner.py | 原/精简必须绑定真实SWE-agent协议的适配器；固定模型预检查；组件日志保留共享模块输出hash |
| src/audit_framework/experiments/methods.py；adapters.py | Trust-first检查原始模型Top-1；失败则abstain并保留候选，不能换成另一候选当作原Top-1通过 |
| src/audit_framework/experiments/projections.py | 修正identifier替换的正则词边界，避免误改嵌套于更长标识符中的名字 |
| scripts/reproduce_controlled_experiments.py | 表3渐进上下文编号修正；表4均值/分母/增益损失核验；表5固定条件和planned/completed核验；表6五方法各266任务；表7要求18不同任务；表8要求40不同任务并核验Gain/Loss；表9要求30不同任务；所有差异输出MISMATCH |
| scripts/reproduce_success_trajectories.py | 旧Table3→新版Table1；mean_units包含Other tool step；共现与顺序分开；加入144项论文数字对照与MATCH/MISMATCH报告 |
| scripts/reproduce_repair_endpoints.py | 诊断表改为Table2；Consistency标签对应Contradiction；真实same-run/cross-run声明必须与run IDs一致；加入激活、移除增益/损失和四个修复端点对照 |
| scripts/reproduce_model_swap.py | 真实Verified200与Lite300身份核验，不能把Common200直接改名；保留三模型18种组合；Lite5切片绘图；表10值和固定上游协议核验，缺失成本不补零 |
| scripts/reproduce_redundancy.py（新增） | Figure6完整分析：266任务配对结果、193随机成功样本、真实种子/IDs和步骤对齐；两工作流都须成功；20648步/7348重叠标签及五类比例核验，近似计数按论文显示精度核验 |
| reproduce.py | 五个分析阶段统一入口；外部数据参数；表1/2/3重新映射；缺失输入或任一差异不能报告完整成功；部分执行标为PARTIAL_MATCH |
| scripts/generate_figures.py | 输出当前Figures3–6；模型/重放/修复移到Figure5；Figure6改为193成功配对的行为冗余；只允许已匹配的实测结果绘图 |
| scripts/verify_artifact.py | 新整包文件清单及SHA-256核验；校验包内无实测数据；支持覆盖安装时保留外部data/results等目录 |
| tests/test_experiments.py；tests/test_paper_alignment.py（新增） | 测试不再依赖随包真实数据；新增266/193、抽样种子、配对成功、重复任务、重叠分类和MISMATCH回归检查；合并原bootstrap/repair自检，总共132项 |
| README.md；REPLACE_INSTRUCTIONS.md；docs/*；configs/experiments/task_lists/README.md | 完整替换步骤、数据链接、各表分母、外部日志格式、工作流限制及当前表图映射 |
| pyproject.toml；src/audit_framework/__init__.py；CITATION.cff | 版本统一为1.1.2 |
| MODIFICATION_LOG.json；artifact_manifest.json；sha256sums.txt | 文件级修改记录、前后hash与完整交付包校验清单 |

## 已验证

132项离线代码/契约测试通过；第三方21个文件和4份许可证按pin验证；原包Table1数据复算144项全部匹配。完整ZIP解压后的代码、入口和文件hash另行验证。

## 案例链接与成功样本统计

主实验266案例通过`266_CASES_LINKS.md`列出官方入口、V1版本及Python筛选条件。`193_SUCCESS_SAMPLE.md`列出193成功配对的论文统计、五类冗余计数及比例；两项均已加入完整包。

本次更新统一README、替换说明、数据说明和修改日志的链接表述，并更新机器可读清单及文件hash。文件级差异见`MODIFICATION_LOG.json`。
