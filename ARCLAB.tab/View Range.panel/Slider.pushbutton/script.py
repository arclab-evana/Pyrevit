# -*- coding: utf-8 -*-
__persistentengine__ = True

from pyrevit import forms, revit, DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import UnitUtils, UnitTypeId
import math

# ---------------------------------------------------------------------
# 1. THE WORKER (Revit updater)
# ---------------------------------------------------------------------
class ViewRangeHandler(IExternalEventHandler):
    def __init__(self):
        self.cut_mm = 1200.0
        self.top_mm = 2300.0
        self.bot_mm = 0.0

    def Execute(self, uiapp):
        try:
            doc = uiapp.ActiveUIDocument.Document
            view = uiapp.ActiveUIDocument.ActiveView
            
            # --- CONVERT MM TO FEET ---
            cut_ft = UnitUtils.ConvertToInternalUnits(self.cut_mm, UnitTypeId.Millimeters)
            top_ft = UnitUtils.ConvertToInternalUnits(self.top_mm, UnitTypeId.Millimeters)
            bot_ft = UnitUtils.ConvertToInternalUnits(self.bot_mm, UnitTypeId.Millimeters)
            
            # Depth is linked to bottom for simplicity in this UI
            depth_ft = bot_ft - UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters)

            with DB.Transaction(doc, "Burger Range Update") as t:
                t.Start()
                
                vr = view.GetViewRange()
                assoc_level_id = view.GenLevel.Id
                
                # Reset all to Associated Level
                planes = [DB.PlanViewPlane.TopClipPlane, 
                          DB.PlanViewPlane.CutPlane, 
                          DB.PlanViewPlane.BottomClipPlane, 
                          DB.PlanViewPlane.ViewDepthPlane]

                for p in planes:
                    vr.SetLevelId(p, assoc_level_id)

                # Set Offsets
                vr.SetOffset(DB.PlanViewPlane.TopClipPlane, top_ft)
                vr.SetOffset(DB.PlanViewPlane.CutPlane, cut_ft)
                vr.SetOffset(DB.PlanViewPlane.BottomClipPlane, bot_ft)
                vr.SetOffset(DB.PlanViewPlane.ViewDepthPlane, depth_ft)
                
                view.SetViewRange(vr)
                t.Commit() 
            
            uiapp.ActiveUIDocument.RefreshActiveView()
            
        except Exception as e:
            # Note: We silence errors here to prevent popup spam while dragging
            # if you prefer logging, print(e)
            pass

    def GetName(self):
        return "Burger Handler"

# ---------------------------------------------------------------------
# 2. THE UI LOGIC (The Burger Physics)
# ---------------------------------------------------------------------
class BurgerWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.handler = ViewRangeHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # --- CONFIGURATION ---
        self.MIN_THICKNESS = 10.0 # mm
        self.MAX_RANGE_MM = 4000.0 # The visual top of the slider
        self.MIN_RANGE_MM = -1000.0 # The visual bottom of the slider
        self.CANVAS_HEIGHT = 350.0 # Matches XAML Canvas Height roughly
        
        # Initial Values
        self.current_cut = 1200.0
        self.current_top = 2300.0
        self.current_bot = 0.0
        
        # Wire up Drag Events
        self.TopThumb.DragDelta += self.on_top_drag
        self.CutThumb.DragDelta += self.on_cut_drag
        self.BotThumb.DragDelta += self.on_bot_drag
        
        # Wire up Release Events (To trigger Revit)
        self.TopThumb.DragCompleted += self.trigger_revit
        self.CutThumb.DragCompleted += self.trigger_revit
        self.BotThumb.DragCompleted += self.trigger_revit

        # Draw Initial State
        self.update_visuals()

    # --- MATH HELPERS ---
    def mm_to_px(self, mm_val):
        # Maps MM value to Pixel Y position (Inverted because Canvas 0 is Top)
        total_span = self.MAX_RANGE_MM - self.MIN_RANGE_MM
        normalized = (mm_val - self.MIN_RANGE_MM) / total_span
        # Invert (1 - norm) because Y=0 is top
        pixel_y = self.CANVAS_HEIGHT * (1.0 - normalized)
        return pixel_y

    def px_to_mm(self, px_val):
        # Maps Pixel Y back to MM
        normalized = 1.0 - (px_val / self.CANVAS_HEIGHT)
        total_span = self.MAX_RANGE_MM - self.MIN_RANGE_MM
        mm_val = self.MIN_RANGE_MM + (normalized * total_span)
        return mm_val

    # --- DRAG HANDLERS ---
    
    def on_cut_drag(self, sender, e):
        # 1. GROUP DRAG: Move Cut, Top, and Bot by the same delta
        delta_mm = -1 * (e.VerticalChange / self.CANVAS_HEIGHT) * (self.MAX_RANGE_MM - self.MIN_RANGE_MM)
        
        self.current_cut += delta_mm
        self.current_top += delta_mm
        self.current_bot += delta_mm
        
        self.update_visuals()

    def on_top_drag(self, sender, e):
        # 1. Calculate new potential Top
        current_px = self.mm_to_px(self.current_top)
        new_px = current_px + e.VerticalChange
        new_mm = self.px_to_mm(new_px)
        
        # 2. Limit Check: Cannot go lower than Cut + 10mm
        limit = self.current_cut + self.MIN_THICKNESS
        if new_mm < limit:
            new_mm = limit
            
        self.current_top = new_mm
        self.update_visuals()

    def on_bot_drag(self, sender, e):
        # 1. Calculate new potential Bot
        current_px = self.mm_to_px(self.current_bot)
        new_px = current_px + e.VerticalChange
        new_mm = self.px_to_mm(new_px)
        
        # 2. Limit Check: Cannot go higher than Cut - 10mm
        limit = self.current_cut - self.MIN_THICKNESS
        if new_mm > limit:
            new_mm = limit
            
        self.current_bot = new_mm
        self.update_visuals()

    # --- VISUAL UPDATE ---
    def update_visuals(self):
        # Update Text Labels
        self.TopLabel.Text = "Top: {}".format(int(self.current_top))
        self.CutLabel.Text = "Cut: {}".format(int(self.current_cut))
        self.BotLabel.Text = "Bot: {}".format(int(self.current_bot))

        # Update Thumb Positions on Canvas
        # Note: We center the thumb vertically on the point
        self.move_thumb(self.TopThumb, self.current_top)
        self.move_thumb(self.CutThumb, self.current_cut)
        self.move_thumb(self.BotThumb, self.current_bot)

    def move_thumb(self, thumb, mm_val):
        y_pos = self.mm_to_px(mm_val)
        # Center the thumb (assuming thumb height ~20-30px)
        # We use Canvas.SetTop
        thumb.SetValue(forms.Canvas.TopProperty, y_pos - (thumb.Height / 2.0))

    # --- REVIT COMMUNICATION ---
    def trigger_revit(self, sender, e):
        self.handler.top_mm = self.current_top
        self.handler.cut_mm = self.current_cut
        self.handler.bot_mm = self.current_bot
        self.ext_event.Raise()

# ---------------------------------------------------------------------
# 3. STARTUP
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if isinstance(revit.active_view, DB.ViewPlan):
        # Create and Show
        window = BurgerWindow("ui.xaml")
        window.show()
    else:
        forms.alert("Open a Floor Plan first.")