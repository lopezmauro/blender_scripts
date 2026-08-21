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
    """Forces dependency graph re-evaluation and 3D Viewport redraw."""
    context.view_layer.update()
    dg = context.evaluated_depsgraph_get()
    dg.update()
    for area in context.screen.areas:
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
    """Matches CTRL_FK transforms to evaluated MCH_IK pose."""
    bl_idname = "rig.snap_fk_to_ik"
    bl_label = "Snap FK to IK"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.StringProperty()
    limb: bpy.props.StringProperty()

    def execute(self, context):
        obj = context.active_object
        side = self.side

        # Candidate names for uppercase and lowercase deform bone sources
        if self.limb == 'Arm':
            candidates = [
                ([f"CTRL_FK_upperarm{side}", f"CTRL_FK_Upperarm{side}"], [f"MCH_IK_upperarm{side}", f"MCH_IK_Upperarm{side}"]),
                ([f"CTRL_FK_lowerarm{side}", f"CTRL_FK_Lowerarm{side}"], [f"MCH_IK_lowerarm{side}", f"MCH_IK_Lowerarm{side}"]),
                ([f"CTRL_FK_hand{side}", f"CTRL_FK_Hand{side}"], [f"CTRL_IK_Hand{side}", f"CTRL_IK_hand{side}"])
            ]
            tweak_names = [f"CTRL_Tweak_Upper_Arm{side}", f"CTRL_Tweak_Mid_Arm{side}", f"CTRL_Tweak_End_Arm{side}"]
        else:
            candidates = [
                ([f"CTRL_FK_thigh{side}", f"CTRL_FK_Thigh{side}"], [f"MCH_IK_thigh{side}", f"MCH_IK_Thigh{side}"]),
                ([f"CTRL_FK_calf{side}", f"CTRL_FK_Calf{side}"], [f"MCH_IK_calf{side}", f"MCH_IK_Calf{side}"]),
                ([f"CTRL_FK_foot{side}", f"CTRL_FK_Foot{side}"], [f"CTRL_IK_Foot{side}", f"CTRL_IK_foot{side}"])
            ]
            tweak_names = [f"CTRL_Tweak_Upper_Leg{side}", f"CTRL_Tweak_Mid_Leg{side}", f"CTRL_Tweak_End_Leg{side}"]

        # Reset tweak offsets
        for twk in tweak_names:
            twk_res = core_framework.find_bone_name(obj, twk)
            if twk_res and twk_res in obj.pose.bones:
                obj.pose.bones[twk_res].location = (0.0, 0.0, 0.0)

        # Match matrix transforms in hierarchical order
        for fk_opts, mch_opts in candidates:
            fk_name_res = next((core_framework.find_bone_name(obj, n) for n in fk_opts if core_framework.find_bone_name(obj, n)), None)
            mch_name_res = next((core_framework.find_bone_name(obj, n) for n in mch_opts if core_framework.find_bone_name(obj, n)), None)

            if not fk_name_res or not mch_name_res:
                continue

            fk_bone = obj.pose.bones.get(fk_name_res)
            mch_bone = obj.pose.bones.get(mch_name_res)

            if fk_bone and mch_bone:
                fk_bone.matrix = mch_bone.matrix.copy()
                context.view_layer.update()

        settings_res = core_framework.find_bone_name(obj, f"CTRL_Settings_{self.limb}{side}")
        if settings_res:
            obj.pose.bones[settings_res]["IK_FK"] = 0.0

        force_viewport_update(context)
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
        else:
            upper_opts = [f"CTRL_FK_thigh{side}", f"CTRL_FK_Thigh{side}"]
            lower_opts = [f"CTRL_FK_calf{side}", f"CTRL_FK_Calf{side}"]
            tip_opts = [f"CTRL_FK_foot{side}", f"CTRL_FK_Foot{side}"]
            ik_target_opts = [f"CTRL_IK_Foot{side}", f"CTRL_IK_foot{side}"]
            pole_target_opts = [f"CTRL_Pole_Leg{side}", f"CTRL_Pole_leg{side}"]
            tweak_names = [f"CTRL_Tweak_Upper_Leg{side}", f"CTRL_Tweak_Mid_Leg{side}", f"CTRL_Tweak_End_Leg{side}"]

        res_upper = next((core_framework.find_bone_name(obj, n) for n in upper_opts if core_framework.find_bone_name(obj, n)), None)
        res_lower = next((core_framework.find_bone_name(obj, n) for n in lower_opts if core_framework.find_bone_name(obj, n)), None)
        res_tip = next((core_framework.find_bone_name(obj, n) for n in tip_opts if core_framework.find_bone_name(obj, n)), None)
        res_ik = next((core_framework.find_bone_name(obj, n) for n in ik_target_opts if core_framework.find_bone_name(obj, n)), None)
        res_pole = next((core_framework.find_bone_name(obj, n) for n in pole_target_opts if core_framework.find_bone_name(obj, n)), None)

        if not all([res_upper, res_lower, res_tip, res_ik, res_pole]):
            return {'CANCELLED'}

        # Reset tweak offsets
        for twk in tweak_names:
            twk_res = core_framework.find_bone_name(obj, twk)
            if twk_res and twk_res in obj.pose.bones:
                obj.pose.bones[twk_res].location = (0.0, 0.0, 0.0)

        p_upper = obj.pose.bones[res_upper]
        p_lower = obj.pose.bones[res_lower]
        p_tip = obj.pose.bones[res_tip]
        p_ik = obj.pose.bones[res_ik]
        p_pole = obj.pose.bones[res_pole]

        # 1. Snap IK Target orientation & position
        p_ik.matrix = p_tip.matrix.copy()
        context.view_layer.update()

        # 2. Extract Evaluated Positions (Armature Space)
        v_upper = p_upper.matrix.translation
        v_lower = p_lower.matrix.translation
        v_tip = p_tip.matrix.translation

        # 3. Orthogonal Bend Vector Calculation
        v_upper_lower = v_lower - v_upper
        v_lower_tip = v_tip - v_lower

        # Normal to the triangle formed by shoulder/hip, elbow/knee, and wrist/ankle
        plane_normal = v_upper_lower.cross(v_lower_tip)

        if plane_normal.length < 1e-4:
            # Fallback when limb is completely straight: derive from the bone's local Z-axis
            pole_dir = p_upper.matrix.to_3x3() @ mathutils.Vector((0.0, 0.0, 1.0 if self.limb == 'Leg' else -1.0))
        else:
            # Perpendicular vector pointing outward from the limb straight line
            limb_dir = (v_tip - v_upper).normalized()
            proj_point = v_upper + limb_dir * ((v_lower - v_upper).dot(limb_dir))
            pole_dir = (v_lower - proj_point)

        pole_dir = pole_dir.normalized()
        pole_dist = (v_upper_lower.length + v_lower_tip.length) * 0.5
        p_pole.matrix.translation = v_lower + (pole_dir * pole_dist)

        # 4. Switch IK/FK Slider
        settings_res = core_framework.find_bone_name(obj, f"CTRL_Settings_{self.limb}{side}")
        if settings_res:
            obj.pose.bones[settings_res]["IK_FK"] = 1.0

        force_viewport_update(context)
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

        # Space Switching UI
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

        # IK/FK Snapping UI
        limb = None
        side = None

        name_lower = name.lower()
        if any(k in name_lower for k in ("arm", "hand", "upperarm", "lowerarm", "clavicle")):
            limb = "Arm"
        elif any(k in name_lower for k in ("leg", "foot", "thigh", "calf", "hip")):
            limb = "Leg"

        if name_lower.endswith(".l") or name_lower.endswith("_l"):
            side = ".L"
        elif name_lower.endswith(".r") or name_lower.endswith("_r"):
            side = ".R"

        if limb and side:
            settings_name = f"CTRL_Settings_{limb}{side}"
            settings_res = core_framework.find_bone_name(obj, settings_name)

            if settings_res and "IK_FK" in obj.pose.bones[settings_res]:
                settings_bone = obj.pose.bones[settings_res]
                layout.label(text=f"{limb} {side} Snapping:", icon='CON_KINEMATIC')
                layout.prop(settings_bone, '["IK_FK"]', text="IK / FK Blend")

                row = layout.row(align=True)
                op_fk_to_ik = row.operator("rig.snap_fk_to_ik", text="Snap FK -> IK")
                op_fk_to_ik.side = side
                op_fk_to_ik.limb = limb

                op_ik_to_fk = row.operator("rig.snap_ik_to_fk", text="Snap IK -> FK")
                op_ik_to_fk.side = side
                op_ik_to_fk.limb = limb

        layout.separator()

        # Pipeline Export
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