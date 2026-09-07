import bpy
import json
import os
import sys
import importlib
import os; os.path and os.system('cls')
parent_dir = r"C:\Users\vince\Documents\dev"
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

def reload_package(package_name):
    """Reloads a top-level package and all of its imported submodules."""
    # Find all currently loaded submodules matching the package prefix
    modules_to_reload = [
        name for name in sys.modules 
        if name == package_name or name.startswith(package_name + ".")
    ]
    
    # Reload each submodule one by one
    for module_name in sorted(modules_to_reload):
        try:
            print(f"Reload {module_name}")
            importlib.reload(sys.modules[module_name])
        except Exception as e:
            print(f"Failed to reload {module_name}: {e}")

# Usage:
import blender_scripts
reload_package("blender_scripts")

# Import components package to trigger registration decorators
import blender_scripts.addons.autorig.components
from blender_scripts.addons.autorig import rig_builder


active_obj = bpy.context.active_object
if active_obj and active_obj.type == 'ARMATURE':
    config_path = r"C:\Users\vince\Documents\dev\blender_scripts\addons\autorig\configs\biped_config.json"
    rig_builder.execute_rig_build(active_obj, config_path)
else:
    print("Please select an Armature object before running the build.")