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
from . import core_framework


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


class RIG_OT_snap_fk_to_ik(bpy.types.Operator):
    """Matches CTRL_FK transforms to evaluated MCH_IK / DEF pose."""
    bl_idname = "rig.snap_fk_to_ik"
    bl_label = "Snap FK to IK"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.StringProperty()
    limb: bpy.props.StringProperty()

    def execute(self, context):
        obj = context.active_object
        side = self.side

        # 1. Reset tweak offsets
        tweak_names = (
            [f"CTRL_Tweak_Upper_Arm{side}", f"CTRL_Tweak_Mid_Arm{side}", f"CTRL_Tweak_End_Arm{side}"]
            if self.limb == 'Arm' else
            [f"CTRL_Tweak_Upper_Leg{side}", f"CTRL_Tweak_Mid_Leg{side}", f"CTRL_Tweak_End_Leg{side}"]
        )
        for twk in tweak_names:
            twk_res = core_framework.find_bone_name(obj, twk)
            if twk_res and twk_res in obj.pose.bones:
                obj.pose.bones[twk_res].location = (0.0, 0.0, 0.0)

        # 2. Comprehensive candidate list covering DEF_, MCH_, and plain bone names
        if self.limb == 'Arm':
            candidates = [
                ([f"CTRL_FK_upperarm{side}", f"CTRL_FK_Upperarm{side}"],
                 [f"MCH_IK_upperarm{side}", f"MCH_IK_Upperarm{side}"]),
                ([f"CTRL_FK_lowerarm{side}", f"CTRL_FK_Lowerarm{side}"],
                 [f"MCH_IK_lowerarm{side}", f"MCH_IK_Lowerarm{side}"]),
                ([f"CTRL_FK_hand{side}", f"CTRL_FK_Hand{side}"],
                 [f"DEF_hand{side}", f"DEF_Hand{side}", f"hand{side}", f"Hand{side}", f"CTRL_IK_Hand{side}", f"CTRL_IK_hand{side}"])
            ]
        else:
            candidates = [
                ([f"CTRL_FK_thigh{side}", f"CTRL_FK_Thigh{side}"],
                 [f"MCH_IK_thigh{side}", f"MCH_IK_Thigh{side}"]),
                ([f"CTRL_FK_calf{side}", f"CTRL_FK_Calf{side}"],
                 [f"MCH_IK_calf{side}", f"MCH_IK_Calf{side}"]),
                ([f"CTRL_FK_foot{side}", f"CTRL_FK_Foot{side}"],
                 [f"DEF_foot{side}", f"DEF_Foot{side}", f"foot{side}", f"Foot{side}", f"MCH_ORG_foot{side}", f"MCH_ORG_Foot{side}"]),
                ([f"CTRL_FK_ball{side}", f"CTRL_FK_Ball{side}", f"CTRL_FK_toe{side}", f"CTRL_FK_Toe{side}"],
                 [f"DEF_ball{side}", f"DEF_Ball{side}", f"DEF_toe{side}", f"DEF_Toe{side}", f"ball{side}", f"Ball{side}", f"toe{side}", f"Toe{side}", f"MCH_IK_Ball{side}"])
            ]

        # Force evaluation so source matrices reflect current IK state
        context.view_layer.update()
        context.evaluated_depsgraph_get().update()

        # 3. Match transforms in hierarchical order with rest-matrix compensation
        for fk_opts, src_opts in candidates:
            fk_name_res = next((core_framework.find_bone_name(obj, n) for n in fk_opts if core_framework.find_bone_name(obj, n)), None)
            src_name_res = next((core_framework.find_bone_name(obj, n) for n in src_opts if core_framework.find_bone_name(obj, n)), None)

            if not fk_name_res or not src_name_res:
                continue

            fk_bone = obj.pose.bones.get(fk_name_res)
            src_bone = obj.pose.bones.get(src_name_res)

            if fk_bone and src_bone:
                # Calculate rest delta: rest_src^-1 @ rest_fk
                rest_delta = src_bone.bone.matrix_local.inverted() @ fk_bone.bone.matrix_local
                # Compensate pose matrix
                fk_bone.matrix = src_bone.matrix @ rest_delta
                context.view_layer.update()

        # 4. Switch mode to FK and zero foot roll settings
        settings_res = core_framework.find_bone_name(obj, f"CTRL_Settings_{self.limb}{side}")
        if settings_res:
            p_set = obj.pose.bones[settings_res]
            p_set["IK_FK"] = 0.0
            for prop in ("Foot_Roll", "Bank", "Heel_Twist", "Toe_Twist"):
                if prop in p_set:
                    p_set[prop] = 0.0

        force_viewport_update(context)
        print("snap_fk_to_ik - FINISHED!")
        return {'FINISHED'}


