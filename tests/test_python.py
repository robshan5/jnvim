"""Round-trip tests for the percent format and the .ipynb reader/writer."""

import base64
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "python"))

from jnvim import notebook, percent  # noqa: E402

FAILED = []


def check(name, got, want):
    if got != want:
        FAILED.append("%s\n   got : %r\n   want: %r" % (name, got, want))


# ------------------------------------------------------------------ percent
cells = [
    {"cell_type": "code", "source": "import os\nprint(os.name)"},
    {"cell_type": "markdown", "source": "# Title\n\nsome text"},
    {"cell_type": "code", "source": "x = 1"},
    {"cell_type": "raw", "source": "verbatim"},
]
text = percent.to_text(cells)
check("markers", text.split("\n")[0], "# %%")
check("markdown marker", "# %% [markdown]" in text, True)
check("markdown is commented", "# # Title" in text, True)
check("raw marker", "# %% [raw]" in text, True)

back = percent.from_text(text)
check("round-trip count", len(back), 4)
for index, cell in enumerate(cells):
    check("round-trip cell %d type" % index, back[index]["cell_type"], cell["cell_type"])
    check("round-trip cell %d source" % index, back[index]["source"], cell["source"])

check("blank line between cells", "\n\n# %%" in text, True)
check("leading text becomes a cell", percent.from_text("a = 1\n"),
      [{"cell_type": "code", "source": "a = 1"}])
check("empty text", percent.from_text(""), [{"cell_type": "code", "source": ""}])
check("bare marker", percent.from_text("#%%\nx"), [{"cell_type": "code", "source": "x"}])
check("md alias", percent.from_text("# %% [md]\n# hi")[0]["cell_type"], "markdown")
check("comment char", percent.comment_char("javascript"), "//")
check("js marker", percent.to_text([{"cell_type": "code", "source": "1"}], "javascript"),
      "// %%\n1")
check("indented comment kept",
      percent.from_text("# %% [markdown]\n#     indented")[0]["source"], "    indented")

# ----------------------------------------------------------------- notebook
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "demo.ipynb")
    doc = {
        "cells": [
            {"cell_type": "code", "source": "print('hi')", "execution_count": 1,
             "outputs": [{"output_type": "stream", "name": "stdout", "text": "hi\n"}]},
            {"cell_type": "markdown", "source": "# title"},
        ],
        "metadata": {"kernelspec": {"name": "python3", "language": "python"}},
    }
    notebook.write(path, doc)
    raw = json.load(open(path, encoding="utf-8"))
    check("nbformat", raw["nbformat"], 4)
    check("source split", raw["cells"][0]["source"], ["print('hi')"])
    check("markdown has no outputs", "outputs" in raw["cells"][1], False)

    again = notebook.read(path)
    check("read cells", len(again["cells"]), 2)
    check("read source", again["cells"][0]["source"], "print('hi')")
    check("language", notebook.language(again["metadata"]), "python")
    check("kernel", notebook.kernel_name(again["metadata"]), "python3")
    check("output lines", notebook.output_lines(again["cells"][0]["outputs"]), [["hi", "stream"]])

    check("missing file", notebook.read(os.path.join(tmp, "nope.ipynb"))["cells"], [])

check("ansi stripped", notebook.output_lines([
    {"output_type": "error", "ename": "ValueError", "evalue": "bad",
     "traceback": ["\x1b[31mValueError\x1b[0m: bad"]}]), [["ValueError: bad", "err"]])
check("image placeholder without a cache dir", notebook.output_lines([
    {"output_type": "display_data", "data": {"image/png": "x" * 2048}}]),
    [["[image/png 2.0 KB]", "image"]])
check("unknown mime", notebook.output_lines([
    {"output_type": "display_data", "data": {"application/pdf": "x" * 1024}}]),
    [["[application/pdf 1.0 KB]", "out"]])

# ------------------------------------------------------------------- images
# a 2x1 red/blue PNG
PNG = base64.b64encode(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAIAAAB7QOjdAAAAEklEQVR4nGP8z4AAT"
    "AxQxlAVAgCj0QIDaT2vJwAAAABJRU5ErkJggg==")).decode()

with tempfile.TemporaryDirectory() as tmp:
    lines = notebook.output_lines([
        {"output_type": "display_data", "data": {"image/png": PNG, "text/plain": "<Figure>"}},
    ], tmp)
    check("image then text", [line[1] for line in lines], ["image", "out"])
    info = lines[0][2]
    check("size parsed", (info["width"], info["height"]), (2, 1))
    check("label", lines[0][0], "[image/png 2x1]")
    check("file written", os.path.exists(info["path"]), True)
    check("file is a png", open(info["path"], "rb").read(4), b"\x89PNG")
    check("text kept", lines[1][0], "<Figure>")

    again = notebook.output_lines([
        {"output_type": "display_data", "data": {"image/png": PNG}}], tmp)
    check("same bytes reuse the same file", again[0][2]["path"], info["path"])
    check("one file on disk", len(os.listdir(tmp)), 1)

    svg = notebook.output_lines([
        {"output_type": "display_data", "data": {"image/svg+xml": "<svg/>"}}], tmp)
    check("svg saved", svg[0][2]["path"].endswith(".svg"), True)

    check("broken base64 is ignored", notebook.save_image("image/png", "not base64 !!", tmp), None)

check("gif size", notebook.image_size(b"GIF89a\x40\x00\x30\x00rest"), (64, 48))
check("not an image", notebook.image_size(b"nope"), None)

if FAILED:
    print("FAILED %d check(s):\n" % len(FAILED))
    print("\n\n".join(FAILED))
    raise SystemExit(1)
print("python tests passed")
