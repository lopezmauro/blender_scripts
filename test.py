import sys
import importlib
import bpy

parent_dir = r"C:\Users\vince\game_dev\Anhedonia_art"
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from blender_scripts import core_framework, guide_limbs, limbs_rig
importlib.reload(core_framework)
importlib.reload(guide_limbs)
importlib.reload(limbs_rig)

arm_obj = bpy.context.active_object
core_framework.organize_initial_deform_bones(arm_obj)
guide_limbs.create_or_get_guides(arm_obj)


limbs_rig.build_limbs_rig(arm_obj)


import sys
import importlib
import bpy

parent_dir = r"C:\Users\vince\game_dev\Anhedonia_art"
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from blender_scripts import core_framework, guides_framework, systems_framework, limbs_rig, hand_rig, tail_rig, facial_rig, spine_head
importlib.reload(core_framework)
importlib.reload(guides_framework)
importlib.reload(systems_framework)
importlib.reload(spine_head)
importlib.reload(limbs_rig)
importlib.reload(hand_rig)
importlib.reload(tail_rig)
importlib.reload(facial_rig)

arm_obj = bpy.context.active_object
core_framework.organize_initial_deform_bones(arm_obj)
#guides_framework.create_or_get_limb_guides(arm_obj)
spine_head.build_spine_head_rig(arm_obj)
limbs_rig.build_limbs_rig(arm_obj)
hand_rig.build_hands_rig(arm_obj)
tail_rig.build_tail_ears_rig(arm_obj)
facial_rig.build_facial_rig(arm_obj)


import sys
import importlib
import bpy

parent_dir = r"C:\Users\vince\game_dev\Anhedonia_art"
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from blender_scripts import core_framework, guides_framework, systems_framework, limbs_rig, hand_rig, tail_rig, facial_rig, spine_head
importlib.reload(core_framework)
importlib.reload(guides_framework)
importlib.reload(systems_framework)
importlib.reload(spine_head)
importlib.reload(limbs_rig)
importlib.reload(hand_rig)
importlib.reload(tail_rig)
importlib.reload(facial_rig)

arm_obj = bpy.context.active_object
core_framework.organize_initial_deform_bones(arm_obj)
#guides_framework.create_or_get_limb_guides(arm_obj)
spine_head.build_spine_head_rig(arm_obj)
limbs_rig.build_limbs_rig(arm_obj)
hand_rig.build_hands_rig(arm_obj)
tail_rig.build_tail_ears_rig(arm_obj)
facial_rig.build_facial_rig(arm_obj)
core_framework.apply_color_coding(arm_obj)
core_framework.setup_space_switching(arm_obj)


from blender_scripts import extra_utilities
extra_utilities.unregister()
extra_utilities.register()