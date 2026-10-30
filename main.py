"""Bookmark Fixer: edit a Chromium bookmark export (HTML) and save a new one.

Usage: python main.py [bookmarks.html]
"""
import sys

from PySide6.QtWidgets import QApplication

from bookmark_fixer.main_window import APP_NAME, MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
