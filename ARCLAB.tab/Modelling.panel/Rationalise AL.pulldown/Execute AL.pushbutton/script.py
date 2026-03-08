# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script
import pickle
import os

# ==========================================
# UI MESSAGES & CONFIGURATION
# ==========================================
UI_TEXT = {
    "err_no_anchor": "No axis found. Please first set up axis first",
    "err_missing_anchor": "Original axis gridl not found.",
    "prompt_select": "Select Dimensions to rationalize",
    "err_pinned": "A pinned wall was detected in your selection.\n\nPlease unpin the elements and try again.",
    "err_unexpected": "An unexpected error occurred: {}",
    "msg_success": "Successfully rationalised {} wall(s) to 5mm increments.",
    "msg_no_move": "No walls needed moving. Everything selected is already rationalized to 5mm.",
    "title_missing": "Missing axis grid",
    "title_cancelled": "Operation Cancelled",
    "title_success": "Execute Complete"
}

temp_path = os.path.join(os.getenv('TEMP'), 'revit_anchor_ids.txt')

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def round_to_5mm(val_ft):
    """Converts feet to mm, rounds to nearest 5, and converts back."""
    val_mm = val_ft * 304.8
    rounded_mm = round(val_mm / 5.0) * 5.0
    return rounded_mm / 304.8

def is_parallel(v1, v2, tolerance=0.01):
    """Checks if two vectors are parallel by comparing their dot product."""
    return abs(abs(v1.DotProduct(v2)) - 1.0) < tolerance

# ==========================================
# MAIN SCRIPT
# ==========================================
doc = revit.doc
uidoc = revit.uidoc
__doc__ = 'Instantly rationalise walls to nearest 5mm, with no domino effect.'

# 1. Load Anchors
if not os.path.exists(temp_path):
    forms.alert(UI_TEXT["err_no_anchor"], title=UI_TEXT["title_missing"], warn_icon=True)
    script.exit()

with open(temp_path, 'rb') as f:
    anchors = pickle.load(f)

anchor_x_el = doc.GetElement(anchors.get("X_DATUM"))
anchor_y_el = doc.GetElement(anchors.get("Y_DATUM"))

if not anchor_x_el or not anchor_y_el:
    forms.alert(UI_TEXT["err_missing_anchor"], title=UI_TEXT["title_missing"], warn_icon=True)
    script.exit()

# Extract Geometry Data
curve_x = anchor_x_el.Curve
dir_x = curve_x.Direction.Normalize()
pt_x = curve_x.GetEndPoint(0)
normal_x = XYZ(-dir_x.Y, dir_x.X, 0).Normalize()

curve_y = anchor_y_el.Curve
dir_y = curve_y.Direction.Normalize()
pt_y = curve_y.GetEndPoint(0)
normal_y = XYZ(-dir_y.Y, dir_y.X, 0).Normalize()

# 2. Select Dimensions to Fix
try:
    dim_refs = uidoc.Selection.PickObjects(
        revit.UI.Selection.ObjectType.Element, 
        UI_TEXT["prompt_select"]
    )
except Exception:
    script.exit()

# 3. Process the Walls with Fail-Safes
walls_moved = 0
pinned_found = False

tg = TransactionGroup(doc, "Rationalize Walls Group")
tg.Start()

t = Transaction(doc, "Rationalize Walls to XY Datums")
t.Start()

try:
    for d_ref in dim_refs:
        dim = doc.GetElement(d_ref)
        if not isinstance(dim, Dimension): 
            continue
        
        for ref in dim.References:
            el = doc.GetElement(ref.ElementId)
            
            if isinstance(el, Wall):
                # --- FAIL SAFE: Check for Pinned Elements ---
                if el.Pinned:
                    pinned_found = True
                    raise ValueError("Pinned Element Found")
                
                wall_curve = el.Location.Curve
                if not isinstance(wall_curve, Line):
                    continue 
                
                wall_dir = wall_curve.Direction.Normalize()
                
                if is_parallel(wall_dir, dir_x):
                    chosen_pt = pt_x
                    chosen_normal = normal_x
                elif is_parallel(wall_dir, dir_y):
                    chosen_pt = pt_y
                    chosen_normal = normal_y
                else:
                    continue 
                    
                wall_pt = wall_curve.GetEndPoint(0)
                vec_to_wall = wall_pt - chosen_pt
                current_dist_ft = vec_to_wall.DotProduct(chosen_normal)
                
                target_dist_ft = round_to_5mm(current_dist_ft)
                delta_ft = target_dist_ft - current_dist_ft
                
                move_vec = chosen_normal * delta_ft
                
                if move_vec.GetLength() > 0.0001: 
                    ElementTransformUtils.MoveElement(doc, el.Id, move_vec)
                    walls_moved += 1

    t.Commit()
    tg.Assimilate()

except ValueError as ve:
    if str(ve) == "Pinned Element Found":
        t.RollBack()
        tg.RollBack()
        forms.alert(UI_TEXT["err_pinned"], title=UI_TEXT["title_cancelled"], warn_icon=True)
        script.exit()
except Exception as e:
    t.RollBack()
    tg.RollBack()
    forms.alert(UI_TEXT["err_unexpected"].format(str(e)), warn_icon=True)
    script.exit()

# 4. Final Success Notification
if not pinned_found:
    if walls_moved > 0:
        forms.alert(UI_TEXT["msg_success"].format(walls_moved), title=UI_TEXT["title_success"], warn_icon=False)
    else:
        forms.alert(UI_TEXT["msg_no_move"], title=UI_TEXT["title_success"], warn_icon=False)