class RIG_OT_snap_ik_to_fk(bpy.types.Operator):
    """Matches CTRL_IK and pole vector to current FK orientation."""
    bl_idname = "rig.snap_ik_to_fk"
    bl_label = "Snap IK to FK"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.StringProperty()
    limb: bpy.props.StringProperty()

    def execute(self, context):
        obj = context.active_object
        side = self.side

        if self.limb == 'Arm':
            upper_opts = [f"CTRL_FK_upperarm{side}", f"CTRL_FK_Upperarm{side}"]
            lower_opts = [f"CTRL_FK_lowerarm{side}", f"CTRL_FK_Lowerarm{side}"]
            tip_opts = [f"CTRL_FK_hand{side}", f"CTRL_FK_Hand{side}"]
            ik_target_opts = [f"CTRL_IK_Hand{side}", f"CTRL_IK_hand{side}"]
            pole_target_opts = [f"CTRL_Pole_Arm{side}", f"CTRL_Pole_arm{side}"]
            tweak_names = [f"CTRL_Tweak_Upper_Arm{side}", f"CTRL_Tweak_Mid_Arm{side}", f"CTRL_Tweak_End_Arm{side}"]
            ball_opts = []
        else:
            upper_opts = [f"CTRL_FK_thigh{side}", f"CTRL_FK_Thigh{side}"]
            lower_opts = [f"CTRL_FK_calf{side}", f"CTRL_FK_Calf{side}"]
            tip_opts = [f"CTRL_FK_foot{side}", f"CTRL_FK_Foot{side}"]
            ik_target_opts = [f"CTRL_IK_Foot{side}", f"CTRL_IK_foot{side}"]
            pole_target_opts = [f"CTRL_Pole_Leg{side}", f"CTRL_Pole_leg{side}"]
            tweak_names = [f"CTRL_Tweak_Upper_Leg{side}", f"CTRL_Tweak_Mid_Leg{side}", f"CTRL_Tweak_End_Leg{side}"]
            ball_opts = [f"CTRL_FK_Ball{side}", f"CTRL_FK_ball{side}"]

        res_upper = next((core_framework.find_bone_name(obj, n) for n in upper_opts if core_framework.find_bone_name(obj, n)), None)
        res_lower = next((core_framework.find_bone_name(obj, n) for n in lower_opts if core_framework.find_bone_name(obj, n)), None)
        res_tip = next((core_framework.find_bone_name(obj, n) for n in tip_opts if core_framework.find_bone_name(obj, n)), None)
        res_ik = next((core_framework.find_bone_name(obj, n) for n in ik_target_opts if core_framework.find_bone_name(obj, n)), None)
        res_pole = next((core_framework.find_bone_name(obj, n) for n in pole_target_opts if core_framework.find_bone_name(obj, n)), None)
        res_ball = next((core_framework.find_bone_name(obj, n) for n in ball_opts if core_framework.find_bone_name(obj, n)), None)

        if not all([res_upper, res_lower, res_tip, res_ik, res_pole]):
            return {'CANCELLED'}

        # 1. Reset tweak offsets
        for twk in tweak_names:
            twk_res = core_framework.find_bone_name(obj, twk)
            if twk_res and twk_res in obj.pose.bones:
                obj.pose.bones[twk_res].location = (0.0, 0.0, 0.0)

        # 2. Reset reverse foot settings on CTRL_Settings to eliminate active pivot offsets
        settings_res = core_framework.find_bone_name(obj, f"CTRL_Settings_{self.limb}{side}")
        if settings_res:
            p_settings = obj.pose.bones[settings_res]
            for prop in ("Foot_Roll", "Bank", "Heel_Twist", "Toe_Twist"):
                if prop in p_settings:
                    p_settings[prop] = 0.0

        context.view_layer.update()
        context.evaluated_depsgraph_get().update()

        p_upper = obj.pose.bones[res_upper]
        p_lower = obj.pose.bones[res_lower]
        p_tip = obj.pose.bones[res_tip]
        p_ik = obj.pose.bones[res_ik]
        p_pole = obj.pose.bones[res_pole]

        # 3. Snap IK Target accounting for edit-bone rest orientation deltas
        # rest_offset = rest_ik_target^-1 @ rest_tip
        b_ik_rest = p_ik.bone.matrix_local
        b_tip_rest = p_tip.bone.matrix_local
        rest_offset = b_ik_rest.inverted() @ b_tip_rest

        p_ik.matrix = p_tip.matrix @ rest_offset.inverted()
        context.view_layer.update()

        # 4. Extract Evaluated Positions (Armature Space)
        v_upper = p_upper.matrix.translation
        v_lower = p_lower.matrix.translation
        v_tip = p_tip.matrix.translation

        # 5. Orthogonal Bend Vector Calculation
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
            if self.limb == 'Leg':
                pole_dir = (p_upper.matrix.to_3x3() @ mathutils.Vector((0.0, 1.0, 0.0))).normalized()
            else:
                pole_dir = (p_upper.matrix.to_3x3() @ mathutils.Vector((0.0, -1.0, 0.0))).normalized()

        arm_len = (v_lower - v_upper).length + (v_tip - v_lower).length
        pole_dist = arm_len * 0.8
        p_pole.matrix.translation = v_lower + (pole_dir * pole_dist)
        context.view_layer.update()

        # 6. Switch IK/FK Slider to IK Mode (1.0)
        if settings_res:
            obj.pose.bones[settings_res]["IK_FK"] = 1.0

        force_viewport_update(context)
        print("snap_ik_to_fk - FINISHED!")
        return {'FINISHED'}


