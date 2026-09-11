bl_info = {
    "name": "Curve Flow Map Generator",
    "author": "Mauro Lopez Gimenez",
    "version": (1, 0, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Object > Flow Map",
    "description": "Generates flow maps from grooming curves to vertex colors and bakes to texture",
    "category": "Pipeline",
}

from . import curve_flow_map_generator

def register():
    curve_flow_map_generator.register()

def unregister():
    curve_flow_map_generator.unregister()

if __name__ == "__main__":
    register()