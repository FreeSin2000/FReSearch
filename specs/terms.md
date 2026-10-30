# 术语表（中英对照 + 检索别名）

用途：统一 `digest.zh.md` 与 `digest.json` 的译法；给检索提供别名（不做 embedding，
靠别名表覆盖同义词）。新增术语时补一行，保持表格有序。

规则：

- 首次出现使用「中文（English）」，之后可只用中文或英文缩写。
- 专有名词（AS、BGP、XGBoost、PathRadar…）保留英文，不硬译。
- `别名` 用于 grep / 字段匹配，可写多个，用 `;` 分隔。

## 网络与路由

| 中文 | English | 别名 | 备注 |
|---|---|---|---|
| 自治系统 | Autonomous System (AS) | 自治域; ASes | 不译“自治系统号” |
| 边界网关协议 | Border Gateway Protocol (BGP) | BGP | |
| 路由信息库 | Routing Information Base (RIB) | RIB | |
| 入站路由表 | RIB-in | RIB in; 入站 RIB | 邻居通告的候选路径 |
| 观测点 | vantage point (VP) | VP; 观测点 | |
| 互联网交换中心 | Internet Exchange Point (IXP) | IXP; 交换中心 | |
| 提供商-客户关系 | provider-customer (p2c) | p2c; 提供商-客户 | 反向为 c2p |
| 对等关系 | peer-to-peer (p2p) | p2p; 对等互联 | |
| 无谷 | valley-free | valley free; 无谷原则 | 路径满足 p2c/p2p 约束 |
| 前缀 | prefix | 网段 | |
| AS 路径 | AS path | AS 级路径 | |
| 路由劫持 | route hijacking | 前缀劫持 | |
| 路由泄漏 | route leak | 路由泄露 | |
| 流量工程 | traffic engineering | TE | |
| 互联网路由注册库 | Internet Routing Registry (IRR) | IRR | |
| 转接 | transit | 中转 | |
| 客户锥 | customer cone | 客户锥体 | |
| 一级 AS | tier-1 AS | tier1; 顶级 AS | |
| 路由策略 | routing policy | 选路策略 | |
| 候选路径 | candidate path | 候选路由 | |
| 路径推断 | path inference | 路由推断 | |
| 目的端 | destination | 目的地 | |
| 策略聚合 | policy aggregation | 策略归并 | |

## 方法与实验

| 中文 | English | 别名 | 备注 |
|---|---|---|---|
| 分类器 | classifier | 分类模型 | |
| 精确率 | precision | 查准率 | |
| 召回率 | recall | 查全率 | |
| 基线 | baseline | 对照方法 | |
| 消融实验 | ablation study | 消融 | |
| 特征重要性 | feature importance | 特征权重 | |
| 真值 | ground truth | 标注真值 | |
| 阈值 | threshold | 门限 | |
| 启发式 | heuristic | 经验规则 | |
| 泛化 | generalization | 外推能力 | |
| 交叉验证 | cross-validation | CV | |
| 监督学习 | supervised learning | 有监督学习 | |
| 推理/推断 | inference | 推测 | 按语境选“推断” |