# ==============================================================================
# 2. EXPORT PIPELINE
# ==============================================================================

class RIG_OT_bake_and_export_unity(bpy.types.Operator):
    """Bakes DEF bones and exports a clean FBX for Unity."""
    bl_idname = "rig.bake_and_export_unity"
    bl_label = "Export to Unity (DEF only)"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Active object is not an armature.")
            return {'CANCELLED'}

        bpy.ops.ed.undo_push(message="Pre-Export State")

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        for child in obj.children:
            if child.type == 'MESH':
                child.select_set(True)

        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='POSE')
        bpy.ops.pose.select_all(action='DESELECT')

        has_def_bones = False
        for pbone in obj.pose.bones:
            if pbone.name.startswith("DEF"):
                if hasattr(pbone.bone, "select_set"):
                    pbone.bone.select_set(True)
                else:
                    pbone.bone.select = True
                has_def_bones = True

        if not has_def_bones:
            self.report({'ERROR'}, "No DEF bones found to export.")
            bpy.ops.ed.undo()
            return {'CANCELLED'}

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

        bpy.ops.export_scene.fbx(
            filepath=self.filepath,
            use_selection=True,
            object_types={'ARMATURE', 'MESH'},
            use_armature_deform_only=True,
            add_leaf_bones=False,
            bake_anim=True,
            bake_anim_use_nla_strips=True,
            bake_anim_use_all_actions=True,
            bake_anim_force_startend_keying=True,
            bake_anim_step=1.0,
            bake_anim_simplify_factor=1.0
        )

        bpy.ops.ed.undo()
        self.report({'INFO'}, f"Successfully exported to {self.filepath}")

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

def resolve_chain_settings_bone(obj, active_bone):
    """
    Finds the master settings bone referenced directly by the active control.
    """
    if not active_bone:
        return None

    # Check for linked settings bone property
    settings_name = active_bone.get("_settings_bone") or active_bone.get("settings_bone")
    if settings_name:
        resolved_name = core_framework.find_bone_name(obj, str(settings_name))
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
            if "IK_FK" in settings_bone:
                # Infer limb/side from bone name for operator properties
                s_name = settings_bone.name
                side = ".L" if ".l" in s_name.lower() or "_l" in s_name.lower() else (".R" if ".r" in s_name.lower() or "_r" in s_name.lower() else "")
                limb = "Leg" if any(k in s_name.lower() for k in ("leg", "foot")) else "Arm"

                row = layout.row(align=True)
                op_fk_to_ik = row.operator("rig.snap_fk_to_ik", text="Snap FK -> IK")
                op_fk_to_ik.side = side
                op_fk_to_ik.limb = limb

                op_ik_to_fk = row.operator("rig.snap_ik_to_fk", text="Snap IK -> FK")
                op_ik_to_fk.side = side
                op_ik_to_fk.limb = limb

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