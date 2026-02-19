# -*- coding: utf-8 -*-
__title__ = "Toggle Point Clouds"
__doc__ = "Toggles the visibility of all point clouds in the active view."

from Autodesk.Revit.DB import FilteredElementCollector, PointCloudInstance, Transaction
from pyrevit import revit, forms

# Get the active document and view
doc = revit.doc
view = revit.active_view

def toggle_point_clouds():
    # 1. Collect all Point Cloud instances in the project
    point_clouds = FilteredElementCollector(doc).OfClass(PointCloudInstance).ToElements()

    if not point_clouds:
        forms.alert("No point clouds found in this project.", title="Toggle Info")
        return

    # 2. Check the current visibility state of the first point cloud to determine the toggle
    # We use the category hidden status in the active view
    category_id = point_clouds[0].Category.Id
    is_hidden = view.GetCategoryHidden(category_id)

    # 3. Start a Transaction to change the view settings
    with Transaction(doc, "Toggle Point Cloud Visibility") as t:
        t.Start()
        try:
            # Toggle the category visibility (True -> False or False -> True)
            view.SetCategoryHidden(category_id, not is_hidden)
            t.Commit()
        except Exception as e:
            t.RollBack()
            forms.alert("Failed to toggle: {}".format(str(e)))

if __name__ == "__main__":
    toggle_point_clouds()