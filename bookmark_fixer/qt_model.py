"""Qt item model exposing a bookmark tree to QTreeView, with drag-and-drop moves."""
from __future__ import annotations

import base64
from typing import Callable

from PySide6.QtCore import QAbstractItemModel, QMimeData, QModelIndex, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QStyle

from .tree import Node

MIME_TYPE = "application/x-bookmarkfixer-node-ids"
COLUMNS = ("Title", "URL")

_icon_cache: dict[str, QIcon | None] = {}


def favicon(data_uri: str | None) -> QIcon | None:
    """Decode an ICON data URI into a QIcon (cached); None if missing or bad."""
    if not data_uri:
        return None
    if data_uri not in _icon_cache:
        icon = None
        header, _, payload = data_uri.partition(",")
        if header.startswith("data:") and header.endswith(";base64"):
            pixmap = QPixmap()
            try:
                if pixmap.loadFromData(base64.b64decode(payload)):
                    icon = QIcon(pixmap)
            except ValueError:
                pass
        _icon_cache[data_uri] = icon
    return _icon_cache[data_uri]


class BookmarkModel(QAbstractItemModel):
    """Read-only view of the tree; all edits go through the main window.

    ``on_drop(ids, folder, row)`` is called (deferred to the event loop) when
    items are dropped; ``row`` is None for "append to folder".
    """

    def __init__(self, root: Node, on_drop: Callable[[list[str], Node, int | None], None],
                 parent=None):
        super().__init__(parent)
        self.root = root
        self.on_drop = on_drop
        style = QApplication.style()
        self.folder_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self.page_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)

    def set_root(self, root: Node) -> None:
        self.beginResetModel()
        self.root = root
        self.endResetModel()

    def node(self, index: QModelIndex) -> Node:
        return index.internalPointer() if index.isValid() else self.root

    def index_for(self, node: Node | None) -> QModelIndex:
        if node is None or node is self.root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.parent.children.index(node), 0, node)

    # --- Structure -------------------------------------------------------

    def index(self, row, column, parent=QModelIndex()):
        folder = self.node(parent)
        if 0 <= row < len(folder.children) and 0 <= column < len(COLUMNS):
            return self.createIndex(row, column, folder.children[row])
        return QModelIndex()

    def parent(self, index=None):
        if index is None:  # QObject.parent()
            return super().parent()
        if not index.isValid():
            return QModelIndex()
        return self.index_for(self.node(index).parent)

    def rowCount(self, parent=QModelIndex()):
        if parent.column() > 0:
            return 0
        node = self.node(parent)
        return len(node.children) if node.is_folder else 0

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def hasChildren(self, parent=QModelIndex()):
        return self.rowCount(parent) > 0

    # --- Data ------------------------------------------------------------

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = self.node(index)
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return node.title
            return "" if node.is_folder else node.url
        if role == Qt.ItemDataRole.DecorationRole and column == 0:
            if node.is_folder:
                return self.folder_icon
            return favicon(node.icon) or self.page_icon
        if role == Qt.ItemDataRole.ToolTipRole and not node.is_folder:
            return f"{node.title}\n{node.url}"
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                 | Qt.ItemFlag.ItemIsDragEnabled)
        if self.node(index).is_folder:
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        return flags

    # --- Drag and drop ---------------------------------------------------

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self):
        return [MIME_TYPE]

    def mimeData(self, indexes):
        ids = list(dict.fromkeys(self.node(i).id for i in indexes if i.isValid()))
        mime = QMimeData()
        mime.setData(MIME_TYPE, "\n".join(ids).encode("ascii"))
        return mime

    def dropMimeData(self, data, action, row, column, parent):
        if action != Qt.DropAction.MoveAction or not data.hasFormat(MIME_TYPE):
            return False
        ids = bytes(data.data(MIME_TYPE)).decode("ascii").split()
        folder = self.node(parent)
        target_row = row if row >= 0 else None
        # Defer: the model is reset by the move, which must not happen while
        # the view is still processing the drop event.
        QTimer.singleShot(0, lambda: self.on_drop(ids, folder, target_row))
        # Returning False stops the view from removing the source rows itself.
        return False
