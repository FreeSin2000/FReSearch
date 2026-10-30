# 关系（relations）

论文之间的关系分两层：**显式边**由 LLM 从正文抽取、必须带证据；**派生边**由
`scripts/build_graph.py` 按固定规则计算，可复算、不带主观判断。

## 1. 节点命名

| 形式 | 用途 | 例子 |
|---|---|---|
| `paper:<slug>` | 已入库论文 | `paper:infocom2025-affinity-model` |
| `ext:<author><year>:<short>` | 未入库的论文/方法引用 | `ext:gao2001:gr-model` |
| `dataset:<slug>` | 数据集/测量平台 | `dataset:routeviews` |

- `author`：第一作者姓氏，小写字母数字。
- `short`：短标题 kebab-case。
- 未入库也先记边；后续入库时手动把 `ext:` 替换为 `paper:`，不丢脉络。

## 2. 边的结构

```jsonc
{
  "target": "ext:gao2001:gr-model",
  "evidence": "§II",
  "confidence": "explicit",
  "note": "AM 在 GR 模型基础上放宽 valley-free 假设"
}
```

- `target` 必填，必须匹配上面的命名格式。
- `evidence` 必填，规则同 `digest-schema.md` §3；显式边不接受 `unverified`。
- `confidence`：`explicit`（LLM 抽取）或 `derived`（脚本计算）。
- `note` 可选，一句话说明关系内容。
- 派生边必须有 `matched_on` 数组，记录触发规则的字段。

## 3. 显式边类型

| 类型 | 方向 | 含义 | 建边条件 |
|---|---|---|---|
| `builds_on` | 本文 → 被继承工作 | 沿用/扩展其模型或框架 | 正文明确说 based on / extend / follow |
| `compares_to` | 本文 → baseline | 实验中直接对比 | 实验节出现该 baseline 且给出结果 |
| `uses_method` | 本文 → 方法/组件 | 使用现成算法/工具 | 方法节明确使用，非自研 |
| `uses_dataset` | 本文 → 数据集/平台 | 使用其数据 | 数据节明确列出 |
| `extends` | 本文 → 论文/系统 | 在其之上做新版本 | 有明确“扩展自”表述 |
| `contradicts` | 本文 → 论文/结论 | 结果或结论相反 | 有明确反驳/不一致陈述 |
| `applies_to` | 本文 → 问题域 | 把方法用于某场景 | 有明确应用场景陈述 |

规则：

- 只抽取**正文明确写出**的关系；靠常识推断的一律不建。
- 同一 `(from, type, target)` 只保留一条；重复出现时合并 `evidence`。
- `compares_to` 必须能在实验节找到对应表格/图，否则不建。

## 4. 派生边（脚本，不看 LLM）

| 类型 | 对称 | 规则 |
|---|---|---|
| `comparable_with` | 是 | 两篇共享 ≥2 个 `keywords.en`，且共享 ≥1 个 `data.name` 或 `metrics` |
| `same_method` | 是 | `method[].name` 归一化后（小写、去除非字母数字）有交集 |
| `same_dataset` | 是 | `data[].name` 归一化后（小写、去除非字母数字）有交集 |

- 对称边在 `graph.jsonl` 中按 `from < to` 字典序只写一条。
- `comparable_with` 的 `matched_on` 记录实际命中的字段，例如
  `["keyword:affinity behavior", "dataset:Route Views"]`；`evidence` 固定为 `"derived"`。
- 派生边不覆盖、不删除显式边；两者可并存。

## 5. 全局图

`index/graph.jsonl` 一行一条：

```jsonc
{"from":"paper:infocom2025-affinity-model","type":"compares_to","to":"ext:gao2001:gr-model",
 "evidence":"§V-C","confidence":"explicit","note":"与 GR 模型对比覆盖率"}
```

`index/compare.md` 由 `comparable_with` 的连通分量生成，每组列出共同关键词、
共享数据集/指标，以及各篇的问题、方法与第一条代表性结果。只陈述
`digest.json` 里已有的字段，不做结论推断。

## 6. 校验

- `validate_digest.py` 检查：target 格式、evidence 非空、显式边无 `unverified`、
  `confidence` 合法、`relations` 七个键齐全。
- `build_graph.py` 检查：派生边可复算；同一 `(from,type,to)` 无重复。
