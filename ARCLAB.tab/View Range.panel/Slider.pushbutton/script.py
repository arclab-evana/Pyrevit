# -*- coding: utf-8 -*-
from pyrevit import forms, revit, DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.DB import UnitUtils, UnitTypeId

# 1. THE WORKER: This class executes the Revit commands
class ViewRangeUpdateHandler(IExternalEventHandler):
    def __init__(self):
        self.new_offset_mm = 0.0

    def Execute(self, uiapp):
        doc = uiapp.ActiveUIDocument.Document
        view = uiapp.ActiveUIDocument.ActiveView
        
        # Guard clause: ensure we are in a plan view
        if not isinstance(view, DB.ViewPlan):
            return

        # Convert the UI Millimeters to Revit Internal Feet
        offset_in_feet = UnitUtils.ConvertToInternalUnits(
            self.new_offset_mm, 
            UnitTypeId.Millimeters
        )

        try:
            # Wrap in a Transaction to save changes to the model
            with DB.Transaction(doc, "Live View Range Change") as t:
                t.Start()
                vr = view.GetViewRange()
                
                # Update the Cut Plane
                vr.SetOffset(DB.PlanViewPlane.CutPlane, offset_in_feet)
                view.SetViewRange(vr)
                
                t.Commit() # Essential to finalize the change
            
            # Forces Revit to redraw point clouds and geometry immediately
            uiapp.ActiveUIDocument.RefreshActiveView()
            
        except Exception as e:
            print("Error updating view range: {}".format(e))

    def GetName(self):
        return "View Range Live Metric Handler"

# 2. THE UI LOGIC: This connects the XAML Slider to the Worker above
class LiveRangeWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        # Create the handler and the event "bridge"
        self.handler = ViewRangeUpdateHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # Set slider to current view's actual value on startup
        cur_vr = revit.active_view.GetViewRange()
        cur_feet = cur_vr.GetOffset(DB.PlanViewPlane.CutPlane)
        
        # Convert internal feet back to MM for the UI display
        cur_mm = UnitUtils.ConvertFromInternalUnits(cur_feet, UnitTypeId.Millimeters)
        
        self.OffsetSlider.Value = cur_mm
        self.ValueDisplay.Text = "{} mm".format(int(cur_mm))

    def on_slider_change(self, sender, e):
        # 1. Update the value in our handler
        self.handler.new_offset_mm = self.OffsetSlider.Value
        
        # 2. Update the UI text label
        self.ValueDisplay.Text = "{} mm".format(int(self.OffsetSlider.Value))
        
        # 3. Trigger the Revit update (This calls the Execute() method above)
        self.ext_event.Raise()

# 3. STARTUP
if __name__ == "__main__":
    # Ensure the user is in a Plan View before opening the window
    if isinstance(revit.active_view, DB.ViewPlan):
        window = LiveRangeWindow("ui.xaml")
        window.show()
    else:
        forms.alert("Please open a Floor Plan or Ceiling Plan first.")