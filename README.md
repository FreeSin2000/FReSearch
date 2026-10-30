# FReSearch

把论文 PDF 变成可检索、可对比的研究库：原始 PDF → 英文 Markdown → 分层中文总结
→ 结构化指纹 + 关系图 → 可检索的目录索引。

> **构建中**：当前完成 P7（全流程复测）。只剩 P8（冷启动与最终提交），
> 计划表见上层目录的 [`构建FReSearch.md`](../构建FReSearch.md)。

## 特点

- **只依赖 LLM + 本地 Python**：不使用 OCR、embedding、向量库或任何在线服务。
- **分层表示**：人读的 L0 一句话 / L1 简洁 / L2 详细 / L3 深度剖析（只写问题与方法）+ 机器读的结构化指纹（L4）。
- **关系分层**：显式引用边（builds_on / compares_to / uses_dataset…）+ 规则派生的可比性边。
- **可回查**：关键数字与结论都标 `§` / `Fig.` / `Table` / 页码，存疑时回 PDF 佐证。
- **可移植**：不写死绝对路径，不修改全局配置；换机器只需重装环境并重新放入 PDF。

## 快速开始

```bash
# 1. 环境（幂等；已有 .venv 时只校验不重装）
bash scripts/bootstrap_env.sh

# 2. 放入论文
cp ~/Downloads/paper.pdf papers/_inbox/

# 3. 打开新会话，让它处理 inbox
pi
#   > 处理 papers/_inbox 里的论文
#   或显式调用：/skill:paper-ingest

# 也可直接跑脚本（幂等、可续跑）
.venv/bin/python scripts/ingest.py papers/_inbox/BEAM.pdf \
    --venue usenixsecurity --year 2024 --slug usenixsecurity2024-beam

# 可选：为已入库论文准备中文翻译分块（LLM 逐块翻译后 assemble）
.venv/bin/python scripts/ingest.py papers/_inbox/BEAM.pdf --translate
.venv/bin/python scripts/translate.py assemble papers/usenixsecurity2024-beam --strict

# 只重建目录
.venv/bin/python scripts/ingest.py --reindex
```

产物：

```
papers/<slug>/
├── meta.json               # 元数据 + 处理状态 + 各步 hash
├── source/paper.pdf        # 原始文件（不进 git）
├── md/paper.md             # 英文 Markdown + pics/ + figures.json
├── digest/digest.zh.md     # L0/L1/L2/L3 中文总结（L3 只写问题与方法）
├── digest/digest.json      # L4 结构化指纹 + relations
└── zh/paper.zh.md          # 可选：--translate 生成的中文全文
index/
├── catalog.jsonl           # 一行一篇，机器读
├── catalog.md              # 人读总表
├── graph.jsonl             # 关系边（显式 + 派生）
└── compare.md              # 按可比性分组的对比表
```

## 目录结构

```
FReSearch/
├── AGENTS.md               # 会话规范（先读这个）
├── skills/                 # Agent Skills：paper-ingest / paper2md / paper-digest
├── specs/                  # 命名、schema、关系、质量门、术语表
├── papers/                 # 每篇论文一个目录，按阶段分子目录
├── index/                  # 派生索引（gitignored，可重建）
├── scripts/                # 环境自检、ingest、校验、翻译分块、索引与关系图
├── tests/                  # 单元测试 + 手写校验样例（提交）
└── requirements.txt        # 精确 pin 的依赖
```

## 设计要点

1. **转换不产出中文**：`paper.md` 保持英文原样，便于核对术语与数字；中文只出现在总结层。
2. **总结默认中文**：关键术语首次出现括注英文，如「偏好行为（affinity behavior）」。
   L3 深度剖析只写问题与方法，弱化结果对比和优越性宣传。
3. **无证据不入库**：`headline_results` 与 `limitations` 必须带 `evidence` 字段。
4. **关系分两类**：LLM 只抽显式边；`comparable_with` 等派生边由脚本按固定规则计算，可复算。
5. **断点续跑**：`meta.json` 记录状态与各步 sha256，只重跑失效步骤；`--force` 全量重跑。

## 限制

- v1 只处理有文本层的**双栏**论文 PDF；单栏路径未验证，后续版本再支持。
- 不支持书籍章节、LaTeX 源码、扫描件；不做 OCR。
- 公式按 PDF 文本层还原，复杂多行公式可能失真；合并表头的复杂表格会保留标题并生成占位行，需回 PDF 查看。
- 原始 PDF 被 gitignore，换机器时必须重新拷贝。

## 构建状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 | 骨架与规范 | ✅ |
| P2 | 环境与自检 | ✅ |
| P3 | paper2md | ✅ |
| P3b | ACM 双栏兼容 | ✅ |
| P4 | paper-digest | ✅ |
| P5 | paper-ingest | ✅ |
| P6 | 关系图与对比 | ✅ |
| P6.5 | L3 问题/方法深度剖析 | ✅ |
| P7 | 全流程测试 | ✅ |
| P8 | 冷启动复现与提交 | ⬜ |
