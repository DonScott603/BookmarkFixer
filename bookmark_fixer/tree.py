"""Bookmark tree data model and editing operations.

Pure Python with no Qt dependency, so everything here is unit-testable.
Nodes compare by identity (``eq=False``) so duplicate bookmarks with equal
fields are still distinct items in lists.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Iterator
from urllib.parse import urlsplit, urlunsplit


def now() -> str:
    """Current time in the seconds-since-epoch string format bookmark files use."""
    return str(int(time.time()))


@dataclass(eq=False)
class Node:
    title: str = ""
    url: str | None = None  # None means this node is a folder
    add_date: str | None = None
    last_modified: str | None = None
    icon: str | None = None  # data URI, e.g. "data:image/png;base64,..."
    extra_attrs: dict[str, str] = field(default_factory=dict)
    children: list[Node] = field(default_factory=list)
    parent: Node | None = field(default=None, repr=False)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def is_folder(self) -> bool:
        return self.url is None


def new_folder(title: str) -> Node:
    stamp = now()
    return Node(title=title, add_date=stamp, last_modified=stamp)


def new_bookmark(title: str, url: str) -> Node:
    return Node(title=title, url=url, add_date=now())


def _touch(folder: Node | None) -> None:
    # Only refresh folders that already carry a timestamp; the root and the
    # toolbar folder in Chrome exports have none.
    if folder is not None and folder.last_modified is not None:
        folder.last_modified = now()


# --- Traversal ---------------------------------------------------------------

def iter_nodes(root: Node) -> Iterator[Node]:
    """All descendants of ``root`` in document (pre-)order, excluding root."""
    for child in root.children:
        yield child
        if child.is_folder:
            yield from iter_nodes(child)


def find_by_id(root: Node, node_id: str) -> Node | None:
    if root.id == node_id:
        return root
    for node in iter_nodes(root):
        if node.id == node_id:
            return node
    return None


def is_ancestor(ancestor: Node, node: Node) -> bool:
    """True if ``ancestor`` is a strict ancestor of ``node``."""
    current = node.parent
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def index_path(node: Node) -> tuple[int, ...]:
    """Child indices from the root down to ``node``; sorts in document order."""
    path = []
    while node.parent is not None:
        path.append(node.parent.children.index(node))
        node = node.parent
    return tuple(reversed(path))


def path_of(node: Node) -> str:
    """Folder path of ``node`` (excluding the root and the node itself)."""
    titles = []
    current = node.parent
    while current is not None and current.parent is not None:
        titles.append(current.title)
        current = current.parent
    return " / ".join(reversed(titles))


def counts(root: Node) -> tuple[int, int]:
    """(folder count, bookmark count) below ``root``."""
    folders = bookmarks = 0
    for node in iter_nodes(root):
        if node.is_folder:
            folders += 1
        else:
            bookmarks += 1
    return folders, bookmarks


def top_level(nodes: Iterable[Node]) -> list[Node]:
    """Drop nodes whose ancestor is also in ``nodes``; return in document order."""
    nodes = list(dict.fromkeys(nodes))
    kept = [n for n in nodes if not any(is_ancestor(other, n) for other in nodes)]
    return sorted(kept, key=index_path)


# --- Mutations ---------------------------------------------------------------

def add_child(parent: Node, node: Node, index: int | None = None) -> None:
    if not parent.is_folder:
        raise ValueError("Bookmarks can only be added to folders.")
    if node.parent is not None:
        remove(node)
    if index is None:
        parent.children.append(node)
    else:
        parent.children.insert(index, node)
    node.parent = parent
    _touch(parent)


def remove(node: Node) -> None:
    parent = node.parent
    if parent is None:
        raise ValueError("The root cannot be removed.")
    parent.children.remove(node)
    node.parent = None
    _touch(parent)


def move(nodes: Iterable[Node], new_parent: Node, index: int | None = None) -> list[Node]:
    """Move ``nodes`` into ``new_parent`` before position ``index`` (None = end).

    ``index`` refers to positions in ``new_parent`` *before* the move, which is
    what a drop indicator shows. Validates everything before mutating anything.
    Returns the moved nodes in their new order.
    """
    if not new_parent.is_folder:
        raise ValueError("Items can only be moved into folders.")
    moving = top_level(nodes)
    for node in moving:
        if node.parent is None:
            raise ValueError("The root cannot be moved.")
        if node is new_parent or is_ancestor(node, new_parent):
            raise ValueError(f"Cannot move folder \"{node.title}\" into itself.")

    if index is None:
        index = len(new_parent.children)
    # Items leaving positions in front of the insertion point shift it left.
    index -= sum(1 for n in moving
                 if n.parent is new_parent and new_parent.children.index(n) < index)

    for node in moving:
        remove(node)
    for offset, node in enumerate(moving):
        add_child(new_parent, node, index + offset)
    return moving


def shift(nodes: Iterable[Node], delta: int) -> bool:
    """Move each node one place up (delta=-1) or down (delta=+1) among its siblings.

    A contiguous selection moves as a block. Returns True if anything moved.
    """
    if delta not in (-1, 1):
        raise ValueError("delta must be -1 or 1")
    moving = top_level(nodes)
    moving_ids = {id(n) for n in moving}
    if delta > 0:
        moving.reverse()
    changed = False
    for node in moving:
        assert node.parent is not None
        siblings = node.parent.children
        i = siblings.index(node)
        j = i + delta
        if 0 <= j < len(siblings) and id(siblings[j]) not in moving_ids:
            siblings[i], siblings[j] = siblings[j], siblings[i]
            _touch(node.parent)
            changed = True
    return changed


def sort_folder(folder: Node, recursive: bool = False) -> None:
    """Sort children: folders first, then case-insensitively by title."""
    folder.children.sort(key=lambda n: (not n.is_folder, n.title.casefold()))
    _touch(folder)
    if recursive:
        for child in folder.children:
            if child.is_folder:
                sort_folder(child, recursive=True)


# --- Duplicates --------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Comparison key: lower-cased scheme and host, no trailing slash on the path."""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(),
                       parts.path.rstrip("/"), parts.query, parts.fragment))


def find_duplicates(root: Node) -> list[list[Node]]:
    """Groups of bookmarks sharing a normalized URL, in document order."""
    groups: dict[str, list[Node]] = {}
    for node in iter_nodes(root):
        if node.url is not None:
            groups.setdefault(normalize_url(node.url), []).append(node)
    return [group for group in groups.values() if len(group) > 1]
