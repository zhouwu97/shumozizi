const fs = require('fs');
const path = require('path');
const {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  HeadingLevel,
  LevelFormat,
  PageNumber,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} = require('docx');

const outputPath = path.resolve(__dirname, '../../artifacts/docs/R1-R5审核说明_当前版本.docx');
const contentWidth = 9026;
const border = { style: BorderStyle.SINGLE, size: 1, color: 'C9D2DC' };
const borders = { top: border, bottom: border, left: border, right: border };

function text(value, options = {}) {
  return new TextRun({ text: value, font: options.font || 'Microsoft YaHei', size: options.size || 22, ...options });
}

function paragraph(children, options = {}) {
  const items = Array.isArray(children) ? children : [text(children)];
  return new Paragraph({ children: items, spacing: { after: 120, line: 320 }, ...options });
}

function heading(value, level) {
  return new Paragraph({
    heading: level,
    children: [text(value, { bold: true })],
  });
}

function code(value) {
  return text(value, { font: 'Consolas', size: 20, color: '374151' });
}

function bullet(value) {
  return new Paragraph({
    numbering: { reference: 'bullets', level: 0 },
    children: [text(value)],
    spacing: { after: 70, line: 300 },
  });
}

function numbered(value) {
  return new Paragraph({
    numbering: { reference: 'numbers', level: 0 },
    children: [text(value)],
    spacing: { after: 70, line: 300 },
  });
}

function cell(value, width, options = {}) {
  const children = Array.isArray(value) ? value : [paragraph(value, { spacing: { after: 0, line: 280 } })];
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    borders,
    margins: { top: 90, bottom: 90, left: 120, right: 120 },
    shading: options.header ? { fill: 'DCE6F1', type: ShadingType.CLEAR } : undefined,
    children,
  });
}

function comparisonTable() {
  const widths = [900, 1900, 3100, 3126];
  const rows = [
    ['审核', '执行时机', '核心定位', '输出结论'],
    ['R1 建模', '路线锁定后、实验前', '验证题意、模型规格、变量/单位、目标、约束和验证计划是否可执行。', 'ACCEPT / ACCEPT_WITH_FIXES / REBUILD'],
    ['R2 实验复现', '每个必做子问题实验完成后', '逐问复现代码、数据、指标 provenance、随机性、硬约束、sealed result 和图表来源。', 'REPRODUCIBLE / REPRODUCIBLE_WITH_WARNINGS / BLOCKED'],
    ['R3 论文逻辑', '全文和 PDF 生成后', '核对题目要求、模型、accepted result、论文数字、公式、claim 和逐问答案的证据链。', 'READY_FOR_COMPREHENSIVE_REVIEW / MAJOR_REVISION / NOT_READY'],
    ['R4 格式视觉', '最终 PDF 生成后', '检查模板、页边距、匿名、字体、公式、图表、裁切、遮挡、黑白可辨性和提交包。', 'COMPLIANT / FIX_REQUIRED / NOT_COMPLIANT'],
    ['R5 全面盲审', 'R3、R4 和 QA 通过后', '全新上下文从评委视角评价生产闭环与竞赛质量，执行 A/B 双轴联合判断。', 'A_PASS/A_BLOCKED；B_STRONG/B_PASS/B_WEAK/B_REBUILD'],
  ];
  return new Table({
    width: { size: contentWidth, type: WidthType.DXA },
    columnWidths: widths,
    rows: rows.map((row, index) => new TableRow({
      children: row.map((value, columnIndex) => cell(value, widths[columnIndex], { header: index === 0 })),
    })),
  });
}

function section(title, intro, fields) {
  const result = [heading(title, HeadingLevel.HEADING_1), paragraph(intro)];
  for (const field of fields) {
    result.push(heading(field.label, HeadingLevel.HEADING_2));
    if (field.type === 'bullets') {
      result.push(...field.items.map(bullet));
    } else if (field.type === 'numbered') {
      result.push(...field.items.map(numbered));
    } else {
      result.push(paragraph(field.value));
    }
  }
  return result;
}

