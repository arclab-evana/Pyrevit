"""
3-Click Section Tool (Succinct Edition)
Features: Breadcrumb Anchor, Temp Connector, Ortho Snapping, Dynamic Depth
"""
import math
from pyrevit import revit, DB, forms # Import pyRevit libraries for API access

doc = revit.doc # Active Revit database
uidoc = revit.uidoc # Active UI document for user interaction

# --- SETTINGS ---

ORTHO_TOLERANCE_DEGREES = 15 # Angular window in degrees for axis snapping
BREADCRUMB_PAPER_MM = 4.0 # Physical size of visual anchor on paper in mm
DEFAULT_HEIGHT_MM = 3000 # Vertical extent if no level found above
MIN_SECTION_LENGTH_MM = 50 # Minimum length to prevent zero-length error
MIN_DEPTH_MM = 50 # Minimum distance for far clip plane
DEFAULT_DEPTH_MM = 500 # Fallback depth if click is on section line

# --- HELPER FUNCTIONS ---

def mm_to_ft(mm): # Convert millimeters to internal decimal feet
    return DB.UnitUtils.ConvertToInternalUnits(mm, DB.UnitTypeId.Millimeters) # Standard API conversion method

def get_upper_level(current_level): # Find level immediately above current level
    all_levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements() # Collect all levels in project
    sorted_levels = sorted(all_levels, key=lambda l: l.Elevation) # Sort levels by elevation height
    
    for i, level in enumerate(sorted_levels): # Iterate through sorted levels
        if level.Id == current_level.Id: # Match current level ID
            if i + 1 < len(sorted_levels): # Check if next level exists
                return sorted_levels[i+1] # Return next level up
    return None # Return nothing if no upper level found

def get_default_section_type(): # Retrieve valid ViewFamilyType for Section
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType) # Collect all view types
    target_name = "AL_Section" # Preferred view type name
    
    for v in vt_collector: # Iterate to find specific match
        if v.ViewFamily == DB.ViewFamily.Section and v.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == target_name: # Check family and name match
            return v # Return specific AL_Section type
            
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType) # Reset collector for fallback search
    return next((v for v in vt_collector if v.ViewFamily == DB.ViewFamily.Section), None) # Return first available Section type

def snap_ortho_with_tolerance(p1, p2, tolerance_degrees): # Align p2 orthogonally if within angle tolerance
    vec = p2 - p1 # Vector from start to end point
    length = vec.GetLength() # Magnitude of vector
    
    if length < 0.001: # Return original point if length is negligible
        return p2

    threshold = math.cos(math.radians(tolerance_degrees)) # Convert degrees to cosine threshold
    
    norm_x = abs(vec.X / length) # Normalized X component
    norm_y = abs(vec.Y / length) # Normalized Y component
    
    if norm_x > threshold: # Check if vector is horizontally dominant
        return DB.XYZ(p2.X, p1.Y, p2.Z) # Snap Y to match start point
    elif norm_y > threshold: # Check if vector is vertically dominant
        return DB.XYZ(p1.X, p2.Y, p2.Z) # Snap X to match start point
        
    return p2 # Return diagonal point if outside tolerance

def create_breadcrumb_visual(doc, center_pt, view): # Create temporary X detail line at point
    ids = [] # List to store created element IDs
    view_scale = view.Scale # Integer scale of current view
    size_model_mm = BREADCRUMB_PAPER_MM * view_scale # Calculate model size based on scale
    size_ft = mm_to_ft(size_model_mm) / 2.0 # Convert half-size to feet for offsets
    
    p1 = center_pt + DB.XYZ(size_ft, size_ft, 0) # Top Right corner
    p2 = center_pt + DB.XYZ(-size_ft, -size_ft, 0) # Bottom Left corner
    p3 = center_pt + DB.XYZ(-size_ft, size_ft, 0) # Top Left corner
    p4 = center_pt + DB.XYZ(size_ft, -size_ft, 0) # Bottom Right corner
    
    try: # Attempt to create geometry
        l1 = DB.Line.CreateBound(p1, p2) # Create first crossing line geometry
        l2 = DB.Line.CreateBound(p3, p4) # Create second crossing line geometry
        
        c1 = doc.Create.NewDetailCurve(view, l1) # Draw first detail line
        c2 = doc.Create.NewDetailCurve(view, l2) # Draw second detail line
        
        ids.append(c1.Id) # Store ID for cleanup
        ids.append(c2.Id) # Store ID for cleanup
    except Exception: # Ignore geometry creation errors
        pass 
        
    return ids # Return list of created IDs

# --- CORE LOGIC ---

