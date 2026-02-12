"""
3-Click Section Tool (Millimeter Edition)
1. Pick Start Point
2. Pick End Point (Defines width)
3. Pick Depth Point (Defines view direction and far clip offset)
Test new
"""
from pyrevit import revit, DB, forms

doc = revit.doc
uidoc = revit.uidoc

# --- USER SETTINGS (IN MILLIMETERS) ---
# Define your safety limits here in MM
DEFAULT_HEIGHT_MM = 3000       # Height if no level above is found
MIN_SECTION_LENGTH_MM = 50     # Minimum length of the section line
MIN_DEPTH_MM = 50              # Minimum far clip depth (if you click too close to line)
DEFAULT_DEPTH_MM = 500         # Default depth if calculation fails or is too small

# --- HELPER FUNCTIONS ---

def mm_to_ft(mm):
    """Converts millimeters to internal Revit feet."""
    return DB.UnitUtils.ConvertToInternalUnits(mm, DB.UnitTypeId.Millimeters)

def get_upper_level(current_level):
    """Finds the level immediately above the current level to determine height."""
    all_levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
    sorted_levels = sorted(all_levels, key=lambda l: l.Elevation)
    
    for i, level in enumerate(sorted_levels):
        if level.Id == current_level.Id:
            if i + 1 < len(sorted_levels):
                return sorted_levels[i+1]
    return None

def get_default_section_type():
    """Finds a valid ViewSection ViewFamilyType."""
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    
    # 1. Look for AL_Section
    target_name = "AL_Section"
    for v in vt_collector:
        if v.ViewFamily == DB.ViewFamily.Section and v.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == target_name:
            return v
            
    # 2. Fallback: Return the first available Section type
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    return next((v for v in vt_collector if v.ViewFamily == DB.ViewFamily.Section), None)

# --- CORE LOGIC ---

def create_3_click_section():
    # 1. Validation: Ensure we are in a Plan View
    active_view = doc.ActiveView
    if active_view.ViewType not in [DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan]:
        forms.alert("Please run this tool from a Floor or Ceiling Plan.", exitscript=True)
    
    curr_level = active_view.GenLevel
    if not curr_level:
        forms.alert("Current view does not have an associated level.", exitscript=True)

    # 2. User Inputs (The 3 Clicks)
    try:
        pt_start = uidoc.Selection.PickPoint("Click 1: Start of Section Line")
        pt_end = uidoc.Selection.PickPoint("Click 2: End of Section Line")
        pt_depth = uidoc.Selection.PickPoint("Click 3: Define Section Depth/Direction")
    except Exception:
        return # User cancelled

    # 3. Vector Math setup
    # Project points to Z=0 to ensure planar math
    p1 = DB.XYZ(pt_start.X, pt_start.Y, 0)
    p2 = DB.XYZ(pt_end.X, pt_end.Y, 0)
    p3 = DB.XYZ(pt_depth.X, pt_depth.Y, 0)

    # Vector representing the section line
    vec_line = p2 - p1
    section_length_ft = vec_line.GetLength()
    
    # EXPLANATION: Length Check in MM
    # We convert our Minimum MM constant to Feet to compare with Revit's internal length
    if section_length_ft < mm_to_ft(MIN_SECTION_LENGTH_MM):
        forms.alert("Section line is too short (<{}mm).".format(MIN_SECTION_LENGTH_MM), exitscript=True)

    # Calculate Midpoint (Origin of the Section)
    midpoint = p1 + (vec_line / 2.0)

    # 4. Determine View Direction
    # Cross product of Line (X,Y,0) and BasisZ (0,0,1) gives a perpendicular vector
    ortho_dir = vec_line.CrossProduct(DB.XYZ.BasisZ).Normalize()
    vec_to_depth = p3 - p1
    
    # Dot product check to flip direction if needed
    if ortho_dir.DotProduct(vec_to_depth) < 0:
        view_dir = -ortho_dir
    else:
        view_dir = ortho_dir

    # 5. Calculate Depth (Far Clip Offset)
    # Project vec_to_depth onto the view_dir
    depth_dist_ft = abs(view_dir.DotProduct(vec_to_depth))
    
    # EXPLANATION: Depth Safety in MM
    # If the user clicks closer than MIN_DEPTH_MM (e.g., 50mm), 
    # we enforce a default depth (e.g. 500mm) instead of creating a flat view.
    min_depth_ft = mm_to_ft(MIN_DEPTH_MM)
    
    if depth_dist_ft < min_depth_ft: 
        depth_dist_ft = mm_to_ft(DEFAULT_DEPTH_MM)

    # 6. Calculate Height
    upper_level = get_upper_level(curr_level)
    if upper_level:
        height_ft = upper_level.Elevation - curr_level.Elevation
    else:
        height_ft = mm_to_ft(DEFAULT_HEIGHT_MM)

    # 7. Construct the BoundingBox (All units are now confirmed Feet derived from MM logic)
    bbox = DB.BoundingBoxXYZ()
    bbox.Min = DB.XYZ(-section_length_ft / 2.0, 0, 0)
    bbox.Max = DB.XYZ(section_length_ft / 2.0, height_ft, depth_dist_ft)

    # 8. Define Orientation Transform
    t = DB.Transform.Identity
    t.Origin = midpoint
    t.BasisZ = view_dir
    t.BasisY = DB.XYZ.BasisZ
    t.BasisX = t.BasisY.CrossProduct(t.BasisZ)
    bbox.Transform = t

    # 9. Create the View (Transactional)
    section_type = get_default_section_type()
    if not section_type:
        forms.alert("No suitable Section View Type found.", exitscript=True)

    # Transaction Group for clean Rollback
    tg = DB.TransactionGroup(doc, "Create 3-Click Section")
    tg.Start()

    try:
        t_inner = DB.Transaction(doc, "Create View")
        t_inner.Start()
        
        # Create Section
        new_section = DB.ViewSection.CreateSection(doc, section_type.Id, bbox)
        
        # Apply visual settings
        new_section.CropBoxActive = True
        new_section.CropBoxVisible = False
        
        # Set Far Clip
        new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING).Set(1) 
        new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR).Set(depth_dist_ft)

        t_inner.Commit()
        tg.Assimilate()

    except Exception as e:
        if 't_inner' in locals() and t_inner.GetStatus() == DB.TransactionStatus.Started:
            t_inner.RollBack()
        tg.RollBack()
        forms.alert("Transaction Failed. Changes rolled back.\nError: {}".format(e))

# --- EXECUTION ---
if __name__ == "__main__":
    create_3_click_section()