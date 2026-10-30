# 质量门（quality gates）

每一步产物都要过门；不过门就停下报告，不静默降级、不把警告当通过。

## G1 转换（paper2md）

- `md/paper.md` 存在，标题层级有序（`#` → `##` → `###`）。
- `paper.md` 中每个 `pics/…` 引用都存在。
- `Fig.` 标题数 == `figures.json` 条数 == `pics/` 文件数。
- `Table` 标题数与 PDF 中表格数一致（人工抽查 1–2 个）。
- 无 `Authorized licensed use` / `Downloaded on … from IEEE` 等页眉泄漏。
- 通过标准：全部满足；任一失败记录失败项与页码，不带着失败项进入总结。

## G2 结构（digest.json）

命令：`.venv/bin/python scripts/validate_digest.py <paper-dir> --strict`

- `schema_version`/`paper_id`/必填字段齐全，类型正确。
- `paper_id` 与目录 slug 一致。
- `keywords` ≥3；`method` ≥1；`headline_results` ≥1。
- `relations` 七个键齐全，target 命名合法，显式边带证据。
- 未知字段只警告。

## G3 证据（anti-hallucination）

- `headline_results[].value` 中的每个数字/百分号组合，能在 `paper.md` 中找到字面匹配。
- `evidence` 里的 `§5.2` / `§V-C` / `Fig. n` / `Table n` 能在 `paper.md`
  解析到对应标题/图/表。
- `limitations` 非空时每条都有 `evidence`；作者未写局限则留空，并在总结中说明。
- 找不到依据的内容：标 `unverified` + 总结中写“存疑”，不得编造。

## G4 分层总结（digest.zh.md）

- 标题齐全且逐字匹配：`## L0 一句话`、`## L1 简洁总结`、`## L2 详细总结`、
  `## L3 深度剖析`，以及 L2 的五个小节与 L3 的五个小节。
- L0 ≤60 汉字；L1 150–300 字；L2 1500–2500 字；L3 2500–5000 字
  （超出为警告，缺节为失败）。
- 中文为主；关键术语首次出现括注英文。
- L2 的每个结论段落至少带一个 `§`/`Fig.`/`Table` 锚点。
- L3 至少 8 个锚点，且只讨论问题与方法：不堆结果数字、不写优越性宣传。

## G5 关系（relations）

- 显式边只来自正文明确陈述；`unverified` 不允许。
- 同一 `(from, type, to)` 无重复。
- `comparable_with` 等派生边由 `build_graph.py` 生成，不手写、不改写。
- 未入库论文用 `ext:`、数据集用 `dataset:` 占位，不因未入库丢边。

## G6 索引与可复现

- `index/catalog.jsonl` 中 `paper_id` 唯一，路径存在。
- `index/graph.jsonl` 每行可被 `json.loads` 解析。
- 重跑同一篇：`status` 与 hash 一致时跳过；`--force` 的转换产物可复现
  （digest 由 LLM 生成，不要求逐字复现）。
- 冷启动：新会话按 `AGENTS.md` 的指引读完 `README.md`、`specs/` 与对应 skill，
  就能完成一次增量入库。

## 失败处理

1. 记录哪一门、哪一条、期望值与实际值。
2. 不修改 `paper.md` 去迁就总结（转换错误单独修转换）。
3. 不把失败项写进 `index/`；保留已有产物，标 `status: failed`。
4. 报告后停下，等用户决定是重跑、放宽规则还是人工修。
