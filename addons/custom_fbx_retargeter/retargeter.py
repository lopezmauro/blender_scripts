import bpy
import json
import os
from mathutils import Matrix, Quaternion, Vector
from bpy_extras.io_utils import ImportHelper, ExportHelper

from .fbx_utils import import_fbx_to_armature


IS_EVALUATING = False


# -------------------------------------------------------------------
# 1. Hierarchy & Transform Evaluation Math
# -------------------------------------------------------------------

def get_bone_depth(armature_obj, bone_name):
    """Calculates parent hierarchy depth for sorting."""
    bone = armature_obj.data.bones.get(bone_name)
    depth = 0
    while bone and bone.parent:
        depth += 1
        bone = bone.parent
    return depth


def evaluate_single_bone(item, src_obj, tgt_obj, insert_keys=False, frame=1):
    """Solves world orientation delta and hierarchy-inverted M_basis."""
    src_pb = src_obj.pose.bones.get(item.source_bone)
    tgt_pb = tgt_obj.pose.bones.get(item.target_bone)

    if not src_pb or not tgt_pb:
        return

    # 1. Orientation Delta Solve
    if item.rot_space == 'WORLD':
        q_src_tpose = Quaternion(item.src_tpose_quat)
        q_tgt_tpose = Quaternion(item.tgt_tpose_quat)
        q_src_cur = (src_obj.matrix_world @ src_pb.matrix).to_quaternion()

        delta_q = q_src_cur @ q_src_tpose.inverted()
        desired_world_rot = delta_q @ q_tgt_tpose
    else:
        desired_world_rot = (tgt_obj.matrix_world @ tgt_pb.matrix).to_quaternion()

    # 2. Position Delta Solve
    if item.trans_space == 'WORLD':
        offset_pos = Vector(item.offset_pos)
        desired_world_pos = (src_obj.matrix_world @ src_pb.matrix.translation) + offset_pos
    else:
        if tgt_pb.parent:
            m_p_pose = tgt_pb.parent.matrix
            m_p_rest = tgt_pb.parent.bone.matrix_local
            m_c_rest = tgt_pb.bone.matrix_local
            desired_world_pos = (tgt_obj.matrix_world @ (m_p_pose @ m_p_rest.inverted() @ m_c_rest)).translation
        else:
            desired_world_pos = (tgt_obj.matrix_world @ tgt_pb.bone.matrix_local).translation

    # 3. Solve Exact Local Basis Matrix
    m_desired_world = Matrix.Translation(desired_world_pos) @ desired_world_rot.to_matrix().to_4x4()
    m_desired_pose = tgt_obj.matrix_world.inverted() @ m_desired_world

    if tgt_pb.parent:
        m_p_pose = tgt_pb.parent.matrix
        m_p_rest = tgt_pb.parent.bone.matrix_local
        m_c_rest = tgt_pb.bone.matrix_local
        m_basis = m_c_rest.inverted() @ m_p_rest @ m_p_pose.inverted() @ m_desired_pose
    else:
        m_basis = tgt_pb.bone.matrix_local.inverted() @ m_desired_pose

    # 4. Apply Transforms to Pose Bone
    if item.rot_space == 'WORLD':
        q_basis = m_basis.to_quaternion()
        if tgt_pb.rotation_mode == 'QUATERNION':
            tgt_pb.rotation_quaternion = q_basis
            if insert_keys:
                tgt_pb.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        elif tgt_pb.rotation_mode == 'AXIS_ANGLE':
            tgt_pb.rotation_axis_angle = (q_basis.angle, q_basis.axis.x, q_basis.axis.y, q_basis.axis.z)
            if insert_keys:
                tgt_pb.keyframe_insert(data_path="rotation_axis_angle", frame=frame)
        else:
            tgt_pb.rotation_euler = q_basis.to_euler(tgt_pb.rotation_mode)
            if insert_keys:
                tgt_pb.keyframe_insert(data_path="rotation_euler", frame=frame)

    if item.trans_space == 'WORLD':
        tgt_pb.location = m_basis.translation
        if insert_keys:
            tgt_pb.keyframe_insert(data_path="location", frame=frame)
    elif item.trans_space == 'NONE' and not insert_keys:
        tgt_pb.location = Vector((0.0, 0.0, 0.0))


