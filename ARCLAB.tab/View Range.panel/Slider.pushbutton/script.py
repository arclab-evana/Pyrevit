# -*- coding: utf-8 -*-
__persistentengine__ = True

from pyrevit import forms, revit, DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import UnitUtils, UnitTypeId, FilteredElementCollector

# --- WPF IMPORTS ---
from System.Windows.Controls import Canvas, TextBlock
from System.Windows.Shapes import Rectangle
from System.Windows.Media import SolidColorBrush, Colors, DoubleCollection
from System.Windows import TextAlignment

# ---------------------------------------------------------------------
# 1. THE WORKER (Revit updater)
# ---------------------------------------------------------------------
class ViewRangeHandler(IExternalEventHandler):
    def __init__(self):
        self.cut_mm = 1200.0
        self.top_offset_mm = 600.0
        self.bot_offset_mm = 600.0

    def Execute(self, uiapp):
        try:
            doc = uiapp.ActiveUIDocument.Document
            view = uiapp.ActiveUIDocument.ActiveView
            
            # Calculations
            cut_abs = self.cut_mm
            top_abs = self.cut_mm + self.top_offset_mm
            bot_abs = self.cut_mm - self.bot_offset_mm
            
            cut_ft = UnitUtils.ConvertToInternalUnits(cut_abs, UnitTypeId.Millimeters)
            top_ft = UnitUtils.ConvertToInternalUnits(top_abs, UnitTypeId.Millimeters)
            bot_ft = UnitUtils.ConvertToInternalUnits(bot_abs, UnitTypeId.Millimeters)
            depth_ft = bot_ft - UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters)

            with DB.Transaction(doc, "Burger Range Update") as t:
                t.Start()
                
                vr = view.GetViewRange()
                assoc_level_id = view.GenLevel.Id
                
                planes = [DB.PlanViewPlane.TopClipPlane, 
                          DB.PlanViewPlane.CutPlane, 
                          DB.PlanViewPlane.BottomClipPlane, 
                          DB.PlanViewPlane.ViewDepthPlane]

                for p in planes:
                    vr.SetLevelId(p, assoc_level_id)

                vr.SetOffset(DB.PlanViewPlane.TopClipPlane, top_ft)
                vr.SetOffset(DB.PlanViewPlane.CutPlane, cut_ft)
                vr.SetOffset(DB.PlanViewPlane.BottomClipPlane, bot_ft)
                vr.SetOffset(DB.PlanViewPlane.ViewDepthPlane, depth_ft)
                
                view.SetViewRange(vr)
                t.Commit() 
            
            uiapp.ActiveUIDocument.RefreshActiveView()
            
        except Exception:
            pass

    def GetName(self):
        return "Burger Handler"

