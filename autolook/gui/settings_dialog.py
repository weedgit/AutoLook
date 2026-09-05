"""Settings dialog with tabs for all AutoLook configuration."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox,
    QListWidget, QPushButton, QFileDialog, QDialogButtonBox,
    QFormLayout, QSlider, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QCheckBox,
)
from PyQt6.QtCore import Qt

from autolook.config import Config
from autolook.detection.nsfw_detector import opennsfw_available


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None, nm_db=None):
        super().__init__(parent)
        self.config = config
        self.nm_db = nm_db
        self.setWindowTitle("AutoLook Settings")
        self.setMinimumSize(700, 520)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(self._paths_tab(), "Paths")
        tabs.addTab(self._detection_tab(), "Detection")
        tabs.addTab(self._watchlists_tab(), "Watchlists")
        tabs.addTab(self._names_tab(), "Names")
        tabs.addTab(self._keywords_tab(), "Keywords")
        tabs.addTab(self._alerts_tab(), "Alerts")

        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- Tab 1: Paths ---
    def _paths_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._nm_db_path = QLineEdit(str(self.config.netmonitor_db_path))
        browse_nm = QPushButton("Browse...")
        browse_nm.clicked.connect(lambda: self._browse_file(self._nm_db_path, "SQLite DB (*.db)"))
        row1 = QHBoxLayout()
        row1.addWidget(self._nm_db_path)
        row1.addWidget(browse_nm)
        form.addRow("Net Monitor DB:", row1)

        self._rec_path = QLineEdit(str(self.config.recording_path or ""))
        browse_rec = QPushButton("Browse...")
        browse_rec.clicked.connect(lambda: self._browse_dir(self._rec_path))
        row2 = QHBoxLayout()
        row2.addWidget(self._rec_path)
        row2.addWidget(browse_rec)
        form.addRow("Recording Folder:", row2)

        self._thumb_path = QLineEdit(str(self.config.thumbnail_path))
        form.addRow("Thumbnails Folder:", self._thumb_path)

        self._screen_path = QLineEdit(str(self.config.screenshot_path))
        form.addRow("Screen Images Folder:", self._screen_path)

        return w

    # --- Tab 2: Detection ---
    def _detection_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._nsfw_engine = QComboBox()
        engine_items = [
            ("nudenet", "NudeNet — find body parts"),
            ("opennsfw", "OpenNSFW2 — whole-image score"),
            ("both", "Both — NudeNet always + OpenNSFW score"),
        ]
        for key, label in engine_items:
            self._nsfw_engine.addItem(label, key)
        idx = self._nsfw_engine.findData(self.config.nsfw_engine)
        self._nsfw_engine.setCurrentIndex(idx if idx >= 0 else 1)  # default OpenNSFW
        self._nsfw_engine.setToolTip(
            "Admin choice for how images are checked.\n"
            "NudeNet: labels exposed body parts (slower, more specific).\n"
            "OpenNSFW2: one 0–100% score for the whole picture (faster).\n"
            "Both: always run NudeNet; also alert if only OpenNSFW2 score is high."
        )
        form.addRow("NSFW Engine:", self._nsfw_engine)

        nsfw_hint = QLabel(
            "OpenNSFW2: ready (ONNX, no TensorFlow)"
            if opennsfw_available()
            else "OpenNSFW2: not installed — pip install opennsfw-onnx"
        )
        nsfw_hint.setStyleSheet("color: #666;")
        form.addRow("", nsfw_hint)

        self._nsfw_sensitivity = QComboBox()
        # Stored keys match config thresholds: low=0.2 (more alerts), high=0.6 (fewer)
        sens_items = [
            ("low", "More alerts — easier to flag (score ≥ 20%)"),
            ("medium", "Balanced (score ≥ 40%)"),
            ("high", "Fewer alerts — stricter (score ≥ 60%)"),
        ]
        for key, label in sens_items:
            self._nsfw_sensitivity.addItem(label, key)
        sidx = self._nsfw_sensitivity.findData(self.config.nsfw_sensitivity)
        self._nsfw_sensitivity.setCurrentIndex(sidx if sidx >= 0 else 1)
        self._nsfw_sensitivity.setToolTip(
            "How high the NSFW score must be before an alert is created.\n"
            "Applies to OpenNSFW2’s whole-image score and to NudeNet part scores.\n"
            "More alerts = lower bar (20%). Fewer alerts = higher bar (60%)."
        )
        form.addRow("NSFW Sensitivity:", self._nsfw_sensitivity)

        korea_hint = QLabel(
            "Korea / keywords: from Net Monitor weblog, applog, and keylog text "
            "(not screen OCR). Google Translate Hangul is ignored; keywords still alert."
        )
        korea_hint.setWordWrap(True)
        korea_hint.setStyleSheet("color: #666;")
        form.addRow("Korea text:", korea_hint)

        self._sample_interval = QSpinBox()
        self._sample_interval.setRange(1, 30)
        self._sample_interval.setValue(self.config.sample_interval)
        self._sample_interval.setSuffix(" seconds")
        self._sample_interval.setToolTip(
            "Shared for video and images:\n"
            "• Video: 1 frame every N seconds (full length, NSFW only)\n"
            "• Images: keep screenshots at least N seconds apart\n"
            "  (time from filename, e.g. …_2026-09-03_11_10_52-…)"
        )
        form.addRow("Sample Rate:", self._sample_interval)

        self._scan_interval = QSpinBox()
        self._scan_interval.setRange(5, 3600)
        self._scan_interval.setValue(self.config.scan_interval)
        self._scan_interval.setSuffix(" seconds")
        form.addRow("Scan Interval:", self._scan_interval)

        self._include_video = QCheckBox("Include video")
        self._include_video.setChecked(self.config.include_video)
        self._include_video.setToolTip(
            "On: scan video files full length (FFmpeg + OpenNSFW per frame).\n"
            "Off (recommended): only images + DB/CSV logs.\n"
            "Video never uses OCR — Hangul/keywords come from NM text logs."
        )
        form.addRow("", self._include_video)

        return w

    # --- Tab 3: Watchlists ---
    def _watchlists_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Websites
        layout.addWidget(QLabel(
            "Watched Websites (saved in Watched web/app history — not NSFW/Korea alerts):"
        ))
        self._websites_list = QListWidget()
        self._websites_list.addItems(self.config.watched_websites)
        layout.addWidget(self._websites_list)
        web_btns = QHBoxLayout()
        self._web_input = QLineEdit()
        self._web_input.setPlaceholderText("Add website (e.g. youtube.com)")
        web_btns.addWidget(self._web_input)
        add_web = QPushButton("Add")
        add_web.clicked.connect(lambda: self._add_to_list(self._web_input, self._websites_list))
        web_btns.addWidget(add_web)
        rm_web = QPushButton("Remove Selected")
        rm_web.clicked.connect(lambda: self._remove_selected(self._websites_list))
        web_btns.addWidget(rm_web)
        layout.addLayout(web_btns)

        # Apps
        layout.addWidget(QLabel(
            "Watched Apps (saved in Watched web/app history — not NSFW/Korea alerts):"
        ))
        self._apps_list = QListWidget()
        self._apps_list.addItems(self.config.watched_apps)
        layout.addWidget(self._apps_list)
        app_btns = QHBoxLayout()
        self._app_input = QLineEdit()
        self._app_input.setPlaceholderText("Add app (e.g. telegram.exe)")
        app_btns.addWidget(self._app_input)
        add_app = QPushButton("Add")
        add_app.clicked.connect(lambda: self._add_to_list(self._app_input, self._apps_list))
        app_btns.addWidget(add_app)
        rm_app = QPushButton("Remove Selected")
        rm_app.clicked.connect(lambda: self._remove_selected(self._apps_list))
        app_btns.addWidget(rm_app)
        layout.addLayout(app_btns)

        # Korean domains
        layout.addWidget(QLabel("Korean Domains:"))
        self._korean_domains_list = QListWidget()
        self._korean_domains_list.addItems(self.config.korean_domains)
        layout.addWidget(self._korean_domains_list)
        kd_btns = QHBoxLayout()
        self._kd_input = QLineEdit()
        self._kd_input.setPlaceholderText("Add domain (e.g. naver.com)")
        kd_btns.addWidget(self._kd_input)
        add_kd = QPushButton("Add")
        add_kd.clicked.connect(lambda: self._add_to_list(self._kd_input, self._korean_domains_list))
        kd_btns.addWidget(add_kd)
        rm_kd = QPushButton("Remove Selected")
        rm_kd.clicked.connect(lambda: self._remove_selected(self._korean_domains_list))
        kd_btns.addWidget(rm_kd)
        layout.addLayout(kd_btns)

        return w

    def _names_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        hint = QLabel(
            "Map teammate computers by IP or hostname. "
            "Windows accounts are often all 'Administrator', so AutoLook uses this map "
            "to show a real name. Example: 192.168.1.15 → Alice"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._names_table = QTableWidget(0, 2)
        self._names_table.setHorizontalHeaderLabels(["IP or Hostname", "Name"])
        self._names_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._names_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._names_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._names_table)

        for ip, name in self.config.host_aliases.items():
            self._add_name_row(ip, name)

        add_row = QHBoxLayout()
        self._ip_input = QLineEdit()
        self._ip_input.setPlaceholderText("192.168.1.15 or DESKTOP-XXXX")
        add_row.addWidget(self._ip_input)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Display name")
        add_row.addWidget(self._name_input)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._on_add_name)
        add_row.addWidget(add_btn)
        rm_btn = QPushButton("Remove Selected")
        rm_btn.clicked.connect(self._on_remove_name)
        add_row.addWidget(rm_btn)
        layout.addLayout(add_row)

        load_row = QHBoxLayout()
        load_btn = QPushButton("Load hosts from Net Monitor")
        load_btn.clicked.connect(self._load_hosts_from_netmonitor)
        load_row.addWidget(load_btn)
        load_row.addStretch()
        layout.addLayout(load_row)

        return w

    def _load_hosts_from_netmonitor(self):
        """Add known HOST values from reporting.db that are not yet mapped."""
        if self.nm_db is None:
            return
        existing = {
            (self._names_table.item(r, 0).text().strip().lower()
             if self._names_table.item(r, 0) else "")
            for r in range(self._names_table.rowCount())
        }
        try:
            hosts = set(self.nm_db.get_distinct_hosts())
        except Exception:
            hosts = set()

        # Also add IP folders from recording path
        rec = self.config.recording_path
        if rec and rec.exists():
            from autolook.utils.host_names import looks_like_ip
            for child in rec.iterdir():
                if child.is_dir() and looks_like_ip(child.name):
                    hosts.add(child.name)

        for host in sorted(hosts):
            if host.lower() in existing:
                continue
            mapped = ""
            for k, v in self.config.host_aliases.items():
                if k.lower() == host.lower():
                    mapped = v
                    break
            # If this is an IP already mapped, also try reverse-DNS hostname row
            from autolook.utils.host_names import looks_like_ip, ip_to_hostname, resolve_display_name
            if not mapped:
                mapped = resolve_display_name(host, self.config.host_aliases)
            self._add_name_row(host, mapped)
            existing.add(host.lower())

            if looks_like_ip(host):
                hname = ip_to_hostname(host)
                if hname and hname.lower() not in existing:
                    self._add_name_row(hname, mapped or self.config.host_aliases.get(host, ""))
                    existing.add(hname.lower())
                    short = hname.split(".")[0]
                    if short.lower() not in existing:
                        self._add_name_row(short, mapped or self.config.host_aliases.get(host, ""))
                        existing.add(short.lower())

    def _add_name_row(self, ip: str, name: str):
        row = self._names_table.rowCount()
        self._names_table.insertRow(row)
        self._names_table.setItem(row, 0, QTableWidgetItem(ip))
        self._names_table.setItem(row, 1, QTableWidgetItem(name))

    def _on_add_name(self):
        ip = self._ip_input.text().strip()
        name = self._name_input.text().strip()
        if not ip or not name:
            return
        self._add_name_row(ip, name)
        self._ip_input.clear()
        self._name_input.clear()

    def _on_remove_name(self):
        rows = sorted({i.row() for i in self._names_table.selectedItems()}, reverse=True)
        for row in rows:
            self._names_table.removeRow(row)

    def _collect_host_aliases(self) -> dict[str, str]:
        aliases = {}
        for row in range(self._names_table.rowCount()):
            ip_item = self._names_table.item(row, 0)
            name_item = self._names_table.item(row, 1)
            ip = ip_item.text().strip() if ip_item else ""
            name = name_item.text().strip() if name_item else ""
            if ip and name:
                aliases[ip] = name
        return aliases

    # --- Tab 4: Keywords ---
    def _keywords_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("English Keywords (Korea-related):"))
        self._english_kw_list = QListWidget()
        self._english_kw_list.addItems(self.config.english_keywords)
        layout.addWidget(self._english_kw_list)
        ek_btns = QHBoxLayout()
        self._ek_input = QLineEdit()
        self._ek_input.setPlaceholderText("Add keyword")
        ek_btns.addWidget(self._ek_input)
        add_ek = QPushButton("Add")
        add_ek.clicked.connect(lambda: self._add_to_list(self._ek_input, self._english_kw_list))
        ek_btns.addWidget(add_ek)
        rm_ek = QPushButton("Remove Selected")
        rm_ek.clicked.connect(lambda: self._remove_selected(self._english_kw_list))
        ek_btns.addWidget(rm_ek)
        layout.addLayout(ek_btns)

        layout.addWidget(QLabel("Custom Keywords (any language):"))
        self._custom_kw_list = QListWidget()
        self._custom_kw_list.addItems(self.config.custom_keywords)
        layout.addWidget(self._custom_kw_list)
        ck_btns = QHBoxLayout()
        self._ck_input = QLineEdit()
        self._ck_input.setPlaceholderText("Add custom keyword")
        ck_btns.addWidget(self._ck_input)
        add_ck = QPushButton("Add")
        add_ck.clicked.connect(lambda: self._add_to_list(self._ck_input, self._custom_kw_list))
        ck_btns.addWidget(add_ck)
        rm_ck = QPushButton("Remove Selected")
        rm_ck.clicked.connect(lambda: self._remove_selected(self._custom_kw_list))
        ck_btns.addWidget(rm_ck)
        layout.addLayout(ck_btns)

        return w

    # --- Tab: Alerts (NSFW / Korea) ---
    def _alerts_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self._alert_nsfw = QCheckBox("Create NSFW alerts")
        self._alert_nsfw.setChecked(self.config.alert_nsfw)
        form.addRow("", self._alert_nsfw)

        self._alert_korea = QCheckBox("Create Korea alerts")
        self._alert_korea.setChecked(self.config.alert_korea)
        form.addRow("", self._alert_korea)

        self._alert_sound = QCheckBox("Play sound on new alert")
        self._alert_sound.setChecked(self.config.alert_sound)
        form.addRow("", self._alert_sound)

        self._skip_keystrokes = QCheckBox("Skip keylog keystrokes (allow typing Korean)")
        self._skip_keystrokes.setChecked(self.config.skip_keylog_keystrokes)
        self._skip_keystrokes.setToolTip(
            "When checked, AutoLook does not scan typed keystrokes for Korea.\n"
            "Window captions are still checked. Recommended: leave ON."
        )
        form.addRow("", self._skip_keystrokes)

        hint = QLabel(
            "Only NSFW and Korea detections create alerts.\n"
            "Watched sites/apps alone do not. Use the toolbar to filter the list."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        form.addRow(hint)

        return w

    # --- Helpers ---
    def _browse_file(self, line_edit: QLineEdit, filter_str: str):
        path, _ = QFileDialog.getOpenFileName(self, "Select File", "", filter_str)
        if path:
            line_edit.setText(path)

    def _browse_dir(self, line_edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path:
            line_edit.setText(path)

    def _add_to_list(self, input_widget: QLineEdit, list_widget: QListWidget):
        text = input_widget.text().strip()
        if text:
            list_widget.addItem(text)
            input_widget.clear()

    def _remove_selected(self, list_widget: QListWidget):
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))

    def _list_items(self, list_widget: QListWidget) -> list[str]:
        return [list_widget.item(i).text() for i in range(list_widget.count())]

    def _save_and_accept(self):
        self.config.set("netmonitor_db_path", self._nm_db_path.text())
        self.config.set("recording_path", self._rec_path.text())
        self.config.set("thumbnail_path", self._thumb_path.text())
        self.config.set("screenshot_path", self._screen_path.text())

        engine = self._nsfw_engine.currentData()
        self.config.set("nsfw_engine", engine if engine else "opennsfw")
        sens = self._nsfw_sensitivity.currentData()
        self.config.set("nsfw_sensitivity", sens if sens else "medium")
        self.config.set("sample_interval_seconds", self._sample_interval.value())
        self.config.set("scan_interval_seconds", self._scan_interval.value())
        self.config.set("include_video", self._include_video.isChecked())

        self.config.set("watched_websites", self._list_items(self._websites_list))
        self.config.set("watched_apps", self._list_items(self._apps_list))
        self.config.set("korean_domains", self._list_items(self._korean_domains_list))

        self.config.set("english_keywords", self._list_items(self._english_kw_list))
        self.config.set("custom_keywords", self._list_items(self._custom_kw_list))
        self.config.set("host_aliases", self._collect_host_aliases())

        self.config.set("alert_nsfw", self._alert_nsfw.isChecked())
        self.config.set("alert_korea", self._alert_korea.isChecked())
        self.config.set("alert_sound", self._alert_sound.isChecked())
        self.config.set("skip_keylog_keystrokes", self._skip_keystrokes.isChecked())

        self.accept()
