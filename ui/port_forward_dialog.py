"""
ui/port_forward_dialog.py
Manage port forwarding rules for a host, and start/stop active forwarders.

Fixes vs earlier version:
  - Rules are tracked by their stable DB id (not table row index), so
    "Start" still works correctly after the table refreshes/re-sorts.
  - Supports tunneling through any hop in a jump-host chain via
    `via_hop_index` (entry hop, intermediate hops, or the final target).
  - Status column reflects live state and survives refresh().
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QLineEdit, QSpinBox, QLabel, QMessageBox,
    QHeaderView, QGroupBox, QFormLayout
)

from db.models import PortForward
from db.repository import get_chain_hosts
from core.port_forward import start_forward

RULE_ID_ROLE = Qt.UserRole + 1


class PortForwardDialog(QDialog):
    def __init__(self, db_session, host, ssh_session=None, parent=None):
        super().__init__(parent)
        self.db = db_session
        self.host = host
        self.ssh_session = ssh_session
        self.active_forwards = {}  # rule_id -> forwarder object

        self.setWindowTitle(f"Port Forwarding - {host.label}")
        self.setMinimumSize(720, 420)

        layout = QVBoxLayout(self)

        # Show the chain so the user understands hop indices
        self.chain_hosts = get_chain_hosts(self.db, host.id)
        chain_label = " -> ".join(f"[{i}] {h.label}" for i, h in enumerate(self.chain_hosts))
        layout.addWidget(QLabel(f"<b>Connection chain:</b> {chain_label}"))

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Type", "Bind Address", "Bind Port", "Dest Address", "Dest Port", "Via Hop", "Status"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        form_box = QGroupBox("New Rule")
        form = QFormLayout(form_box)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["local", "remote", "dynamic"])
        self.type_combo.currentTextChanged.connect(self._toggle_dest_fields)

        self.bind_addr_edit = QLineEdit("127.0.0.1")
        self.bind_port_spin = QSpinBox()
        self.bind_port_spin.setRange(1, 65535)
        self.bind_port_spin.setValue(8080)

        self.dest_addr_edit = QLineEdit("127.0.0.1")
        self.dest_port_spin = QSpinBox()
        self.dest_port_spin.setRange(1, 65535)
        self.dest_port_spin.setValue(80)

        self.via_hop_combo = QComboBox()
        for i, h in enumerate(self.chain_hosts):
            suffix = " (target)" if i == len(self.chain_hosts) - 1 else " (jump host)"
            self.via_hop_combo.addItem(f"[{i}] {h.label}{suffix}", i)
        self.via_hop_combo.setCurrentIndex(self.via_hop_combo.count() - 1)

        form.addRow("Type:", self.type_combo)
        form.addRow("Bind Address:Port:", self._row(self.bind_addr_edit, self.bind_port_spin))
        form.addRow("Destination Address:Port:", self._row(self.dest_addr_edit, self.dest_port_spin))
        form.addRow("Tunnel through hop:", self.via_hop_combo)

        add_btn = QPushButton("Add Rule")
        add_btn.clicked.connect(self._add_rule)
        form.addRow(add_btn)

        layout.addWidget(form_box)

        btn_row = QHBoxLayout()
        del_btn = QPushButton("Delete Selected Rule")
        del_btn.clicked.connect(self._delete_rule)
        start_btn = QPushButton("Start")
        start_btn.clicked.connect(self._start_selected)
        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self._stop_selected)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)

        btn_row.addWidget(del_btn)
        btn_row.addWidget(start_btn)
        btn_row.addWidget(stop_btn)
        btn_row.addStretch()
        btn_row.addWidget(refresh_btn)
        layout.addLayout(btn_row)

        self.refresh()

    @staticmethod
    def _row(*widgets):
        from PySide6.QtWidgets import QWidget
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        for widget in widgets:
            h.addWidget(widget)
        return container

    def _toggle_dest_fields(self, ftype):
        enabled = ftype != "dynamic"
        self.dest_addr_edit.setEnabled(enabled)
        self.dest_port_spin.setEnabled(enabled)

    def refresh(self):
        self.table.setRowCount(0)
        rules = self.db.query(PortForward).filter(PortForward.host_id == self.host.id).all()
        for rule in rules:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(rule.type))
            self.table.setItem(row, 1, QTableWidgetItem(rule.bind_address))
            self.table.setItem(row, 2, QTableWidgetItem(str(rule.bind_port)))
            self.table.setItem(row, 3, QTableWidgetItem(rule.dest_address or ""))
            self.table.setItem(row, 4, QTableWidgetItem(str(rule.dest_port) if rule.dest_port else ""))

            via_idx = rule.via_hop_index if rule.via_hop_index is not None else -1
            if 0 <= via_idx < len(self.chain_hosts):
                via_label = f"[{via_idx}] {self.chain_hosts[via_idx].label}"
            else:
                via_label = f"[{len(self.chain_hosts) - 1}] {self.chain_hosts[-1].label} (target)"
            self.table.setItem(row, 5, QTableWidgetItem(via_label))

            status = "Running" if rule.id in self.active_forwards else "Stopped"
            self.table.setItem(row, 6, QTableWidgetItem(status))

            # Store the stable rule id on the first cell for lookups
            self.table.item(row, 0).setData(RULE_ID_ROLE, rule.id)

    def _selected_rule_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(RULE_ID_ROLE)

    def _add_rule(self):
        ftype = self.type_combo.currentText()
        rule = PortForward(
            host_id=self.host.id,
            type=ftype,
            bind_address=self.bind_addr_edit.text().strip() or "127.0.0.1",
            bind_port=self.bind_port_spin.value(),
            dest_address=self.dest_addr_edit.text().strip(),
            dest_port=self.dest_port_spin.value() if ftype != "dynamic" else None,
            via_hop_index=self.via_hop_combo.currentData(),
        )
        self.db.add(rule)
        self.db.commit()
        self.refresh()

    def _delete_rule(self):
        rule_id = self._selected_rule_id()
        if rule_id is None:
            return
        if rule_id in self.active_forwards:
            self.active_forwards[rule_id].stop()
            del self.active_forwards[rule_id]
        rule = self.db.query(PortForward).get(rule_id)
        if rule:
            self.db.delete(rule)
            self.db.commit()
        self.refresh()

    def _start_selected(self):
        if not self.ssh_session or not self.ssh_session.is_active():
            QMessageBox.warning(self, "Error", "No active SSH session to tunnel through.")
            return
        rule_id = self._selected_rule_id()
        if rule_id is None:
            return
        if rule_id in self.active_forwards:
            QMessageBox.information(self, "Info", "Already running.")
            return

        rule = self.db.query(PortForward).get(rule_id)
        config = {
            "type": rule.type,
            "bind_address": rule.bind_address,
            "bind_port": rule.bind_port,
            "dest_address": rule.dest_address,
            "dest_port": rule.dest_port,
        }
        try:
            hop_index = rule.via_hop_index if rule.via_hop_index is not None else -1
            transport = self.ssh_session.get_transport(hop_index)
            if transport is None or not transport.is_active():
                raise RuntimeError("Selected hop's transport is not active.")
            fwd = start_forward(transport, config)
            self.active_forwards[rule_id] = fwd
            self.refresh()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not start forward:\n{e}")

    def _stop_selected(self):
        rule_id = self._selected_rule_id()
        if rule_id is None:
            return
        if rule_id in self.active_forwards:
            self.active_forwards[rule_id].stop()
            del self.active_forwards[rule_id]
            self.refresh()

    def closeEvent(self, event):
        for fwd in self.active_forwards.values():
            fwd.stop()
        super().closeEvent(event)
