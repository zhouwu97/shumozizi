# KNOWLEDGE_PACK 兼容导入（已废弃）

该接口只用于复验历史运行，不属于当前主流程。新运行必须使用 `knowledge/cards/papers/`、
`knowledge/indexes/papers.json` 和路线前检索产物，不得要求其他仓库生成
`dist/KNOWLEDGE_PACK.json`，也不得把外部知识包作为 `RUN_CONFIG_LOCK.json` 的必要输入。

只有需要读取旧运行时才使用以下兼容命令：

```powershell
python scripts/codex/import_knowledge_pack.py `
  runs/2026-A-001 `
  ..\..\数模\dist\KNOWLEDGE_PACK.json `
  --problem-source problems/2026-A `
  --questions-json questions.json `
  --claims-json claims.json
```

兼容导入器会：

1. 校验包 Schema、版本、卡片 ID 和内容哈希；
2. 安装到 `knowledge/packs/<pack_id>.json`，拒绝覆盖不同字节；
3. 检查题面/附件名称和文本中的同题来源题号或题名，并复验来源内容哈希；
4. 拒绝题面目录中越过题面根目录的符号链接，避免用路径绕过泄漏检查；
5. 将 `pack_id`、版本、来源 commit、路径和 SHA-256 写入 `RUN_CONFIG_LOCK.json`；
6. 为旧运行生成 `paper/PAPER_BLUEPRINT.md` 与 `claims/ARGUMENT_MAP.json`。

该兼容路径不应出现在新路线、基准或生产说明中，也不会继续扩展。
