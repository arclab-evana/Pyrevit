# -*- coding: utf-8 -*-
__persistentengine__ = True

from pyrevit import forms, revit, DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import UnitUtils, UnitTypeId

# --- FIX: Import Canvas explicitly from Windows Controls ---
from System.Windows.Controls import Canvas 

# ---------------------------------------------------------------------
# 1. THE WORKER (Revit updater)
# ---------------------------------------------------------------------
class ViewRangeHandler(IExternalEventHandler):
    def __init__(self):
        # ANCHOR LOGIC:
        # We store 1 Absolute Position (Cut) and 2 Relative Offsets (Thickness)
        self.cut_mm = 1200.0
        self.top_offset_mm = 600.0
        self.bot_offset_mm = 600.0

    def Execute(self, uiapp):
        try:
            doc = uiapp.ActiveUIDocument.Document
            view = uiapp.ActiveUIDocument.ActiveView
            
            # 1. CALCULATE ABSOLUTE POSITIONS
            cut_abs = self.cut_mm
            top_abs = self.cut_mm + self.top_offset_mm
            bot_abs = self.cut_mm - self.bot_offset_mm
            
            # 2. CONVERT TO FEET
            cut_ft = UnitUtils.ConvertToInternalUnits(cut_abs, UnitTypeId.Millimeters)
            top_ft = UnitUtils.ConvertToInternalUnits(top_abs, UnitTypeId.Millimeters)
            bot_ft = UnitUtils.ConvertToInternalUnits(bot_abs, UnitTypeId.Millimeters)
            
            # Depth buffer (100mm below bottom)
            depth_ft = bot_ft - UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters)

            with DB.Transaction(doc, "Burger Range Update") as t:
                t.Start()
                
                vr = view.GetViewRange()
                assoc_level_id = view.GenLevel.Id
                
                # Reset all planes to level first
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
            # Silence errors during drag
            pass

    def GetName(self):
        return "Burger Handler"

# ---------------------------------------------------------------------
# 2. THE UI LOGIC (Anchor Physics)
# ---------------------------------------------------------------------
class BurgerWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.handler = ViewRangeHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # --- CONFIGURATION ---
        self.MIN_THICKNESS = 10.0 # Minimum distance between Cut and Top/Bot
        self.MAX_RANGE_MM = 4000.0 # Visual Top
        self.MIN_RANGE_MM = -1000.0 # Visual Bottom
        self.CANVAS_HEIGHT = 350.0 # Must match XAML Canvas Height
        
        # --- STATE (Anchor Logic) ---
        self.cut_mm = 1200.0       # The Anchor
        self.top_thick = 600.0     # Distance ABOVE Cut
        self.bot_thick = 600.0     # Distance BELOW Cut
        
        # Wire up Drag Events
        self.CutThumb.DragDelta += self.on_cut_drag
        self.TopThumb.DragDelta += self.on_top_drag
        self.BotThumb.DragDelta += self.on_bot_drag
        
        # Wire up Release Events (Update Revit)
        self.CutThumb.DragCompleted += self.trigger_revit
        self.TopThumb.DragCompleted += self.trigger_revit
        self.BotThumb.DragCompleted += self.trigger_revit

        # Initial Draw
        self.update_visuals()

    # --- MATH HELPERS ---
    def mm_to_px(self, mm_val):
        # Converts an Absolute MM value to a Pixel Y position
        total_span = self.MAX_RANGE_MM - self.MIN_RANGE_MM
        normalized = (mm_val - self.MIN_RANGE_MM) / total_span
        pixel_y = self.CANVAS_HEIGHT * (1.0 - normalized)
        return pixel_y

    def px_to_mm(self, px_val):
        # Converts a Pixel Y position back to Absolute MM
        normalized = 1.0 - (px_val / self.CANVAS_HEIGHT)
        total_span = self.MAX_RANGE_MM - self.MIN_RANGE_MM
        mm_val = self.MIN_RANGE_MM + (normalized * total_span)
        return mm_val

    # --- DRAG HANDLERS ---
    
    def on_cut_drag(self, sender, e):
        # 1. MOVE ANCHOR: We only change the Cut Plane
        # The Top/Bot Thickness remains constant, so they move with it.
        delta_mm = -1 * (e.VerticalChange / self.CANVAS_HEIGHT) * (self.MAX_RANGE_MM - self.MIN_RANGE_MM)
        self.cut_mm += delta_mm
        self.update_visuals()

    def on_top_drag(self, sender, e):
        # 1. Calculate new Absolute Top
        current_top_abs = self.cut_mm + self.top_thick
        current_px = self.mm_to_px(current_top_abs)
        new_px = current_px + e.VerticalChange
        new_abs = self.px_to_mm(new_px)
        
        # 2. Update Thickness (Distance from Cut)
        new_thick = new_abs - self.cut_mm
        
        # 3. Safety Check
        if new_thick < self.MIN_THICKNESS:
            new_thick = self.MIN_THICKNESS
            
        self.top_thick = new_thick
        self.update_visuals()

    def on_bot_drag(self, sender, e):
        # 1. Calculate new Absolute Bottom
        current_bot_abs = self.cut_mm - self.bot_thick
        current_px = self.mm_to_px(current_bot_abs)
        new_px = current_px + e.VerticalChange
        new_abs = self.px_to_mm(new_px)
        
        # 2. Update Thickness (Distance from Cut)
        # Note: Thickness is always positive distance
        new_thick = self.cut_mm - new_abs
        
        # 3. Safety Check
        if new_thick < self.MIN_THICKNESS:
            new_thick = self.MIN_THICKNESS
            
        self.bot_thick = new_thick
        self.update_visuals()

    # --- VISUAL UPDATE ---
    def update_visuals(self):
        # 1. Calculate Absolutes for Drawing
        top_abs = self.cut_mm + self.top_thick
        bot_abs = self.cut_mm - self.bot_thick
        
        # 2. Update Text Labels
        self.TopLabel.Text = "Top: +{}".format(int(self.top_thick))
        self.CutLabel.Text = "Cut: {}".format(int(self.cut_mm))
        self.BotLabel.Text = "Bot: -{}".format(int(self.bot_thick))

        # 3. Move Thumbs
        # Top Thumb (Left Arrow)
        self.move_thumb(self.TopThumb, top_abs)
        # Cut Thumb (Burger)
        self.move_thumb(self.CutThumb, self.cut_mm)
        # Bot Thumb (Right Arrow)
        self.move_thumb(self.BotThumb, bot_abs)

    def move_thumb(self, thumb, mm_val):
        y_pos = self.mm_to_px(mm_val)
        # Center thumb vertically
        # --- FIXED LINE BELOW: Use Canvas.TopProperty ---
        thumb.SetValue(Canvas.TopProperty, y_pos - (thumb.Height / 2.0))

    # --- REVIT COMMUNICATION ---
    def trigger_revit(self, sender, e):
        self.handler.cut_mm = self.cut_mm
        self.handler.top_offset_mm = self.top_thick
        self.handler.bot_offset_mm = self.bot_thick
        self.ext_event.Raise()

# ---------------------------------------------------------------------
# 3. STARTUP
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if isinstance(revit.active_view, DB.ViewPlan):
        window = BurgerWindow("ui.xaml")
        window.show()
    else:
        forms.alert("Open a Floor Plan first.")