bl_info = {
    "name": "Custom FBX Retargeter",
    "author": "Mauro Lopez Gimenez",
    "version": (1, 0, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Retarget",
    "description": "Data model, UI list, and mapping controls for FBX retargeting",
    "category": "Animation",
}

from . import retargeter

def register():
    retargeter.register()

def unregister():
    retargeter.unregister()

if __name__ == "__main__":
    register()