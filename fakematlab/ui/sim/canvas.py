"""
The editing canvas.
===================
Drag blocks from the palette, wire ports together, move, delete, copy, paste,
undo. The model is the source of truth: every edit goes through a
:class:`~PySide6.QtGui.QUndoCommand` that mutates the
:class:`~fakematlab.sim.model.SimModel`, after which the scene is rebuilt from
it. The drawing therefore cannot drift out of step with what will actually be
simulated.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QUndoStack
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView, QMenu

from ...sim.block import block_types
from ...sim.compile import CompileError, compile_model
from ...sim.model import ModelError, PortRef, SimModel
from . import commands as cmd
from .items import GRID, BlockItem, PortItem, WireItem, sel_colour, snap, wire_colour

MIME_TYPE = "application/x-fakematlab-blocks"


class SimCanvas(QGraphicsView):
    """Editable block-diagram canvas."""

    model_changed = Signal()
    selection_changed = Signal(object)      # BlockItem | None
    status = Signal(str)
    path_changed = Signal(list)             # breadcrumb, outermost first

    def __init__(self, model: SimModel | None = None, parent=None) -> None:
        super().__init__(parent)
        self.model = model or SimModel("untitled")
        self.undo_stack = QUndoStack(self)
        self.undo_stack.setUndoLimit(200)

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-2000, -2000, 4000, 4000)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

        #: Stack of (parent model, subsystem block id, parent undo stack) for
        #: each level we have descended into.
        self._stack: list[tuple[SimModel, str, QUndoStack]] = []
        self._blocks: dict[str, BlockItem] = {}
        self._wires: list[WireItem] = []
        self._pending_port: PortItem | None = None
        self._rubber_wire = None

        self._scene.selectionChanged.connect(self._on_selection)
        self.rebuild()

    # ── model ↔ scene ───────────────────────────────────────────

    def set_model(self, model: SimModel) -> None:
        self.model = model
        self._stack.clear()
        self.undo_stack.clear()
        self.rebuild()
        self.model_changed.emit()

    def restore_model(self, data: dict) -> None:
        """Replace the model wholesale — used by undo/redo."""
        self.model = SimModel.from_dict(data)
        self.rebuild()
        self.model_changed.emit()

    def rebuild(self) -> None:
        """Redraw the scene from the model."""
        selected = {i.block_id for i in self._scene.selectedItems()
                    if isinstance(i, BlockItem)}
        self._scene.blockSignals(True)
        self._scene.clear()
        self._blocks.clear()
        self._wires.clear()
        self._pending_port = None
        self._rubber_wire = None

        for block in self.model:
            place = self.model.placement(block.block_id)
            item = BlockItem(block, place.x, place.y)
            item.moved.connect(self._on_block_moved)
            item.double_clicked.connect(self._edit_params)
            self._scene.addItem(item)
            self._blocks[block.block_id] = item
            if block.block_id in selected:
                item.setSelected(True)

        for conn in self.model.connections:
            src = self._port_item(conn.src, is_input=False)
            dst = self._port_item(conn.dst, is_input=True)
            if src is None or dst is None:
                continue
            wire = WireItem(conn, src, dst)
            self._scene.addItem(wire)
            self._wires.append(wire)

        self._scene.blockSignals(False)
        self.validate()
        self.model_changed.emit()

    def _port_item(self, ref: PortRef, is_input: bool) -> PortItem | None:
        item = self._blocks.get(ref.block)
        return item.ports.get((ref.port, is_input)) if item else None

    # ── validation ──────────────────────────────────────────────

    def validate(self) -> str:
        """
        Compile the whole model and mark any block the compiler complains about.

        Validation runs after every edit, so a mistake shows up when it is
        made rather than when Run is pressed. It always compiles the *root*
        model: a subsystem viewed on its own has bare Inport/Outport blocks
        and no context, so compiling only what is on screen would report
        problems that do not exist and miss loops that close outside.
        """
        for item in self._blocks.values():
            item.set_error("")
        if len(self.model) == 0:
            return ""

        prefix = self._flat_prefix()
        try:
            compiled = compile_model(self.root_model())
        except CompileError as exc:
            message = str(exc)
            self._mark(message, message, prefix)
            return message

        if compiled.has_algebraic_loop:
            from ...sim.compile import describe_algebraic_loop
            message = describe_algebraic_loop(compiled)
            self._mark(" ".join(compiled.algebraic_loop), message, prefix)
            return message
        return ""

    def _flat_prefix(self) -> str:
        """How the blocks on screen are named once the model is flattened."""
        return "".join(f"{block_id}/" for _m, block_id, _s in self._stack)

    def _mark(self, haystack: str, message: str, prefix: str) -> None:
        for bid, item in self._blocks.items():
            if prefix + bid in haystack or (not prefix and bid in haystack):
                item.set_error(message)

    # ── editing ─────────────────────────────────────────────────

    def add_block(self, type_name: str, pos: QPointF | None = None) -> None:
        where = pos or self._free_spot()
        self.undo_stack.push(
            cmd.AddBlock(self, type_name, snap(where.x()), snap(where.y())))

    def _free_spot(self) -> QPointF:
        centre = self.mapToScene(self.viewport().rect().center())
        return QPointF(snap(centre.x()), snap(centre.y()))

    def _on_block_moved(self, block_id: str, x: float, y: float) -> None:
        self.undo_stack.push(cmd.MoveBlock(self, block_id, x, y))

    def delete_selection(self) -> None:
        blocks = [i.block_id for i in self._scene.selectedItems()
                  if isinstance(i, BlockItem)]
        wires = [i.connection for i in self._scene.selectedItems()
                 if isinstance(i, WireItem)]
        if blocks or wires:
            self.undo_stack.push(cmd.DeleteSelection(self, blocks, wires))

    def select_all(self) -> None:
        for item in self._blocks.values():
            item.setSelected(True)

    # ── clipboard ───────────────────────────────────────────────

    def copy_selection(self) -> None:
        ids = {i.block_id for i in self._scene.selectedItems()
               if isinstance(i, BlockItem)}
        if not ids:
            return
        data = self.model.to_dict()
        payload = {
            "blocks": [b for b in data["blocks"] if b["id"] in ids],
            "connections": [
                c for c in data["connections"]
                if c["src"].split(".")[0] in ids and c["dst"].split(".")[0] in ids
            ],
        }
        QApplication.clipboard().setText(json.dumps(payload))
        self.status.emit(f"Copied {len(payload['blocks'])} block(s)")

    def paste(self) -> None:
        try:
            payload = json.loads(QApplication.clipboard().text())
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict) or "blocks" not in payload:
            return
        self.undo_stack.push(cmd.PasteBlocks(self, payload, GRID * 3, GRID * 3))

    # ── wiring ──────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        """
        Start a wire, or finish the one already in progress.

        Both gestures work: **drag** from one port to another, or **click**
        one port and then click the other. The click-click form is the one
        that used to be dead — a second click on a port restarted the wire
        instead of completing it, so nothing ever connected and every
        abandoned attempt left a dashed line on the canvas.
        """
        item = self.itemAt(event.position().toPoint())
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        if isinstance(item, PortItem):
            if self._pending_port is not None and item is not self._pending_port:
                self._finish_wire(item)
                self._cancel_wire()
            else:
                self._start_wire(item)
            event.accept()
            return

        if self._pending_port is not None:
            # Clicking anywhere else abandons the wire, rather than leaving an
            # invisible half-connection armed until something else clears it.
            self._cancel_wire()
            self.status.emit("Wiring cancelled")

        # Rubber-band only from empty canvas: starting one on top of a block
        # would make blocks undraggable.
        self.setDragMode(QGraphicsView.RubberBandDrag if item is None
                         else QGraphicsView.NoDrag)
        super().mousePressEvent(event)

    def _start_wire(self, port: PortItem) -> None:
        # Never leave the previous rubber band behind: a second _start_wire
        # used to orphan it in the scene, one stray dashed line per attempt.
        self._cancel_wire()
        self._pending_port = port
        port.set_highlight(True)
        self._rubber_wire = self._scene.addPath(
            QPainterPath(), QPen(sel_colour(), 1.6, Qt.DashLine))
        self._rubber_wire.setZValue(5)
        kind = "input" if port.is_input else "output"
        self.status.emit(
            f"Wiring from {port.block_id}.{port.port} ({kind}) — "
            f"click an {'output' if port.is_input else 'input'} port, "
            f"or press Esc")
        self._highlight_targets(port, True)

    def _highlight_targets(self, port: PortItem, on: bool) -> None:
        """Light up the ports this wire could legally reach."""
        for item in self._blocks.values():
            for (name, is_input), candidate in item.ports.items():
                if candidate is port:
                    continue
                legal = (is_input != port.is_input and
                         candidate.block_id != port.block_id)
                if legal and on and is_input:
                    ref = PortRef(candidate.block_id, name)
                    legal = self.model.connection_into(ref) is None
                if legal:
                    candidate.set_highlight(on)

    def mouseMoveEvent(self, event) -> None:
        if self._rubber_wire is not None and self._pending_port is not None:
            path = QPainterPath(self._pending_port.scene_pos())
            path.lineTo(self.mapToScene(event.position().toPoint()))
            self._rubber_wire.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._pending_port is not None:
            target = self.itemAt(event.position().toPoint())
            if isinstance(target, PortItem) and target is not self._pending_port:
                # A drag that landed on another port: connect and finish.
                self._finish_wire(target)
                self._cancel_wire()
            # Releasing on the starting port, or on empty space, leaves the
            # wire *armed* so the next click can complete it. Cancelling here
            # is what broke click-click wiring: the press had started a wire
            # and the release immediately threw it away.
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _finish_wire(self, target: PortItem) -> None:
        start = self._pending_port
        if start.is_input == target.is_input:
            self.status.emit(
                f"Cannot connect two {'inputs' if start.is_input else 'outputs'}"
                f" — a wire runs from an output to an input.")
            return
        src, dst = (target, start) if start.is_input else (start, target)
        try:
            self.undo_stack.push(cmd.Connect(
                self, f"{src.block_id}.{src.port}",
                f"{dst.block_id}.{dst.port}"))
            self.status.emit(f"Connected {src.block_id}.{src.port} → "
                             f"{dst.block_id}.{dst.port}")
        except ModelError as exc:
            self.status.emit(str(exc))

    def _cancel_wire(self) -> None:
        if self._pending_port is not None:
            self._highlight_targets(self._pending_port, False)
            self._pending_port.set_highlight(False)
            self._pending_port = None
        if self._rubber_wire is not None:
            self._scene.removeItem(self._rubber_wire)
            self._rubber_wire = None

    # ── arranging ───────────────────────────────────────────────

    def selected_blocks(self) -> list:
        from .items import BlockItem

        return [i for i in self._scene.selectedItems()
                if isinstance(i, BlockItem)]

    def align_selection(self, axis: str) -> int:
        """
        Line the selected blocks up. ``axis`` is ``"x"`` or ``"y"``.

        Returns how many moved, so a caller can say nothing happened rather
        than silently doing nothing.
        """
        blocks = self.selected_blocks()
        if len(blocks) < 2:
            self.status.emit("Select two or more blocks to align them")
            return 0
        if axis == "x":
            target = sum(b.pos().x() for b in blocks) / len(blocks)
            moves = [(b.block_id, target, b.pos().y()) for b in blocks]
        else:
            target = sum(b.pos().y() for b in blocks) / len(blocks)
            moves = [(b.block_id, b.pos().x(), target) for b in blocks]
        self.undo_stack.push(cmd.MoveBlocks(self, moves))
        return len(moves)

    def distribute_selection(self, axis: str) -> int:
        """Space the selected blocks evenly along ``axis``."""
        blocks = self.selected_blocks()
        if len(blocks) < 3:
            self.status.emit("Select three or more blocks to distribute them")
            return 0
        key = (lambda b: b.pos().x()) if axis == "x" else (lambda b: b.pos().y())
        ordered = sorted(blocks, key=key)
        first, last = key(ordered[0]), key(ordered[-1])
        step = (last - first) / (len(ordered) - 1)
        moves = []
        for index, block in enumerate(ordered):
            value = first + index * step
            if axis == "x":
                moves.append((block.block_id, value, block.pos().y()))
            else:
                moves.append((block.block_id, block.pos().x(), value))
        self.undo_stack.push(cmd.MoveBlocks(self, moves))
        return len(moves)

    # ── parameters ──────────────────────────────────────────────

    def _edit_params(self, block_id: str) -> None:
        """Double-click: descend into a subsystem, or edit parameters."""
        block = self.model.block(block_id)
        if block.type_name == "Subsystem":
            self.descend(block_id)
            return

        from .params import ParamDialog

        dialog = ParamDialog(block, self)
        if dialog.exec() and dialog.changes:
            self.undo_stack.push(cmd.SetParams(self, block_id, dialog.changes))

    # ── hierarchy ───────────────────────────────────────────────

    def descend(self, block_id: str) -> None:
        """
        Open a subsystem's contents, remembering the way back.

        Edits inside are written back into the parent's ``model`` parameter
        when you ascend, as one undoable step — so descending, editing and
        coming back up is a single entry in the undo history rather than a
        trail the user has to unwind one block at a time.
        """
        block = self.model.block(block_id)
        self._stack.append((self.model, block_id, self.undo_stack))
        inner = block.inner_model()
        inner.name = block.params.get("name", block_id)
        self.model = inner
        self.undo_stack = QUndoStack(self)
        self.rebuild()
        self.fit_all()
        self.path_changed.emit(self.breadcrumb())

    def ascend(self) -> None:
        """Go back up one level, saving whatever changed inside."""
        if not self._stack:
            return
        inner = self.model
        parent, block_id, parent_stack = self._stack.pop()
        self.model = parent
        self.undo_stack = parent_stack
        self.undo_stack.push(
            cmd.SetParams(self, block_id, {"model": inner.to_dict()}))
        self.rebuild()
        self.fit_all()
        self.path_changed.emit(self.breadcrumb())

    def breadcrumb(self) -> list[str]:
        """Names from the top level down to what is on screen."""
        names = [parent.name for parent, _bid, _stack in self._stack]
        return names + [self.model.name]

    @property
    def inside_subsystem(self) -> bool:
        return bool(self._stack)

    def root_model(self) -> SimModel:
        """
        The top-level model, with any open subsystem's edits folded in.

        Running or saving while inside a subsystem must use the whole model,
        not just the part on screen.
        """
        if not self._stack:
            return self.model
        inner = self.model
        for parent, block_id, _stack in reversed(self._stack):
            parent.block(block_id).set_param("model", inner.to_dict())
            inner = parent
        return inner

    # ── input ───────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key_Escape:
            if self._pending_port is not None:
                self._cancel_wire()
                self.status.emit("")
            elif self.inside_subsystem:
                self.ascend()
        elif key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selection()
        elif event.matches(QKeySequence.Copy):
            self.copy_selection()
        elif event.matches(QKeySequence.Paste):
            self.paste()
        elif event.matches(QKeySequence.SelectAll):
            self.select_all()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        item = self.itemAt(event.pos())
        if isinstance(item, BlockItem):
            if item.block.type_name == "Subsystem":
                menu.addAction("Open subsystem",
                               lambda: self.descend(item.block_id))
            else:
                menu.addAction("Parameters…",
                               lambda: self._edit_params(item.block_id))
            menu.addSeparator()
        if self.inside_subsystem:
            menu.addAction("↑ Up one level", self.ascend)
            menu.addSeparator()
        menu.addAction("Delete", self.delete_selection)
        menu.addAction("Copy", self.copy_selection)
        menu.addAction("Paste", self.paste)
        menu.addSeparator()
        menu.addAction("Fit to view", self.fit_all)
        menu.exec(event.globalPos())

    # ── drag & drop from the palette ────────────────────────────

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(MIME_TYPE):
            return
        type_name = bytes(event.mimeData().data(MIME_TYPE)).decode()
        if type_name in block_types():
            self.add_block(type_name,
                           self.mapToScene(event.position().toPoint()))
            event.acceptProposedAction()

    # ── view helpers ────────────────────────────────────────────

    def fit_all(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            self.resetTransform()
            return
        self.resetTransform()
        self.fitInView(rect.adjusted(-40, -40, 40, 40), Qt.KeepAspectRatio)
        # Never zoom past 1:1 — a three-block model filling the screen at 400%
        # looks broken rather than helpful.
        if self.transform().m11() > 1.0:
            self.resetTransform()
            self.centerOn(rect.center())

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        colour = QColor(wire_colour())
        colour.setAlpha(36)
        painter.setPen(QPen(colour, 0.6))
        step = GRID * 5
        left = int(rect.left() - rect.left() % step)
        top = int(rect.top() - rect.top() % step)
        lines = []
        x = left
        while x < rect.right():
            lines.append(((x, rect.top()), (x, rect.bottom())))
            x += step
        y = top
        while y < rect.bottom():
            lines.append(((rect.left(), y), (rect.right(), y)))
            y += step
        for (x1, y1), (x2, y2) in lines:
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _on_selection(self) -> None:
        blocks = [i for i in self._scene.selectedItems()
                  if isinstance(i, BlockItem)]
        self.selection_changed.emit(blocks[0] if len(blocks) == 1 else None)
