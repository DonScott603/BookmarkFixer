# Bookmark Fixer

A small desktop app for cleaning up bookmarks for Chromium-based browsers
(Chrome, Edge, Brave, …). Open an exported bookmarks `.html` file, reorganize
it, and save a new `.html` file to import back into the browser. The browser's
own profile data is never touched.

## Setup

```
pip install -r requirements.txt
python main.py                          # start empty, then File > Open
python main.py merged_bookmarks.html    # open a file directly
```

## Features

| Action | How |
|---|---|
| New folder / bookmark | `Ctrl+Shift+N` / `Ctrl+N`. Added inside the selected folder, or after the selected bookmark |
| Rename / edit | `F2`, `Enter`, or double-click a bookmark |
| Delete | `Del` (asks first if a folder isn't empty) |
| Move | Drag and drop (multi-select works), `Ctrl+M` to pick a folder, `Ctrl+Up` / `Ctrl+Down` to reorder |
| Sort A–Z | Sorts the selected folder (or the folder holding the selected bookmark): folders first, then by title. A second menu item also sorts subfolders |
| Search | `Ctrl+F`, filters by title or URL. Drag and drop is off while filtering, but the other actions still work |
| Find duplicates | Tools menu. URLs are compared ignoring scheme/host case and a trailing `/` |
| Undo / redo | `Ctrl+Z` / `Ctrl+Y`, covers every change (up to 100 steps) |

Save As suggests `<name>_fixed.html` so the original file isn't overwritten by
accident. Icons, dates and other attributes are kept: opening and saving a file
without changes gives a byte-identical copy.

## Importing into the browser

1. Export a backup first: Bookmark manager (`Ctrl+Shift+O`) → ⋮ → **Export bookmarks**.
2. Bookmark manager → ⋮ → **Import bookmarks** → choose the saved file.

Chrome *adds* imported bookmarks to the existing ones. If your bookmarks bar is
empty, the imported "Bookmarks bar" contents go onto the bar. Otherwise they land
in an "Imported" folder. To replace your bookmarks completely, delete the
existing ones first (with sync on, that deletion syncs to other devices too).

## Tests

```
python -m pytest
```

The data layer (`bookmark_fixer/tree.py`, `bookmark_fixer/netscape.py`) has no
Qt dependency and is fully covered by the tests. The GUI lives in `qt_model.py`,
`main_window.py` and `dialogs.py`.
