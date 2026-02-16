# -*- coding: utf-8 -*-
from pyrevit import forms, revit, DB
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.Exceptions import InvalidOperationException

# 1. THE HANDLER: This is the "Worker" that actually changes Revit
class ViewRangeUpdateHandler(IExternalEventHandler):
    def __init__(self):
        self.new_offset = 0.0

    def Execute(self, uiapp):
        doc = uiapp.ActiveUIDocument.Document
        view = uiapp.ActiveUIDocument.ActiveView
        
        if not isinstance(view, DB.ViewPlan):
            return

        try:
            with DB.Transaction(doc, "Live View Range") as t:
                t.Start()
                vr = view.GetViewRange()
                # Setting the Cut Plane offset (Standard Revit Internal Units: Feet)
                vr.SetOffset(DB.PlanViewPlane.CutPlane, self.new_offset)
                view.SetViewRange(vr)
                t.Commit()
            
            # This forces the Point Cloud and Geometry to redraw immediately
            uiapp.ActiveUIDocument.RefreshActiveView()
        except Exception as e:
            print("Error updating view: {}".format(e))

    def GetName(self):
        return "View Range Live Updater"

# 2. THE WINDOW: This links the UI Slider to the Handler
class LiveRangeWindow(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        # Setup the External Event
        self.handler = ViewRangeUpdateHandler()
        self.ext_event = ExternalEvent.Create(self.handler)
        
        # Initialize Slider starting position from current view
        cur_vr = revit.active_view.GetViewRange()
        start_val = cur_vr.GetOffset(DB.PlanViewPlane.CutPlane)
        self.OffsetSlider.Value = start_val
        self.ValueDisplay.Text = "{} ft".format(round(start_val, 2))

    def on_slider_change(self, sender, e):
        # Update the handler with the new value from slider
        self.handler.new_offset = self.OffsetSlider.Value
        self.ValueDisplay.Text = "{} ft".format(round(self.OffsetSlider.Value, 2))
        
        # Tell Revit: "Run the handler when you are next idle"
        self.ext_event.Raise()

# 3. EXECUTION
if __name__ == "__main__":
    # Ensure we are in a Plan View
    if isinstance(revit.active_view, DB.ViewPlan):
        window = LiveRangeWindow("ui.xaml")
        window.show()
    else:
        forms.alert("Please run this tool in a Floor Plan or Ceiling Plan.")