def create_3_click_section(): # Main execution function
    active_view = doc.ActiveView # Get currently open view
    
    if active_view.ViewType not in [DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan]: # Validate view type is Plan
        forms.alert("Please run this tool from a Floor or Ceiling Plan.", exitscript=True) # Alert user and exit
    
    curr_level = active_view.GenLevel # Get associated level of view
    if not curr_level: # Validate level existence
        forms.alert("Current view does not have an associated level.", exitscript=True) # Alert user and exit

    tg = DB.TransactionGroup(doc, "Create 3-Click Section") # Group transactions for single undo
    tg.Start() # Start transaction group

    temp_ids_to_delete = [] # Initialize list for temporary elements

    try:
        # --- CLICK 1 ---
        pt_start = uidoc.Selection.PickPoint("Click 1: Start of Section Line") # Pause for first user click
        p1 = DB.XYZ(pt_start.X, pt_start.Y, 0) # Create start point with Z flattened to 0

        # --- VISUAL FEEDBACK 1 ---
        t_crumb = DB.Transaction(doc, "Draw Breadcrumb") # Start sub-transaction for anchor
        t_crumb.Start() # Begin transaction
        
        crumb_ids = create_breadcrumb_visual(doc, p1, active_view) # Create visual X anchor
        temp_ids_to_delete.extend(crumb_ids) # Add anchor IDs to delete list
        
        doc.Regenerate() # Force graphics update to show anchor
        t_crumb.Commit() # Commit anchor creation
        
        # --- CLICK 2 ---
        pt_end_raw = uidoc.Selection.PickPoint("Click 2: End of Section Line") # Pause for second user click
        
        p2_raw = DB.XYZ(pt_end_raw.X, pt_end_raw.Y, 0) # Flatten Z of raw end point
        p2 = snap_ortho_with_tolerance(p1, p2_raw, ORTHO_TOLERANCE_DEGREES) # Calculate snapped end point

        vec_line = p2 - p1 # Calculate vector between points
        if vec_line.GetLength() < mm_to_ft(MIN_SECTION_LENGTH_MM): # Check minimum length constraint
            tg.RollBack() # Cancel all changes if too short
            forms.alert("Section line is too short (<{}mm).".format(MIN_SECTION_LENGTH_MM), exitscript=True) # Alert user

        # --- VISUAL FEEDBACK 2 ---
        t_temp = DB.Transaction(doc, "Draw Temp Line") # Start sub-transaction for connector
        t_temp.Start() # Begin transaction
        try:
            line_geom = DB.Line.CreateBound(p1, p2) # Create line geometry between points
            temp_crv = doc.Create.NewDetailCurve(active_view, line_geom) # Draw detail line
            temp_ids_to_delete.append(temp_crv.Id) # Add line ID to delete list
            doc.Regenerate() # Force graphics update to show line
        except Exception: # Handle drawing errors
            pass 
        t_temp.Commit() # Commit temp line creation

        # --- CLICK 3 ---
        pt_depth = uidoc.Selection.PickPoint("Click 3: Define Section Depth/Direction") # Pause for third depth click
        p3 = DB.XYZ(pt_depth.X, pt_depth.Y, 0) # Flatten Z of depth point

        # --- CALCULATIONS ---
        midpoint = p1 + (vec_line / 2.0) # Calculate center point of section line
        
        ortho_dir = vec_line.CrossProduct(DB.XYZ.BasisZ).Normalize() # Calculate perpendicular direction vector
        
        vec_to_depth = p3 - p1 # Vector from start to depth point
        
        if ortho_dir.DotProduct(vec_to_depth) < 0: # Check if click is behind line
            view_dir = -ortho_dir # Flip direction if behind
        else: # Click is in front
            view_dir = ortho_dir # Keep direction

        depth_dist_ft = abs(view_dir.DotProduct(vec_to_depth)) # Calculate perpendicular depth distance
        
        min_depth_ft = mm_to_ft(MIN_DEPTH_MM) # Convert minimum depth to feet
        if depth_dist_ft < min_depth_ft: # Check if depth is too shallow
            depth_dist_ft = mm_to_ft(DEFAULT_DEPTH_MM) # Use default depth if too shallow

        upper_level = get_upper_level(curr_level) # Find level above
        if upper_level: # Upper level exists
            height_ft = upper_level.Elevation - curr_level.Elevation # Calculate height from levels
        else: # No upper level
            height_ft = mm_to_ft(DEFAULT_HEIGHT_MM) # Use default height

        section_length_ft = vec_line.GetLength() # Get final length in feet
        bbox = DB.BoundingBoxXYZ() # Initialize bounding box
        bbox.Min = DB.XYZ(-section_length_ft / 2.0, 0, 0) # Set left extent
        bbox.Max = DB.XYZ(section_length_ft / 2.0, height_ft, depth_dist_ft) # Set right, top, and depth extents

        t = DB.Transform.Identity # Initialize identity transform
        t.Origin = midpoint # Set origin to section midpoint
        t.BasisZ = view_dir # Set view direction
        t.BasisY = DB.XYZ.BasisZ # Set up direction to global Z
        t.BasisX = t.BasisY.CrossProduct(t.BasisZ) # Calculate right direction
        bbox.Transform = t # Apply transform to bounding box

        # --- CREATION ---
        t_final = DB.Transaction(doc, "Create View") # Start final creation transaction
        t_final.Start() # Begin transaction
        
        if temp_ids_to_delete: # Check for temporary items
            doc.Delete(revit.framework.List[DB.ElementId](temp_ids_to_delete)) # Delete all temp visual aids

        section_type = get_default_section_type() # Get section view type
        if not section_type: # Validate type existence
            forms.alert("No Section View Type found.", exitscript=True) # Alert user if missing

        new_section = DB.ViewSection.CreateSection(doc, section_type.Id, bbox) # Create section view in database
        
        new_section.CropBoxActive = True # Enable crop box
        new_section.CropBoxVisible = False # Hide crop box visibility
        
        new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_FAR_CLIPPING).Set(1) # Set far clip to 'Clip without line'
        new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR).Set(depth_dist_ft) # Set far clip offset value

        t_final.Commit() # Commit final view creation
        
        tg.Assimilate() # Merge all transactions into one undo group

    except Exception as e: # Catch any runtime errors
        tg.RollBack() # Undo all changes on error
        if "Operation canceled" not in str(e): # Ignore user cancellation errors
            forms.alert("Error: {}".format(e)) # Show error alert

if __name__ == "__main__": # Check if running as main script
    create_3_click_section() # Execute main function