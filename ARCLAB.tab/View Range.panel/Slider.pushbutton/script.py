# -*- coding: utf-8 -*-
__persistentengine__ = True

from pyrevit import forms, revit, DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import UnitUtils, UnitTypeId

# ---------------------------------------------------------------------
# 1. THE WORKER
# ---------------------------------------------------------------------
class ViewRangeUpdateHandler(IExternalEventHandler):
    def __init__(self):
        # We now store 3 values
        self.cut_mm = 1200.0
        self.top_offset_mm = 500.0
        self.bot_offset_mm = 500.0

    def Execute(self, uiapp):
        try:
            doc = uiapp.ActiveUIDocument.Document
            view = uiapp.ActiveUIDocument.ActiveView
            
            # --- CALCULATE FINAL POSITIONS ---
            # Top Absolute = Cut + Top Offset
            # Bottom Absolute = Cut - Bottom Offset
            
            cut_feet = UnitUtils.ConvertToInternalUnits(self.cut_mm, UnitTypeId.Millimeters)
            top_feet = UnitUtils.ConvertToInternalUnits(self.cut_mm + self.top_offset_mm, UnitTypeId.Millimeters)
            bot_feet = UnitUtils.ConvertToInternalUnits(self.cut_mm - self.bot_offset_mm, UnitTypeId.Millimeters)
            
            # Depth buffer (slightly below bottom)
            depth_feet = bot_feet - UnitUtils.ConvertToInternalUnits(100, UnitTypeId.Millimeters)

            with DB.Transaction(doc, "Burger View Range") as t:
                t.Start()
                
                vr = view.GetViewRange()
                assoc_level_id = view.GenLevel.Id
                
                # 1. Reset all to level to prevent "Top < Cut" errors
                planes = [DB.PlanViewPlane.TopClipPlane, 
                          DB.PlanViewPlane.CutPlane, 
                          DB.PlanViewPlane.BottomClipPlane, 
                          DB.PlanViewPlane.ViewDepthPlane]

                for p in planes:
                    vr.SetLevelId(p, assoc_level_id)

                # 2. Set Values (Top > Cut > Bottom)
                vr.SetOffset(DB.PlanViewPlane.TopClipPlane, top_feet)
                vr.SetOffset(DB.PlanViewPlane.CutPlane, cut_feet)
                vr.SetOffset(DB.PlanViewPlane.BottomClipPlane, bot_feet)
                vr.SetOffset(DB.PlanViewPlane.ViewDepthPlane, depth_feet)
                
                view.SetViewRange(vr)
                t.Commit() 
            
            uiapp.ActiveUIDocument.RefreshActiveView()
            
        except Exception as e:
            forms.alert("Error: {}".format(e))

    def GetName(self):
        return "Burger Handler"

# ---------------------------------------------------------------------
# 2. THE UI LOGIC
# ---------------------------------------------------------------------
class BurgerWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.handler = ViewRangeUpdateHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # Wire up events for ALL sliders
        sliders = [self.CutPlaneSlider, self.TopOffsetSlider, self.BottomOffsetSlider]
        
        for sl in sliders:
            sl.ValueChanged += self.update_text
            sl.PreviewMouseLeftButtonUp += self.trigger_revit

        self.update_text(None, None)

    def update_text(self, sender, args):
        # Update UI Labels
        self.CutDisplay.Text = "Cut: {}mm".format(int(self.CutPlaneSlider.Value))
        self.TopDisplay.Text = "+{}mm".format(int(self.TopOffsetSlider.Value))
        self.BotDisplay.Text = "-{}mm".format(int(self.BottomOffsetSlider.Value))

    def trigger_revit(self, sender, args):
        # Update Handler Data
        self.handler.cut_mm = self.CutPlaneSlider.Value
        self.handler.top_offset_mm = self.TopOffsetSlider.Value
        self.handler.bot_offset_mm = self.BottomOffsetSlider.Value
        
        # Fire Event
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