# 完整替换包：AUDIT 1.1.2

ZIP根目录就是项目根目录。包内包含完整代码、配置、测试、修改日志及案例链接。

1. 备份现有项目，将压缩包全部文件解压到原项目根目录，覆盖同名文件。
2. 在项目根目录运行 `python reproduce.py --tests-only` 和 `python scripts/verify_artifact.py`。
3. 266案例入口见 `266_CASES_LINKS.md`；193成功样本的论文统计见 `193_SUCCESS_SAMPLE.md`。
4. 修改位置见 `CHANGELOG.md` 和 `MODIFICATION_LOG.json`；运行命令见 `README.md`。

主实验使用266个不同的SWE-bench Pro V1 Python任务。193个是其中随机抽取的Luna成功样本，Figure6采用原/精简两个工作流均成功的配对样本。

数据按你的要求以链接形式提供。覆盖安装时保留现有data/、results/、paper/目录；运行入口使用--data-root、--pro-catalog及--task-list-root指定数据位置。
