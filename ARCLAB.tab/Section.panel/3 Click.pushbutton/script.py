"""
3-Click Section Tool (Succinct Edition)
Features: Breadcrumb Anchor, Temp Connector, Ortho Snapping, Dynamic Depth, Auto-Open
"""
import math
from pyrevit import revit, DB, forms

doc = revit.doc
uidoc = revit.uidoc

# --- SETTINGS ---
ORTHO_TOLERANCE_DEGREES = 15
BREADCRUMB_PAPER_MM = 4.0
DEFAULT_HEIGHT_MM = 3000
MIN_SECTION_LENGTH_MM = 50
MIN_DEPTH_MM = 50
DEFAULT_DEPTH_MM = 500

# --- HELPER FUNCTIONS ---
def mm_to_ft(mm):
    return DB.UnitUtils.ConvertToInternalUnits(mm, DB.UnitTypeId.Millimeters)

def get_upper_level(current_level):
    all_levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
    sorted_levels = sorted(all_levels, key=lambda l: l.Elevation)
    
    for i, level in enumerate(sorted_levels):
        if level.Id == current_level.Id:
            if i + 1 < len(sorted_levels):
                return sorted_levels[i+1]
    return None

def get_default_section_type():
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    target_name = "AL_Section"
    
    for v in vt_collector:
        if v.ViewFamily == DB.ViewFamily.Section and v.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == target_name:
            return v
            
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    return next((v for v in vt_collector if v.ViewFamily == DB.ViewFamily.Section), None)

def snap_ortho_with_tolerance(p1, p2, tolerance_degrees):
    vec = p2 - p1
    length = vec.GetLength()
    if length < 0.001: return p2

    threshold = math.cos(math.radians(tolerance_degrees))
    norm_x = abs(vec.X / length)
    norm_y = abs(vec.Y / length)
    
    if norm_x > threshold: return DB.XYZ(p2.X, p1.Y, p2.Z)
    elif norm_y > threshold: return DB.XYZ(p1.X, p2.Y, p2.Z)
    return p2

def create_breadcrumb_visual(doc, center_pt, view):
    ids = []
    view_scale = view.Scale
    size_ft = (mm_to_ft(BREADCRUMB_PAPER_MM * view_scale)) / 2.0
    
    p1, p2 = center_pt + DB.XYZ(size_ft, size_ft, 0), center_pt + DB.XYZ(-size_ft, -size_ft, 0)
    p3, p4 = center_pt + DB.XYZ(-size_ft, size_ft, 0), center_pt + DB.XYZ(size_ft, -size_ft, 0)
    
    try:
        l1, l2 = DB.Line.CreateBound(p1, p2), DB.Line.CreateBound(p3, p4)
        ids.append(doc.Create.NewDetailCurve(view, l1).Id)
        ids.append(doc.Create.NewDetailCurve(view, l2).Id)
    except: pass 
    return ids

# --- CORE LOGIC ---
def create_3_click_section():
    active_view = doc.ActiveView
    if active_view.ViewType not in [DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan]:
        forms.alert("Please run this tool from a Floor or Ceiling Plan.", exitscript=True)
    
    curr_level = active_view.GenLevel
    if not curr_level:
        forms.alert("Current view does not have an associated level.", exitscript=True)

    tg = DB.TransactionGroup(doc, "Create 3-Click Section")
    tg.Start()
    temp_ids_to_delete = []

    try:
        # CLICK 1
        pt_start = uidoc.Selection.PickPoint("Click 1: Start of Section Line")
        p1 = DB.XYZ(pt_start.X, pt_start.Y, 0)

        t_crumb = DB.Transaction(doc, "Draw Breadcrumb")
        t_crumb.Start()
        temp_ids_to_delete.extend(create_breadcrumb_visual(doc, p1, active_view))
        doc.Regenerate()
        t_crumb.Commit()
        
        # CLICK 2
        pt_end_raw = uidoc.Selection.PickPoint("Click 2: End of Section Line")
        p2 = snap_ortho_with_tolerance(p1, DB.XYZ(pt_end_raw.X, pt_end_raw.Y, 0), ORTHO_TOLERANCE_DEGREES)

        vec_line = p2 - p1
        if vec_line.GetLength() < mm_to_ft(MIN_SECTION_LENGTH_MM):
            tg.RollBack()
            forms.alert("Section line too short.", exitscript=True)

        t_temp = DB.Transaction(doc, "Draw Temp Line")
        t_temp.Start()
        temp_ids_to_delete.append(doc.Create.NewDetailCurve(active_view, DB.Line.CreateBound(p1, p2)).Id)
        doc.Regenerate()
        t_temp.Commit()

        # CLICK 3
        pt_depth = uidoc.Selection.PickPoint("Click 3: Depth/Direction")
        p3 = DB.XYZ(pt_depth.X, pt_depth.Y, 0)

        # CALCULATIONS
        midpoint = p1 + (vec_line / 2.0)
        ortho_dir = vec_line.CrossProduct(DB.XYZ.BasisZ).Normalize()
        vec_to_depth = p3 - p1
        view_dir = ortho_dir if ortho_dir.DotProduct(vec_to_depth) >= 0 else -ortho_dir

        depth_dist_ft = max(abs(view_dir.DotProduct(vec_to_depth)), mm_to_ft(MIN_DEPTH_MM))
        
        upper_level = get_upper_level(curr_level)
        height_ft = (upper_level.Elevation - curr_level.Elevation) if upper_level else mm_to_ft(DEFAULT_HEIGHT_MM)

        section_length_ft = vec_line.GetLength()
        bbox = DB.BoundingBoxXYZ()
        bbox.Min = DB.XYZ(-section_length_ft / 2.0, 0, 0)
        bbox.Max = DB.XYZ(section_length_ft / 2.0, height_ft, depth_dist_ft)

        t = DB.Transform.Identity
        t.Origin = midpoint
        t.BasisZ = view_dir
        t.BasisY = DB.XYZ.BasisZ
        t.BasisX = t.BasisY.CrossProduct(t.BasisZ)
        bbox.Transform = t

        # FINAL CREATION
        t_final = DB.Transaction(doc, "Create View")
        t_final.Start()
        
        if temp_ids_to_delete:
            doc.Delete(revit.framework.List[DB.ElementId](temp_ids_to_delete))

        section_type = get_default_section_type()
        new_section = DB.ViewSection.CreateSection(doc, section_type.Id, bbox)
        
        # --- UPDATED PROPERTIES ---
        new_section.CropBoxActive = False # Untick Crop View
        new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING).Set(1)
        new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR).Set(depth_dist_ft)

        t_final.Commit()
        tg.Assimilate()

        # --- AUTO-OPEN VIEW ---
        uidoc.ActiveView = new_section

    except Exception as e:
        tg.RollBack()
        if "Operation canceled" not in str(e):
            forms.alert("Error: {}".format(e))

if __name__ == "__main__":
    create_3_click_section()