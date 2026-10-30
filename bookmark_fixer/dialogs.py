"""Dialogs: edit a bookmark/folder, pick a destination folder, review duplicates."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import tree
from .tree import Node


class EditDialog(QDialog):
    """Title (and URL for bookmarks). Both are required."""

    def __init__(self, parent, heading: str, is_folder: bool, title: str = "", url: str = ""):
        super().__init__(parent)
        self.setWindowTitle(heading)
        self.setMinimumWidth(520)
        form = QFormLayout()
        self.title_edit = QLineEdit(title)
        form.addRow("Name:" if is_folder else "Title:", self.title_edit)
        self.url_edit = None
        if not is_folder:
            self.url_edit = QLineEdit(url)
            form.addRow("URL:", self.url_edit)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        for edit in (self.title_edit, self.url_edit):
            if edit is not None:
                edit.textChanged.connect(self._validate)
        self._validate()
        self.title_edit.selectAll()

    def _validate(self):
        ok = bool(self.title.strip())
        if self.url_edit is not None:
            ok = ok and bool(self.url.strip())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    @property
    def title(self) -> str:
        return self.title_edit.text()

    @property
    def url(self) -> str:
        return self.url_edit.text() if self.url_edit is not None else ""


class MoveToFolderDialog(QDialog):
    """Pick a destination folder. Folders being moved (and their contents) are hidden."""

    def __init__(self, parent, root: Node, moving: list[Node]):
        super().__init__(parent)
        self.setWindowTitle("Move to Folder")
        self.resize(420, 520)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self._nodes: dict[int, Node] = {}

        top = QTreeWidgetItem(["(Top level)"])
        self._nodes[id(top)] = root
        self.tree.addTopLevelItem(top)
        excluded = {id(n) for n in moving}
        self._add_folders(top, root, excluded)
        self.tree.expandAll()
        self.tree.setCurrentItem(top)
        self.tree.itemDoubleClicked.connect(self.accept)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addWidget(buttons)

    def _add_folders(self, item: QTreeWidgetItem, folder: Node, excluded: set[int]):
        icon = self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon)
        for child in folder.children:
            if child.is_folder and id(child) not in excluded:
                child_item = QTreeWidgetItem([child.title])
                child_item.setIcon(0, icon)
                self._nodes[id(child_item)] = child
                item.addChild(child_item)
                self._add_folders(child_item, child, excluded)

    def selected_folder(self) -> Node | None:
        item = self.tree.currentItem()
        return self._nodes.get(id(item)) if item is not None else None


class DuplicatesDialog(QDialog):
    """Lists duplicate groups; the user checks the copies to delete."""

    def __init__(self, parent, groups: list[list[Node]]):
        super().__init__(parent)
        self.setWindowTitle("Find Duplicates")
        self.resize(900, 560)
        self._items: list[tuple[QTreeWidgetItem, Node]] = []
        self._groups: list[list[QTreeWidgetItem]] = []

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Title", "Folder", "URL"])
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for group in groups:
            header = QTreeWidgetItem([f"{tree.normalize_url(group[0].url or '')}  ({len(group)} copies)"])
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(header)
            header.setFirstColumnSpanned(True)
            members = []
            for node in group:
                item = QTreeWidgetItem([node.title, tree.path_of(node) or "(Top level)", node.url or ""])
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                header.addChild(item)
                self._items.append((item, node))
                members.append(item)
            self._groups.append(members)
        self.tree.expandAll()
        for column in (0, 1):
            self.tree.resizeColumnToContents(column)
            self.tree.setColumnWidth(column, min(self.tree.columnWidth(column), 320))

        summary = QLabel(f"{len(groups)} URLs appear more than once "
                         f"({sum(len(g) - 1 for g in groups)} extra copies). "
                         "Check the copies to delete.")
        keep_first = QPushButton("Check all but first of each")
        keep_first.clicked.connect(self._check_all_but_first)
        uncheck = QPushButton("Uncheck all")
        uncheck.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))

        buttons = QDialogButtonBox()
        self.delete_button = buttons.addButton("Delete checked",
                                               QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._confirm)
        buttons.rejected.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(keep_first)
        row.addWidget(uncheck)
        row.addStretch()
        row.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.tree)
        layout.addLayout(row)

    def _set_all(self, state):
        for item, _ in self._items:
            item.setCheckState(0, state)

    def _check_all_but_first(self):
        for members in self._groups:
            for position, item in enumerate(members):
                item.setCheckState(0, Qt.CheckState.Checked if position else Qt.CheckState.Unchecked)

    def _confirm(self):
        whole = sum(1 for members in self._groups
                    if all(i.checkState(0) == Qt.CheckState.Checked for i in members))
        if whole:
            answer = QMessageBox.question(
                self, "Find Duplicates",
                f"Every copy is checked for {whole} URL(s), so they will be removed "
                "completely. Continue?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def checked_nodes(self) -> list[Node]:
        return [node for item, node in self._items
                if item.checkState(0) == Qt.CheckState.Checked]
