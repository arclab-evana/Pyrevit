# -*- coding: utf-8 -*-
__persistentengine__ = True

import os
from pyrevit import forms, revit, DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import UnitUtils, UnitTypeId, FilteredElementCollector

# --- WPF IMPORTS ---
from System.Windows.Controls import Canvas, TextBlock
from System.Windows.Shapes import Rectangle
from System.Windows.Media import SolidColorBrush, Colors, DoubleCollection
from System.Windows import TextAlignment

# ---------------------------------------------------------------------
# 1. THE WORKER (RCP Logic)
# ---------------------------------------------------------------------
class RCPRangeHandler(IExternalEventHandler):
    def __init__(self):
        self.cut_mm = 2300.0       
        self.top_offset_mm = 600.0  
        self.view_depth_mm = 0.0    

    def Execute(self, uiapp):
        try:
            doc = uiapp.ActiveUIDocument.Document
            view = uiapp.ActiveUIDocument.ActiveView
            
            # RCP View Range Logic
            # Convert MM inputs to Internal Feet
            cut_ft = UnitUtils.ConvertToInternalUnits(self.cut_mm, UnitTypeId.Millimeters)
            top_ft = UnitUtils.ConvertToInternalUnits(self.cut_mm + self.top_offset_mm, UnitTypeId.Millimeters)
            bot_ft = 0.0 
            depth_ft = top_ft + UnitUtils.ConvertToInternalUnits(self.view_depth_mm, UnitTypeId.Millimeters)

            with DB.Transaction(doc, "RCP Burger Update") as t:
                t.Start()
                vr = view.GetViewRange()
                assoc_level_id = view.GenLevel.Id
                
                planes = [DB.PlanViewPlane.TopClipPlane, 
                          DB.PlanViewPlane.CutPlane, 
                          DB.PlanViewPlane.BottomClipPlane, 
                          DB.PlanViewPlane.ViewDepthPlane]

                for p in planes:
                    vr.SetLevelId(p, assoc_level_id)

                vr.SetOffset(DB.PlanViewPlane.BottomClipPlane, bot_ft)
                vr.SetOffset(DB.PlanViewPlane.CutPlane, cut_ft)
                vr.SetOffset(DB.PlanViewPlane.TopClipPlane, top_ft)
                vr.SetOffset(DB.PlanViewPlane.ViewDepthPlane, depth_ft)
                
                view.SetViewRange(vr)
                t.Commit() 
            
            uiapp.ActiveUIDocument.RefreshActiveView()
        except Exception:
            pass

    def GetName(self):
        return "RCP Burger Handler"

