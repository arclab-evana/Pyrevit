# -*- coding: utf-8 -*-
__doc__ = "Switches point cloud display between RGB and Normals."

from Autodesk.Revit.DB import (
    FilteredElementCollector, 
    PointCloudInstance, 
    Transaction, 
    PointCloudColorMode,
    BuiltInCategory,
    ElementId
)
from Autodesk.Revit.DB.PointClouds import PointCloudOverrideSettings

from pyrevit import revit, forms

doc = revit.doc
view = revit.active_view

def toggle_pc_color_mode():
    # 1. Collect point clouds
    pcs = FilteredElementCollector(doc).OfClass(PointCloudInstance).ToElements()
    
    if not pcs:
        forms.alert("No point clouds found in the project.", title="Error")
        return

    # 2. Check if the Point Cloud category is visible
    pc_cat_id = ElementId(BuiltInCategory.OST_PointClouds)
    if view.GetCategoryHidden(pc_cat_id):
        forms.alert("Turn point cloud on before proceeding.", title="Visibility Off")
        return

    # 3. Access Overrides
    pc_overrides = view.GetPointCloudOverrides()

    with Transaction(doc, "Toggle PC Color Mode") as t:
        t.Start()
        
        for pc in pcs:
            # 4. Get current override settings for this instance
            current_settings = pc_overrides.GetPointCloudScanOverrideSettings(pc.Id)
            current_mode = current_settings.ColorMode

            # 5. Logic: Switch between RGB (NoOverride) and Normals
            if current_mode == PointCloudColorMode.Normals:
                new_mode = PointCloudColorMode.NoOverride
            else:
                new_mode = PointCloudColorMode.Normals
            
            # 6. Apply new settings
            new_settings = PointCloudOverrideSettings()
            new_settings.ColorMode = new_mode
            
            pc_overrides.SetPointCloudScanOverrideSettings(pc.Id, new_settings)
        
        t.Commit()

if __name__ == "__main__":
    toggle_pc_color_mode()