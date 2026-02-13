"""
3-Click Section Tool (Optimized Edition)
Changes: Removed doc.Regenerate, optimized collectors, used context managers.
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
TEMP_LINE_STYLE_NAME = "<Overhead>"

# --- HELPER FUNCTIONS ---

def mm_to_ft(mm):
    return DB.UnitUtils.ConvertToInternalUnits(mm, DB.UnitTypeId.Millimeters)

def get_upper_level(current_level):
    # Faster collection: Filter levels before bringing into Python
    all_levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
    # Find levels higher than current, then pick the lowest of those
    upper_levels = sorted([l for l in all_levels if l.Elevation > current_level.Elevation], key=lambda l: l.Elevation)
    return upper_levels[0] if upper_levels else None

def get_default_section_type():
    # Targeted search: Look only for ElementTypes to reduce memory footprint
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    
    # Use a single pass to find the preferred name or fallback
    fallback = None
    for v in vt_collector:
        if v.ViewFamily == DB.ViewFamily.Section:
            if not fallback: fallback = v
            if v.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == "AL_Section":
                return v
    return fallback

def get_linestyle_by_name(doc, name):
    collector = DB.FilteredElementCollector(doc).OfClass(DB.GraphicsStyle)
    for gs in collector:
        if gs.Name == name:
            return gs
    return None

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
    
    p_top = center_pt + DB.XYZ(0, size_ft, 0)
    p_bottom = center_pt + DB.XYZ(0, -size_ft, 0)
    p_left = center_pt + DB.XYZ(-size_ft, 0, 0)
    p_right = center_pt + DB.XYZ(size_ft, 0, 0)
    
    try:
        l1 = DB.Line.CreateBound(p_top, p_bottom)
        l2 = DB.Line.CreateBound(p_left, p_right)
        ids.append(doc.Create.NewDetailCurve(view, l1).Id)
        ids.append(doc.Create.NewDetailCurve(view, l2).Id)
    except: pass 
    return ids

# --- CORE LOGIC ---

def create_3_click_section():
    active_view = doc.ActiveView
    if active_view.ViewType not in [DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan]:
        forms.alert("Please run from a Plan view.", exitscript=True)
    
    curr_level = active_view.GenLevel
    if not curr_level:
        forms.alert("No associated level found.", exitscript=True)

    # Use TransactionGroup for a clean undo stack
    with DB.TransactionGroup(doc, "Fast 3-Click Section") as tg:
        tg.Start()
        temp_ids = []

        try:
            # CLICK 1
            pt_start = uidoc.Selection.PickPoint("Click 1: Start")
            p1 = DB.XYZ(pt_start.X, pt_start.Y, 0)

            # VISUAL 1: Context Manager handles Start/Commit automatically
            with DB.Transaction(doc, "Crumb") as t1:
                t1.Start()
                temp_ids.extend(create_breadcrumb_visual(doc, p1, active_view))
                t1.Commit()
            
            # FAST REFRESH (No Regeneration)
            uidoc.RefreshActiveView()

            # CLICK 2
            pt_end_raw = uidoc.Selection.PickPoint("Click 2: End")
            p2 = snap_ortho_with_tolerance(p1, DB.XYZ(pt_end_raw.X, pt_end_raw.Y, 0), ORTHO_TOLERANCE_DEGREES)

            # VISUAL 2
            with DB.Transaction(doc, "TempLine") as t2:
                t2.Start()
                line_geom = DB.Line.CreateBound(p1, p2)
                temp_crv = doc.Create.NewDetailCurve(active_view, line_geom)
                style = get_linestyle_by_name(doc, TEMP_LINE_STYLE_NAME)
                if style: temp_crv.LineStyle = style
                temp_ids.append(temp_crv.Id)
                t2.Commit()
            
            uidoc.RefreshActiveView()

            # CLICK 3
            pt_depth = uidoc.Selection.PickPoint("Click 3: Depth")
            p3 = DB.XYZ(pt_depth.X, pt_depth.Y, 0)

            # CALCULATIONS
            vec_line = p2 - p1
            midpoint = p1 + (vec_line / 2.0)
            ortho_dir = vec_line.CrossProduct(DB.XYZ.BasisZ).Normalize()
            vec_to_depth = p3 - p1
            view_dir = ortho_dir if ortho_dir.DotProduct(vec_to_depth) >= 0 else -ortho_dir
            
            depth_dist_ft = max(abs(view_dir.DotProduct(vec_to_depth)), mm_to_ft(MIN_DEPTH_MM))
            upper_level = get_upper_level(curr_level)
            height_ft = (upper_level.Elevation - curr_level.Elevation) if upper_level else mm_to_ft(DEFAULT_HEIGHT_MM)

            # BBOX SETUP
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
            with DB.Transaction(doc, "Create View") as t_final:
                t_final.Start()
                if temp_ids: doc.Delete(revit.framework.List[DB.ElementId](temp_ids))
                
                s_type = get_default_section_type()
                new_sec = DB.ViewSection.CreateSection(doc, s_type.Id, bbox)
                new_sec.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING).Set(1)
                new_sec.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR).Set(depth_dist_ft)
                t_final.Commit()

            tg.Assimilate()

        except Exception as e:
            tg.RollBack()
            if "canceled" not in str(e).lower():
                forms.alert("Error: {}".format(e))

if __name__ == "__main__":
    create_3_click_section()