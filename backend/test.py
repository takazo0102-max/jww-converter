import ezdxf

try:
    doc = ezdxf.readfile("uploads/dda71f07-1273-4dbc-9702-8f673fc42977.dwg")
    print("Success")
except Exception as e:
    print(f"Error: {type(e).__name__} - {e}")
