import bpy
import os

def import_fbx_to_armature(filepath: str, armature_name: str) -> bpy.types.Action:
    """
    Imports an FBX animation, replaces the armature data block on the named object
    to ensure 100% rest-pose parity, assigns the slotted action, and purges NLA/constraints.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"FBX path not found: {filepath}")

    target_obj = bpy.data.objects.get(armature_name)
    if not target_obj or target_obj.type != 'ARMATURE':
        raise ValueError(f"Armature '{armature_name}' not found or is not an ARMATURE.")

    pre_import_objs = set(bpy.data.objects)

    # 1. Import raw FBX without altering bone rolls
    bpy.ops.import_scene.fbx(
        filepath=filepath,
        use_anim=True,
        ignore_leaf_bones=False,
        automatic_bone_orientation=False,
        force_connect_children=False
    )

    new_objs = set(bpy.data.objects) - pre_import_objs
    imported_armature = next((o for o in new_objs if o.type == 'ARMATURE'), None)

    if not imported_armature or not imported_armature.animation_data or not imported_armature.animation_data.action:
        for obj in new_objs:
            bpy.data.objects.remove(obj, do_unlink=True)
        raise RuntimeError(f"No valid animation found in FBX: {filepath}")

    imported_action = imported_armature.animation_data.action
    imported_action.use_fake_user = True
    imported_data = imported_armature.data

    # 2. Clear any lingering bone constraints from previous retargeting tests
    for pb in target_obj.pose.bones:
        for c in list(pb.constraints):
            pb.constraints.remove(c)

    # 3. Swap the Armature Data block (matches bone rolls and rest matrices 1:1)
    old_data = target_obj.data
    target_obj.data = imported_data

    # Unlink old data block if no longer referenced
    if old_data.users == 0:
        bpy.data.armatures.remove(old_data)

    # 4. Clear existing NLA tracks that cause pose blending
    if not target_obj.animation_data:
        target_obj.animation_data_create()
    else:
        for track in list(target_obj.animation_data.nla_tracks):
            target_obj.animation_data.nla_tracks.remove(track)

    # 5. Assign Action and configure Blender 5.1 Action Slot
    target_obj.animation_data.action = imported_action
    if hasattr(target_obj.animation_data, "action_slot") and hasattr(imported_action, "slots"):
        if imported_action.slots:
            target_obj.animation_data.action_slot = imported_action.slots[0]

    # 6. Remove temporary imported objects
    for obj in new_objs:
        bpy.data.objects.remove(obj, do_unlink=True)

    # 7. Sync scene timeline to action bounds
    start_frame = int(imported_action.frame_range[0])
    end_frame = int(imported_action.frame_range[1])
    scene = bpy.context.scene
    scene.frame_start = start_frame
    scene.frame_end = end_frame
    scene.frame_set(start_frame)
    bpy.context.view_layer.update()

    print(f"Applied '{imported_action.name}' to '{armature_name}' with rest-pose synchronization.")
    return imported_action


# -----------------------------------------------------------------------------
# Test Call
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    FBX_FILEPATH = r"C:\path\to\your\walk_cycle.fbx"
    TARGET_ARMATURE_NAME = "skeleton"

    try:
        import_fbx_to_armature(FBX_FILEPATH, TARGET_ARMATURE_NAME)
    except Exception as err:
        print(f"Execution failed: {err}")