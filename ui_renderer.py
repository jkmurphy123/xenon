# ui_renderer.py
import os
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect, QEasingCurve, QPropertyAnimation
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QTextBrowser, QStatusBar,
    QApplication, QGraphicsOpacityEffect
)

class UIRenderer(QWidget):
    chunkPlaybackFinished = pyqtSignal()

    def __init__(self, config_ui: dict):
        super().__init__()
        self.ui_cfg = config_ui
        self.design_w = int(self.ui_cfg.get("screen_width", 1024))
        self.design_h = int(self.ui_cfg.get("screen_height", 768))
        self.chunk_duration_s = int(self.ui_cfg.get("chunk_duration_s", 30))
        self.fade_ms = int(self.ui_cfg.get("fade_ms", 600))

        self.setWindowTitle(self.ui_cfg.get("window_title", "LLM Streamer"))
        self.resize(self.design_w, self.design_h)

        # Root layout
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)

        # Background label
        self.bg_label = QLabel()
        self.bg_label.setAlignment(Qt.AlignCenter)
        self.bg_label.setStyleSheet("background-color: black;")
        self.root.addWidget(self.bg_label, 1)

        # Overlay container (balloon)
        self.overlay = QWidget(self.bg_label)
        self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.overlay_layout = QVBoxLayout(self.overlay)
        self.overlay_layout.setContentsMargins(0, 0, 0, 0)

        self.balloon = QTextBrowser(self.overlay)
        self.balloon.setOpenExternalLinks(False)
        self.balloon.setReadOnly(True)
        self.balloon.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.balloon.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.balloon.setAlignment(Qt.AlignCenter)  # horizontal center
        # Styling
        rounding = int(self.ui_cfg.get("balloon_rounding_px", 24))
        opacity = float(self.ui_cfg.get("balloon_opacity", 0.96))
        bg_rgba = f"rgba(255,255,255,{opacity})"
        self.balloon.setStyleSheet(
            f"QTextBrowser{{background:{bg_rgba}; border: none; border-radius:{rounding}px; padding:20px;}}"
        )
        # Font
        f = QFont(self.ui_cfg.get("font_family", "DejaVu Sans"))
        f.setPointSize(int(self.ui_cfg.get("font_point_size", 16)))
        self.balloon.setFont(f)

        self.overlay_layout.addWidget(self.balloon)

        # Opacity for fades
        self.opacity = QGraphicsOpacityEffect(self.balloon)
        self.balloon.setGraphicsEffect(self.opacity)
        self.opacity.setOpacity(1.0)

        # Status bar
        self.status = QStatusBar()
        self.status.setStyleSheet(self.ui_cfg.get("status_style", ""))
        self.root.addWidget(self.status)

        # Animations
        self.fade_out = QPropertyAnimation(self.opacity, b"opacity")
        self.fade_out.setDuration(self.fade_ms)
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QEasingCurve.InOutQuad)

        self.fade_in = QPropertyAnimation(self.opacity, b"opacity")
        self.fade_in.setDuration(self.fade_ms)
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.setEasingCurve(QEasingCurve.InOutQuad)

        self.chunks = []
        self._chunk_idx = -1
        self._rect_design = QRect(80, 80, 864, 560)

    # ----- Public API -----
    def show_status(self, text: str):
        self.status.showMessage(text)

    def set_background(self, path: str):
        if not path or not os.path.exists(path):
            self.bg_label.clear()
            self.bg_label.setStyleSheet("background-color:black;")
            return
        pm = QPixmap(path)
        if not pm.isNull():
            # Fit background to current window
            scaled = pm.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.bg_label.setPixmap(scaled)

    def set_balloon_rect_design(self, x: int, y: int, w: int, h: int):
        self._rect_design = QRect(int(x), int(y), int(w), int(h))
        self._apply_balloon_geometry()

    def play_chunks(self, chunks, duration_s: int = None):
        self.chunks = list(chunks) if chunks else []
        self._chunk_idx = -1
        if duration_s is None:
            duration_s = self.chunk_duration_s
        self._chunk_duration_ms = max(1000, int(duration_s * 1000))
        if not self.chunks:
            self.balloon.setText("")
            QTimer.singleShot(300, self.chunkPlaybackFinished.emit)
            return
        self._show_next_chunk(initial=True)

    # ----- Internals -----
    def _apply_balloon_geometry(self):
        # Map design-space rect to current window size
        w, h = self.width(), self.height()
        rx = self._rect_design.x() / max(1, self.design_w)
        ry = self._rect_design.y() / max(1, self.design_h)
        rw = self._rect_design.width() / max(1, self.design_w)
        rh = self._rect_design.height() / max(1, self.design_h)
        gx = int(rx * w)
        gy = int(ry * h)
        gw = int(rw * w)
        gh = int(rh * h)
        self.overlay.setGeometry(QRect(gx, gy, gw, gh))
        self._center_text_vertically()

    def _center_text_vertically(self):
        # Center text vertically by padding the viewport top margin
        doc = self.balloon.document()
        doc.setTextWidth(self.balloon.viewport().width() - 40)  # account for padding
        dh = doc.size().height()
        vh = self.balloon.viewport().height()
        top_pad = max(0, int((vh - dh) / 2))
        # Use viewportMargins to push content down
        self.balloon.setViewportMargins(0, top_pad, 0, 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Rescale background
        pm = self.bg_label.pixmap()
        if pm:
            scaled = pm.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self.bg_label.setPixmap(scaled)
        self._apply_balloon_geometry()

    def _show_next_chunk(self, initial=False):
        self._chunk_idx += 1
        if self._chunk_idx >= len(self.chunks):
            self.chunkPlaybackFinished.emit()
            return
        text = self.chunks[self._chunk_idx]
        def _swap():
            self.balloon.setHtml(self._wrap_html(text))
            self._center_text_vertically()
            self.fade_in.finished.connect(_hold_then_fade)
            self.fade_in.start()
        def _hold_then_fade():
            self.fade_in.finished.disconnect(_hold_then_fade)
            QTimer.singleShot(self._chunk_duration_ms, self._start_fade_out)
        if initial:
            self.opacity.setOpacity(0.0)
            _swap()
        else:
            self.fade_out.finished.connect(_swap)
            self.fade_out.start()

    def _start_fade_out(self):
        self.fade_out.finished.disconnect()
        self.fade_out.finished.connect(lambda: self._show_next_chunk(initial=False))
        self.fade_out.start()

    def _wrap_html(self, text: str) -> str:
        safe_text = self._escape_html(text).replace("\n", "<br/>")
        return (
        f"<div style='text-align:center; font-size:{self.ui_cfg.get('font_point_size',16)}pt;'>"
        f"{safe_text}"
        "</div>"
    )

    @staticmethod
    def _escape_html(s: str) -> str:
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace("\"", "&quot;"))