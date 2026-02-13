"""
3-Click Section Tool (Educational Edition)
Features:
- "Breadcrumb" Anchor (Dynamic Size based on View Scale)
- Temp Connector Line
- Intelligent Ortho Snapping
- Dynamic Depth
"""
import math
# pyrevit imports allow access to the Revit API and UI tools
from pyrevit import revit, DB, forms

# 'doc' represents the active Revit database (the current project file)
doc = revit.doc
# 'uidoc' represents the UI of the active document (selection, clicks, view interactions)
uidoc = revit.uidoc

# --- SETTINGS (USER CONFIGURABLE) ---

# Snapping Tolerance: The angular window (in degrees) where the script forces a straight line.
# If the angle is within 15 degrees of the X or Y axis, it snaps to that axis.
ORTHO_TOLERANCE_DEGREES = 15 

# Visual Aid Size: The physical size of the "X" marker in millimeters as it would appear on paper.
# This ensures the marker is visible regardless of the view scale (1:50 vs 1:500).
BREADCRUMB_PAPER_MM = 4.0      

# Default Height: The vertical extent of the section if no level is found above the current one.
DEFAULT_HEIGHT_MM = 3000       
# Minimum Length: Prevents creating zero-length sections if the user double-clicks.
MIN_SECTION_LENGTH_MM = 50     
# Minimum Depth: Prevents the Far Clip Plane from being set too close to the section line.
MIN_DEPTH_MM = 50              
# Default Depth: The fallback depth used if the user clicks directly on the section line.
DEFAULT_DEPTH_MM = 500         

# --- HELPER FUNCTIONS ---

def mm_to_ft(mm):
    """
    Converts a value from Millimeters to Decimal Feet.
    Revit's internal database ALWAYS uses decimal feet, regardless of project unit settings.
    """
    # UnitUtils.ConvertToInternalUnits: The standard API method for unit conversion.
    # UnitTypeId.Millimeters: The strict identifier for millimeter units in newer Revit versions.
    return DB.UnitUtils.ConvertToInternalUnits(mm, DB.UnitTypeId.Millimeters)

def get_upper_level(current_level):
    """
    Scans the project to find the Level element immediately above the provided level.
    Used to automatically set the top constraint of the section box.
    """
    # FilteredElementCollector: Search engine for the Revit database.
    # OfClass(DB.Level): Restricts search to objects of type 'Level'.
    # ToElements(): Executes the search and returns a Python list of Level objects.
    all_levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
    
    # Sorts the list of levels based on their 'Elevation' property (height from zero).
    sorted_levels = sorted(all_levels, key=lambda l: l.Elevation)
    
    # Iterate through the sorted list to find the current level's index.
    for i, level in enumerate(sorted_levels):
        if level.Id == current_level.Id:
            # Check if there is a next level in the list (index + 1).
            if i + 1 < len(sorted_levels):
                # Return the level object found at the next index.
                return sorted_levels[i+1]
    return None

def get_default_section_type():
    """
    Retrieves a ViewFamilyType to be used for the new Section.
    Prioritizes a type named 'AL_Section', otherwise grabs the first available Section type.
    """
    # Collector for all ViewFamilyTypes (Floor Plans, Sections, Elevations, etc.)
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    
    # Target Name: The specific View Type name we prefer to use.
    target_name = "AL_Section"
    
    # Iterate to find the specific match.
    for v in vt_collector:
        # Check if family is 'Section' AND name matches target.
        if v.ViewFamily == DB.ViewFamily.Section and v.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == target_name:
            return v
            
    # Fallback: Reset the collector (since generators are consumed after iteration).
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    # Return the first type where the ViewFamily is 'Section'.
    return next((v for v in vt_collector if v.ViewFamily == DB.ViewFamily.Section), None)

