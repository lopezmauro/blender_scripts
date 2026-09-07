import bpy
import mathutils
from typing import List, Tuple, Optional
from .. import core_framework, base_component, naming


@base_component.register_component("OrbitalMasters")
class OrbitalMastersComponent(base_component.BaseRigComponent):
    """
    Creates inner and outer eye orbital master controls.
    Positions the inner corner master at the average of the upper and lower eyelid tips.
    """
    def validate(self) -> List[str]:
        errors = []
        for key in ("corner_out", "corner_in"):
            b_name = self.params.get(key)
            if not b_name or not core_framework.find_bone_name(self.armature_obj, b_name):
                errors.append(f"Orbital corner bone '{key}' ({b_name}) not found.")
        
        corner_in_up = self.params.get("corner_in_up")
        if corner_in_up and not core_framework.find_bone_name(self.armature_obj, corner_in_up):
            errors.append(f"Orbital upper inner corner bone 'corner_in_up' ({corner_in_up}) not found.")

        return errors

    def build_edit(self) -> None:
        edit_bones = self.armature_obj.data.edit_bones
        parent_socket = self.resolve_parent_socket()
        collection = self.params.get("collection", "CTRL_Face")

        out_def = core_framework.find_bone_name(self.armature_obj, self.params["corner_out"])
        in_def_down = core_framework.find_bone_name(self.armature_obj, self.params["corner_in"])
        in_def_up_param = self.params.get("corner_in_up")
        in_def_up = core_framework.find_bone_name(self.armature_obj, in_def_up_param) if in_def_up_param else None

        # Derive normalized side from param or parse from corner deform bone
        comp_side = self.params.get("side")
        if comp_side is not None:
            side = naming.normalize_side(comp_side)
        else:
            _, side = naming.parse_bone_side(out_def)

        # Outer corner sits at the root (head) of bone 01
        pos_out = edit_bones[out_def].head.copy()

        # Inner corner sits at the midpoint between the tip (tail) of down_06 and up_06
        tip_down = edit_bones[in_def_down].tail.copy()
        if in_def_up:
            tip_up = edit_bones[in_def_up].tail.copy()
            pos_in = (tip_down + tip_up) * 0.5
        else:
            pos_in = tip_down

        # Formatted names: e.g. "orbital_corner_out_ctrl.L", "orbital_corner_in_ctrl.L"
        out_name = self.format_name(
            extra="corner_out",
            role=naming.ROLE_CTRL,
            side=side
        )
        ctrl_out = core_framework.create_bone(
            self.armature_obj, out_name,
            head=pos_out, tail=pos_out + mathutils.Vector((0.0, 0.0, 0.025)),
            parent_name=parent_socket, collection_name=collection
        )

        in_name = self.format_name(
            extra="corner_in",
            role=naming.ROLE_CTRL,
            side=side
        )
        ctrl_in = core_framework.create_bone(
            self.armature_obj, in_name,
            head=pos_in, tail=pos_in + mathutils.Vector((0.0, 0.0, 0.025)),
            parent_name=parent_socket, collection_name=collection
        )

        self.edit_data = {"ctrl_out": ctrl_out, "ctrl_in": ctrl_in}
        self.register_output("corner_out", ctrl_out)
        self.register_output("corner_in", ctrl_in)
        self.register_control(ctrl_out)
        self.register_control(ctrl_in)

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        shapes = self.context.shapes
        scale = self.params.get("widget_scale", 0.08)
        
        for k in ("ctrl_out", "ctrl_in"):
            ctrl_name = self.edit_data[k]
            core_framework.assign_bone_shape(
                pose_bones[ctrl_name], shapes['Box'], scale=(scale, scale, scale)
            )