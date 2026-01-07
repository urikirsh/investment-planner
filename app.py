import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    win = MainWindow(json_path="portfolio.json")
    win.resize(1100, 650)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