def evaluate_retarget_pose(scene, depsgraph=None):
    """Viewport frame callback for live preview."""
    global IS_EVALUATING
    if IS_EVALUATING:
        return

    settings = scene.retarget_settings
    src_obj = settings.source_armature
    tgt_obj = settings.target_armature

    if not src_obj or not tgt_obj or not settings.live_preview:
        return

    IS_EVALUATING = True
    try:
        # Sort items by hierarchy so parents update before child bones
        sorted_mappings = sorted(
            [m for m in settings.mappings if m.target_bone],
            key=lambda item: get_bone_depth(tgt_obj, item.target_bone)
        )
        for item in sorted_mappings:
            evaluate_single_bone(item, src_obj, tgt_obj, insert_keys=False)
            tgt_obj.update_tag(refresh={'DATA'})
    finally:
        IS_EVALUATING = False


def update_mapping_property(self, context):
    if context.scene.retarget_settings.live_preview:
        evaluate_retarget_pose(context.scene)
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def toggle_live_preview(self, context):
    scene = context.scene
    settings = scene.retarget_settings

    if settings.live_preview:
        if evaluate_retarget_pose not in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.append(evaluate_retarget_pose)
        evaluate_retarget_pose(scene)
    else:
        if evaluate_retarget_pose in bpy.app.handlers.frame_change_post:
            bpy.app.handlers.frame_change_post.remove(evaluate_retarget_pose)

        tgt_obj = settings.target_armature
        if tgt_obj and tgt_obj.pose:
            for pb in tgt_obj.pose.bones:
                pb.location = Vector((0.0, 0.0, 0.0))
                pb.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
                pb.rotation_euler = (0.0, 0.0, 0.0)
                pb.scale = Vector((1.0, 1.0, 1.0))

    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


# -------------------------------------------------------------------
# 2. Data Model
# -------------------------------------------------------------------

class RETARGET_BoneMappingItem(bpy.types.PropertyGroup):
    source_bone: bpy.props.StringProperty(name="Source Joint", default="")
    target_bone: bpy.props.StringProperty(name="Target Bone", default="")
    trans_space: bpy.props.EnumProperty(
        name="Translation Space",
        items=[('NONE', "None", ""), ('LOCAL', "Local", ""), ('WORLD', "World", "")],
        default='NONE',
        update=update_mapping_property
    )
    rot_space: bpy.props.EnumProperty(
        name="Rotation Space",
        items=[('NONE', "None", ""), ('LOCAL', "Local", ""), ('WORLD', "World", "")],
        default='WORLD',
        update=update_mapping_property
    )
    src_tpose_quat: bpy.props.FloatVectorProperty(size=4, default=(1.0, 0.0, 0.0, 0.0))
    tgt_tpose_quat: bpy.props.FloatVectorProperty(size=4, default=(1.0, 0.0, 0.0, 0.0))
    offset_pos: bpy.props.FloatVectorProperty(size=3, default=(0.0, 0.0, 0.0))


class RETARGET_Settings(bpy.types.PropertyGroup):
    source_armature: bpy.props.PointerProperty(
        name="Source Rig",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE'
    )
    target_armature: bpy.props.PointerProperty(
        name="Target Rig",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'ARMATURE'
    )
    mappings: bpy.props.CollectionProperty(type=RETARGET_BoneMappingItem)
    active_mapping_index: bpy.props.IntProperty(name="Active Index", default=0)
    live_preview: bpy.props.BoolProperty(
        name="Live Preview",
        default=False,
        update=toggle_live_preview
    )
    # Adjustable column width properties
    col_src_width: bpy.props.FloatProperty(
        name="Source Width",
        description="Width proportion for Source Joint column",
        default=0.36,
        min=0.15,
        max=0.55,
        subtype='PERCENTAGE'
    )
    col_tgt_width: bpy.props.FloatProperty(
        name="Target Width",
        description="Width proportion for Target Control column",
        default=0.36,
        min=0.15,
        max=0.55,
        subtype='PERCENTAGE'
    )
    show_col_settings: bpy.props.BoolProperty(
        name="Show Column Width Controls",
        default=False
    )


# -------------------------------------------------------------------
# 3. Calibration & JSON I/O Operators
# -------------------------------------------------------------------

