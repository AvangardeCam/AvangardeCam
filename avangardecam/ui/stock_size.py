# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Stock > Stock size...: the user types the block's X, Y and Z and the
stock is put with the model in its middle (engine.stock_size)."""

import FreeCADGui

from PySide import QtCore, QtWidgets

from avangardecam import tr
from avangardecam.engine import ProjectError
from avangardecam.engine import op_zero
from avangardecam.engine import stock_size
from avangardecam.model import stock as model_stock
from avangardecam.ui import details


class StockSizeDialog(QtWidgets.QDialog):
    """X, Y, Z of the block, starting at the stock's present size."""

    def __init__(self, job, parent=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamStockSize")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowTitle(tr("Stock size"))
        self.job = job
        edit = op_zero.stock_edit(job)  # on the active zero point's axes, or on the stock's own
        model = edit.model
        present = edit.bounds.size
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.boxes = []
        for axis, value, model_size in zip("XYZ", present, model.size):
            box = details.length_box(
                value, 0.0, model_size + 2 * model_stock.BoxStock.MAX_ALLOWANCE_MM
            )
            box.setObjectName("AvangardeCamStockSize" + axis)
            box.setToolTip(tr("Model: {}").format(details.mm(model_size)))
            form.addRow(tr("Size {}").format(axis) + ":", box)
            self.boxes.append(box)
        layout.addLayout(form)
        note = QtWidgets.QLabel(
            tr("Model: {}. The stock is put with the model in its middle: the same allowance on both sides in X, in Y and in Z.").format(  # fmt: skip
                details.size_text(model)
            )
        )
        if edit.own:
            from avangardecam.ui import stock_dialog

            note.setText(note.text() + " " + stock_dialog.OWN_ZERO_NOTE())
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def sizes(self):
        return [float(box.property("rawValue")) for box in self.boxes]

    def accept(self):
        """Apply the size (one undo step); a refused size keeps the dialog open."""
        doc = self.job.Document
        doc.openTransaction(tr("Stock size"))
        try:
            stock_size.set_size(self.job, *self.sizes())
        except (ValueError, ProjectError) as exc:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(self, "AvangardeCam", tr(str(exc)))
            return
        doc.commitTransaction()
        super().accept()


def ask(job):
    """Open the dialog (from the stock's details)."""
    try:
        dialog = StockSizeDialog(job)
    except ProjectError as exc:
        QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", str(exc))
        return None
    dialog.open()
    return dialog
