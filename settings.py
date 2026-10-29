"""User settings (stored in the registry via QSettings), start-with-Windows,
and the Settings dialog."""
import sys
import winreg
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton, QVBoxLayout,
                               QKeySequenceEdit)

import formats
from hotkey import DEFAULT_HOTKEY, display_name, parse_hotkey

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "FileRing"


@dataclass
class Settings:
    hotkey: str = DEFAULT_HOTKEY
    output_dir: str = str(formats.DEFAULT_OUTPUT_DIR)
    next_to_original: bool = False
    explorer_menu: bool = True
    compress_mb: float = 10.0
    auto_update: bool = True

    @classmethod
    def load(cls) -> "Settings":
        q = QSettings(APP_NAME, APP_NAME)
        s = cls()
        s.hotkey = q.value("hotkey", s.hotkey, str)
        s.output_dir = q.value("output_dir", s.output_dir, str)
        s.next_to_original = q.value("next_to_original", s.next_to_original, bool)
        s.explorer_menu = q.value("explorer_menu", s.explorer_menu, bool)
        s.compress_mb = q.value("compress_mb", s.compress_mb, float)
        s.auto_update = q.value("auto_update", s.auto_update, bool)
        if parse_hotkey(s.hotkey) is None:
            s.hotkey = DEFAULT_HOTKEY
        return s

    def save(self):
        q = QSettings(APP_NAME, APP_NAME)
        q.setValue("hotkey", self.hotkey)
        q.setValue("output_dir", self.output_dir)
        q.setValue("next_to_original", self.next_to_original)
        q.setValue("explorer_menu", self.explorer_menu)
        q.setValue("compress_mb", self.compress_mb)
        q.setValue("auto_update", self.auto_update)

    def apply(self):
        formats.OUTPUT_DIR = Path(self.output_dir)
        formats.SAVE_NEXT_TO_ORIGINAL = self.next_to_original
        formats.COMPRESS_MB = self.compress_mb


# ---- start with Windows --------------------------------------------------------

def _launch_command() -> str:
    if getattr(sys, "frozen", False):          # packaged FileRing.exe
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw}" "{Path(__file__).with_name("main.py")}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def set_autostart(enabled: bool):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def refresh_autostart():
    """If start-with-Windows is on, point it at this copy of FileRing (it may have moved)."""
    if autostart_enabled():
        set_autostart(True)


# ---- dialog -------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, settings: Settings):
        super().__init__()
        self.setWindowTitle("FileRing settings")
        self.setMinimumWidth(480)
        self.settings = settings

        # Hotkey
        self.key_edit = QKeySequenceEdit(QKeySequence(settings.hotkey))
        self.key_edit.setMaximumSequenceLength(1)
        self.key_edit.keySequenceChanged.connect(self._check_hotkey)
        reset = QPushButton("Reset", clicked=lambda: self.key_edit.setKeySequence(
            QKeySequence(DEFAULT_HOTKEY)))
        self.key_hint = QLabel()
        self.key_hint.setWordWrap(True)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(reset)
        key_box = QGroupBox("Hotkey to show the ring")
        kl = QVBoxLayout(key_box)
        kl.addLayout(key_row)
        kl.addWidget(self.key_hint)

        # Output location
        self.to_folder = QRadioButton("In this folder:")
        self.to_original = QRadioButton("Next to the original file")
        group = QButtonGroup(self)
        group.addButton(self.to_folder)
        group.addButton(self.to_original)
        (self.to_original if settings.next_to_original else self.to_folder).setChecked(True)
        self.folder_edit = QLineEdit(settings.output_dir)
        browse = QPushButton("Browse…", clicked=self._browse)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        self.to_folder.toggled.connect(self.folder_edit.setEnabled)
        self.to_folder.toggled.connect(browse.setEnabled)
        self.folder_edit.setEnabled(self.to_folder.isChecked())
        browse.setEnabled(self.to_folder.isChecked())
        out_box = QGroupBox("Save converted files")
        ol = QVBoxLayout(out_box)
        ol.addWidget(self.to_folder)
        ol.addLayout(folder_row)
        ol.addWidget(self.to_original)

        # Start with Windows
        self.autostart = QCheckBox("Start FileRing when Windows starts")
        self.autostart.setChecked(autostart_enabled())
        self.explorer_menu = QCheckBox("Show \"Convert with FileRing\" when right-clicking files")
        self.explorer_menu.setChecked(settings.explorer_menu)
        self.auto_update = QCheckBox("Update FileRing automatically")
        self.auto_update.setChecked(settings.auto_update)

        # Compress to size
        self.compress = QDoubleSpinBox(decimals=1, minimum=0.1, maximum=4000, singleStep=1,
                                       suffix=" MB", value=settings.compress_mb)
        compress_box = QGroupBox("Compress to size")
        cl = QFormLayout(compress_box)
        cl.addRow("Make files smaller than:", self.compress)
        hint = QLabel("For example 10 MB for email, 25 MB for Teams, 1 MB for web uploads.")
        hint.setWordWrap(True)
        cl.addRow(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)

        layout = QVBoxLayout(self)
        layout.addWidget(key_box)
        layout.addWidget(out_box)
        layout.addWidget(compress_box)
        layout.addWidget(self.autostart)
        layout.addWidget(self.explorer_menu)
        layout.addWidget(self.auto_update)
        layout.addStretch()
        layout.addWidget(buttons)
        self._check_hotkey()

    def _hotkey_text(self) -> str:
        return self.key_edit.keySequence().toString(QKeySequence.PortableText)

    def _check_hotkey(self):
        text = self._hotkey_text()
        ok = parse_hotkey(text) is not None
        self.key_hint.setText(
            f"Press {display_name(text)} anywhere (even mid-drag) to show the ring." if ok else
            "Use Ctrl, Alt or Win plus a letter, number, F-key or Space.")
        self.ok_button.setEnabled(ok)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Save converted files in",
                                                  self.folder_edit.text())
        if folder:
            self.folder_edit.setText(str(Path(folder)))

    def accept(self):
        s = self.settings
        s.hotkey = self._hotkey_text()
        s.output_dir = self.folder_edit.text().strip() or str(formats.DEFAULT_OUTPUT_DIR)
        s.next_to_original = self.to_original.isChecked()
        s.explorer_menu = self.explorer_menu.isChecked()
        s.auto_update = self.auto_update.isChecked()
        s.compress_mb = round(self.compress.value(), 1)
        s.save()
        s.apply()
        if self.autostart.isChecked() != autostart_enabled():
            set_autostart(self.autostart.isChecked())
        super().accept()
