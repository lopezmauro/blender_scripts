from typing import List
from blender_scripts.autorig import core_framework
from blender_scripts.autorig.base_component import BaseRigComponent
from blender_scripts.autorig.base_component import register_component

def _build_direct_tweaker(armature_obj, def_name, ctrl_name, parent_name, collection_name):
    return core_framework.duplicate_bone(
        armature_obj, def_name, ctrl_name,
        collection_name=collection_name, parent_name=parent_name, use_deform=False
    )

@register_component("DirectTweaker")
class DirectTweakerComponent(BaseRigComponent):
    """
    Direct Tweaker controls with weighted following against target sockets.
    Supports explicit custom control names via custom_ctrl_name or per-target ctrl_name.
    """
    def validate(self) -> List[str]:
        errors = []
        targets = self.params.get("targets", [])
        if not targets:
            errors.append("No 'targets' specified in DirectTweaker params.")
        for item in targets:
            b_name = item if isinstance(item, str) else item.get("deform_bone")
            if not core_framework.find_bone_name(self.armature_obj, b_name):
                errors.append(f"Target deform bone '{b_name}' not found.")
        return errors

    def build_edit(self) -> None:
        parent_bone = self.resolve_parent_socket()
        collection = self.params.get("collection", "CTRL_Face")
        ctrl_prefix = self.params.get("prefix", f"CTRL_{self.name}_")
        explicit_ctrl_name = self.params.get("custom_ctrl_name")
        self.tweakers = []

        for item in self.params.get("targets", []):
            if isinstance(item, str):
                def_name = core_framework.find_bone_name(self.armature_obj, item)
                follow_spec = None
                follow_socket = None
                ctrl_name = explicit_ctrl_name if explicit_ctrl_name else f"{ctrl_prefix}{def_name}"
            else:
                def_name = core_framework.find_bone_name(self.armature_obj, item.get("deform_bone"))
                follow_spec = item.get("mouth_corner_follow", item.get("jaw_follow"))
                follow_socket = item.get("follow_target", self.params.get("jaw_socket"))
                ctrl_name = item.get("ctrl_name", explicit_ctrl_name or f"{ctrl_prefix}{def_name}")

            if follow_spec is not None:
                mch_name = f"MCH_{self.name}_{def_name}"
                created_mch = core_framework.duplicate_bone(
                    self.armature_obj, def_name, mch_name,
                    collection_name="MCH", parent_name="", use_deform=False
                )
                created_ctrl = core_framework.duplicate_bone(
                    self.armature_obj, def_name, ctrl_name,
                    collection_name=collection, parent_name=created_mch, use_deform=False
                )
                self.tweakers.append({
                    "def": def_name, "ctrl": created_ctrl, "mch": created_mch,
                    "follow": follow_spec, "follow_socket": follow_socket
                })
            else:
                created_ctrl = _build_direct_tweaker(
                    self.armature_obj, def_name, ctrl_name, parent_bone, collection
                )
                self.tweakers.append({
                    "def": def_name, "ctrl": created_ctrl, "mch": None, "follow": None
                })
            self.register_output(def_name, created_ctrl)
            if explicit_ctrl_name:
                self.register_output("main", created_ctrl)

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        shapes = self.context.shapes
        scale = self.params.get("widget_scale", 0.09)
        shape_type = self.params.get("widget_shape", "Sphere")
        head_target = self.resolve_parent_socket()

        for t in self.tweakers:
            def_name = t["def"]
            ctrl_name = t["ctrl"]
            mch_name = t["mch"]
            follow_target = self.context.resolve_socket(t.get("follow_socket"))

            if mch_name and follow_target and head_target:
                p_ctrl = pose_bones[ctrl_name]
                p_mch = pose_bones[mch_name]
                core_framework.create_custom_property(
                    p_ctrl, "Follow_Weight", default=t["follow"], min_val=0.0, max_val=1.0,
                    description="Influence of the target transform"
                )
                arm_con = p_mch.constraints.new(type='ARMATURE')
                t1 = arm_con.targets.new()
                t1.target = self.armature_obj
                t1.subtarget = head_target
                t2 = arm_con.targets.new()
                t2.target = self.armature_obj
                t2.subtarget = follow_target

                core_framework.add_driver(
                    target_id=t1, target_datapath="weight",
                    source_id=self.armature_obj,
                    source_prop_path=f'pose.bones["{ctrl_name}"]["Follow_Weight"]',
                    expression="1.0 - follow", var_name="follow"
                )
                core_framework.add_driver(
                    target_id=t2, target_datapath="weight",
                    source_id=self.armature_obj,
                    source_prop_path=f'pose.bones["{ctrl_name}"]["Follow_Weight"]',
                    expression="follow", var_name="follow"
                )
                p_def = pose_bones[def_name]
                for c in list(p_def.constraints):
                    p_def.constraints.remove(c)
                core_framework.add_constraint(p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ctrl_name)
                core_framework.assign_bone_shape(p_ctrl, shapes[shape_type], scale=(scale, scale, scale))
            else:
                p_def = pose_bones[def_name]
                for c in list(p_def.constraints):
                    p_def.constraints.remove(c)
                core_framework.add_constraint(p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ctrl_name)
                core_framework.assign_bone_shape(pose_bones[ctrl_name], shapes.get(shape_type, shapes['Sphere']), scale=(scale, scale, scale))