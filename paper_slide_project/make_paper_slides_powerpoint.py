import json
import re
import sys
import time
from pathlib import Path

import win32com.client as win32


POWERPOINT_FILE_FORMAT_PPTX = 24
MSO_SHAPE_TYPE_GROUP = 6


def make_replacement_value(value):
    """
    PowerPointでは改行を \r として扱うことが多いので変換する。
    """
    if value is None:
        return ""
    return str(value).replace("\n", "\r")


def replace_placeholders(text, data):
    """
    {{jp_title}} のようなプレースホルダーを置換する。
    念のため {{journal.doi}} のようにドットで書いてしまった場合もある程度拾う。
    """
    if text is None:
        return text

    for key, value in data.items():
        replacement = make_replacement_value(value)

        # 通常パターン：{{journal_doi}}
        text = text.replace("{{" + key + "}}", replacement)

        # ゆるめパターン：{{ journal_doi }} や {{journal.doi}} も拾う
        parts = [re.escape(part) for part in key.split("_")]
        pattern = r"\{\{\s*" + r"\s*[_\.]\s*".join(parts) + r"\s*\}\}"
        text = re.sub(pattern, replacement, text)

    return text


def replace_in_text_frame(text_frame, data):
    try:
        if not text_frame.HasText:
            return

        old_text = text_frame.TextRange.Text
        new_text = replace_placeholders(old_text, data)

        if new_text != old_text:
            text_frame.TextRange.Text = new_text

    except Exception:
        pass


def process_shape(shape, data):
    """
    通常テキスト、表、グループ化された図形の中の文字を置換する。
    """
    # グループ図形
    try:
        if shape.Type == MSO_SHAPE_TYPE_GROUP:
            for i in range(1, shape.GroupItems.Count + 1):
                process_shape(shape.GroupItems(i), data)
    except Exception:
        pass

    # 表
    try:
        if shape.HasTable:
            table = shape.Table
            for r in range(1, table.Rows.Count + 1):
                for c in range(1, table.Columns.Count + 1):
                    cell_shape = table.Cell(r, c).Shape
                    process_shape(cell_shape, data)
    except Exception:
        pass

    # 通常テキスト
    try:
        if shape.HasTextFrame:
            replace_in_text_frame(shape.TextFrame, data)
    except Exception:
        pass


def fill_slide(slide, data):
    for i in range(1, slide.Shapes.Count + 1):
        process_shape(slide.Shapes(i), data)


def copy_slide_to_end(presentation, slide_index):
    """
    PowerPoint自身にスライドをコピーさせる。
    これがデザイン再現に一番強い。
    """
    presentation.Slides(slide_index).Copy()
    time.sleep(0.1)

    # 最後に貼り付け
    pasted = presentation.Slides.Paste(presentation.Slides.Count + 1)
    return pasted.Item(1)


def load_papers(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        papers = json.load(f)

    if isinstance(papers, dict):
        papers = [papers]

    if not isinstance(papers, list):
        raise ValueError("papers.json は、JSONオブジェクトまたは配列にしてください。")

    return papers


def make_deck(template_path, json_path, output_path):
    template_path = Path(template_path).resolve()
    json_path = Path(json_path).resolve()
    output_path = Path(output_path).resolve()

    if not template_path.exists():
        raise FileNotFoundError(f"template.pptx が見つかりません: {template_path}")

    if not json_path.exists():
        raise FileNotFoundError(f"papers.json が見つかりません: {json_path}")

    if output_path.exists():
        output_path.unlink()

    papers = load_papers(json_path)

    app = None
    presentation = None

    try:
        app = win32.DispatchEx("PowerPoint.Application")
        app.Visible = True
        app.DisplayAlerts = 0

        presentation = app.Presentations.Open(str(template_path), False, False, True)

        template_slide_count = presentation.Slides.Count

        if template_slide_count == 0:
            raise ValueError("template.pptx にスライドがありません。")

        # 論文数ぶん、テンプレート4枚をコピーして埋める
        for index, paper in enumerate(papers, start=1):
            data = dict(paper)

            if not data.get("paper_no"):
                data["paper_no"] = f"論文{index}"

            for slide_no in range(1, template_slide_count + 1):
                new_slide = copy_slide_to_end(presentation, slide_no)
                fill_slide(new_slide, data)

        # 先頭に残っているテンプレート原本スライドを削除
        for _ in range(template_slide_count):
            presentation.Slides(1).Delete()

        presentation.SaveAs(str(output_path), POWERPOINT_FILE_FORMAT_PPTX)
        print(f"Saved: {output_path}")

    finally:
        if presentation is not None:
            presentation.Close()
        if app is not None:
            app.Quit()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("使い方:")
        print("python make_paper_slides_powerpoint.py template.pptx papers.json output.pptx")
        sys.exit(1)

    make_deck(
        template_path=sys.argv[1],
        json_path=sys.argv[2],
        output_path=sys.argv[3],
    )