# -*- coding: utf-8 -*-
from pyrevit import forms, revit, DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import UnitUtils, UnitTypeId

# 1. THE WORKER: Updated to handle plane collisions and forced refresh
class ViewRangeUpdateHandler(IExternalEventHandler):
    def __init__(self):
        self.new_offset_mm = 0.0

    def Execute(self, uiapp):
        print("--- Handler Triggered ---") # If this doesn't show up, the Event isn't Raising.
        doc = uiapp.ActiveUIDocument.Document
        view = uiapp.ActiveUIDocument.ActiveView
        
        if not isinstance(view, DB.ViewPlan):
            return

        # Convert UI Millimeters to Internal Feet
        offset_in_feet = UnitUtils.ConvertToInternalUnits(
            self.new_offset_mm, 
            UnitTypeId.Millimeters
        )

        try:
            with DB.Transaction(doc, "Live View Range Change") as t:
                t.Start()
                vr = view.GetViewRange()
                
                # FIX 1: Move Top/Bottom planes out of the way to prevent errors
                # We set a 500mm buffer above and below the Cut Plane
                buffer = UnitUtils.ConvertToInternalUnits(500, UnitTypeId.Millimeters)
                
                vr.SetOffset(DB.PlanViewPlane.TopClipPlane, offset_in_feet + buffer)
                vr.SetOffset(DB.PlanViewPlane.CutPlane, offset_in_feet)
                vr.SetOffset(DB.PlanViewPlane.BottomClipPlane, offset_in_feet - buffer)
                vr.SetOffset(DB.PlanViewPlane.ViewDepth, offset_in_feet - buffer)
                
                # FIX 2: Push the modified object back to the View
                view.SetViewRange(vr)
                
                t.Commit() 
            
            # FIX 3: Force redrawing of Point Clouds and Geometry
            uiapp.ActiveUIDocument.RefreshActiveView()
            
        except Exception as e:
            # If this prints, a View Template is likely locking the view
            print("REVIT ERROR: {}. Check if a View Template is active.".format(e))

    def GetName(self):
        return "View Range Live Metric Handler"

# 2. THE UI LOGIC
class LiveRangeWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.handler = ViewRangeUpdateHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # Get current value to sync slider on open
        cur_vr = revit.active_view.GetViewRange()
        cur_feet = cur_vr.GetOffset(DB.PlanViewPlane.CutPlane)
        cur_mm = UnitUtils.ConvertFromInternalUnits(cur_feet, UnitTypeId.Millimeters)
        
        self.OffsetSlider.Value = cur_mm
        self.ValueDisplay.Text = "{} mm".format(int(cur_mm))

    def on_slider_change(self, sender, e):
        # Ensure the event exists before raising
        if hasattr(self, 'ext_event'):
            self.handler.new_offset_mm = self.OffsetSlider.Value
            self.ValueDisplay.Text = "{} mm".format(int(self.OffsetSlider.Value))
            
            # Raise the event to trigger Execute()
            self.ext_event.Raise()

# 3. STARTUP
if __name__ == "__main__":
    if isinstance(revit.active_view, DB.ViewPlan):
        # Check if View Range is controlled by a Template
        view = revit.active_view
        vt_id = view.ViewTemplateId
        if vt_id != DB.ElementId.InvalidElementId:
            forms.alert("This view is controlled by a View Template. Please disable 'View Range' in the template or set Template to <None>.")
        
        window = LiveRangeWindow("ui.xaml")
        window.show()
    else:
        forms.alert("Please open a Floor Plan or Ceiling Plan.")