class RETARGET_OT_CalibrateTPose(bpy.types.Operator):
    """Calibrate base T-pose orientations from current viewport pose"""
    bl_idname = "retarget.calibrate_tpose"
    bl_label = "Calibrate T-Pose Offsets"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.retarget_settings
        src_obj = settings.source_armature
        tgt_obj = settings.target_armature

        if not src_obj or not tgt_obj:
            self.report({'ERROR'}, "Select both Source and Target armatures first.")
            return {'CANCELLED'}

        count = 0
        for item in settings.mappings:
            if not item.target_bone:
                continue

            src_pb = src_obj.pose.bones.get(item.source_bone)
            tgt_pb = tgt_obj.pose.bones.get(item.target_bone)

            if not src_pb or not tgt_pb:
                continue

            q_src = (src_obj.matrix_world @ src_pb.matrix).to_quaternion()
            q_tgt = (tgt_obj.matrix_world @ tgt_pb.matrix).to_quaternion()
            src_pos = src_obj.matrix_world @ src_pb.matrix.translation
            tgt_pos = tgt_obj.matrix_world @ tgt_pb.matrix.translation

            item.src_tpose_quat = (q_src.w, q_src.x, q_src.y, q_src.z)
            item.tgt_tpose_quat = (q_tgt.w, q_tgt.x, q_tgt.y, q_tgt.z)
            item.offset_pos = tgt_pos - src_pos
            count += 1

        self.report({'INFO'}, f"Calibrated T-pose basis for {count} bones.")
        return {'FINISHED'}


class RETARGET_OT_ExportJSON(bpy.types.Operator, ExportHelper):
    """Export bone mappings and T-pose world quaternions to a JSON file"""
    bl_idname = "retarget.export_json"
    bl_label = "Export Mapping JSON"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.retarget_settings
        data = {
            "source_armature": settings.source_armature.name if settings.source_armature else "",
            "target_armature": settings.target_armature.name if settings.target_armature else "",
            "mappings": [
                {
                    "source_bone": item.source_bone,
                    "target_bone": item.target_bone,
                    "trans_space": item.trans_space,
                    "rot_space": item.rot_space,
                    "src_tpose_quat": list(item.src_tpose_quat),
                    "tgt_tpose_quat": list(item.tgt_tpose_quat),
                    "offset_pos": list(item.offset_pos)
                }
                for item in settings.mappings
            ]
        }
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

        self.report({'INFO'}, f"Saved mapping to {self.filepath}")
        return {'FINISHED'}


class RETARGET_OT_ImportJSON(bpy.types.Operator, ImportHelper):
    """Import bone mappings and T-pose world quaternions from a JSON file"""
    bl_idname = "retarget.import_json"
    bl_label = "Import Mapping JSON"
    filename_ext = ".json"
    filter_glob: bpy.props.StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        settings = context.scene.retarget_settings
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to load JSON: {e}")
            return {'CANCELLED'}

        settings.mappings.clear()
        for entry in data.get("mappings", []):
            item = settings.mappings.add()
            item.source_bone = entry.get("source_bone", "")
            item.target_bone = entry.get("target_bone", "")
            item.trans_space = entry.get("trans_space", "NONE")
            item.rot_space = entry.get("rot_space", "WORLD")
            item.src_tpose_quat = entry.get("src_tpose_quat", (1.0, 0.0, 0.0, 0.0))
            item.tgt_tpose_quat = entry.get("tgt_tpose_quat", (1.0, 0.0, 0.0, 0.0))
            item.offset_pos = entry.get("offset_pos", (0.0, 0.0, 0.0))

        self.report({'INFO'}, f"Loaded {len(settings.mappings)} mapping entries.")
        return {'FINISHED'}


# -------------------------------------------------------------------
# 4. Pipeline Execution: FBX Loader, Retarget & NLA Strip Baker
# -------------------------------------------------------------------

