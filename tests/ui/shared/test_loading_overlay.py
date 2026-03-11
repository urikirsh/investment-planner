from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ui.shared.loading_overlay import LoadingOverlay


def test_loading_overlay_tracks_parent_geometry(qapp: object) -> None:
    _ = qapp
    parent = QWidget()
    parent.resize(320, 240)
    overlay = LoadingOverlay(parent)

    assert overlay.geometry() == parent.rect()

    parent.resize(640, 400)
    overlay.show_overlay()

    assert overlay.geometry() == parent.rect()


def test_loading_overlay_show_hide_and_spinner_size(qapp: object) -> None:
    _ = qapp
    parent = QWidget()
    overlay = LoadingOverlay(parent)

    overlay.show_overlay()
    assert not overlay.isHidden()
    assert overlay._spinner.width() >= 120
    assert overlay._status_label.text() == "fetching data"
    assert "font-size: 34px" in overlay._status_label.styleSheet()

    overlay.hide_overlay()
    assert overlay.isHidden()
