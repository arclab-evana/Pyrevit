# -*- coding: utf-8 -*-
from pyrevit import revit, forms
from Autodesk.Revit.DB import TransactionGroup, Transaction, ViewType

# Correct way to access doc and uidoc in pyRevit
doc = revit.doc
uidoc = revit.uidoc
active_view = doc.ActiveView

def run_zoom_sequence():
    # 1. Check if the active view is a Section
    if active_view.ViewType != ViewType.Section:
        forms.alert("Please use this tool in a Section view.", title="Wrong View Type")
        return

    # Initialize Transaction Group
    tg = TransactionGroup(doc, "Section Zoom Sequence")
    tg.Start()

    try:
        # 2. Set Crop View to True
        t = Transaction(doc, "Toggle Crop On")
        t.Start()
        active_view.CropBoxActive = True
        t.Commit()

        # 3. Zoom to Fit (UI Commands don't need a Transaction)
        uiviews = uidoc.GetOpenUIViews()
        for uv in uiviews:
            if uv.ViewId == active_view.Id:
                uv.ZoomToFit()
                break

        # 4. Set Crop View to False
        t.Start()
        active_view.CropBoxActive = False
        t.Commit()

        # Merge the two 't' transactions into one 'tg' entry
        tg.Assimilate()

    except Exception as e:
        if tg.GetStatus() == tg.GetStatus().Started:
            tg.RollBack()
        forms.alert("An error occurred: {}".format(str(e)))

if __name__ == "__main__":
    run_zoom_sequence()