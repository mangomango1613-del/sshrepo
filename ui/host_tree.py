"""
ui/host_tree.py
Sidebar tree showing groups and hosts, with context menu actions
(connect, edit, delete, new group/host).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QMenu, QWidget, QVBoxLayout,
    QLineEdit, QAbstractItemView
)

from db.models import Host, Group

HOST_ITEM = 1001
GROUP_ITEM = 1002


class HostTree(QWidget):
    connect_requested = Signal(int)       # host_id
    sftp_requested = Signal(int)          # host_id
    dual_sftp_requested = Signal(int)     # host_id - open dual-pane SFTP starting here
    edit_host_requested = Signal(int)     # host_id
    duplicate_host_requested = Signal(int)  # host_id
    new_host_requested = Signal(object)   # group_id or None
    new_group_requested = Signal(object)  # parent_group_id or None
    delete_host_requested = Signal(int)
    delete_group_requested = Signal(int)
    connect_all_requested = Signal(list)  # list[host_id] - open a terminal for each, in parallel

    def __init__(self, db_session, parent=None):
        super().__init__(parent)
        self.db = db_session

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search hosts...")
        self.search_box.textChanged.connect(self._filter)
        layout.addWidget(self.search_box)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.tree)

        self.refresh()

    def refresh(self):
        self.tree.clear()
        groups = self.db.query(Group).filter(Group.parent_id.is_(None)).all()
        for g in groups:
            self._add_group_item(g, self.tree.invisibleRootItem())

        # hosts without a group, at root
        ungrouped = self.db.query(Host).filter(Host.group_id.is_(None)).all()
        for h in ungrouped:
            self._add_host_item(h, self.tree.invisibleRootItem())

        self.tree.expandAll()

    def _add_group_item(self, group, parent_item):
        item = QTreeWidgetItem(parent_item, [group.name])
        item.setData(0, Qt.UserRole, GROUP_ITEM)
        item.setData(0, Qt.UserRole + 1, group.id)

        for child in self.db.query(Group).filter(Group.parent_id == group.id).all():
            self._add_group_item(child, item)

        for host in self.db.query(Host).filter(Host.group_id == group.id).all():
            self._add_host_item(host, item)

        return item

    def _add_host_item(self, host, parent_item):
        label = host.label or host.hostname
        item = QTreeWidgetItem(parent_item, [f"{label}  ({host.hostname})"])
        item.setData(0, Qt.UserRole, HOST_ITEM)
        item.setData(0, Qt.UserRole + 1, host.id)
        if host.color_tag:
            item.setForeground(0, Qt.GlobalColor.cyan)
        return item

    def _collect_host_ids(self, group_id):
        """Recursively collect every host id under a group (including
        nested subgroups)."""
        host_ids = [h.id for h in self.db.query(Host).filter(Host.group_id == group_id).all()]
        for child in self.db.query(Group).filter(Group.parent_id == group_id).all():
            host_ids.extend(self._collect_host_ids(child.id))
        return host_ids

    def _on_double_click(self, item, column):
        item_type = item.data(0, Qt.UserRole)
        item_id = item.data(0, Qt.UserRole + 1)
        if item_type == HOST_ITEM:
            self.connect_requested.emit(item_id)
        elif item_type == GROUP_ITEM:
            host_ids = self._collect_host_ids(item_id)
            if host_ids:
                self.connect_all_requested.emit(host_ids)

    def _show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        if item is None:
            menu.addAction("New Group", lambda: self.new_group_requested.emit(None))
            menu.addAction("New Host", lambda: self.new_host_requested.emit(None))
            menu.addSeparator()
            all_ids = [h.id for h in self.db.query(Host).all()]
            connect_all_action = menu.addAction(f"Connect All Hosts ({len(all_ids)})")
            connect_all_action.setEnabled(bool(all_ids))
            connect_all_action.triggered.connect(lambda: self.connect_all_requested.emit(all_ids))
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return

        item_type = item.data(0, Qt.UserRole)
        item_id = item.data(0, Qt.UserRole + 1)

        if item_type == HOST_ITEM:
            menu.addAction("Connect (SSH)", lambda: self.connect_requested.emit(item_id))
            menu.addAction("Open SFTP", lambda: self.sftp_requested.emit(item_id))
            menu.addAction("Open Dual-Pane SFTP (Transfer)", lambda: self.dual_sftp_requested.emit(item_id))
            menu.addSeparator()
            menu.addAction("Edit", lambda: self.edit_host_requested.emit(item_id))
            menu.addAction("Duplicate", lambda: self.duplicate_host_requested.emit(item_id))
            menu.addAction("Delete", lambda: self.delete_host_requested.emit(item_id))
        elif item_type == GROUP_ITEM:
            host_ids = self._collect_host_ids(item_id)
            connect_all_action = menu.addAction(
                f"Connect All ({len(host_ids)} host{'s' if len(host_ids) != 1 else ''})"
            )
            connect_all_action.setEnabled(bool(host_ids))
            connect_all_action.triggered.connect(lambda: self.connect_all_requested.emit(host_ids))
            menu.addSeparator()
            menu.addAction("New Host Here", lambda: self.new_host_requested.emit(item_id))
            menu.addAction("New Subgroup", lambda: self.new_group_requested.emit(item_id))
            menu.addSeparator()
            menu.addAction("Delete Group", lambda: self.delete_group_requested.emit(item_id))

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _filter(self, text):
        text = text.lower().strip()

        def filter_item(item):
            item_type = item.data(0, Qt.UserRole)
            matched_child = False
            for i in range(item.childCount()):
                if filter_item(item.child(i)):
                    matched_child = True

            if item_type == HOST_ITEM:
                visible = text in item.text(0).lower() or not text
            else:
                visible = matched_child or not text

            item.setHidden(not visible)
            return visible and (item_type == HOST_ITEM or matched_child or not text)

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            filter_item(root.child(i))
