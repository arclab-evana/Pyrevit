"""
3-Click Section Tool
Features:
- Live Visual Feedback (Temp Line)
- Intelligent Ortho Snapping (with Tolerance)
- Dynamic Depth
"""
import math
from pyrevit import revit, DB, forms

doc = revit.doc
uidoc = revit.uidoc

# --- SETTINGS (USER CONFIGURABLE) ---
# Units: Millimeters

# Snapping Tolerance (Degrees)
# If your angle is within this many degrees of X or Y axis, it will snap.
# Set to 90 to ALWAYS snap (old behavior). Set to 0 to NEVER snap.
ORTHO_TOLERANCE_DEGREES = 15 

# Dimensions
DEFAULT_HEIGHT_MM = 3000       # Height if no level above is found
MIN_SECTION_LENGTH_MM = 50     # Minimum length of the section line
MIN_DEPTH_MM = 50              # Minimum far clip depth (if you click too close to line)
DEFAULT_DEPTH_MM = 500         # Default depth if calculation fails or is too small

# --- HELPER FUNCTIONS ---

def mm_to_ft(mm):
    """Converts millimeters to internal Revit feet."""
    return DB.UnitUtils.ConvertToInternalUnits(mm, DB.UnitTypeId.Millimeters)

def get_upper_level(current_level):
    """Finds the level immediately above the current level."""
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

def snap_ortho_with_tolerance(p1, p2, tolerance_degrees):
    """
    Checks the angle of the line P1->P2.
    If it is within 'tolerance_degrees' of an axis, it snaps orthogonal.
    """
    vec = p2 - p1
    length = vec.GetLength()
    
    # Avoid division by zero for tiny clicks
    if length < 0.001: 
        return p2

    # Calculate threshold for Dot Product comparison
    # cos(0) = 1.0 (Perfectly aligned)
    # cos(15) = ~0.96
    threshold = math.cos(math.radians(tolerance_degrees))
    
    norm_x = abs(vec.X / length)
    norm_y = abs(vec.Y / length)
    
    # Check Horizontal Snap (Vector is mostly X)
    if norm_x > threshold:
        return DB.XYZ(p2.X, p1.Y, p2.Z) # Keep X, force Y to match p1
        
    # Check Vertical Snap (Vector is mostly Y)
    elif norm_y > threshold:
        return DB.XYZ(p1.X, p2.Y, p2.Z) # Keep Y, force X to match p1
        
    # Otherwise, return original diagonal point
    return p2

# --- CORE LOGIC ---

