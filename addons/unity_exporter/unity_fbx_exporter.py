import bpy
import os


def get_deform_bones(armature_obj):
    """Returns a list of pose bones designated for deformation."""
    deform_bones = []
    for pbone in armature_obj.pose.bones:
        is_def = (
            pbone.bone.use_deform
            or "_def." in pbone.name.lower()
            or pbone.name.startswith("DEF")
        )
        if is_def:
            deform_bones.append(pbone)
    return deform_bones


def set_bone_selection(pbone, state: bool = True):
    """Safely selects or deselects a pose bone across Blender versions."""
    # Blender 4.0+ stores pose selection on PoseBone
    if hasattr(pbone, "select"):
        pbone.select = state
    elif hasattr(pbone, "select_set"):
        pbone.select_set(state)
    # Blender 3.6 and older stored pose selection on Bone
    elif hasattr(pbone.bone, "select"):
        pbone.bone.select = state
    elif hasattr(pbone.bone, "select_set"):
        pbone.bone.select_set(state)


def select_deform_bones_only(armature_obj):
    """Selects only the deforming bones in pose mode."""
    bpy.ops.pose.select_all(action='DESELECT')
    for pbone in get_deform_bones(armature_obj):
        set_bone_selection(pbone, True)


class UNITY_OT_export_base_mesh(bpy.types.Operator):
    """Exports the base armature in rest pose with all child meshes (no animations)."""
    bl_idname = "unity.export_base_mesh"
    bl_label = "Export Base Model (T-Pose)"
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(
        name="File Path",
        subtype='FILE_PATH',
        default="base_model.fbx"
    )

    def execute(self, context):
        obj = context.active_object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Active object must be an armature.")
            return {'CANCELLED'}

        prev_mode = obj.mode
        prev_pose_position = obj.data.pose_position

        # 1. Switch armature to rest pose
        obj.data.pose_position = 'REST'
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')

        # 2. Select armature and child meshes
        obj.select_set(True)
        for child in obj.children:
            if child.type == 'MESH':
                child.select_set(True)

        context.view_layer.objects.active = obj

        # 3. Export base model
        bpy.ops.export_scene.fbx(
            filepath=self.filepath,
            use_selection=True,
            object_types={'ARMATURE', 'MESH'},
            use_armature_deform_only=True,
            add_leaf_bones=False,
            bake_anim=False,
            apply_scale_options='FBX_SCALE_ALL'
        )

        # 4. Restore initial state
        obj.data.pose_position = prev_pose_position
        bpy.ops.object.mode_set(mode=prev_mode)

        self.report({'INFO'}, f"Base model exported: {self.filepath}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class UNITY_OT_export_nla_animations(bpy.types.Operator):
    """Bakes each NLA strip and exports individual animation FBXs without meshes."""
    bl_idname = "unity.export_nla_animations"
    bl_label = "Export NLA Clips"
    bl_options = {'REGISTER'}

    directory: bpy.props.StringProperty(
        name="Output Directory",
        subtype='DIR_PATH'
    )
    base_prefix: bpy.props.StringProperty(
        name="Base Name Prefix",
        description="Prefix before @. Defaults to armature name if left blank.",
        default=""
    )

    def execute(self, context):
        armature = context.active_object
        if not armature or armature.type != 'ARMATURE':
            self.report({'ERROR'}, "Active object must be an armature.")
            return {'CANCELLED'}

        anim_data = armature.animation_data
        if not anim_data or not anim_data.nla_tracks:
            self.report({'ERROR'}, "No NLA tracks found on the armature.")
            return {'CANCELLED'}

        prefix = self.base_prefix.strip() or armature.name
        export_dir = bpy.path.abspath(self.directory)
        os.makedirs(export_dir, exist_ok=True)

        prev_mode = armature.mode
        prev_active_action = anim_data.action

        # Collect unmuted tracks
        valid_tracks = [t for t in anim_data.nla_tracks if not t.mute]
        solo_states = {t: t.is_solo for t in anim_data.nla_tracks}

        exported_count = 0

        try:
            for track in valid_tracks:
                # Solo current track
                for t in anim_data.nla_tracks:
                    t.is_solo = (t == track)

                for strip in track.strips:
                    start_frame = int(strip.frame_start)
                    end_frame = int(strip.frame_end)
                    clip_name = strip.name.replace(" ", "_")

                    # Clear active action to prevent it from overriding the solo NLA strip
                    anim_data.action = None

                    # Select deform bones
                    bpy.ops.object.mode_set(mode='POSE')
                    select_deform_bones_only(armature)

                    # Bake visual transforms for the deform bones
                    bpy.ops.nla.bake(
                        frame_start=start_frame,
                        frame_end=end_frame,
                        step=1,
                        only_selected=True,
                        visual_keying=True,
                        clear_constraints=False,
                        clear_parents=False,
                        use_current_action=False,
                        bake_types={'POSE'}
                    )

                    baked_action = anim_data.action

                    # Select armature only (exclude meshes)
                    bpy.ops.object.mode_set(mode='OBJECT')
                    bpy.ops.object.select_all(action='DESELECT')
                    armature.select_set(True)
                    context.view_layer.objects.active = armature

                    # Export FBX using Unity '@' convention
                    out_filename = f"{prefix}@{clip_name}.fbx"
                    out_path = os.path.join(export_dir, out_filename)

                    bpy.ops.export_scene.fbx(
                        filepath=out_path,
                        use_selection=True,
                        object_types={'ARMATURE'},
                        use_armature_deform_only=True,
                        add_leaf_bones=False,
                        bake_anim=True,
                        bake_anim_use_nla_strips=False,
                        bake_anim_use_all_actions=False,
                        bake_anim_force_startend_keying=True,
                        bake_anim_step=1.0,
                        bake_anim_simplify_factor=0.0,
                        apply_scale_options='FBX_SCALE_ALL'
                    )

                    # Cleanup temporary baked action
                    anim_data.action = None
                    if baked_action:
                        bpy.data.actions.remove(baked_action)

                    exported_count += 1

        finally:
            # Restore NLA solo states and previous active action
            for t, state in solo_states.items():
                t.is_solo = state
            anim_data.action = prev_active_action
            bpy.ops.object.mode_set(mode=prev_mode)

        self.report({'INFO'}, f"Exported {exported_count} animation clips to {export_dir}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class UNITY_PT_export_panel(bpy.types.Panel):
    """UI Panel in the 3D Viewport Sidebar"""
    bl_label = "Unity Exporter"
    bl_idname = "UNITY_PT_export_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Unity Export'

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        if not obj or obj.type != 'ARMATURE':
            layout.label(text="Select an armature to export.", icon='INFO')
            return

        box_mesh = layout.box()
        box_mesh.label(text="Base Model (Mesh + Rig):", icon='MESH_DATA')
        box_mesh.operator("unity.export_base_mesh", text="Export Base FBX")

        box_anim = layout.box()
        box_anim.label(text="Animation Clips (NLA):", icon='ACTION')
        box_anim.operator("unity.export_nla_animations", text="Export All NLA Clips")


classes = (
    UNITY_OT_export_base_mesh,
    UNITY_OT_export_nla_animations,
    UNITY_PT_export_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)