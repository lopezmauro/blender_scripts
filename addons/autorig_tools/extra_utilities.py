bl_info = {
    "name": "AutoRig Tools & Runtime",
    "author": "Mauro Lopez Gimenez",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Item > Rig Tools",
    "description": "Modular autorig generation and animation runtime tools",
    "category": "Rigging",
}

import bpy
import mathutils
from typing import Optional, List

def force_viewport_update(context):
    """Forces dependency graph re-evaluation, driver updates, and viewport redraw."""
    obj = context.active_object
    if obj:
        obj.update_tag(refresh={'DATA', 'TIME'})
    context.view_layer.update()
    context.evaluated_depsgraph_get().update()
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# ==============================================================================
# 1. OPERATORS: SPACE SWITCHING & SNAPPING
# ==============================================================================

class RIG_OT_switch_space(bpy.types.Operator):
    """Seamlessly switches parent space maintaining current world transform."""
    bl_idname = "rig.switch_space"
    bl_label = "Switch Space Seamlessly"
    bl_options = {'REGISTER', 'UNDO'}

    bone_name: bpy.props.StringProperty()
    target_space_index: bpy.props.IntProperty()

    def execute(self, context):
        obj = context.active_object
        pbone = obj.pose.bones.get(self.bone_name)
        if not pbone:
            return {'CANCELLED'}

        # Cache current world matrix
        world_mat = obj.matrix_world @ pbone.matrix

        # Switch property
        pbone["Space"] = self.target_space_index
        context.evaluated_depsgraph_get().update()

        # Re-apply compensated matrix
        pbone.matrix = obj.matrix_world.inverted() @ world_mat
        force_viewport_update(context)

        return {'FINISHED'}

def get_metadata_list(pbone: bpy.types.PoseBone, key: str) -> List[str]:
    """Safely retrieves a list of bone names from a comma-separated IDProperty."""
    val = pbone.get(key, "")
    if isinstance(val, str):
        return [x.strip() for x in val.split(",") if x.strip()]
    return list(val)

def get_settings_bone_from_context(context, explicit_name: str = "") -> Optional[bpy.types.PoseBone]:
    """Resolves the settings pose bone from operator properties or active bone metadata."""
    obj = context.active_object
    if not obj or obj.type != 'ARMATURE' or not obj.pose:
        return None

    if explicit_name and explicit_name in obj.pose.bones:
        return obj.pose.bones[explicit_name]

    active_pbone = context.active_pose_bone
    if not active_pbone:
        return None

    linked_name = active_pbone.get("_settings_bone") or active_pbone.get("settings_bone")
    if linked_name and str(linked_name) in obj.pose.bones:
        return obj.pose.bones[str(linked_name)]

    if "_snap_fk_chain" in active_pbone:
        return active_pbone

    return None

class RIG_OT_snap_fk_to_ik(bpy.types.Operator):
    """Matches FK controls to evaluated IK pose using bone metadata."""
    bl_idname = "rig.snap_fk_to_ik"
    bl_label = "Snap FK to IK"
    bl_options = {'REGISTER', 'UNDO'}

    settings_bone: bpy.props.StringProperty(default="")

    def execute(self, context):
        obj = context.active_object
        p_settings = get_settings_bone_from_context(context, self.settings_bone)

        if not p_settings or "_snap_fk_chain" not in p_settings:
            self.report({'ERROR'}, "No snapping metadata found on settings bone.")
            return {'CANCELLED'}

        fk_chain = get_metadata_list(p_settings, "_snap_fk_chain")
        ik_sources = get_metadata_list(p_settings, "_snap_ik_sources")
        tweaks = get_metadata_list(p_settings, "_snap_tweaks")

        # 1. Reset tweak offsets
        for twk_name in tweaks:
            if twk_name in obj.pose.bones:
                obj.pose.bones[twk_name].location = (0.0, 0.0, 0.0)

        # 2. Reset roll/bank properties
        for prop in ("Foot_Roll", "Bank", "Heel_Twist", "Toe_Twist"):
            if prop in p_settings:
                p_settings[prop] = 0.0

        context.view_layer.update()
        context.evaluated_depsgraph_get().update()

        # 3. Pre-cache target world matrices before modifying any bones
        snap_targets = []
        for fk_name, src_name in zip(fk_chain, ik_sources):
            fk_pbone = obj.pose.bones.get(fk_name)
            src_pbone = obj.pose.bones.get(src_name)

            if fk_pbone and src_pbone:
                rest_delta = src_pbone.bone.matrix_local.inverted() @ fk_pbone.bone.matrix_local
                target_mat = src_pbone.matrix.copy() @ rest_delta
                snap_targets.append((fk_pbone, target_mat))

        # 4. Apply transforms sequentially with intermediate view layer updates
        for fk_pbone, target_mat in snap_targets:
            fk_pbone.matrix = target_mat
            context.view_layer.update()

        # 5. Switch slider to FK (0.0)
        if "IK_FK" in p_settings:
            p_settings["IK_FK"] = 0.0

        force_viewport_update(context)
        return {'FINISHED'}


