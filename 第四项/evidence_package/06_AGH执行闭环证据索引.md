# Agnes Harness 执行闭环证据索引

- **证据文件**：`evidence_package\agh_sessions\AGH诊断包_会话1f119668_20261013.zip`
- **文件性质**：Agnes Harness（AGH）官方"诊断包"导出（内含 `index.html`、`trace.json`、`events.jsonl`、`system.json`、`logs\daemon.jsonl`、`logs\host.jsonl`、`logs\browser.json` 共 8 个条目）
- **会话标识**：`1f119668-ec74-4f92-a07e-402e84f03131`
- **导出时间**：2026-10-13T15:58:05Z（北京时间 2026-10-13 23:58）
- **会话时间跨度**：2026-10-13T02:46:21Z – 2026-10-13T15:55:56Z（北京时间 10:46 – 23:55）
- **文件大小**：1,032,965 字节
- **SHA256**：`C9109E79A84CE6DBDBDF8AD58C8E32186A30F1A1675B32784CD4D1F81FFAA7ED`
- **安全声明**：已用自动化脚本扫描（API key / token / Bearer / 密钥字段 / 本地用户名 / 邮箱模式），**未发现任何密钥或个人信息**；唯一命中的邮箱是 AiZynthFinder 项目作者的公开联系邮箱（出现在被引用的技术文本中）。

## 一、该诊断包记录了哪些可核验内容

| 闭环环节 | 诊断包中的对应记录 | 本会话实测 |
| --- | --- | --- |
| 任务规划 | `plan.items` 计划快照事件 | 8 次快照，开工条目与完成条目一一对应，无条目被静默丢弃 |
| 工具调用 | `tool/call` 事件（含调用名、参数、策略位与执行域字段） | 113 次调用，覆盖 shell / read / write / edit / ls / grep / find / web_fetch |
| 执行反馈 | `effect/intent` → `effect/settled`、`step/start` → `step/end`、`tool/result` | 每次调用均有配对结果事件 |
| 结果验证 | `verifier/signal`（含 verdict 与 reason） | 本会话 222 次校验信号 |
| 异常处理与治理 | `repair/decision`、`approval/asked`、`approval/decided`、`turn/end` 终态 | 会话内修复决策与终态均可追溯 |
| 用户指令 | `user/message` 事件 | 6 条指令原文（咖啡酸测试 → 界面标题与字体 → UI/UX 重构 → 字体回归 → 证据材料整理） |

## 二、如何查看

1. 解压后双击 `index.html`：离线自包含页面，含总览、工具调用、校验、日志等标签页；
2. 或直接用文本工具检索 `events.jsonl`（按行 JSON，可用 `Select-String` 检索 `verifier/signal`、`repair/decision` 等类型）；
3. `trace.json` 为执行轨迹快照，`logs\*.jsonl` 为守护进程、宿主与浏览器桥接日志。

## 三、与其他证据文件的关系

- `01_任务执行记录.md`、`02_工具与设备调用链.md`、`03_测试样例_正常_边界_失败.md`、`04_验证结果_学科匹配.md` 为**成文版**证据；
- 本诊断包提供**原始会话级证据**（不可事后编辑的事件流），可与上述四份文档逐条对应，构成"文档—原始记录"双重证据；
- 本会话中由 AGH 实际执行的三类测试（咖啡酸 PASS 10 条路线 / 甲醇 PASS 1 条 0 步 / `min_routes=0` BLOCKED；无效 SMILES 退出码 1 / 非法参数退出码 2）与证据包 `runs\` 目录中的产物一致。

## 四、尚缺会话（建议补充导出）

本诊断包仅覆盖 2026-10-13 的第三个会话（S3）。以下两个会话尚未导出，建议在 AGH 中各自导出一次后放入本目录，可进一步强化"异常处理"环节的证据链：

| 会话 | 北京时间 | 主要内容 | 状态 |
| --- | --- | --- | --- |
| S1 | 10-13 01:31–02:20 | 将不确定态进度条改造为基于真实 MCTS 计数的确定性百分比进度条；证明进度开关前后科学输出逐字节同构 | 待导出 |
| S2 | 10-13 08:32–09:38 | 中文路径 BLOCKED 根因定位与对照实验、三处启动入口修复、整包搬迁至纯英文路径、结果页自动打开修复 | 待导出 |

> 导出方法：在 AGH 会话界面选择"导出诊断包"，保存后按 `<会话简称>_<日期>.zip` 命名放入 `evidence_package\agh_sessions\`，并重新运行 `evidence_package\_rebuild_hash_index.py`（或按 `05_证据索引与哈希.md` 的"生成方式"重算）更新索引。
