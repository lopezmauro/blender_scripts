import bpy
import json
import os
import sys
import importlib
import os; os.path and os.system('cls')
parent_dir = r"C:\Users\vince\game_dev\Anhedonia_art"
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
            importlib.reload(sys.modules[module_name])
        except Exception as e:
            print(f"Failed to reload {module_name}: {e}")

# Usage:
import blender_scripts
reload_package("blender_scripts")

# Import components package to trigger registration decorators
import blender_scripts.autorig.components
from blender_scripts.autorig.rig_builder import RigBuilder
from blender_scripts.autorig.base_component import COMPONENT_REGISTRY


def execute_rig_build(armature_obj: bpy.types.Object, config_filepath: str):
    if not os.path.exists(config_filepath):
        print(f"[Build Error] Config file not found: {config_filepath}")
        return

    print(f"[RigBuilder] Loaded components in registry: {list(COMPONENT_REGISTRY.keys())}")

    with open(config_filepath, 'r') as f:
        config_data = json.load(f)

    builder = RigBuilder(armature_obj=armature_obj, config=config_data)
    success = builder.build()

    if success:
        print(f"[Build Complete] '{config_data.get('rig_name')}' generated successfully.")


active_obj = bpy.context.active_object
if active_obj and active_obj.type == 'ARMATURE':
    config_path = r'C:\Users\vince\game_dev\Anhedonia_art\blender_scripts\autorig\configs\biped_config.json'
    execute_rig_build(active_obj, config_path)
else:
    print("Please select an Armature object before running the build.")