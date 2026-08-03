# 国赛 Word 论文模板：可复用版式合同

## Reference

- retained reference: `E:\AI\Shumocg\国赛word论文模版.docx`
- SHA-256: `5d26daa0ada105d4d7e0d325642220c5909d8758f2e2314e3474a64cf8c6d656`
- file size: `26835` bytes
- rendered reference pages: `8`
- section count: `1`
- render evidence: task-local `template-reference-render-direct/page-1.png` through `page-8.png`
- conversion note: the original Chinese path made the local LibreOffice wrapper fail on the first read-only render. An identical temporary ASCII-path copy was rendered; the retained reference hash was checked before and after and the original file was not edited.

## Page system

- paper size: A4, `8.27 x 11.69 in` (`11906 x 16838` twips)
- orientation: portrait
- columns: one, column gap `425` twips
- margins: left/right `1531` twips (`1.063 in`), top/bottom `1440` twips (`1.000 in`)
- header/footer distances: header `851` twips, footer `992` twips
- first-page, default-page, and even-page header/footer references are present; the reference uses a first-page/default/even split even though the rendered sample leaves the header visually empty.
- document grid: line grid, line pitch `312` twips
- page number: centered footer `PAGE \\* MERGEFORMAT` field; the cached field text must be refreshed in Word when the final document is opened.

## Typography and paragraph roles

- `Normal`: East Asian `宋体`, Latin `Times New Roman`, 12 pt body size, justified, first-line indent `200` characters in the style and `480` twips in the populated body slots; widow control is disabled in the base style.
- title slot: centered, `黑体`, 16 pt.
- abstract heading slot: centered, `黑体`, approximately 14 pt, with the template's split `摘  要` runs preserved unless the source patch intentionally replaces the whole run sequence.
- `Heading 1`: centered, `黑体`, 14 pt, keep-with-next and keep-lines, outline level 0, automatic decimal numbering level 0, 6 pt before/after.
- `Heading 2`: left aligned, `黑体`/major East Asian heading font, keep-with-next and keep-lines, outline level 1, automatic decimal numbering level 1, approximately 3.5 pt after.
- `Heading 3`: left aligned, `黑体`, keep-with-next and keep-lines, outline level 2, automatic decimal numbering level 2.
- footer: centered page field, approximately 9 pt.
- heading numbering must remain Heading-style based; do not replace it with manual numbers or direct formatting.

## Lists, formulas, and tables

- numbering part contains one decimal multilevel definition with `%1`, `%1.%2`, `%1.%2.%3`, etc.; preserve `word/numbering.xml` and its relationships.
- five formula slots are two-column `Table Grid` tables: a wide formula cell and a narrow right-aligned equation-number cell. The cached examples use `(1)`–`(5)` and must be replaced by real equations/labels, never left as placeholders.
- symbol table: two columns, five starter rows, centered bold header `符号 / 说明`, top and bottom rules, body cells intentionally empty in the retained sample.
- three appendix blocks: one-column three-row `Table Grid` tables; gray heading rows, a description row, and a large content cell for supporting files/code. These are appendices, not a substitute for missing body derivation.
- all tables use the retained grid/border/fill components. The reference's auto-width diagnostics are known template properties; do not normalize them into a second table design without a measured reason.

## Content flow and slots

1. Page 1: title, abstract, one paragraph per required question, closing paragraph, keywords.
2. Page 2: problem restatement, problem background/statement, problem analysis by question, model assumptions, symbol explanation/table.
3. Pages 3–4: model establishment and solution, with one or more question subsections and equation slots.
4. Page 5: model analysis/test and model evaluation (advantages, limitations, improvements, extension).
5. Page 6: references.
6. Pages 7–8: appendices and supporting material.

The editable slot map is semantic rather than prose-copy based:

- `word/document.xml` body paragraphs 0–8: title, abstract, question summary, closing summary, keywords.
- Heading 1/2 paragraphs after the first page break: section and subsection headings. Existing bookmarks and heading styles are stable locators.
- body paragraphs immediately after each Heading 2: replace with question-specific problem facts, derivation, mechanism, boundary, and answer prose; empty red-text paragraphs in the sample are placeholders and must be removed or replaced.
- formula tables 1–5: replace only with current model equations and their real equation numbers.
- symbol table 0: populate from the current `MODELING_UNITS` symbol contract.
- appendix tables 6–8: populate only with real supporting files, reproducible code descriptions, or stability material that is not needed to understand the main result.

The template's placeholder wording is not an evidence source and is not authoritative scientific content. Unsupported optional slots may remain intentionally empty or be removed only when the final source's section contract permits it. Never invent text to fill the large appendix cells.

## Package preservation

The reference package contains 30 ZIP parts, including `word/styles.xml`, `word/numbering.xml`, `word/theme/theme1.xml`, three headers, three footers, settings, font table, footnotes/endnotes, bookmarks, custom XML, and relationship files. It has no inline/anchored images and no content controls. It contains five `AUTONUM` fields in the body and one `PAGE` field in the footer.

Preserve styles, numbering, headers, footers, section properties, bookmarks, fields, custom XML, and all untouched relationships. When the template is used, work on a copy and pass it to Pandoc as `--reference-doc`; do not rebuild the output from a generic style pack. If a future source patch edits this DOCX in place, compare the preserve-only package inventory and rerender every page.

## Fidelity and length gates

- retain the exact reference SHA-256 recorded above; a mismatch requires fresh distillation.
- render every final DOCX page at publication width and inspect PNG and PDF output; a contact sheet is only a navigation aid.
- run structural audits for sections, styles, headings, fields, tables, placeholders, and DOCX ZIP integrity.
- record the final PDF page count separately from the template's sample page count. For CUMCM 2026, the body must not exceed 30 pages; no minimum page target is inferred from the template.
- page count is a risk signal, not permission to pad. Expand only with real derivation, mechanism, contrast, boundary, typical cases, and question-specific figures from current evidence; keep source code and control logs in the appendix/attachment according to the paper contract.