def snap_ortho_with_tolerance(p1, p2, tolerance_degrees):
    """
    Adjusts point p2 to align horizontally or vertically with p1 if the angle is close to 90 degrees.
    Uses vector math to determine if the line is 'mostly horizontal' or 'mostly vertical'.
    """
    # Vector Subtraction: Creates a directional vector from Start(p1) to End(p2).
    vec = p2 - p1
    # GetLength: Calculates the magnitude (distance) of the vector.
    length = vec.GetLength()
    
    # Safety Check: If points are effectively identical, return p2 to avoid division by zero.
    if length < 0.001: 
        return p2

    # Threshold Calculation: Converts degrees to a cosine value (0.0 to 1.0).
    # 1.0 = 0 degrees (perfect alignment), 0.0 = 90 degrees (perpendicular).
    threshold = math.cos(math.radians(tolerance_degrees))
    
    # Normalization: Calculates the ratio of the vector in X and Y directions.
    # norm_x: How "Horizontal" is the line? (1.0 = Horizontal).
    norm_x = abs(vec.X / length)
    # norm_y: How "Vertical" is the line? (1.0 = Vertical).
    norm_y = abs(vec.Y / length)
    
    # If the X component is greater than the threshold, snap Y to match p1 (Horizontal Line).
    if norm_x > threshold:
        return DB.XYZ(p2.X, p1.Y, p2.Z) 
    # If the Y component is greater than the threshold, snap X to match p1 (Vertical Line).
    elif norm_y > threshold:
        return DB.XYZ(p1.X, p2.Y, p2.Z) 
    
    # If neither, the user drew a diagonal line intentionally. Return original point.
    return p2

def create_breadcrumb_visual(doc, center_pt, view):
    """
    Creates a temporary Detail Line "X" (Crosshair) at a specific point.
    Used to visually anchor the user's eye between clicks.
    """
    ids = []
    
    # View.Scale: Returns the integer scale of the view (e.g., 100 for 1:100).
    view_scale = view.Scale
    
    # Calculation: Multiplies paper mm by scale to get model mm size.
    size_model_mm = BREADCRUMB_PAPER_MM * view_scale
    
    # Convert the calculated model size to feet (Revit's internal unit).
    size_ft = mm_to_ft(size_model_mm) / 2.0
    
    # Define 4 corner points relative to the center point to create an X shape.
    p1 = center_pt + DB.XYZ(size_ft, size_ft, 0)   # Top Right
    p2 = center_pt + DB.XYZ(-size_ft, -size_ft, 0) # Bottom Left
    p3 = center_pt + DB.XYZ(-size_ft, size_ft, 0)  # Top Left
    p4 = center_pt + DB.XYZ(size_ft, -size_ft, 0)  # Bottom Right
    
    try:
        # CreateBound: Creates a Line geometry object (abstract math, not a Revit element yet).
        l1 = DB.Line.CreateBound(p1, p2)
        l2 = DB.Line.CreateBound(p3, p4)
        
        # NewDetailCurve: Creates the actual Detail Line element in the specific view.
        c1 = doc.Create.NewDetailCurve(view, l1)
        c2 = doc.Create.NewDetailCurve(view, l2)
        
        # Collect the Element IDs so we can delete them later.
        ids.append(c1.Id)
        ids.append(c2.Id)
    except Exception:
        pass 
        
    return ids

# --- CORE LOGIC ---

def create_3_click_section():
    # ActiveView: The view currently open on the user's screen.
    active_view = doc.ActiveView
    
    # Validation: Checks if the ViewType is Plan or Ceiling (cannot make sections in 3D views).
    if active_view.ViewType not in [DB.ViewType.FloorPlan, DB.ViewType.CeilingPlan]:
        forms.alert("Please run this tool from a Floor or Ceiling Plan.", exitscript=True)
    
    # GenLevel: The 'associated level' property of the current view.
    curr_level = active_view.GenLevel
    if not curr_level:
        forms.alert("Current view does not have an associated level.", exitscript=True)

    # TransactionGroup: A wrapper that groups multiple transactions into a single "Undo" item.
    tg = DB.TransactionGroup(doc, "Create 3-Click Section")
    tg.Start()

    # List initialization to store IDs of temporary visual aids for cleanup.
    temp_ids_to_delete = []

    try:
        # --- CLICK 1: START POINT ---
        # PickPoint: Pauses script