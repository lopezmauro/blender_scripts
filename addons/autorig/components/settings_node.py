import mathutils
from typing import List
from .. import core_framework, base_component, naming

@base_component.register_component("SettingsNode")
class SettingsNodeComponent(base_component.BaseRigComponent):
    """
    Creates a standalone control bone designed to hold custom properties (drivers).
    It does not deform geometry or constrain any target bones.
    """
    def validate(self) -> List[str]:
        return []

    def build_edit(self) -> None:
        parent_bone = self.resolve_parent_socket()
        collection = self.params.get("collection", "CTRL_Main")
        custom_name = self.params.get("custom_ctrl_name")
        ctrl_name = custom_name if custom_name else self.format_name(role=naming.ROLE_CTRL, side="C")
        edit_bones = self.armature_obj.data.edit_bones
        if parent_bone and parent_bone in edit_bones:
            head_pos = edit_bones[parent_bone].head.copy()
        else:
            head_pos = mathutils.Vector((0.0, 0.0, 0.0))
        
        offset_val = self.params.get("offset", [0.0, 0.0, 0.15])
        offset = mathutils.Vector(offset_val)

        created_ctrl = core_framework.create_bone(
            self.armature_obj,
            ctrl_name,
            head=head_pos + offset,
            tail=head_pos + offset + mathutils.Vector((0.0, 0.0, 0.05)),
            parent_name=parent_bone,
            collection_name=collection
        )
        
        self.ctrl_name = created_ctrl
        self.register_output("main", created_ctrl)
        self.register_control(created_ctrl)

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        shapes = self.context.shapes
        scale = self.params.get("widget_scale", 0.35)
        shape_type = self.params.get("widget_shape", "Gear")
        
        p_ctrl = pose_bones[self.ctrl_name]
        core_framework.assign_bone_shape(
            p_ctrl, shapes.get(shape_type, shapes['Gear']), scale=(scale, scale, scale)
        )
        
        if self.params.get("lock_transforms", True):
            p_ctrl.lock_location = (True, True, True)
            p_ctrl.lock_rotation = (True, True, True)
            p_ctrl.lock_scale = (True, True, True)