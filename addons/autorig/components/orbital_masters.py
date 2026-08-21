import bpy
import mathutils
from typing import List
from blender_scripts.autorig import core_framework
from blender_scripts.autorig.base_component import BaseRigComponent, register_component

@register_component("OrbitalMasters")
class OrbitalMastersComponent(BaseRigComponent):
    """
    Creates inner and outer eye orbital master controls.
    """
    def validate(self) -> List[str]:
        errors = []
        for key in ("corner_out", "corner_in"):
            b_name = self.params.get(key)
            if not b_name or not core_framework.find_bone_name(self.armature_obj, b_name):
                errors.append(f"Orbital corner bone '{key}' ({b_name}) not found.")
        return errors

    def build_edit(self) -> None:
        edit_bones = self.armature_obj.data.edit_bones
        parent_socket = self.resolve_parent_socket()
        collection = self.params.get("collection", "CTRL_Face")
        side = self.params.get("side", "")

        out_def = core_framework.find_bone_name(self.armature_obj, self.params["corner_out"])
        in_def = core_framework.find_bone_name(self.armature_obj, self.params["corner_in"])

        pos_out = edit_bones[out_def].head.copy()
        pos_in = edit_bones[in_def].head.copy()

        ctrl_out = core_framework.create_bone(
            self.armature_obj, f"CTRL_Orbital_Corner_Out{side}",
            head=pos_out, tail=pos_out + mathutils.Vector((0.0, 0.0, 0.025)),
            parent_name=parent_socket, collection_name=collection
        )
        ctrl_in = core_framework.create_bone(
            self.armature_obj, f"CTRL_Orbital_Corner_In{side}",
            head=pos_in, tail=pos_in + mathutils.Vector((0.0, 0.0, 0.025)),
            parent_name=parent_socket, collection_name=collection
        )

        self.edit_data = {"ctrl_out": ctrl_out, "ctrl_in": ctrl_in}
        self.register_output("corner_out", ctrl_out)
        self.register_output("corner_in", ctrl_in)

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        shapes = self.context.shapes
        scale = self.params.get("widget_scale", 0.08)
        
        for k in ("ctrl_out", "ctrl_in"):
            ctrl_name = self.edit_data[k]
            core_framework.assign_bone_shape(
                pose_bones[ctrl_name], shapes['Box'], scale=(scale, scale, scale)
            )