def create_3_click_section():
    # 1. Validation
    active_view = doc.ActiveView
    if active_view.ViewType not in [DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan]:
        forms.alert("Please run this tool from a Floor or Ceiling Plan.", exitscript=True)
    
    curr_level = active_view.GenLevel
    if not curr_level:
        forms.alert("Current view does not have an associated level.", exitscript=True)

    # 2. Start Transaction Group
    # We use a Group so we can commit temp lines then roll them back if needed,
    # or commit the whole thing as one "Undo" step.
    tg = DB.TransactionGroup(doc, "Create 3-Click Section")
    tg.Start()

    temp_ids_to_delete = []

    try:
        # --- CLICK 1: START ---
        pt_start = uidoc.Selection.PickPoint("Click 1: Start of Section Line")
        
        # --- CLICK 2: END (With Ortho Snap) ---
        pt_end_raw = uidoc.Selection.PickPoint("Click 2: End of Section Line")
        
        # Logic: Flatten Z (Project to ground plane)
        p1 = DB.XYZ(pt_start.X, pt_start.Y, 0)
        p2_raw = DB.XYZ(pt_end_raw.X, pt_end_raw.Y, 0)
        
        # Logic: Apply Snap with Tolerance
        p2 = snap_ortho_with_tolerance(p1, p2_raw, ORTHO_TOLERANCE_DEGREES)

        # Logic: Check Length (in Feet, converted from MM)
        vec_line = p2 - p1
        if vec_line.GetLength() < mm_to_ft(MIN_SECTION_LENGTH_MM):
            tg.RollBack()
            forms.alert("Section line is too short (<{}mm).".format(MIN_SECTION_LENGTH_MM), exitscript=True)

        # --- VISUAL FEEDBACK (TEMP LINE) ---
        # Draw a temporary line so user sees the "spine" while picking depth
        t_temp = DB.Transaction(doc, "Draw Temp Line")
        t_temp.Start()
        try:
            line_geom = DB.Line.CreateBound(p1, p2)
            # Create Detail Line on current view
            temp_crv = doc.Create.NewDetailCurve(active_view, line_geom)
            temp_ids_to_delete.append(temp_crv.Id)
            doc.Regenerate() # Force screen update
        except Exception:
            pass # Ignore if drawing fails
        t_temp.Commit()

        # --- CLICK 3: DEPTH ---
        pt_depth = uidoc.Selection.PickPoint("Click 3: Define Section Depth/Direction")
        p3 = DB.XYZ(pt_depth.X, pt_depth.Y, 0)

        # --- CALCULATION PHASE ---
        
        # 1. Midpoint (Origin)
        midpoint = p1 + (vec_line / 2.0)

        # 2. View Direction
        # Cross product of Line (X,Y,0) and BasisZ (0,0,1) gives perpendicular vector
        ortho_dir = vec_line.CrossProduct(DB.XYZ.BasisZ).Normalize()
        vec_to_depth = p3 - p1
        
        # Dot product checks if we are looking "up" or "down" relative to line
        if ortho_dir.DotProduct(vec_to_depth) < 0:
            view_dir = -ortho_dir
        else:
            view_dir = ortho_dir

        # 3. Depth (Far Clip Offset)
        depth_dist_ft = abs(view_dir.DotProduct(vec_to_depth))
        
        # Apply Minimum Depth logic
        min_depth_ft = mm_to_ft(MIN_DEPTH_MM)
        if depth_dist_ft < min_depth_ft: 
            depth_dist_ft = mm_to_ft(DEFAULT_DEPTH_MM)

        # 4. Height
        upper_level = get_upper_level(curr_level)
        if upper_level:
            height_ft = upper_level.Elevation - curr_level.Elevation
        else:
            height_ft = mm_to_ft(DEFAULT_HEIGHT_MM)

        # 5. Bounding Box Construction
        section_length_ft = vec_line.GetLength()
        bbox = DB.BoundingBoxXYZ()
        # Centered horizontally
        bbox.Min = DB.XYZ(-section_length_ft / 2.0, 0, 0)
        # Max defines height and depth
        bbox.Max = DB.XYZ(section_length_ft / 2.0, height_ft, depth_dist_ft)

        # 6. Transform (Orientation)
        t = DB.Transform.Identity
        t.Origin = midpoint
        t.BasisZ = view_dir
        t.BasisY = DB.XYZ.BasisZ
        t.BasisX = t.BasisY.CrossProduct(t.BasisZ)
        bbox.Transform = t

        # --- CREATION PHASE ---
        t_final = DB.Transaction(doc, "Create View")
        t_final.Start()
        
        # 1. Cleanup temp line
        if temp_ids_to_delete:
            doc.Delete(revit.framework.List[DB.ElementId](temp_ids_to_delete))

        # 2. Create Section
        section_type = get_default_section_type()
        if not section_type:
            # Create a fallback if somehow none exist
            forms.alert("No Section View Type found.", exitscript=True)

        new_section = DB.ViewSection.CreateSection(doc, section_type.Id, bbox)
        
        # 3. Apply Visual Settings
        new_section.CropBoxActive = True
        new_section.CropBoxVisible = False
        
        # Set Far Clip (1 = Clip without line)
        new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING).Set(1) 
        new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR).Set(depth_dist_ft)

        t_final.Commit()
        
        # Finalize the Transaction Group
        tg.Assimilate()

    except Exception as e:
        # If user presses Esc or error occurs, roll back everything
        tg.RollBack()
        # Only alert if it's a real error, not a user cancellation
        if "Operation canceled" not in str(e):
            forms.alert("Error: {}".format(e))

# --- EXECUTION ---
if __name__ == "__main__":
    create_3_click_section()