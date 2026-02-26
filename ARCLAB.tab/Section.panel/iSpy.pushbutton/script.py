# -*- coding: utf-8 -*-
from pyrevit import revit, forms
from Autodesk.Revit.DB import TransactionGroup, Transaction, ViewType

# Standard pyRevit access to Document and UI Document
doc = revit.doc
uidoc = revit.uidoc
__doc__ = "Zooms back into relevant area""
active_view = doc.ActiveView

def run_zoom_sequence():
    # 1. Check if the active view is a Section
    # Note: ViewType.Section covers building sections, detail sections, etc.
    if active_view.ViewType != ViewType.Section:
        forms.alert("Please use this tool in a Section view.", title="Wrong View Type")
        return

    # Initialize Transaction Group to wrap multiple transactions into one 'Undo'
    tg = TransactionGroup(doc, "Section Zoom & Crop Sequence")
    tg.Start()

    try:
        # 2. Set Crop View to True so ZoomToFit has a boundary to target
        t = Transaction(doc, "Enable Crop")
        t.Start()
        active_view.CropBoxActive = True
        active_view.CropBoxVisible = True # Show it briefly for the UI to register
        t.Commit()

        # 3. Zoom to Fit
        # UI commands like ZoomToFit do not require an active Transaction
        uiviews = uidoc.GetOpenUIViews()
        for uv in uiviews:
            if uv.ViewId == active_view.Id:
                uv.ZoomToFit()
                break

        # 4. Set Crop View and Visibility to False
        t.Start()
        active_view.CropBoxActive = False
        active_view.CropBoxVisible = False
        t.Commit()

        # Merge all sub-transactions into one entry in the Undo menu
        tg.Assimilate()

    except Exception as e:
        # If any step fails, revert the model to its original state
        if tg.GetStatus() == tg.GetStatus().Started:
            tg.RollBack()
        forms.alert("An error occurred during the sequence:\n\n{}".format(str(e)))

if __name__ == "__main__":
    run_zoom_sequence()