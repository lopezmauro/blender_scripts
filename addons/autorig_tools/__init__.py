bl_info = {
    "name": "AutoRig Tools & Runtime",
    "author": "Mauro Lopez Gimenez",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Item > Rig Tools",
    "description": "Modular autorig generation and animation runtime tools",
    "category": "Rigging",
}

from . import extra_utilities

def register():
    extra_utilities.register()

def unregister():
    extra_utilities.unregister()

if __name__ == "__main__":
    register()