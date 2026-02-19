if __name__ == "__main__":
    try:
        v = revit.active_view
        if isinstance(v, DB.ViewPlan) and v.ViewType == DB.ViewType.CeilingPlan:
            cur_dir = os.path.dirname(__file__)
            xaml_file = os.path.join(cur_dir, "ui.xaml")
            
            if os.path.exists(xaml_file):
                window = BurgerWindowRCP(xaml_file)
                window.show()
            else:
                forms.alert("Missing ui.xaml file.")
        else:
            forms.alert("Please open an RCP view.")
    except Exception as e:
        # This will show you exactly which line failed (e.g., "UpButton not found")
        import traceback
        forms.alert(str(e), sub_msg=traceback.format_exc())