"""Main window: bookmark tree, search box, menus/toolbar, undo/redo."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHeaderView, QInputDialog,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QTreeView)

from . import netscape, tree
from .dialogs import DuplicatesDialog, EditDialog, MoveToFolderDialog
from .qt_model import BookmarkModel
from .tree import Node

APP_NAME = "Bookmark Fixer"
UNDO_LIMIT = 100
FILE_FILTER = "Bookmark files (*.html *.htm);;All files (*)"

# Returned by an ``apply`` function to signal that nothing changed.
UNCHANGED = object()


def empty_tree() -> Node:
    root = Node(title="Bookmarks")
    bar = Node(title="Bookmarks bar", extra_attrs={"PERSONAL_TOOLBAR_FOLDER": "true"})
    tree.add_child(root, bar)
    return root


class MainWindow(QMainWindow):
    def __init__(self, path: str | None = None):
        super().__init__()
        self.root = empty_tree()
        self.path: Path | None = None
        self.dirty = False
        self.undo_stack: list[tuple[str, Node]] = []
        self.redo_stack: list[tuple[str, Node]] = []
        self._expanded_before_filter: set[str] | None = None

        self.model = BookmarkModel(self.root, self._on_drop, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setAutoAcceptChildRows(True)

        self.view = QTreeView()
        self.view.setModel(self.proxy)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.view.setDropIndicatorShown(True)
        self.view.setUniformRowHeights(True)
        self.view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.view.header().setStretchLastSection(True)
        self.view.setColumnWidth(0, 420)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.doubleClicked.connect(self._on_double_click)
        self.view.selectionModel().selectionChanged.connect(self._update_actions)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self.view, self.edit_selected,
                  context=Qt.ShortcutContext.WidgetShortcut)
        self.setCentralWidget(self.view)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search titles and URLs…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(360)
        self.search.textChanged.connect(self._on_search)
        QShortcut(QKeySequence.StandardKey.Find, self, self.search.setFocus)

        self._create_actions()
        self.resize(1100, 750)
        if path:
            self.open_path(Path(path))
        else:
            self._refresh()

    # --- Actions / menus -------------------------------------------------

    def _action(self, text: str, slot: Callable, shortcut=None, tip: str = "") -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setStatusTip(tip)
        action.triggered.connect(slot)
        return action

    def _create_actions(self):
        S = QKeySequence.StandardKey
        self.open_action = self._action("&Open…", self.open_file, S.Open)
        self.save_action = self._action("&Save", self.save, S.Save)
        self.save_as_action = self._action("Save &As…", self.save_as, "Ctrl+Shift+S")
        self.exit_action = self._action("E&xit", self.close)

        self.undo_action = self._action("&Undo", self.undo, S.Undo)
        self.redo_action = self._action("&Redo", self.redo, "Ctrl+Y")
        self.new_folder_action = self._action("New &Folder…", self.new_folder, "Ctrl+Shift+N")
        self.new_bookmark_action = self._action("New &Bookmark…", self.new_bookmark, "Ctrl+N")
        self.edit_action = self._action("&Edit…", self.edit_selected, "F2",
                                        "Rename / edit the selected item")
        self.delete_action = self._action("&Delete", self.delete_selected, S.Delete)
        self.move_to_action = self._action("&Move to Folder…", self.move_to_folder, "Ctrl+M")
        self.move_up_action = self._action("Move &Up", lambda: self.shift_selected(-1), "Ctrl+Up")
        self.move_down_action = self._action("Move Do&wn", lambda: self.shift_selected(1),
                                             "Ctrl+Down")
        self.sort_action = self._action("&Sort Folder A–Z", lambda: self.sort_folder(False),
                                        tip="Folders first, then by title")
        self.sort_all_action = self._action("Sort Folder A–Z (&Including Subfolders)",
                                            lambda: self.sort_folder(True))
        self.duplicates_action = self._action("Find &Duplicates…", self.find_duplicates)
        self.expand_action = self._action("E&xpand All", self.view.expandAll)
        self.collapse_action = self._action("&Collapse All", self.view.collapseAll)

        menu = self.menuBar().addMenu("&File")
        menu.addActions([self.open_action, self.save_action, self.save_as_action])
        menu.addSeparator()
        menu.addAction(self.exit_action)

        menu = self.menuBar().addMenu("&Edit")
        menu.addActions([self.undo_action, self.redo_action])
        menu.addSeparator()
        self._add_item_actions(menu)

        menu = self.menuBar().addMenu("&View")
        menu.addActions([self.expand_action, self.collapse_action])

        menu = self.menuBar().addMenu("&Tools")
        menu.addAction(self.duplicates_action)

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        toolbar.addActions([self.open_action, self.save_action, self.save_as_action])
        toolbar.addSeparator()
        toolbar.addActions([self.undo_action, self.redo_action])
        toolbar.addSeparator()
        toolbar.addActions([self.new_folder_action, self.new_bookmark_action, self.edit_action,
                            self.delete_action, self.move_to_action, self.move_up_action,
                            self.move_down_action, self.sort_action])
        toolbar.addSeparator()
        toolbar.addAction(self.duplicates_action)
        toolbar.addSeparator()
        toolbar.addWidget(self.search)

    def _item_actions(self) -> list[QAction | None]:
        return [self.new_folder_action, self.new_bookmark_action, None,
                self.edit_action, self.delete_action, None,
                self.move_to_action, self.move_up_action, self.move_down_action, None,
                self.sort_action, self.sort_all_action]

    def _add_item_actions(self, menu: QMenu):
        for action in self._item_actions():
            if action is None:
                menu.addSeparator()
            else:
                menu.addAction(action)

    def _context_menu(self, pos):
        menu = QMenu(self)
        self._add_item_actions(menu)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _update_actions(self):
        selected = self.selected_nodes()
        self.edit_action.setEnabled(len(selected) == 1)
        for action in (self.delete_action, self.move_to_action,
                       self.move_up_action, self.move_down_action):
            action.setEnabled(bool(selected))
        for action, stack, verb in ((self.undo_action, self.undo_stack, "Undo"),
                                    (self.redo_action, self.redo_stack, "Redo")):
            action.setEnabled(bool(stack))
            action.setText(f"&{verb} {stack[-1][0]}" if stack else f"&{verb}")

    # --- Selection helpers -----------------------------------------------

    def _view_index(self, node: Node) -> QModelIndex:
        return self.proxy.mapFromSource(self.model.index_for(node))

    def selected_nodes(self) -> list[Node]:
        rows = self.view.selectionModel().selectedRows(0)
        nodes = [self.model.node(self.proxy.mapToSource(i)) for i in rows]
        return sorted(nodes, key=tree.index_path)

    def current_node(self) -> Node | None:
        index = self.view.currentIndex()
        if not index.isValid() or not self.view.selectionModel().isSelected(index):
            return None
        return self.model.node(self.proxy.mapToSource(index))

    def _insertion_point(self) -> tuple[Node, int | None]:
        """Inside the current folder, or just after the current bookmark."""
        node = self.current_node()
        if node is None:
            return self.root, None
        if node.is_folder:
            return node, None
        assert node.parent is not None
        return node.parent, node.parent.children.index(node) + 1

    def _target_folder(self) -> Node:
        node = self.current_node()
        if node is None:
            return self.root
        return node if node.is_folder else (node.parent or self.root)

    # --- Core edit/undo machinery ----------------------------------------

    def apply(self, description: str, fn: Callable[[], object]) -> None:
        """Run an edit with undo support.

        ``fn`` mutates ``self.root`` and returns nodes to select, ``None`` to
        keep the current selection, or ``UNCHANGED`` if it did nothing.
        """
        snapshot = copy.deepcopy(self.root)
        try:
            result = fn()
        except ValueError as error:
            QMessageBox.warning(self, APP_NAME, str(error))
            return
        if result is UNCHANGED:
            return
        self.undo_stack.append((description, snapshot))
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()
        self.dirty = True
        select = None if result is None else [n.id for n in result]  # type: ignore[union-attr]
        self._refresh(select)

    def _swap_state(self, source: list, target: list) -> None:
        description, snapshot = source.pop()
        target.append((description, self.root))
        self.root = snapshot
        self.dirty = True
        self._refresh()

    def undo(self):
        if self.undo_stack:
            self._swap_state(self.undo_stack, self.redo_stack)

    def redo(self):
        if self.redo_stack:
            self._swap_state(self.redo_stack, self.undo_stack)

    def _expanded_ids(self) -> set[str]:
        return {n.id for n in tree.iter_nodes(self.model.root)
                if n.is_folder and self.view.isExpanded(self._view_index(n))}

    def _refresh(self, select_ids: list[str] | None = None, expanded: set[str] | None = None):
        """Reset the model to ``self.root``, keeping expansion and selection by id."""
        if expanded is None:
            expanded = self._expanded_ids()
        if select_ids is None:
            select_ids = [n.id for n in self.selected_nodes()]
        self.model.set_root(self.root)

        selected = [n for n in (tree.find_by_id(self.root, i) for i in select_ids) if n]
        for node in selected:
            parent = node.parent
            while parent is not None:
                expanded.add(parent.id)
                parent = parent.parent
        if self.search.text():
            self.view.expandAll()
        else:
            for node in tree.iter_nodes(self.root):
                if node.is_folder and node.id in expanded:
                    self.view.expand(self._view_index(node))

        selection = self.view.selectionModel()
        selection.clearSelection()
        flags = (QItemSelectionModel.SelectionFlag.Select
                 | QItemSelectionModel.SelectionFlag.Rows)
        for node in selected:
            selection.select(self._view_index(node), flags)
        if selected:
            index = self._view_index(selected[0])
            selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.view.scrollTo(index)
        self._update_title()
        self._update_actions()

    def _update_title(self):
        name = self.path.name if self.path else "Untitled"
        self.setWindowTitle(f"{name}{' *' if self.dirty else ''} — {APP_NAME}")
        folders, bookmarks = tree.counts(self.root)
        where = str(self.path) if self.path else "not saved yet"
        self.statusBar().showMessage(f"{folders} folders, {bookmarks} bookmarks   |   {where}")

    # --- Edit commands ---------------------------------------------------

    def new_folder(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name.strip():
            return
        parent, index = self._insertion_point()
        folder = tree.new_folder(name.strip())

        def do():
            tree.add_child(parent, folder, index)
            return [folder]
        self.apply("New Folder", do)

    def new_bookmark(self):
        dialog = EditDialog(self, "New Bookmark", is_folder=False, url="https://")
        if not dialog.exec():
            return
        parent, index = self._insertion_point()
        bookmark = tree.new_bookmark(dialog.title.strip(), dialog.url.strip())

        def do():
            tree.add_child(parent, bookmark, index)
            return [bookmark]
        self.apply("New Bookmark", do)

    def edit_selected(self):
        selected = self.selected_nodes()
        if len(selected) != 1:
            return
        node = selected[0]
        kind = "Folder" if node.is_folder else "Bookmark"
        dialog = EditDialog(self, f"Edit {kind}", node.is_folder, node.title, node.url or "")
        if not dialog.exec():
            return
        title, url = dialog.title.strip(), dialog.url.strip()
        if title == node.title and (node.is_folder or url == node.url):
            return

        def do():
            node.title = title
            if not node.is_folder:
                node.url = url
            return [node]
        self.apply(f"Edit {kind}", do)

    def _on_double_click(self, index: QModelIndex):
        if not self.model.node(self.proxy.mapToSource(index)).is_folder:
            self.edit_selected()

    def delete_selected(self):
        nodes = tree.top_level(self.selected_nodes())
        if not nodes:
            return
        inside = sum(1 for n in nodes if n.is_folder for _ in tree.iter_nodes(n))
        if inside:
            answer = QMessageBox.question(
                self, "Delete",
                f"Delete {len(nodes)} selected item(s), including {inside} item(s) "
                "inside folders?\n\nYou can undo this with Ctrl+Z.")
            if answer != QMessageBox.StandardButton.Yes:
                return

        def do():
            # Afterwards select whatever now sits where the first item was.
            first = nodes[0]
            parent = first.parent
            assert parent is not None
            position = parent.children.index(first)
            for node in nodes:
                tree.remove(node)
            if parent.children:
                return [parent.children[min(position, len(parent.children) - 1)]]
            return [parent] if parent is not self.root else []
        self.apply("Delete", do)

    def move_to_folder(self):
        nodes = tree.top_level(self.selected_nodes())
        if not nodes:
            return
        dialog = MoveToFolderDialog(self, self.root, nodes)
        if not dialog.exec():
            return
        folder = dialog.selected_folder()
        if folder is None:
            return
        self.apply("Move", lambda: tree.move(nodes, folder))

    def shift_selected(self, delta: int):
        nodes = self.selected_nodes()
        if nodes:
            self.apply("Move Up" if delta < 0 else "Move Down",
                       lambda: None if tree.shift(nodes, delta) else UNCHANGED)

    def sort_folder(self, recursive: bool):
        folder = self._target_folder()

        def do():
            tree.sort_folder(folder, recursive)
        self.apply("Sort", do)

    def find_duplicates(self):
        groups = tree.find_duplicates(self.root)
        if not groups:
            QMessageBox.information(self, "Find Duplicates", "No duplicate URLs found.")
            return
        dialog = DuplicatesDialog(self, groups)
        if not dialog.exec():
            return
        doomed = dialog.checked_nodes()
        if not doomed:
            return

        def do():
            for node in doomed:
                tree.remove(node)
            return []
        self.apply("Delete Duplicates", do)

    def _on_drop(self, ids: list[str], folder: Node, row: int | None):
        # ``folder`` comes from the live model, so it belongs to self.root.
        nodes = [n for n in (tree.find_by_id(self.root, i) for i in ids) if n]
        if nodes:
            self.apply("Move", lambda: tree.move(nodes, folder, row))

    # --- Search ----------------------------------------------------------

    def _on_search(self, text: str):
        if text and self._expanded_before_filter is None:
            self._expanded_before_filter = self._expanded_ids()
        self.proxy.setFilterFixedString(text)
        if text:
            self.view.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            self.view.expandAll()
        else:
            self.view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            expanded = self._expanded_before_filter or set()
            self._expanded_before_filter = None
            self._refresh(expanded=expanded)

    # --- Files -----------------------------------------------------------

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, APP_NAME, "Save changes before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    def open_file(self):
        if not self._confirm_discard():
            return
        start = str(self.path.parent) if self.path else ""
        name, _ = QFileDialog.getOpenFileName(self, "Open Bookmarks", start, FILE_FILTER)
        if name:
            self.open_path(Path(name))

    def open_path(self, path: Path):
        try:
            root = netscape.load(path)
        except OSError as error:
            QMessageBox.critical(self, APP_NAME, f"Could not open {path}:\n{error}")
            return
        self.root = root
        self.path = path
        self.dirty = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.search.clear()
        # Start with the top-level folders (e.g. the bookmarks bar) open.
        top = {n.id for n in root.children if n.is_folder}
        self._refresh(select_ids=[], expanded=top)

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        if self.path is not None:
            suggestion = self.path.with_name(f"{self.path.stem}_fixed{self.path.suffix}")
        else:
            suggestion = Path("bookmarks.html")
        name, _ = QFileDialog.getSaveFileName(self, "Save Bookmarks As", str(suggestion),
                                              FILE_FILTER)
        if not name:
            return False
        return self._write(Path(name))

    def _write(self, path: Path) -> bool:
        try:
            netscape.save(self.root, path)
        except OSError as error:
            QMessageBox.critical(self, APP_NAME, f"Could not save {path}:\n{error}")
            return False
        self.path = path
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 5000)
        return True

    def closeEvent(self, event):
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