# ---------------------------------------------------------------------
# 2. THE UI LOGIC
# ---------------------------------------------------------------------
class BurgerWindowRCP(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name) 
        
        self.handler = RCPRangeHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # --- CONFIGURATION ---
        self.MIN_THICKNESS = 10.0 
        self.MAX_RANGE_MM = 5000.0 
        self.MIN_RANGE_MM = 0.0 
        self.CANVAS_HEIGHT = 350.0 
        
        # --- STATE ---
        self.cut_mm = 2300.0       
        self.top_thick = 600.0     

        # Try to read actual Revit values to overwrite defaults
        self.init_from_current_view()

        self.check_active_view(None, None) 
        self.draw_level_references() 
        
        # Event Hookups
        self.MouseMove += self.check_active_view
        self.CutThumb.DragDelta += self.on_cut_drag
        self.TopThumb.DragDelta += self.on_top_drag
        self.BotThumb.DragDelta += self.on_bot_drag
        
        # Trigger Revit on release
        self.CutThumb.DragCompleted += self.trigger_revit
        self.TopThumb.DragCompleted += self.trigger_revit
        self.BotThumb.DragCompleted += self.trigger_revit
        
        self.ResetButton.Click += self.reset_defaults

        self.update_visuals()

    def init_from_current_view(self):
        """Reads the current active RCP's View Range and updates UI state."""
        try:
            view = revit.active_view
            if isinstance(view, DB.ViewPlan) and view.ViewType == DB.ViewType.CeilingPlan:
                vr = view.GetViewRange()
                
                # Helper to extract MM from a specific plane
                def get_plane_mm(plane_enum):
                    val_ft = vr.GetOffset(plane_enum)
                    return UnitUtils.ConvertFromInternalUnits(val_ft, UnitTypeId.Millimeters)

                # Get absolute MM values from Revit
                abs_cut = get_plane_mm(DB.PlanViewPlane.CutPlane)
                abs_top = get_plane_mm(DB.PlanViewPlane.TopClipPlane)
                
                # Convert to "Burger" logic
                self.cut_mm = abs_cut
                self.top_thick = abs_top - abs_cut
                
                # Sanity check to prevent negative thickness
                if self.top_thick < self.MIN_THICKNESS: 
                    self.top_thick = self.MIN_THICKNESS
        except Exception as e:
            # If reading fails, stick to defaults
            print("Could not read existing view range: {}".format(e))
            pass

    def check_active_view(self, sender, args):
        try:
            v = revit.active_view
            if v:
                self.ViewNameLabel.Text = v.Name.upper()
        except:
            pass

    def snap_to_5(self, val):
        return round(val / 5.0) * 5.0

    def mm_to_px(self, mm_val):
        total_span = self.MAX_RANGE_MM - self.MIN_RANGE_MM
        normalized = (mm_val - self.MIN_RANGE_MM) / total_span
        return self.CANVAS_HEIGHT * (1.0 - normalized)

    def px_to_mm(self, px_val):
        normalized = 1.0 - (px_val / self.CANVAS_HEIGHT)
        return self.MIN_RANGE_MM + (normalized * (self.MAX_RANGE_MM - self.MIN_RANGE_MM))
    
    def draw_level_references(self):
        doc = revit.doc
        view = revit.active_view
        if not view.GenLevel: return
        
        current_elev = view.GenLevel.Elevation
        levels = sorted(FilteredElementCollector(doc).OfClass(DB.Level).ToElements(), key=lambda x: x.Elevation)
        
        for lvl in levels:
            delta = lvl.Elevation - current_elev
            mm = UnitUtils.ConvertFromInternalUnits(delta, UnitTypeId.Millimeters)
            if self.MIN_RANGE_MM <= mm <= self.MAX_RANGE_MM:
                y_pos = self.mm_to_px(mm)
                line = Rectangle(Width=60.0, Height=1.0, Fill=SolidColorBrush(Colors.Gray))
                line.StrokeDashArray = DoubleCollection([4.0, 2.0])
                Canvas.SetLeft(line, 5.0); Canvas.SetTop(line, y_pos)
                
                label = TextBlock(Text=lvl.Name.upper(), FontSize=8.0, Foreground=SolidColorBrush(Colors.Gray), Width=60.0, TextAlignment=TextAlignment.Right)
                Canvas.SetLeft(label, 5.0); Canvas.SetTop(label, y_pos - 11.0)
                self.SliderCanvas.Children.Insert(0, line)
                self.SliderCanvas.Children.Insert(0, label)

    def on_cut_drag(self, sender, e):
        delta_mm = -1 * (e.VerticalChange / self.CANVAS_HEIGHT) * (self.MAX_RANGE_MM - self.MIN_RANGE_MM)
        self.cut_mm = self.snap_to_5(self.cut_mm + delta_mm)
        self.update_visuals()

    def on_top_drag(self, sender, e):
        # Top moves relative to Cut
        new_abs = self.px_to_mm(self.mm_to_px(self.cut_mm + self.top_thick) + e.VerticalChange)
        self.top_thick = max(self.MIN_THICKNESS, self.snap_to_5(new_abs - self.cut_mm))
        self.update_visuals()

    def on_bot_drag(self, sender, e):
        # Bottom Drag adjusts cut height in RCP mode
        new_abs = self.px_to_mm(self.mm_to_px(self.cut_mm) + e.VerticalChange)
        self.cut_mm = max(self.MIN_THICKNESS, self.snap_to_5(new_abs))
        self.update_visuals()

    # --- RESET LOGIC ---
    def get_upper_level_delta(self):
        doc = revit.doc
        view = revit.active_view
        if not view.GenLevel: return None
        
        current_elev = view.GenLevel.Elevation
        # Get levels sorted by elevation
        levels = FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
        levels = sorted(levels, key=lambda x: x.Elevation)
        
        # Find the next level up
        for lvl in levels:
            if lvl.Elevation > (current_elev + 0.01): # Tolerance
                diff = lvl.Elevation - current_elev
                return UnitUtils.ConvertFromInternalUnits(diff, UnitTypeId.Millimeters)
        return None

    def reset_defaults(self, sender, args):
        upper_level_mm = self.get_upper_level_delta()
        
        if upper_level_mm:
            # Set Cut Plane 200mm below the upper level
            self.cut_mm = upper_level_mm - 200.0
            # Set Top of Range exactly at the Upper Level
            # (If cut is at Upper-200, then Top thickness needs to be 200 to reach Upper)
            self.top_thick = 200.0
        else:
            # Fallback if no level above (e.g. Roof)
            self.cut_mm = 2300.0
            self.top_thick = 600.0

        self.update_visuals()
        self.trigger_revit(None, None)

    def update_visuals(self):
        self.TopLabel.Text = "+{}".format(int(self.top_thick))
        self.CutLabel.Text = "{}".format(int(self.cut_mm))
        self.BotLabel.Text = "LEVEL"

        self.move_thumb(self.TopThumb, self.cut_mm + self.top_thick, anchor="bottom")
        self.move_thumb(self.CutThumb, self.cut_mm, anchor="center")
        self.move_thumb(self.BotThumb, 0, anchor="top")

    def move_thumb(self, thumb, mm_val, anchor="center"):
        y_pos = self.mm_to_px(mm_val)
        if anchor == "center": Canvas.SetTop(thumb, y_pos - (thumb.Height / 2.0))
        elif anchor == "bottom": Canvas.SetTop(thumb, y_pos - thumb.Height)
        elif anchor == "top": Canvas.SetTop(thumb, y_pos)

    def trigger_revit(self, sender, e):
        self.handler.cut_mm = self.cut_mm
        self.handler.top_offset_mm = self.top_thick
        self.ext_event.Raise()

if __name__ == "__main__":
    v = revit.active_view
    if isinstance(v, DB.ViewPlan) and v.ViewType == DB.ViewType.CeilingPlan:
        cur_dir = os.path.dirname(__file__)
        # Ensure your file is named ui.xaml (not .xmal)
        xaml_file = os.path.join(cur_dir, "ui.xaml")
        
        if os.path.exists(xaml_file):
            window = BurgerWindowRCP(xaml_file)
            window.show()
        else:
            forms.alert("Could not find ui.xaml.\nPlease check the file extension is .xaml, not .xmal")
    else:
        forms.alert("Please open a Reflected Ceiling Plan first.")