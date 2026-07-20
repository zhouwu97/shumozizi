# KNOWLEDGE_PACK 导入合同

`shumozizi` 只把知识包作为运行配置输入，不建立 `KNOWLEDGE_LOCK`、`KNOWLEDGE_STATE` 或知识晋级 Gate。知识包进入已有 `RUN_CONFIG_LOCK.json` 后，路线锁定前不得替换。

```powershell
python scripts/codex/import_knowledge_pack.py `
  runs/2026-A-001 `
  ..\..\数模\dist\KNOWLEDGE_PACK.json `
  --problem-source problems/2026-A `
  --questions-json questions.json `
  --claims-json claims.json
```

导入器会：

1. 校验包 Schema、版本、卡片 ID 和内容哈希；
2. 安装到 `knowledge/packs/<pack_id>.json`，拒绝覆盖不同字节；
3. 检查题面/附件名称和文本中的同题来源题号或题名，并复验来源内容哈希；
4. 拒绝题面目录中越过题面根目录的符号链接，避免用路径绕过泄漏检查；
5. 将 `pack_id`、版本、来源 commit、路径和 SHA-256 写入 `RUN_CONFIG_LOCK.json`；
6. 生成 `paper/PAPER_BLUEPRINT.md` 与 `claims/ARGUMENT_MAP.json`。

`ARGUMENT_MAP.json` 的 `outcome` 允许 `supported`、`partially_supported`、`rejected`、`inconclusive` 和 `stale`。知识包不会把 advisory 建议或不确定结果变成阻断条件。
