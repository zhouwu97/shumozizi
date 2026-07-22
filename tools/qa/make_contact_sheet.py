"""将 PDF 页面渲染为一张便于人工快速检查的联系表。"""

from __future__ import annotations

import argparse
from math import ceil
from pathlib import Path

import pdfplumber
from PIL import Image, ImageDraw


def make_contact_sheet(pdf_path: Path, output_path: Path, *, columns: int = 3) -> Path:
    """渲染 PDF 页面并生成 PNG 联系表。

    Args:
        pdf_path: 输入 PDF。
        output_path: 输出 PNG 路径。
        columns: 每行页面数。

    Returns:
        已生成的输出路径。

    Raises:
        ValueError: PDF 没有页面或列数非法。
    """
    if columns < 1:
        raise ValueError("columns 必须大于零")
    pages: list[Image.Image] = []
    with pdfplumber.open(str(pdf_path)) as document:
        for page in document.pages:
            image = page.to_image(resolution=100).original.convert("RGB")
            image.thumbnail((360, 500))
            pages.append(image.copy())
    if not pages:
        raise ValueError("PDF 没有页面")
    cell_width = max(image.width for image in pages) + 16
    cell_height = max(image.height for image in pages) + 36
    rows = ceil(len(pages) / columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(pages):
        column = index % columns
        row = index // columns
        x = column * cell_width + (cell_width - image.width) // 2
        y = row * cell_height + 20
        sheet.paste(image, (x, y))
        draw.text((column * cell_width + 6, row * cell_height + 4), f"Page {index + 1}", fill="black")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, format="PNG")
    return output_path


def main() -> int:
    """提供联系表命令行入口。

    Returns:
        成功时为零。
    """
    parser = argparse.ArgumentParser(description="生成 PDF 联系表")
    parser.add_argument("pdf")
    parser.add_argument("output")
    parser.add_argument("--columns", type=int, default=3)
    args = parser.parse_args()
    make_contact_sheet(Path(args.pdf), Path(args.output), columns=args.columns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
