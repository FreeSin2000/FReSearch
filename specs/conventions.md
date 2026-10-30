# 约定（conventions）

本文件定义所有 skill 与脚本共享的命名、布局、状态和语言规则。与 `digest-schema.md`、
`relations.md`、`quality-gates.md` 冲突时，以本文件为准。

## 1. 处理范围

- 输入：有文本层的研究论文 PDF，v1 只验证 IEEE/ACM 双栏；单栏路径未验证，`--single-column` 仅为实验开关。
- 不支持：书籍章节、LaTeX 源码、扫描件（无文本层）、OCR、非论文 PDF。
- 遇到不支持的类型：停止并说明原因，不生成半成品。

## 2. slug

```
<venue><year>-<short-title>
```

- 全小写 kebab-case，只含 `[a-z0-9-]`。
- `venue`：会议/期刊简称，见下表；不确定时用 `arxiv` 或 `unknown`。
- `year`：4 位出版年。
- `short-title`：标题中 2–3 个实词，去掉停用词与副标题。
- 重名：追加 `-2`、`-3`。
- 例：标题 *Affinity-Model: Improving AS Routing Models…* → `infocom2025-affinity-model`；
  *HopLab: A Topology…* → `sigcomm2024-hoplab`。

| venue 字段 | 对应 |
|---|---|
| `infocom` / `sigcomm` / `nsdi` / `imc` / `conext` / `hotnets` | 对应会议 |
| `ton` / `jsac` / `tcc` | 对应期刊 |
| `arxiv` | arXiv preprint |
| `unknown` | 无法识别 |

> 识别依据：PDF 首页页眉/页脚、版权行、DOI、arXiv 编号。识别不到就回退，不猜。

## 3. 每篇论文的目录

```
papers/<slug>/
├── meta.json               # 元数据 + 状态 + hash（唯一在论文根下的文件）
├── source/paper.pdf        # 原始 PDF，只读
├── md/
│   ├── paper.md            # 英文 Markdown，转换结果
│   ├── pics/figN.png       # 图
│   └── figures.json        # 图清单（label/caption/page/clip/file）
├── digest/
│   ├── digest.zh.md        # L0–L3，中文
│   └── digest.json         # L4 结构化指纹 + relations
└── zh/paper.zh.md          # 可选：中文全文翻译
```

文件名固定，不随论文变化；同一 slug 下不出现第二份 `paper.md`。

## 4. 语言策略

| 产物 | 语言 | 规则 |
|---|---|---|
| `paper.md` | 英文原文 | 不改写、不翻译；只做 PDF→Markdown 的结构还原 |
| `digest.zh.md` | 简体中文 | 关键术语首次出现括注英文；节号/图号/表号保留原文 |
| `digest.json` | 中英双语 | 文本字段中文，`en` 字段与 `keywords` 保留英文原词 |
| `zh/paper.zh.md` | 简体中文 | 仅在 `--translate` 时生成，可后补 |

专有名词（AS、BGP、XGBoost、PathRadar 等）保留英文，不强行翻译。

## 5. 证据锚点

所有事实性陈述必须带锚点，格式统一：

```
§IV-B          # 节-子节（IEEE）
§5.2           # 节-子节（ACM）
Fig. 5         # 图
Table VI       # 表
p. 7           # 页码（PDF 物理页）
```

- `headline_results[].evidence` 与 `limitations[].evidence` **必填**。
- 一个结论跨多处时用 `;` 或 `/` 分隔，如 `"§V-C; Fig. 6"`。
- 无法定位则写 `"unverified"`，并在总结中标注「存疑」，不得编造。

## 6. 状态机（meta.json）

```jsonc
{
  "slug": "infocom2025-affinity-model",
  "status": "converted",          // new | converted | digested | done | failed
  "source_sha256": "...",
  "paper_md_sha256": "...",       // 未转换时 null
  "digest_sha256": "...",         // 未总结时 null
  "steps": {
    "converted_at": "2025-01-01T00:00:00Z",
    "digested_at": null,
    "indexed_at": null
  },
  "error": null
}
```

状态迁移：

```
new → converted → digested → done
  ↘ failed（任一步出错，保留已有产物）
```

- 每步开始前校验前置 hash：`source_sha256` 变则整篇重跑；`paper_md_sha256` 变则重跑
  digest 与 index；`digest_sha256` 变则重跑 index。
- 前置产物的 hash 与当前输入不匹配时标为 `stale`，由对应步骤重建，不静默沿用。
- `--force`：忽略状态与 hash，重新转换 Markdown；若已有 digest 则标记为 stale。
  新产物先写临时文件再原子替换，失败不丢旧产物。

## 7. 幂等与并发

- 同一 slug 重复处理：默认跳过（`status: done` 且 hash 一致）；`--force` 才重跑。
- 写入统一用「临时文件 + `os.replace`」，避免中断留下半个 JSON。
- 单篇处理串行；`index/` 由单进程重建，不做并发写。

## 8. 索引

`index/catalog.jsonl` 一行一篇，至少包含：

```jsonc
{"paper_id":"...","slug":"...","title_zh":"...","title_en":"...","venue":"...","year":2025,
 "keywords":["..."],"problem_zh":"...","method_names":["..."],"datasets":["..."],
 "metrics":["..."],"headline":"...","paths":{"md":"papers/.../md/paper.md"}}
```

`index/graph.jsonl` 一行一条边：

```jsonc
{"from":"paper:infocom2025-affinity-model","type":"compares_to","to":"ext:gao2001:gr-model",
 "evidence":"§V-C","confidence":"explicit"}
```

- `from` / `to`：`paper:<slug>`、`ext:<第一作者><年份>:<短标题>` 或 `dataset:<slug>`。
- `confidence`：`explicit`（LLM 抽取，必须有证据）或 `derived`（脚本按规则计算）。

## 9. git 边界

提交：`skills/`、`specs/`、`scripts/`、`tests/`、`requirements.txt`、`README.md`、
`AGENTS.md`、`.gitignore`、`.pi/settings.json`、各处 `.gitkeep`。

忽略：`.venv/`、`papers/**/*.pdf`、`papers/*/{source,md,digest,zh}/*`（保留 `.gitkeep`）、
`papers/*/meta.json`、`index/*`（保留 `.gitkeep`）。

## 10. 可移植性

- 不写死绝对路径；脚本以「仓库根」为基准定位 `papers/`、`index/`、`specs/`。
- 环境只依赖 `requirements.txt` 中 pin 的版本；不依赖全局 pip 包。
- 不修改 `~/.pi/`、不写全局 settings；`.pi/settings.json` 只做仓库内路径映射。