class RIG_OT_snap_ik_to_fk(bpy.types.Operator):
    """Matches IK controls and pole vector to current FK pose using bone metadata."""
    bl_idname = "rig.snap_ik_to_fk"
    bl_label = "Snap IK to FK"
    bl_options = {'REGISTER', 'UNDO'}

    settings_bone: bpy.props.StringProperty(default="")

    def execute(self, context):
        obj = context.active_object
        p_settings = get_settings_bone_from_context(context, self.settings_bone)

        if not p_settings or "_snap_fk_chain" not in p_settings:
            self.report({'ERROR'}, "No snapping metadata found on settings bone.")
            return {'CANCELLED'}

        fk_chain = get_metadata_list(p_settings, "_snap_fk_chain")
        ik_ctrl_name = p_settings.get("_snap_ik_ctrl")
        pole_ctrl_name = p_settings.get("_snap_pole_ctrl")
        limb_type = p_settings.get("_snap_limb_type", "Arm")
        tweaks = get_metadata_list(p_settings, "_snap_tweaks")

        p_upper = obj.pose.bones.get(fk_chain[0]) if len(fk_chain) > 0 else None
        p_lower = obj.pose.bones.get(fk_chain[1]) if len(fk_chain) > 1 else None
        p_tip = obj.pose.bones.get(fk_chain[2]) if len(fk_chain) > 2 else None
        p_ik = obj.pose.bones.get(ik_ctrl_name)
        p_pole = obj.pose.bones.get(pole_ctrl_name)

        if not all([p_upper, p_lower, p_tip, p_ik, p_pole]):
            self.report({'ERROR'}, "One or more kinematic bones referenced in metadata are missing.")
            return {'CANCELLED'}

        # 1. Reset tweaks and roll offsets
        for twk_name in tweaks:
            if twk_name in obj.pose.bones:
                obj.pose.bones[twk_name].location = (0.0, 0.0, 0.0)

        for prop in ("Foot_Roll", "Bank", "Heel_Twist", "Toe_Twist"):
            if prop in p_settings:
                p_settings[prop] = 0.0

        context.view_layer.update()
        context.evaluated_depsgraph_get().update()

        # 2. Match IK Target matrix to FK Tip
        b_ik_rest = p_ik.bone.matrix_local
        b_tip_rest = p_tip.bone.matrix_local
        rest_offset = b_ik_rest.inverted() @ b_tip_rest

        p_ik.matrix = p_tip.matrix @ rest_offset.inverted()
        context.view_layer.update()

        # 3. Orthogonal Bend Vector calculation for Pole
        v_upper = p_upper.matrix.translation
        v_lower = p_lower.matrix.translation
        v_tip = p_tip.matrix.translation

        limb_vec = v_tip - v_upper
        limb_len = limb_vec.length

        if limb_len > 1e-4:
            limb_dir = limb_vec.normalized()
            proj_point = v_upper + limb_dir * ((v_lower - v_upper).dot(limb_dir))
            bend_vec = v_lower - proj_point
        else:
            bend_vec = mathutils.Vector((0.0, 0.0, 0.0))

        if bend_vec.length > 1e-4:
            pole_dir = -bend_vec.normalized()
        else:
            if limb_type == 'Leg':
                pole_dir = (p_upper.matrix.to_3x3() @ mathutils.Vector((0.0, 1.0, 0.0))).normalized()
            else:
                pole_dir = (p_upper.matrix.to_3x3() @ mathutils.Vector((0.0, -1.0, 0.0))).normalized()

        arm_len = (v_lower - v_upper).length + (v_tip - v_lower).length
        pole_dist = arm_len * 0.8
        p_pole.matrix.translation = v_lower + (pole_dir * pole_dist)
        context.view_layer.update()

        # 4. Switch slider to IK (1.0)
        if "IK_FK" in p_settings:
            p_settings["IK_FK"] = 1.0

        force_viewport_update(context)
        return {'FINISHED'}
