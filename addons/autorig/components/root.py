from typing import List
import mathutils
from blender_scripts.autorig import core_framework
from blender_scripts.autorig.base_component import BaseRigComponent
from blender_scripts.autorig.base_component import register_component


@register_component("Root")
class RootComponent(BaseRigComponent):
    """Generates the master root control."""

    def validate(self) -> List[str]:
        # Root can duplicate an existing root def bone or create at origin if none provided
        return []

    def build_edit(self) -> None:
        def_root = self.params.get("deform_bone", "root")
        resolved = core_framework.find_bone_name(self.armature_obj, def_root)

        if resolved:
            ctrl_root = core_framework.duplicate_bone(
                self.armature_obj, resolved, f"CTRL_{self.name.capitalize()}",
                collection_name="CTRL_Root", use_deform=False, parent_name=None
            )
        else:
            ctrl_root = core_framework.create_bone(
                self.armature_obj, f"CTRL_{self.name.capitalize()}",
                head=mathutils.Vector((0.0, 0.0, 0.0)),
                tail=mathutils.Vector((0.0, 0.2, 0.0)),
                collection_name="CTRL_Root", use_deform=False
            )

        self.register_output("main", ctrl_root)
        self.deform_bone = resolved

    def build_pose(self) -> None:
        ctrl_root = self.outputs["main"]
        p_ctrl = self.armature_obj.pose.bones[ctrl_root]
        
        # Assign shape from context library
        shape = self.context.shapes.get("Circle")
        if shape:
            core_framework.assign_bone_shape(p_ctrl, shape, scale=(1.5, 1.5, 1.5))

        # Constrain deform bone if present
        if self.deform_bone:
            p_def = self.armature_obj.pose.bones[self.deform_bone]
            for c in list(p_def.constraints):
                p_def.constraints.remove(c)
            core_framework.add_constraint(p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ctrl_root)