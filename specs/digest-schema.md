# digest schema（L3 结构化指纹）

`papers/<slug>/digest/digest.json` 的契约。校验器：`scripts/validate_digest.py`。
字段名、类型、必填性不得随意改动；新增字段须先改本文件并升 `schema_version`。

## 1. 顶层

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `schema_version` | string | 是 | 固定 `"1"` |
| `paper_id` | string | 是 | 与目录 slug 一致；`^[a-z0-9]+(-[a-z0-9]+)*$` |
| `title` | object | 是 | `{en, zh}`，均非空 |
| `venue` | string | 是 | 会议/期刊简称（小写），或 `arxiv` / `unknown` |
| `year` | integer | 是 | 1900–2100 |
| `doi` | string \| null | 是 | 可为 `null` |
| `arxiv` | string \| null | 是 | 可为 `null`，如 `"2501.01234"` |
| `problem` | object | 是 | `{zh, en}`：研究什么问题，各一句话 |
| `gap` | object | 是 | `{zh, en}`：现有工作缺什么 |
| `insight` | object | 是 | `{zh, en}`：核心洞见/关键假设 |
| `method` | array | 是 | ≥1 项，见 §2 |
| `assumptions` | array[string] | 是 | 可为空；每条一个前提 |
| `data` | array | 是 | 可为空，见 §2 |
| `baselines` | array[string] | 是 | 可为空 |
| `metrics` | array[string] | 是 | 可为空 |
| `headline_results` | array | 是 | ≥1 项，见 §2 |
| `limitations` | array | 是 | 可为空，见 §2 |
| `keywords` | array | 是 | ≥3 项，见 §2 |
| `relations` | object | 是 | 7 个键都必须存在，见 `relations.md` |

未知顶层字段：警告（多半是拼写错误）；缺字段或类型错误：失败。

## 2. 嵌套结构

```jsonc
"method": [
  { "name": "PathRadar", "role": "推断 RIB-in 候选路径", "detail": "复用现成算法，不改其内部" }
]
```

- `method[].name` 非空；`role` 非空（一句话作用）；`detail` 可为空字符串。

```jsonc
"data": [
  { "name": "Route Views", "scale": "2022-01 快照，1,604 个 VP", "source": "公开数据集" }
]
```

- 三个字段都必须是字符串；未知规模写 `"unknown"`，不要编造。

```jsonc
"headline_results": [
  { "claim": "整体可建模的 AS 路由行为比例", "value": "85.9%", "evidence": "§V-D / Fig. 6" }
]
```

- `value` 必须是论文中出现的数字/字符串（允许 `"81% / 79%"` 这类组合）；
  校验器会在 `paper.md` 中做字面匹配，匹配不到则失败。
- `evidence` 必填，规则见 §3。

```jsonc
"limitations": [
  { "text": "p2p 链路观测不完整，non-vf 召回率受影响", "evidence": "§V-C" }
]
```

- 可为空数组；非空时每项必须带 `evidence`。作者未明确写局限时，不要编造条目，
  在 `digest.zh.md` 的「局限」小节写“原文未明确说明”，数组留空。

```jsonc
"keywords": [
  { "zh": "偏好行为", "en": "affinity behavior" }
]
```

- ≥3 项；`zh`/`en` 均非空；`en` 用论文原词，便于检索与术语对齐。

## 3. evidence

- 单项格式：`§IV-B`、`§V-C`（IEEE）或 `§5.2`、`§3.1`（ACM）、`Fig. 6`、`Table VI`、`p. 7`。
- 多项用 `;` 分隔：`"§V-C; Fig. 6"`。
- 允许的特殊值：`"unverified"`（找不到依据，校验器给警告；`digest.zh.md` 必须标“存疑”）。
- 不允许空字符串、`"N/A"`、`"见上文"` 这类无法定位的值。
- 校验器会解析 `§` / `Fig.` / `Table` 并在 `paper.md` 中核对锚点是否存在（给 `--paper-md` 时）。

## 4. `digest.zh.md` 结构

```markdown
# <论文中文标题>

## L0 一句话
<≤60 字>

## L1 简洁总结
- <5–8 条，150–300 字>

## L2 详细总结
### 背景与问题
### 方法
### 实验设置
### 主要结果
### 局限与可拓展点
```

- 标题必须逐字匹配上面的一级/二级标题（校验器按标题名提取段落）。
- L0 ≤60 个汉字；L1 150–300 字；L2 1500–2500 字（超出给警告，结构缺失给失败）。
- 所有数字保留原文单位与符号；术语首次出现括注英文。

## 5. 版本

- `schema_version` 变更时，旧 `digest.json` 允许保留，但校验器只保证当前版本；
  批量迁移由后续脚本完成，不在会话里手改历史文件。