# ==============================================================================
# 2. EXPORT PIPELINE
# ==============================================================================

class RIG_OT_bake_and_export_unity(bpy.types.Operator):
    """Bakes deforming bones and exports an FBX cleanly for Unity."""
    bl_idname = "rig.bake_and_export_unity"
    bl_label = "Export to Unity (DEF only)"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Active object is not an armature.")
            return {'CANCELLED'}

        bpy.ops.ed.undo_push(message="Pre-Export State")

        # Select meshes and armature
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        for child in obj.children:
            if child.type == 'MESH':
                child.select_set(True)

        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='DESELECT')

        # Select all true deforming bones via native flag and name pattern
        deform_count = 0
        for pbone in obj.pose.bones:
            is_deform = pbone.bone.use_deform or "_def." in pbone.name.lower() or pbone.name.startswith("DEF")
            if is_deform:
                if hasattr(pbone.bone, "select_set"):
                    pbone.bone.select_set(True)
                else:
                    pbone.bone.select = True
                deform_count += 1

        if deform_count == 0:
            self.report({'ERROR'}, "No deforming bones found on armature.")
            bpy.ops.object.mode_set(mode='OBJECT')
            bpy.ops.ed.undo()
            return {'CANCELLED'}

        # Bake pose visual transformations
        bpy.ops.nla.bake(
            frame_start=context.scene.frame_start,
            frame_end=context.scene.frame_end,
            step=1,
            only_selected=True,
            visual_keying=True,
            clear_constraints=False,
            clear_parents=False,
            use_current_action=True,
            bake_types={'POSE'}
        )

        bpy.ops.object.mode_set(mode='OBJECT')

        bpy.ops.export_scene.fbx(
            filepath=self.filepath,
            use_selection=True,
            object_types={'ARMATURE', 'MESH'},
            use_armature_deform_only=True,
            add_leaf_bones=False,
            bake_anim=True,
            bake_anim_use_nla_strips=False,
            bake_anim_use_all_actions=False,
            bake_anim_force_startend_keying=True,
            bake_anim_step=1.0,
            bake_anim_simplify_factor=0.0
        )

        bpy.ops.ed.undo()
        self.report({'INFO'}, f"Exported {deform_count} deform bones to {self.filepath}")
        return {'FINISHED'}


# ==============================================================================
# 3. SIDEBAR PANEL
# ==============================================================================
def draw_ordered_properties(layout, pose_bone, title=None, icon='PROPERTIES'):
    """Draws custom properties in creation order tracked by _prop_order."""
    if not pose_bone:
        return

    # Fallback to non-private keys if _prop_order is absent
    ordered_keys = pose_bone.get("_prop_order", [k for k in pose_bone.keys() if not k.startswith("_")])
    valid_keys = [k for k in ordered_keys if k in pose_bone and not k.startswith("_")]

    if not valid_keys:
        return

    if title:
        layout.label(text=title, icon=icon)

    col = layout.column(align=True)
    for prop_key in valid_keys:
        is_toggle = (
            prop_key.startswith("Show_")
            or prop_key.startswith("Is_")
            or prop_key.startswith("Enable_")
        )
        col.prop(
            pose_bone,
            f'["{prop_key}"]',
            text=prop_key.replace("_", " "),
            toggle=is_toggle
        )

