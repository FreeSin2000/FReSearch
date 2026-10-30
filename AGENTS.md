# FReSearch 会话规范

本文件是任何新会话的入口。开工前按顺序读：

1. `README.md` —— 项目做什么、产物长什么样。
2. `specs/conventions.md` —— 命名、目录、状态机、语言策略。
3. 当前步骤对应的 `skills/<name>/SKILL.md` 与 `specs/*.md`。
4. `../构建FReSearch.md` 末尾的「分步构建计划」—— 当前只做哪一步。

## 当前阶段

P7（全流程复测）已完成，等待用户确认后进入 P8（冷启动复现与最终提交）。
**一次只推进一步，完成即停，等用户确认后再进入下一步。**
未轮到的步骤不要预写代码或产物。

## 硬性约束

- 所有读写都在本仓库内；不修改 `~/.pi/` 或其他全局配置，不写系统 Python 环境。
- 不使用 OCR、embedding、向量库、在线 embedding 服务；不引入深度学习依赖。
- 生成数据（PDF、md、digest、meta、index）不进 git；只提交 `skills/`、`specs/`、
  `scripts/`、`tests/`、`requirements.txt`、`README.md`、`AGENTS.md`、
  `.gitignore`、`.pi/settings.json`。
- 总结中的每个数字/结论必须能追溯到 `§` / `Fig.` / `Table` / 页码；找不到依据就标注存疑，
  不臆造。
- 不一次性把整篇 `paper.md` 塞进上下文；按章节分块读。
- 路径一律相对仓库根或 `$FRESEARCH_ROOT`，不写死 `/home/...`。

## 常用命令

```bash
bash scripts/bootstrap_env.sh          # 环境（幂等，已存在则跳过）
.venv/bin/python scripts/check_env.py  # 依赖自检
.venv/bin/python scripts/ingest.py papers/_inbox/<file>.pdf
.venv/bin/python scripts/build_index.py
.venv/bin/python scripts/translate.py prepare papers/<slug>
.venv/bin/python scripts/translate.py assemble papers/<slug> --strict
.venv/bin/python scripts/build_graph.py
```

> 以上命令均已实现；新增或改名时先更新本文件与对应 SKILL.md。

## 完成一步后的输出格式

1. 改动文件清单（`git status --short`）。
2. 验收命令与真实输出（不概括、不省略报错）。
3. 已知偏差 / 未覆盖项。
4. 下一步建议，然后**停下等确认**。

## 提交风格

- 祈使句，首行 ≤ 72 字符。
- P0–P6.5 已分批提交；之后每次只提交一个逻辑变更，提交前先跑
  `.venv/bin/python -m unittest discover -s tests`。
- 提交前确认 `git status` 中没有 PDF、`.venv/`、生成数据。
