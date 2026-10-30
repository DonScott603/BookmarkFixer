"""Read and write Netscape-format bookmark HTML, as exported by Chromium browsers."""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from pathlib import Path

from .tree import Node

HEADER = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file.
     It will be read and overwritten.
     DO NOT EDIT! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
"""

# Attributes mapped to Node fields; anything else is kept in Node.extra_attrs.
_FIELD_ATTRS = {"HREF": "url", "ADD_DATE": "add_date",
                "LAST_MODIFIED": "last_modified", "ICON": "icon"}


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(title="Bookmarks")
        self.stack = [self.root]
        self.pending_folder: Node | None = None  # an <H3> waiting for its <DL>
        self.capture: Node | None = None  # node whose title text is being read
        self.in_h1 = False
        self.h1_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.in_h1 = True
        elif tag in ("h3", "a"):
            node = Node(url="" if tag == "a" else None)
            for name, value in attrs:
                name = name.upper()
                value = value or ""
                if name in _FIELD_ATTRS:
                    if name == "HREF" and tag != "a":
                        continue
                    setattr(node, _FIELD_ATTRS[name], value)
                else:
                    node.extra_attrs[name] = value
            parent = self.stack[-1]
            node.parent = parent
            parent.children.append(node)
            self.capture = node
            if tag == "h3":
                self.pending_folder = node
        elif tag == "dl":
            # The outermost <DL> (and any stray one) belongs to the current folder.
            self.stack.append(self.pending_folder or self.stack[-1])
            self.pending_folder = None

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_h1 = False
        elif tag in ("h3", "a"):
            self.capture = None
        elif tag == "dl":
            if len(self.stack) > 1:
                self.stack.pop()
            self.pending_folder = None

    def handle_data(self, data):
        if self.capture is not None:
            self.capture.title += data
        elif self.in_h1:
            self.h1_text += data


def parse(text: str) -> Node:
    parser = _Parser()
    parser.feed(text)
    parser.close()
    if parser.h1_text.strip():
        parser.root.title = parser.h1_text.strip()
    return parser.root


def _attrs(node: Node) -> str:
    pairs = []
    if not node.is_folder:
        pairs.append(("HREF", node.url))
    pairs += [("ADD_DATE", node.add_date), ("LAST_MODIFIED", node.last_modified),
              ("ICON", node.icon)]
    pairs += list(node.extra_attrs.items())
    return "".join(f' {name}="{escape(value)}"' for name, value in pairs if value is not None)


def _write_children(folder: Node, depth: int, out: list[str]) -> None:
    pad = "    " * depth
    for node in folder.children:
        if node.is_folder:
            out.append(f"{pad}<DT><H3{_attrs(node)}>{escape(node.title)}</H3>\n")
            out.append(f"{pad}<DL><p>\n")
            _write_children(node, depth + 1, out)
            out.append(f"{pad}</DL><p>\n")
        else:
            out.append(f"{pad}<DT><A{_attrs(node)}>{escape(node.title)}</A>\n")


def write(root: Node) -> str:
    out = [HEADER, f"<H1>{escape(root.title)}</H1>\n", "<DL><p>\n"]
    _write_children(root, 1, out)
    out.append("</DL><p>\n")
    return "".join(out)


def load(path: str | Path) -> Node:
    data = Path(path).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return parse(text)


def save(root: Node, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(write(root))
