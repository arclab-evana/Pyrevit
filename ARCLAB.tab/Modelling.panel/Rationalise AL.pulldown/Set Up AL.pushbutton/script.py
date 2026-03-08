# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import * # Import Revit Database namespace for API access
from pyrevit import revit, script, forms  # Import pyRevit modules for Revit UI and script control
import pickle                        # Import pickle for serializing/saving data to disk
import os                            # Import os for file path and environment variable handling

# ==========================================
# UI MESSAGES & CONFIGURATION
# ==========================================
# Dictionary containing all user-facing strings for localization and easy editing
UI_TEXT = {
    "status_bar_1": "Pick the first Grid Line",
    "status_bar_2": "Pick the second Grid Line (perpendicular to the first)",
    "err_not_grid": "You must select a Grid. Please run again.",
    "err_duplicate_axis": "You selected two grids in the same direction. Please run again and pick perpendicular grids.",
    "msg_y_selected": "Y axis has been selected.",
    "msg_x_selected": "X axis has been selected.",
    "title_step_1": "Step 1 Complete",
    "title_step_2": "Step 2 Complete",
    "title_success": "Setup Complete",
    "msg_success": "Both X and Y axes are recognised.\nYou can now run the Rationalise tool."
}

# Define file path in the Windows TEMP folder to store selected Grid IDs
temp_path = os.path.join(os.getenv('TEMP'), 'revit_anchor_ids.txt')

# ==========================================
# MAIN SCRIPT
# ==========================================
uidoc = revit.uidoc  # Get the active UI document (user interface level)
doc = revit.doc      # Get the active database document (data level)

# Initialize dictionary to store the UniqueIds of the anchor Grids
anchors = {"X_DATUM": None, "Y_DATUM": None}

def determine_axis(grid_element):
    """
    Returns 'Y' if grid runs North-South (controls horizontal distribution).
    Returns 'X' if grid runs West-East (controls vertical distribution).
    """
    dir_vec = grid_element.Curve.Direction  # Extract the direction vector of the Grid line
    # Compare vector components: if Y component is dominant, it is a vertical-ish line
    if abs(dir_vec.Y) > abs(dir_vec.X):
        return "Y"
    return "X"

try:
    # --- STEP 1: First Grid ---
    # Prompt user to select an object in Revit with specific status bar text
    ref_1 = uidoc.Selection.PickObject(revit.UI.Selection.ObjectType.Element, UI_TEXT["status_bar_1"])
    el_1 = doc.GetElement(ref_1)  # Retrieve the actual Element from the selection reference
    
    # Validate that the selected element is actually a Revit Grid
    if not isinstance(el_1, Grid):
        forms.alert(UI_TEXT["err_not_grid"], warn_icon=True)  # Show error dialog
        script.exit()  # Terminate script execution
        
    axis_1 = determine_axis(el_1)  # Determine if Grid 1 is X or Y oriented
    
    # Assign UniqueId to the correct key in the anchors dictionary
    if axis_1 == "Y":
        anchors["Y_DATUM"] = el_1.UniqueId
        forms.alert(UI_TEXT["msg_y_selected"], title=UI_TEXT["title_step_1"], warn_icon=False)
    else:
        anchors["X_DATUM"] = el_1.UniqueId
        forms.alert(UI_TEXT["msg_x_selected"], title=UI_TEXT["title_step_1"], warn_icon=False)

    # --- STEP 2: Second Grid ---
    # Prompt user to select the second perpendicular Grid
    ref_2 = uidoc.Selection.PickObject(revit.UI.Selection.ObjectType.Element, UI_TEXT["status_bar_2"])
    el_2 = doc.GetElement(ref_2)  # Retrieve the second Element
    
    # Validate that the second selection is a Grid
    if not isinstance(el_2, Grid):
        forms.alert(UI_TEXT["err_not_grid"], warn_icon=True)
        script.exit()
        
    axis_2 = determine_axis(el_2)  # Determine orientation of Grid 2
    
    # Ensure the user didn't pick two parallel Grids
    if axis_1 == axis_2:
        forms.alert(UI_TEXT["err_duplicate_axis"], warn_icon=True)
        script.exit()
        
    # Assign Grid 2's UniqueId to the remaining dictionary key
    if axis_2 == "Y":
        anchors["Y_DATUM"] = el_2.UniqueId
        forms.alert(UI_TEXT["msg_y_selected"], title=UI_TEXT["title_step_2"], warn_icon=False)
    else:
        anchors["X_DATUM"] = el_2.UniqueId
        forms.alert(UI_TEXT["msg_x_selected"], title=UI_TEXT["title_step_2"], warn_icon=False)

    # --- STEP 3: Save to File ---
    # Open the temp file in Write Binary mode to save the data
    with open(temp_path, 'wb') as f:
        pickle.dump(anchors, f)  # Serialize the dictionary to the file for later use
        
    # Inform user of successful setup
    forms.alert(UI_TEXT["msg_success"], title=UI_TEXT["title_success"], warn_icon=False)

except Exception:
    # Handle user cancellation (hitting ESC) by exiting quietly without error messages
    pass