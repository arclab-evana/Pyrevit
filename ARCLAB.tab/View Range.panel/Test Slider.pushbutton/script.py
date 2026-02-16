from pyrevit import revit, DB

view = revit.active_view
# The correct way to handle a transaction
with DB.Transaction(revit.doc, "Manual Test") as t:
    t.Start()
    vr = view.GetViewRange()
    # 1500mm in Feet is approx 4.92
    vr.SetOffset(DB.PlanViewPlane.CutPlane, 4.92) 
    view.SetViewRange(vr)
    t.Commit()

revit.uidoc.RefreshActiveView()