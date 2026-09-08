bl_info = {
    "name": "Unity Rig & Animation Exporter",
    "author": "Mauro Lopez Gimenez",
    "version": (1, 0, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > Unity Export",
    "description": "Exports decoupled base meshes and NLA animation clips for Unity.",
    "category": "Import-Export",
}

from . import unity_fbx_exporter

def register():
    unity_fbx_exporter.register()

def unregister():
    unity_fbx_exporter.unregister()

if __name__ == "__main__":
    register()