# ---------------------------------------------------------------------
# 2. THE UI LOGIC
# ---------------------------------------------------------------------
class BurgerWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.handler = ViewRangeHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # --- CONFIGURATION ---
        self.MIN_THICKNESS = 10.0 
        self.MAX_RANGE_MM = 4000.0 
        self.MIN_RANGE_MM = -1000.0 
        self.CANVAS_HEIGHT = 350.0 
        
        # --- STATE ---
        self.cut_mm = 1200.0       
        self.top_thick = 600.0     
        self.bot_thick = 600.0     

        # --- SETUP ---
        self.check_active_view(None, None) 
        self.draw_level_references() 
        
        self.MouseMove += self.check_active_view

        self.CutThumb.DragDelta += self.on_cut_drag
        self.TopThumb.DragDelta += self.on_top_drag
        self.BotThumb.DragDelta += self.on_bot_drag
        
        self.CutThumb.DragCompleted += self.trigger_revit
        self.TopThumb.DragCompleted += self.trigger_revit
        self.BotThumb.DragCompleted += self.trigger_revit
        
        # New Reset Button Event
        self.ResetButton.Click += self.reset_defaults

        self.update_visuals()

    def check_active_view(self, sender, args):
        try:
            v = revit.active_view
            if v:
                self.ViewNameLabel.Text = v.Name.upper()
        except:
            pass

    # --- MATH HELPERS ---
    def snap_to_5(self, val):
        """Rounds value to nearest 5"""
        return round(val / 5.0) * 5.0

    def mm_to_px(self, mm_val):
        total_span = self.MAX_RANGE_MM - self.MIN_RANGE_MM
        if total_span == 0: return 0
        normalized = (mm_val - self.MIN_RANGE_MM) / total_span
        pixel_y = self.CANVAS_HEIGHT * (1.0 - normalized)
        return pixel_y

    def px_to_mm(self, px_val):
        normalized = 1.0 - (px_val / self.CANVAS_HEIGHT)
        total_span = self.MAX_RANGE_MM - self.MIN_RANGE_MM
        mm_val = self.MIN_RANGE_MM + (normalized * total_span)
        return mm_val
    
    def draw_level_references(self):
        doc = revit.doc
        view = revit.active_view
        
        if not isinstance(view, DB.ViewPlan) or not view.GenLevel:
            return

        current_level = view.GenLevel
        current_elev = current_level.Elevation
        
        levels = FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
        levels = sorted(levels, key=lambda x: x.Elevation)
        
        ref_levels = []
        ref_levels.append(("LEVEL 0", 0.0))
        
        for i, lvl in enumerate(levels):
            if lvl.Id == current_level.Id:
                if i > 0:
                    below = levels[i-1]
                    delta = below.Elevation - current_elev
                    mm = UnitUtils.ConvertFromInternalUnits(delta, UnitTypeId.Millimeters)
                    ref_levels.append((below.Name.upper(), mm))
                if i < len(levels) - 1:
                    above = levels[i+1]
                    delta = above.Elevation - current_elev
                    mm = UnitUtils.ConvertFromInternalUnits(delta, UnitTypeId.Millimeters)
                    ref_levels.append((above.Name.upper(), mm))
                break
        
        for name, mm in ref_levels:
            if self.MIN_RANGE_MM <= mm <= self.MAX_RANGE_MM:
                y_pos = self.mm_to_px(mm)
                
                line = Rectangle()
                line.Width = 60.0 
                line.Height = 1.0
                line.Fill = SolidColorBrush(Colors.Gray)
                line.StrokeDashArray = DoubleCollection([4.0, 2.0])
                
                Canvas.SetLeft(line, 5.0) 
                Canvas.SetTop(line, y_pos)
                
                label = TextBlock()
                label.Text = name
                label.FontSize = 8.0 
                label.Foreground = SolidColorBrush(Colors.Gray)
                label.TextAlignment = TextAlignment.Right
                label.Width = 60.0 
                
                Canvas.SetLeft(label, 5.0) 
                Canvas.SetTop(label, y_pos - 11.0)
                
                self.SliderCanvas.Children.Insert(0, line)
                self.SliderCanvas.Children.Insert(0, label)

    # --- DRAG HANDLERS (With Snapping) ---
    def on_cut_drag(self, sender, e):
        delta_mm = -1 * (e.VerticalChange / self.CANVAS_HEIGHT) * (self.MAX_RANGE_MM - self.MIN_RANGE_MM)
        # Apply Snap
        self.cut_mm = self.snap_to_5(self.cut_mm + delta_mm)
        self.update_visuals()

    def on_top_drag(self, sender, e):
        tip_px = self.mm_to_px(self.cut_mm + self.top_thick)
        new_tip_px = tip_px + e.VerticalChange
        new_abs = self.px_to_mm(new_tip_px)
        
        # Calculate raw thickness then snap
        raw_thick = new_abs - self.cut_mm
        new_thick = self.snap_to_5(raw_thick)

        if new_thick < self.MIN_THICKNESS: new_thick = self.MIN_THICKNESS
        self.top_thick = new_thick
        self.update_visuals()

    def on_bot_drag(self, sender, e):
        tip_px = self.mm_to_px(self.cut_mm - self.bot_thick)
        new_tip_px = tip_px + e.VerticalChange
        new_abs = self.px_to_mm(new_tip_px)
        
        raw_thick = self.cut_mm - new_abs
        new_thick = self.snap_to_5(raw_thick)
        
        if new_thick < self.MIN_THICKNESS: new_thick = self.MIN_THICKNESS
        self.bot_thick = new_thick
        self.update_visuals()

    # --- RESET HANDLER ---
    def reset_defaults(self, sender, args):
        self.cut_mm = 1500.0
        self.top_thick = 100.0
        self.bot_thick = 100.0
        
        self.update_visuals()
        self.trigger_revit(None, None)

    def update_visuals(self):
        top_abs = self.cut_mm + self.top_thick
        bot_abs = self.cut_mm - self.bot_thick
        
        self.TopLabel.Text = "+{}".format(int(self.top_thick))
        self.CutLabel.Text = "{}".format(int(self.cut_mm))
        self.BotLabel.Text = "-{}".format(int(self.bot_thick))

        self.move_thumb(self.TopThumb, top_abs, anchor="bottom")
        self.move_thumb(self.CutThumb, self.cut_mm, anchor="center")
        self.move_thumb(self.BotThumb, bot_abs, anchor="top")

    def move_thumb(self, thumb, mm_val, anchor="center"):
        y_pos = self.mm_to_px(mm_val)
        
        if anchor == "center":
            thumb.SetValue(Canvas.TopProperty, y_pos - (thumb.Height / 2.0))
        elif anchor == "bottom":
            thumb.SetValue(Canvas.TopProperty, y_pos - thumb.Height)
        elif anchor == "top":
            thumb.SetValue(Canvas.TopProperty, y_pos)

    def trigger_revit(self, sender, e):
        self.handler.cut_mm = self.cut_mm
        self.handler.top_offset_mm = self.top_thick
        self.handler.bot_offset_mm = self.bot_thick
        self.ext_event.Raise()

if __name__ == "__main__":
    if isinstance(revit.active_view, DB.ViewPlan):
        window = BurgerWindow("ui.xaml")
        window.show()
    else:
        forms.alert("Open a Floor Plan first.")