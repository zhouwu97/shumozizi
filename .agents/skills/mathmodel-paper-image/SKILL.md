---
name: mathmodel-paper-image
description: 为数学建模论文规划解释型流程图候选，生成 A/B Prompt，执行候选审图并接入现有 Visual Sandbox；不把 AI 图片直接作为正式论文证据。
---

# 论文解释型生图

该流程只处理方法、流程、机制和时间过程的视觉设计候选。真实数据曲线、热力图、统计图和敏感性图优先由 `skills/sci-box/scibox-figure` 母版模板（复制原脚本只换数据入口）生成，其次才由 `3coding-visual` 使用确定性 renderer 生成。

## 工作链

```text
VISUAL_REQUIREMENTS
→ paper image opportunity
→ high / medium / low
→ A/B Prompt
→ candidate generation
→ Hard / Soft review
→ KEEP / RETRY / DROP_AI_IMAGE
→ Visual Sandbox
→ formal renderer or DrawIO
→ existing promotion
```

## 浏览器候选生成

默认使用浏览器中的独立 ChatGPT 新对话生成 A/B 设计候选：上传已登记的风格参考图，分别提交
`variant_a.txt` 与 `variant_b.txt`，等待图像生成完成后下载原始 PNG 到
`figures/sandbox/<image_id>/browser-candidates/`。不得用网页截图冒充原图，也不得在同一条提示中
要求模型同时拼接 A/B。

浏览器回执必须记录候选路径、SHA-256、画布尺寸、对话 URL、Prompt SHA-256 和生成时间。
浏览器候选仍只属于 Sandbox 设计参考；其中的公式、文字和数字不得直接作为论文事实。
本地 `image_gen` 或 CLI provider 只在用户明确要求时使用，缺少本地 provider 不再阻断浏览器路径。

使用：

```powershell
python scripts/figures/build_paper_image_prompts.py <run_dir>
python scripts/figures/generate_paper_images.py <run_dir> <image_id> `
  --generator-executable <provider-wrapper> `
  --reviewer-executable <reviewer-wrapper> `
  --reviewer-context-id <fresh-id>
```

上述 CLI 用于可执行 provider wrapper；浏览器路径由 Codex Browser 完成，并把下载原图与回执接回
同一 `image_id` 的 Sandbox 后继续 Hard/Soft review。

P0 只生产 `academic_flowchart`。`mechanism_diagram` 和 `timeline_diagram` 目前只记录建议，不自动进入正式闭环。

`academic_flowchart` 必须绑定 `style_reference=academic_bilingual_infographic_v1`，并同时规划 layout 与 `visual_elements`。Hero 候选至少包含两种非文字视觉元素，例如公式、网络小图、状态示意、时间轴、迷你曲线、指标或判定节点；只有文字、矩形和箭头的普通框图不能通过。

Soft review 必须包含 `academic_visual_richness` 和 `generic_box_diagram_score/level`。`generic_box_diagram_level=HIGH` 时总分上限为 6.5；丰富度不足 7 时同样限分。缺少两种非文字视觉元素属于 Hard FAIL，不能被对齐、留白或配色分数抵消。

`academic_flowchart` 不是普通 DrawIO 框图。默认风格引用为 `academic_bilingual_infographic_v1`：中文主标题 + 英文副标题、彩色阶段分区、模块内子卡片、语义线性图标、短公式/判据、真实数学对象小图和底部方法总结。Hero 候选至少包含两种非文字视觉元素；只有文字、矩形和箭头的候选必须失败或被严格限分。

Soft review 必须包含 `academic_visual_richness`（S10）和 `generic_box_diagram_score`。若普通框图感为 HIGH 或分数达到 7，最终 soft score 上限为 6.5；S10 低于 4 时上限为 5.5。旧版只检查对齐、留白和配色的 reviewer 回执不具备晋级资格。

候选图片中的数字、公式和标签不是科学事实来源。`selected_pending_promotion` 只表示设计参考胜出；必须从 current 结果重渲染 PNG/PDF、生成 manifest、完成人工内容复核和现有 promotion 后，才能进入 `figures/current`。

两轮 Hard review 仍失败时记录 `DROP_AI_IMAGE` 和 `fallback=drawio`，不继续抽取第三轮。
