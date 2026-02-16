# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------
# 1. PERSISTENCE (Crucial Fix)
# This keeps the background thread alive so the External Event 
# doesn't get "Garbage Collected" (deleted) by Python.
# ---------------------------------------------------------------------
__persistentengine__ = True

from pyrevit import forms, revit, DB, script
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import UnitUtils, UnitTypeId

# ---------------------------------------------------------------------
# 2. THE WORKER (External Event Handler)
# ---------------------------------------------------------------------
class ViewRangeUpdateHandler(IExternalEventHandler):
    def __init__(self):
        self.new_offset_mm = 0.0

    def Execute(self, uiapp):
        try:
            doc = uiapp.ActiveUIDocument.Document
            view = uiapp.ActiveUIDocument.ActiveView
            
            # Check 1: Is it a Plan View?
            if not isinstance(view, DB.ViewPlan):
                # Using forms.alert ensures you see the error, unlike 'print'
                forms.alert("Active view is not a Floor/Ceiling Plan.")
                return

            # Check 2: Is a View Template blocking us?
            if view.ViewTemplateId != DB.ElementId.InvalidElementId:
                # View Templates lock the view range.
                forms.alert("View is controlled by a View Template. Disable it to use this tool.")
                return

            # Conversion
            offset_in_feet = UnitUtils.ConvertToInternalUnits(
                self.new_offset_mm, 
                UnitTypeId.Millimeters
            )
            
            # Buffer (1000mm)
            buffer = UnitUtils.ConvertToInternalUnits(1000, UnitTypeId.Millimeters)

            with DB.Transaction(doc, "Live View Range") as t:
                t.Start()
                
                vr = view.GetViewRange()
                assoc_level_id = view.GenLevel.Id
                
                # 1. Reset all planes to the associated level
                # This prevents "Top is below Cut" errors during transition
                for plane in [DB.PlanViewPlane.TopClipPlane, 
                             DB.PlanViewPlane.CutPlane, 
                             DB.PlanViewPlane.BottomClipPlane, 
                             DB.PlanViewPlane.ViewDepthPlane]:
                    vr.SetLevelId(plane, assoc_level_id)

                # 2. Apply Offsets (Logic: Top > Cut > Bottom >= Depth)
                vr.SetOffset(DB.PlanViewPlane.TopClipPlane, offset_in_feet + buffer)
                vr.SetOffset(DB.PlanViewPlane.CutPlane, offset_in_feet)
                vr.SetOffset(DB.PlanViewPlane.BottomClipPlane, offset_in_feet - buffer)
                vr.SetOffset(DB.PlanViewPlane.ViewDepthPlane, offset_in_feet - buffer)
                
                view.SetViewRange(vr)
                t.Commit() 
            
            uiapp.ActiveUIDocument.RefreshActiveView()
            
        except Exception as e:
            # Alert the user if something crashes silently
            forms.alert("Error: {}".format(e))

    def GetName(self):
        return "View Range Live Metric Handler"

# ---------------------------------------------------------------------
# 3. THE UI LOGIC
# ---------------------------------------------------------------------
class LiveRangeWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.handler = ViewRangeUpdateHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # Initialize UI with current view value
        self.sync_with_current_view()

        # EVENT WIRING:
        # We separate the "Visual Update" from the "Revit Update"
        # 1. When slider moves -> Update Text ONLY (Smooth UI)
        self.OffsetSlider.ValueChanged += self.update_text_display
        
        # 2. When mouse release -> Fire Revit Event (Prevents flooding)
        self.OffsetSlider.PreviewMouseLeftButtonUp += self.trigger_revit_update

    def sync_with_current_view(self):
        view = revit.active_view
        if isinstance(view, DB.ViewPlan):
            vr = view.GetViewRange()
            cur_feet = vr.GetOffset(DB.PlanViewPlane.CutPlane)
            cur_mm = UnitUtils.ConvertFromInternalUnits(cur_feet, UnitTypeId.Millimeters)
            
            # Temporarily unsubscribe to avoid triggering events during startup
            self.OffsetSlider.ValueChanged -= self.update_text_display
            self.OffsetSlider.Value = cur_mm
            self.OffsetSlider.ValueChanged += self.update_text_display
            
            self.ValueDisplay.Text = "{} mm".format(int(cur_mm))

    # Fast: Updates the text label instantly
    def update_text_display(self, sender, args):
        self.ValueDisplay.Text = "{} mm".format(int(self.OffsetSlider.Value))

    # Slow: Only runs when you let go of the mouse
    def trigger_revit_update(self, sender, args):
        self.handler.new_offset_mm = self.OffsetSlider.Value
        self.ext_event.Raise()

# ---------------------------------------------------------------------
# 4. STARTUP
# ---------------------------------------------------------------------
if __name__ == "__main__":
    if isinstance(revit.active_view, DB.ViewPlan):
        window = LiveRangeWindow("ui.xaml")
        window.show()
    else:
        forms.alert("Please open a Floor Plan first.")