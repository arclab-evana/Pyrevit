"Section Perpendicular"
"You should add this plugin onto Quick Access Bar!"
"Imrpoved and better"
from pyrevit import revit, DB, forms

doc = revit.doc
uidoc = revit.uidoc
__doc__ = "Perpendicular sections for QA/QC windows"

# --- SETTINGS --- 
SECTION_TYPE_NAME = "AL_Section" #Find Section type and applies it to section. 
SECTION_LENGTH_MM = 3000
FAR_CLIP_MM = 100

def mm_to_ft(mm):
    ""
    return DB.UnitUtils.ConvertToInternalUnits(mm, DB.UnitTypeId.Millimeters)

def get_upper_level(current_level):
    """Finds the level immediately above the current level."""
    all_levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
    # Sort levels by elevation
    sorted_levels = sorted(all_levels, key=lambda l: l.Elevation)
    
    for i, level in enumerate(sorted_levels):
        if level.Id == current_level.Id:
            if i + 1 < len(sorted_levels):
                return sorted_levels[i+1]
    return None

def create_ortho_section(origin, direction):
    active_view = doc.ActiveView
    curr_level = active_view.GenLevel
    upper_level = get_upper_level(curr_level)
    
    # Vertical height logic
    if upper_level:
        height = upper_level.Elevation - curr_level.Elevation
    else:
        height = mm_to_ft(3000)

    # 1. Define Bounding Box
    section_length = mm_to_ft(SECTION_LENGTH_MM)
    section_depth = mm_to_ft(FAR_CLIP_MM)
    
    bbox = DB.BoundingBoxXYZ()
    bbox.Min = DB.XYZ(-section_length/2, 0, 0) 
    bbox.Max = DB.XYZ(section_length/2, height, section_depth)

    # 2. Define Orientation
    t = DB.Transform.Identity
    t.Origin = origin
    t.BasisX = direction
    t.BasisY = DB.XYZ.BasisZ 
    t.BasisZ = direction.CrossProduct(DB.XYZ.BasisZ) 
    bbox.Transform = t
    
    # 3. Find specific Section Type "AL_Section"
    vt_collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    section_type = next((v for v in vt_collector if v.ViewFamily == DB.ViewFamily.Section 
                         and v.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == SECTION_TYPE_NAME), None)
    
    if not section_type:
        # Use forms.alert (requires 'import forms' at top)
        forms.alert("Could not find Section Type: {}. Please create it first.".format(SECTION_TYPE_NAME), exitscript=True)

    # 4. Create Section
    new_section = DB.ViewSection.CreateSection(doc, section_type.Id, bbox)

    # 5. Apply Overrides (FIXED API ATTRIBUTES)
    new_section.CropBoxActive = True   # Checks "Crop View"
    new_section.CropBoxVisible = False # Unchecks "Crop Region Visible"

    # Set Far Clip Offset explicitly via Parameter
    far_clip_param = new_section.get_Parameter(DB.BuiltInParameter.VIEWER_BOUND_OFFSET_FAR)
    if far_clip_param:
        far_clip_param.Set(section_depth)

    # Force "Hide at scales coarser than" to 1:5000
        # This ensures the section marker is visible in almost all plan views
        coarser_scale_param = new_section.get_Parameter(DB.BuiltInParameter.SECTION_COARSER_SCALE_PULLDOWN_METRIC)
        if coarser_scale_param:
            coarser_scale_param.Set(5000)

    return new_section

# --- EXECUTION ---

# Check 1: Ensure we are in a Plan View
active_view = doc.ActiveView
if not hasattr(active_view, "GenLevel") or active_view.GenLevel is None:
    forms.alert("This tool must be run in a Floor or Ceiling Plan associated with a Level.", exitscript=True)

try:
    # Check 2: User interaction
    click_pt = uidoc.Selection.PickPoint("Select intersection point")
    
    # Transaction Grouping
    with DB.Transaction(doc, "Create Perpendicular Sections") as t:
        t.Start()
        try:
            create_ortho_section(click_pt, DB.XYZ.BasisX) # Horizontal
            create_ortho_section(click_pt, DB.XYZ.BasisY) # Vertical
            t.Commit()
        except Exception as e:
            # If creating one section fails, rollback both
            t.RollBack()
            print("Transaction failed and was rolled back. Error: {}".format(e))

except Exception as e:
    # Handle user cancellation (Esc key) or other UI errors
    pass