const children = [
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 220 },
    children: [text('R1-R5 审核说明（当前版本）', { bold: true, size: 34, color: '1F2937' })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 260 },
    children: [text('MathModelAgent · 生产闭环与竞赛质量双轴优化', { size: 22, color: '4B5563' })],
  }),
  paragraph([text('文档用途：', { bold: true }), text('说明当前 R1-R5 审核契约、执行边界和判定方式。\n'.replace('\\n', '')), text('版本依据：'), code('2026-07-20 当前代码与审核技能说明')]),
  heading('一、当前结论', HeadingLevel.HEADING_1),
  paragraph('当前 R1-R5 已经形成一套分阶段、可复验、带输入边界和独立性约束的审核体系。R1-R4 是局部审核，分别覆盖建模、实验、论文逻辑和 PDF 格式；R5 不是简单的第五次文件检查，而是全新上下文中的独立盲审，并用 A/B 双轴判断生产闭环是否完整以及作品是否达到竞赛质量。'),
  comparisonTable(),
  paragraph('注：所有审核默认只读，只能写入自己的 review_report.json 和 review_receipt.json。审核失败后生成带来源哈希的 REPAIR_PLAN.json，不能由审核任务直接修改模型、实验结果或论文。'),
  ...section('二、R1 建模审核', 'R1 判断“模型设计是否足以进入实验”，不评价实验结果和论文表达。它是正式实验前的建模闸门。', [
    { label: '执行时机', value: '路线锁定、模型规格完成后，正式实验开始前。' },
    { label: '必须读取', type: 'bullets', items: ['problem_manifest', 'route_lock', 'model_spec'] },
    { label: '禁止读取', type: 'bullets', items: ['实验结果', '论文和最终 PDF', 'R2-R5 或 J0 审核报告'] },
    { label: '核心检查', type: 'bullets', items: ['题意和问题全集是否覆盖完整。', '变量、单位、目标函数和核心约束是否明确且一致。', 'baseline、primary、robustness/ablation 是否可执行。', '验证计划是否能支撑后续结果验收。', '是否存在改变题意、模型类别或已锁路线的隐性路线漂移。'] },
    { label: '输出结论', value: 'ACCEPT、ACCEPT_WITH_FIXES 或 REBUILD。只有通过后才进入 EXPERIMENTING。' },
    { label: '失败后的返工', value: '修正模型规格、变量/单位、约束或验证计划；若涉及路线漂移，必须回到人工路线确认点。' },
  ]),
  ...section('三、R2 逐问实验复现审核', 'R2 判断“结果能否从现有代码和输入中重新得到”。每个必做子问题独立执行，未通过的结果不能进入论文。', [
    { label: '执行时机', value: '每个必做子问题的实验完成后，逐问审核。' },
    { label: '必须读取', type: 'bullets', items: ['model_spec', 'execution_manifest', 'execution_record', 'source_code', 'result_registry', 'sealed_result'] },
    { label: '核心检查', type: 'bullets', items: ['代码、输入和输出是否真实运行，哈希是否一致。', '指标 provenance 是否完整，单位和计算口径是否正确。', '随机种子、数据划分和重复运行是否可追溯。', 'baseline 与 primary 是否公平可比。', '硬约束是否满足，违反约束的结果是否被阻断。', 'sealed result 是否有效，图表是否来自已接受结果。'] },
    { label: '输出结论', value: 'REPRODUCIBLE、REPRODUCIBLE_WITH_WARNINGS 或 BLOCKED。' },
    { label: '失败后的返工', value: '优先修正代码或数据，再按同一路线调整参数/求解器；仍失败时才申请已确认备用路线或路线漂移确认。' },
  ]),
  ...section('四、R3 论文逻辑审核', 'R3 判断论文是否真实、直接、完整地回答每一道题，而不只是文字通顺。', [
    { label: '执行时机', value: '全文和最终 PDF 生成后，与 R4 处于同一论文审核阶段。' },
    { label: '必须读取', type: 'bullets', items: ['problem_manifest', 'model_spec', 'result_registry', 'question_acceptance', 'paper_plan', 'final_pdf'] },
    { label: '核心检查', type: 'bullets', items: ['题目要求、模型、实验输出、accepted result 与逐问论文答案是否一一对应。', '公式、变量、单位、数字和表格是否一致。', '每个 claim 的状态和证据是否匹配。', '限制条件、适用边界、图表和引用是否被准确表达。', '是否存在用未接受、revoked 或 superseded 结果写入论文的情况。'] },
    { label: '输出结论', value: 'READY_FOR_COMPREHENSIVE_REVIEW、MAJOR_REVISION 或 NOT_READY。' },
    { label: '失败后的返工', value: '修正论文逻辑、数字、公式、图表或证据映射；若模型或核心数字发生变化，必须按影响范围重跑实验并刷新受影响回执。' },
  ]),
  ...section('五、R4 格式与视觉审核', 'R4 判断“提交出去的 PDF 实际上是否合规、可读、可提交”，与 R3 的内容逻辑检查分开。', [
    { label: '执行时机', value: '最终 PDF 生成后。' },
    { label: '必须读取', type: 'bullets', items: ['RUN_CONFIG_LOCK.json', 'paper_plan', 'figure_plan', 'final_pdf'] },
    { label: '核心检查', type: 'bullets', items: ['模板、页边距、页数和匿名信息是否合规。', '字体嵌入、公式渲染、图表分辨率和图例是否正常。', '单位、标题、标注是否清楚，是否存在裁切、遮挡或重叠。', '黑白打印或低分辨率查看时，图表是否仍可辨识。', '提交包文件、哈希和审核回执是否绑定当前 PDF。'] },
    { label: '输出结论', value: 'COMPLIANT、FIX_REQUIRED 或 NOT_COMPLIANT。' },
    { label: '失败后的返工', value: '修复排版、图表、字体、匿名或提交包，并重新生成 PDF、QA 结果和相关回执。' },
  ]),
  ...section('六、R5 全面盲审', 'R5 是独立评委视角的综合质量判断，不读取作者解释和前序审核结论，防止“审核意见互相引用”造成自证闭环。', [
    { label: '执行时机', value: 'R3、R4 和机械 QA 全部通过后；随后再进入 J0 自然评委盲评。' },
    { label: '允许读取', type: 'bullets', items: ['原始题目和 problem_manifest', '冻结 PDF 和必要的代码/结果证据', 'QA 报告', 'RUN_CONFIG_LOCK.json', '必要的 result_registry、paper_plan 和 evidence_report'] },
    { label: '禁止读取', type: 'bullets', items: ['作者解释或自我辩护材料', 'R1-R4、J0 审核报告', '上一轮 R5 报告'] },
    { label: 'A 轴：生产闭环', value: 'A_PASS 或 A_BLOCKED。主要判断题目是否完整覆盖、结果是否可追溯、证据链是否闭合、提交物是否真实可验。' },
    { label: 'B 轴：竞赛质量', value: 'B_STRONG、B_PASS、B_WEAK 或 B_REBUILD。评价题目覆盖、模型深度、实验验证和整体竞赛竞争力。' },
    { label: 'B 轴通过条件', type: 'bullets', items: ['总分至少 75。', '题目覆盖、模型深度、实验验证三项均至少 60。', '质量等级必须为 B_STRONG 或 B_PASS。'] },
    { label: '额外输出', type: 'bullets', items: ['A-E 奖项估计和置信度。', '证据和降级原因。', 'joint_verdict。', 'repair_scope。', 'required_retests。'] },
    { label: '最终候选条件', value: '只有 A、B 两轴同时通过，且没有 P0/P1 问题，才可以标记为 FINAL_CANDIDATE。竞赛模式 R5 最多 3 轮，训练模式最多 5 轮。' },
  ]),
  heading('七、整体状态流转', HeadingLevel.HEADING_1),
    paragraph([code('MODEL_SPEC_READY'), text('  ->  R1  ->  EXPERIMENTING  ->  每个必做问题分别执行 R2  ->  RESULTS_ACCEPTED  ->  论文完成后 R3 + R4  ->  QA 通过  ->  R5  ->  WAITING_HUMAN_FINAL  ->  人工批准  ->  COMPLETE；J0 仅为可选评委模拟。')]),
  heading('八、通用约束', HeadingLevel.HEADING_1),
  bullet('PROBLEM_MANIFEST.json 是权威问题全集，所有必做问题都必须完成。'),
  bullet('state.json 只能由 StateService 写入，不能通过聊天历史或任务 ID 推断工作流状态。'),
  bullet('只有 result_registry 中仍为 accepted、paper_allowed=true 且封条有效的结果可以进入论文。revoked 和 superseded 结果一律禁止引用。'),
  bullet('Route、Paper、QA 和 Final Approval 必须读取同一份 RUN_CONFIG_LOCK.json。'),
  bullet('不得把 Schema 通过直接等同于竞赛质量通过。'),
  bullet('模型、数字、核心图表、假设、约束或结论发生变化时，必须按影响范围重跑实验并刷新受影响审核回执。'),
  heading('九、当前审核说明来源', HeadingLevel.HEADING_1),
  paragraph('本说明对应项目内的审核技能和工作流规则，主要来源如下：'),
  bullet('.agents/skills/mathmodel-review-r1-modeling/SKILL.md'),
  bullet('.agents/skills/mathmodel-review-r2-experiment/SKILL.md'),
  bullet('.agents/skills/mathmodel-review-r3-paper-logic/SKILL.md'),
  bullet('.agents/skills/mathmodel-review-r4-format-visual/SKILL.md'),
  bullet('.agents/skills/mathmodel-review-r5-comprehensive/SKILL.md'),
  bullet('src/shumozizi/workflow/review_policy.py 与 src/shumozizi/workflow/reviews.py'),
  bullet('docs/PRODUCTION_REVIEW_REPAIR_PLAN.md 与 docs/CODEX_WORKFLOW.md'),
];

const document = new Document({
  numbering: {
    config: [
      { reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: 'numbers', levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ],
  },
  styles: {
    default: { document: { run: { font: 'Microsoft YaHei', size: 22 }, paragraph: { spacing: { line: 320 } } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: 'Microsoft YaHei', size: 28, bold: true, color: '1F4E79' }, paragraph: { spacing: { before: 260, after: 140 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: 'Microsoft YaHei', size: 24, bold: true, color: '2F5597' }, paragraph: { spacing: { before: 180, after: 90 }, outlineLevel: 1 } },
    ],
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1200, right: 1440, bottom: 1200, left: 1440 },
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [text('R1-R5 审核说明 · 第 ', { size: 18, color: '6B7280' }), new TextRun({ children: [PageNumber.CURRENT], font: 'Microsoft YaHei', size: 18, color: '6B7280' }), text(' 页', { size: 18, color: '6B7280' })] })],
      }),
    },
    children,
  }],
});

Packer.toBuffer(document).then((buffer) => {
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, buffer);
  console.log(outputPath);
});