class RETARGET_OT_ImportAndRetargetFBX(bpy.types.Operator, ImportHelper):
    """Import FBX to Source skeleton, solve transforms, and bake directly to Target NLA"""
    bl_idname = "retarget.import_and_bake_fbx"
    bl_label = "Select FBX & Retarget to NLA"
    filename_ext = ".fbx"
    filter_glob: bpy.props.StringProperty(default="*.fbx", options={'HIDDEN'})

    def execute(self, context):
        scene = context.scene
        settings = scene.retarget_settings
        src_obj = settings.source_armature
        tgt_obj = settings.target_armature

        if not src_obj or src_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select a valid Source Armature.")
            return {'CANCELLED'}

        if not tgt_obj or tgt_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select a valid Target Armature.")
            return {'CANCELLED'}

        if len(settings.mappings) == 0:
            self.report({'ERROR'}, "Mapping list is empty. Load a JSON configuration first.")
            return {'CANCELLED'}

        was_live = settings.live_preview
        if was_live:
            settings.live_preview = False

        orig_frame = scene.frame_current

        # 1. Import and synchronize FBX animation on the source skeleton
        try:
            source_action = import_fbx_to_armature(self.filepath, src_obj.name)
        except Exception as err:
            self.report({'ERROR'}, f"FBX import failed: {err}")
            if was_live:
                settings.live_preview = True
            return {'CANCELLED'}

        take_name = bpy.path.display_name_from_filepath(self.filepath)
        start_frame = int(source_action.frame_range[0])
        end_frame = int(source_action.frame_range[1])

        # 2. Prepare new Target Action datablock
        target_action_name = f"{take_name}_Retargeted"
        target_action = bpy.data.actions.new(name=target_action_name)
        target_action.use_fake_user = True

        if not tgt_obj.animation_data:
            tgt_obj.animation_data_create()
        tgt_obj.animation_data.action = target_action

        # Blender 5.1 Slotted Action binding
        if hasattr(tgt_obj.animation_data, "action_slot") and hasattr(target_action, "slots"):
            if target_action.slots:
                tgt_obj.animation_data.action_slot = target_action.slots[0]

        # 3. Sort bones by hierarchy depth
        sorted_mappings = sorted(
            [m for m in settings.mappings if m.target_bone],
            key=lambda item: get_bone_depth(tgt_obj, item.target_bone)
        )

        # 4. Frame-by-Frame Transfer Loop
        for frame in range(start_frame, end_frame + 1):
            scene.frame_set(frame)
            context.view_layer.update()

            for item in sorted_mappings:
                evaluate_single_bone(item, src_obj, tgt_obj, insert_keys=True, frame=frame)
                tgt_obj.update_tag(refresh={'DATA'})
                context.view_layer.update()

        # 5. Push baked Target Action to an NLA track
        tgt_tracks = tgt_obj.animation_data.nla_tracks
        tgt_track = tgt_tracks.new()
        tgt_track.name =take_name
        tgt_track.strips.new(
            name=target_action_name,
            start=start_frame,
            action=target_action
        )
        tgt_obj.animation_data.action = None

        # 6. Push Source Action to an NLA track
        src_tracks = src_obj.animation_data.nla_tracks
        src_track = src_tracks.new()
        src_track.name = f"FBX_{take_name}"
        src_track.strips.new(
            name=f"{take_name}_Source",
            start=start_frame,
            action=source_action
        )
        src_obj.animation_data.action = None

        scene.frame_set(orig_frame)
        if was_live:
            settings.live_preview = True

        self.report({'INFO'}, f"Retargeted '{take_name}' to NLA ({start_frame} -> {end_frame}).")
        return {'FINISHED'}


# -------------------------------------------------------------------
# 5. UI Setup & Operators
# -------------------------------------------------------------------

class RETARGET_OT_PopulateSourceBones(bpy.types.Operator):
    bl_idname = "retarget.populate_source_bones"
    bl_label = "Read Source Bones"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.retarget_settings
        src_obj = settings.source_armature
        tgt_obj = settings.target_armature

        if not src_obj or src_obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select a valid Source Armature.")
            return {'CANCELLED'}

        settings.mappings.clear()
        target_bone_names = set(tgt_obj.data.bones.keys()) if tgt_obj and tgt_obj.type == 'ARMATURE' else set()

        for bone in src_obj.data.bones:
            item = settings.mappings.add()
            item.source_bone = bone.name
            item.target_bone = bone.name if bone.name in target_bone_names else ""

            if any(k in bone.name.lower() for k in ("hip", "root", "pelvis")):
                item.trans_space = 'WORLD'
                item.rot_space = 'WORLD'
            else:
                item.trans_space = 'NONE'
                item.rot_space = 'WORLD'

        return {'FINISHED'}


class RETARGET_OT_AssignSelectedTarget(bpy.types.Operator):
    bl_idname = "retarget.assign_selected_target"
    bl_label = "Assign Selected Bone"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.retarget_settings
        index = settings.active_mapping_index
        if not (0 <= index < len(settings.mappings)):
            return {'CANCELLED'}

        active_pbone = context.active_pose_bone
        if not active_pbone:
            self.report({'WARNING'}, "Select a bone in Pose Mode on the Target Rig.")
            return {'CANCELLED'}

        settings.mappings[index].target_bone = active_pbone.name
        return {'FINISHED'}