def find_bone_name(armature_obj, target_name):
    bones = armature_obj.data.edit_bones if armature_obj.mode == 'EDIT' else armature_obj.data.bones
    if target_name in bones:
        return target_name

    target_clean = target_name.strip().lower()
    for b in bones:
        if b.name.strip().lower() == target_clean:
            return b.name
    return None


def resolve_chain_settings_bone(obj, active_bone):
    """
    Finds the master settings bone referenced directly by the active control.
    """
    if not active_bone:
        return None

    # Check for linked settings bone property
    settings_name = active_bone.get("_settings_bone") or active_bone.get("settings_bone")
    if settings_name:
        resolved_name = find_bone_name(obj, str(settings_name))
        if resolved_name:
            target_pbone = obj.pose.bones.get(resolved_name)
            # Avoid self-referencing if the settings bone itself is selected
            if target_pbone and target_pbone != active_bone:
                return target_pbone

    return None

class RIG_PT_rig_tools(bpy.types.Panel):
    """Creates a Panel in the 3D Viewport sidebar"""
    bl_label = "Rig Tools"
    bl_idname = "RIG_PT_rig_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Item'

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None
            and obj.type == 'ARMATURE'
            and obj.mode == 'POSE'
            and "autorig_type" in obj
        )

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        active_bone = context.active_pose_bone

        if not active_bone:
            layout.label(text="Select a control bone.")
            return

        name = active_bone.name

        # 1. Space Switching UI
        if "Space" in active_bone:
            layout.label(text="Space Switching:", icon='CONSTRAINT')
            row = layout.row(align=True)

            spaces = []
            if "CTRL_IK_Hand" in name or "CTRL_IK_hand" in name:
                spaces = ["Root", "Pelvis", "Chest", "Head"]
            elif "CTRL_IK_Foot" in name or "CTRL_IK_foot" in name:
                spaces = ["Root", "Pelvis"]
            elif "CTRL_Head" in name or "CTRL_head" in name:
                spaces = ["Root", "Chest"]

            current_space = active_bone["Space"]
            for i, space_name in enumerate(spaces):
                icon = 'RADIOBUT_ON' if i == current_space else 'RADIOBUT_OFF'
                op = row.operator("rig.switch_space", text=space_name, icon=icon)
                op.bone_name = name
                op.target_space_index = i

            layout.separator()

        # 2. Active Bone Properties
        draw_ordered_properties(layout, active_bone, title=f"{name} Properties:", icon='SETTINGS')

        # 3. Linked Settings Bone Properties (Macro chains, Limbs, etc.)
        settings_bone = resolve_chain_settings_bone(obj, active_bone)
        if settings_bone:
            layout.separator()
            draw_ordered_properties(
                layout, 
                settings_bone, 
                title=f"{settings_bone.name} Settings:", 
                icon='CON_KINEMATIC'
            )

            # Draw IK/FK snapping operators if this is a limb settings bone
            if "IK_FK" in settings_bone or "_snap_fk_chain" in settings_bone:
                row = layout.row(align=True)
                op_fk_to_ik = row.operator("rig.snap_fk_to_ik", text="Snap FK -> IK")
                op_fk_to_ik.settings_bone = settings_bone.name

                op_ik_to_fk = row.operator("rig.snap_ik_to_fk", text="Snap IK -> FK")
                op_ik_to_fk.settings_bone = settings_bone.name

        layout.separator()

        # 4. Pipeline Export
        layout.label(text="Pipeline:", icon='EXPORT')
        layout.operator("rig.bake_and_export_unity", text="Export to Unity")


classes = (
    RIG_OT_switch_space,
    RIG_OT_snap_fk_to_ik,
    RIG_OT_snap_ik_to_fk,
    RIG_OT_bake_and_export_unity,
    RIG_PT_rig_tools,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()