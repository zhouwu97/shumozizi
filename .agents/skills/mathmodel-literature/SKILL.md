---
name: mathmodel-literature
description: 按需为数学建模论文规划并记录双语文献检索、机构数据库浏览、候选来源核验和引用台账审计。用于论文引用规划、中文本土背景或标准核验、引用覆盖缺口修复，以及用户明确要求检索文献时；不用于搜索同题答案或替代当前实验。
---

# 数学建模文献检索

## 边界

- 只作为按需工具，不新增工作流阶段，也不替代 `mathmodel-paper` 的论文论证。
- CNKI、万方、维普、图书馆发现系统、Crossref、OpenAlex 和公开网页都是可选 provider；不要把流程绑定到单一数据库。
- 不搜索同题答案、往届题解、现成结论或可直接迁移的代码。
- 不自动填写、接收、记录或导出密码、验证码、Cookie、令牌、VPN 配置或统一认证回调。
- 用户在浏览器页面中亲自完成首次认证；随后只在已认证会话中执行少量、明确选择的检索或下载。
- 禁止并发抓取、批量下载、绕过访问控制和自动重试登录。全文只作为本地工作材料，不进入提交包或引用证据链，除非用户另有明确授权且符合数据库许可。

## 工作流

1. 读取题面、`PAPER_BLUEPRINT.md` 和当前 `CITATION_PLAN.md`，按 `background`、`core_method`、`validation`、`uncertainty`、`extension` 生成中文和英文查询式。
2. 对涉及中国政策、标准、统计口径或本土行业事实的论文，将 `chinese_search_required` 设为 `true`；纯数学、方法原始论文和通用统计定义不机械强制中文来源。
3. 运行 `python scripts/paper/prepare_literature_search.py <run_dir> --topic ...` 生成 `paper/generated/literature-search-plan.json`。机构访问使用 `--institutional-access manual-browser`，表示用户负责认证，不表示脚本拥有凭据。
4. 需要登录时，使用 Codex 浏览器或 Chrome 扩展打开用户指定的入口，暂停让用户完成认证；不得要求用户把密码粘贴到聊天、命令行或 JSON。
5. 若当前浏览器仍保持已认证的机构会话，AI 可以直接自行执行查询、打开候选摘要和处理用户明确选择的少量下载；不要重新打开登录页，也不要尝试读取或复用密码。
6. 一旦跳回统一认证页、出现验证码或会话过期，立即暂停并让用户重新完成认证；不得自动提交登录表单、绕过验证或重试认证。
7. 对用户选中的少量候选，保存元数据 JSON 后运行 `python scripts/paper/record_literature_candidate.py <run_dir> --input <candidate.json>`。每条来源必须标记发现渠道、权威来源、语言和 `metadata`/`abstract`/`fulltext` 核验级别。
8. 没有合适中文来源时，显式记录检索已执行、候选数和不采用理由；不要为了满足数量凑引用。
9. 运行 `python scripts/paper/audit_literature_search.py <run_dir>`，区分硬错误与 advisory。中文检索只有在被判定为必需且未执行时才阻断；来源数量、语言比例和未选候选只产生建议。
10. 最终采用来源仍必须回写 `paper/CITATION_PLAN.md` 并绑定正文具体判断。检索账本不替代引用覆盖报告，摘要核验不得写成全文核验。

## 输出

- `paper/generated/literature-search-plan.json`：查询范围、语言要求和机构访问模式。
- `paper/generated/literature-search-report.json`：候选来源、核验层级、选择状态和审计结果。
- `paper/CITATION_PLAN.md`：只记录最终采用来源及正文绑定，不承载完整搜索历史。

脚本只接受 Schema 允许的字段；任何凭据字段都会被拒绝。所有输出必须位于当前运行目录内。

已确认的沈阳理工大学机构访问记录见 [references/shenyang-ligong-access.md](references/shenyang-ligong-access.md)。