class RETARGET_OT_ClearMappings(bpy.types.Operator):
    bl_idname = "retarget.clear_mappings"
    bl_label = "Clear All"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        context.scene.retarget_settings.mappings.clear()
        return {'FINISHED'}

def draw_mapping_columns(layout, settings, is_header=False, item=None, tgt_obj=None):
    """Draws four aligned table columns using relative percentage splits."""
    w_src = min(max(settings.col_src_width, 0.15), 0.55)
    w_tgt = min(max(settings.col_tgt_width, 0.15), 0.55)

    # Ensure Pos and Rot have at least 20% combined width
    if w_src + w_tgt > 0.80:
        scale = 0.80 / (w_src + w_tgt)
        w_src *= scale
        w_tgt *= scale

    # Column 1: Source Joint
    split1 = layout.split(factor=w_src, align=True)
    col_src = split1.column(align=True)

    # Column 2: Target Control
    rem1 = 1.0 - w_src
    fac2 = w_tgt / rem1
    split2 = split1.split(factor=fac2, align=True)
    col_tgt = split2.column(align=True)

    # Columns 3 & 4: Pos and Rot (split remaining space 50/50)
    split3 = split2.split(factor=0.5, align=True)
    col_trans = split3.column(align=True)
    col_rot = split3.column(align=True)

    if is_header:
        col_src.label(text="Source Joint")
        col_tgt.label(text="Target Control")
        col_trans.label(text="Pos")
        col_rot.label(text="Rot")
    else:
        col_src.label(text=item.source_bone, icon='BONE_DATA')
        if tgt_obj and tgt_obj.type == 'ARMATURE':
            col_tgt.prop_search(item, "target_bone", tgt_obj.data, "bones", text="")
        else:
            col_tgt.prop(item, "target_bone", text="")
        col_trans.prop(item, "trans_space", text="")
        col_rot.prop(item, "rot_space", text="")


class RETARGET_UL_BoneMappingList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        settings = context.scene.retarget_settings
        tgt_obj = settings.target_armature

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            draw_mapping_columns(row, settings, is_header=False, item=item, tgt_obj=tgt_obj)


class RETARGET_PT_MainPanel(bpy.types.Panel):
    bl_label = "FBX Retargeter"
    bl_idname = "RETARGET_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Retarget'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.retarget_settings

        # 1. Armatures
        box_rigs = layout.box()
        box_rigs.label(text="Armatures", icon='ARMATURE_DATA')
        box_rigs.prop(settings, "source_armature")
        box_rigs.prop(settings, "target_armature")

        row_pop = layout.row(align=True)
        row_pop.operator("retarget.populate_source_bones", icon='IMPORT')
        row_pop.operator("retarget.clear_mappings", icon='TRASH')

        # 2. Joint Mapping List Header & Controls
        row_header_top = layout.row(align=True)
        row_header_top.label(text="Joint Mappings:", icon='SOLO_ON')
        row_header_top.prop(settings, "show_col_settings", text="", icon='PREFERENCES')

        if settings.show_col_settings:
            box_cfg = layout.box()
            col_cfg = box_cfg.column(align=True)
            col_cfg.label(text="Table Column Widths:", icon='ARROW_LEFTRIGHT')
            col_cfg.prop(settings, "col_src_width", text="Source Joint", slider=True)
            col_cfg.prop(settings, "col_tgt_width", text="Target Control", slider=True)

        # Table Column Header Row (with insets to match UIList inner borders & scrollbar)
        row_head = layout.row(align=True)
        row_head.separator(factor=0.6)
        draw_mapping_columns(row_head, settings, is_header=True)
        row_head.separator(factor=1.4)

        layout.template_list(
            "RETARGET_UL_BoneMappingList", "",
            settings, "mappings",
            settings, "active_mapping_index",
            rows=7
        )

        row_assign = layout.row(align=True)
        row_assign.operator("retarget.assign_selected_target", icon='RESTRICT_SELECT_OFF')
        row_assign.operator("retarget.mirror_mappings", text="Mirror L -> R", icon='MOD_MIRROR')

        # 3. Calibration & Config
        box_calib = layout.box()
        box_calib.label(text="1. Calibration & Config", icon='POSE_HLT')
        box_calib.operator("retarget.calibrate_tpose", icon='SNAP_ON')
        
        row_io = box_calib.row(align=True)
        row_io.operator("retarget.export_json", text="Export JSON", icon='EXPORT')
        row_io.operator("retarget.import_json", text="Import JSON", icon='IMPORT')
        box_calib.prop(settings, "live_preview", toggle=True, icon='PLAY')

        # 4. Retarget Animation
        box_bake = layout.box()
        box_bake.label(text="2. Animation Retarget", icon='NLA')
        box_bake.operator("retarget.import_and_bake_fbx", text="Import FBX & Bake to NLA", icon='ACTION')


def get_mirrored_l_to_r(name: str) -> str | None:
    """Returns the Right-side counterpart of a Left-side bone name, or None."""
    if not name:
        return None

    # Suffixes (.L, _L, .l, _l, _left, etc.)
    if name.endswith(".L"):
        return name[:-2] + ".R"
    if name.endswith("_L"):
        return name[:-2] + "_R"
    if name.endswith(".l"):
        return name[:-2] + ".r"
    if name.endswith("_l"):
        return name[:-2] + "_r"
    if name.endswith("_left"):
        return name[:-5] + "_right"
    if name.endswith("_Left"):
        return name[:-5] + "_Right"
    if name.endswith(".left"):
        return name[:-5] + ".right"

    # Prefixes (l_, L_, left_, etc.)
    if name.startswith("l_"):
        return "r_" + name[2:]
    if name.startswith("L_"):
        return "R_" + name[2:]
    if name.startswith("left_"):
        return "right_" + name[5:]
    if name.startswith("Left_"):
        return "Right_" + name[5:]
    if name.startswith("l."):
        return "r." + name[2:]
    if name.startswith("L."):
        return "R." + name[2:]

    # Infixes (_l_, _L_, etc.)
    if "_l_" in name:
        return name.replace("_l_", "_r_")
    if "_L_" in name:
        return name.replace("_L_", "_R_")
    if ".l." in name:
        return name.replace(".l.", ".r.")
    if ".L." in name:
        return name.replace(".L.", ".R.")
    if "_left_" in name:
        return name.replace("_left_", "_right_")
    if "_Left_" in name:
        return name.replace("_Left_", "_Right_")

    return None


class RETARGET_OT_MirrorAssignments(bpy.types.Operator):
    """Mirror Left-side bone mappings to corresponding Right-side bones"""
    bl_idname = "retarget.mirror_mappings"
    bl_label = "Mirror Mappings (L -> R)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.retarget_settings
        tgt_obj = settings.target_armature

        map_by_src = {item.source_bone: item for item in settings.mappings}
        mirrored_count = 0
        missing_targets = []

        for item in list(settings.mappings):
            if not item.target_bone:
                continue

            r_src = get_mirrored_l_to_r(item.source_bone)
            r_tgt = get_mirrored_l_to_r(item.target_bone)

            if not r_src or not r_tgt:
                continue

            target_item = map_by_src.get(r_src)
            if not target_item:
                continue

            # Verify target bone exists on target armature if assigned
            if tgt_obj and tgt_obj.type == 'ARMATURE':
                if r_tgt not in tgt_obj.data.bones:
                    missing_targets.append(r_tgt)
                    continue

            target_item.target_bone = r_tgt
            target_item.trans_space = item.trans_space
            target_item.rot_space = item.rot_space
            mirrored_count += 1

        if missing_targets:
            self.report({'WARNING'}, f"Mirrored {mirrored_count} bones. {len(missing_targets)} target bones missing on rig.")
        else:
            self.report({'INFO'}, f"Successfully mirrored {mirrored_count} bone mappings (L -> R).")

        return {'FINISHED'}


# -------------------------------------------------------------------
# 6. Registration
# -------------------------------------------------------------------

classes = (
    RETARGET_BoneMappingItem,
    RETARGET_Settings,
    RETARGET_OT_CalibrateTPose,
    RETARGET_OT_ExportJSON,
    RETARGET_OT_ImportJSON,
    RETARGET_OT_ImportAndRetargetFBX,
    RETARGET_OT_PopulateSourceBones,
    RETARGET_OT_AssignSelectedTarget,
    RETARGET_OT_MirrorAssignments,
    RETARGET_OT_ClearMappings,
    RETARGET_UL_BoneMappingList,
    RETARGET_PT_MainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.retarget_settings = bpy.props.PointerProperty(type=RETARGET_Settings)

def unregister():
    if evaluate_retarget_pose in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(evaluate_retarget_pose)
    del bpy.types.Scene.retarget_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()