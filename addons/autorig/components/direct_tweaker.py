from typing import List, Tuple, Optional
from .. import core_framework, base_component, naming


def _parse_bone_side(bone_name: str) -> Tuple[str, Optional[str]]:
    """
    Extracts the base name and normalized side from a bone name.
    e.g., 'lip_upper.L' -> ('lip_upper', 'L')
          'nose_bridge'  -> ('nose_bridge', None)
    """
    # Clean possible suffixes like .L, .R, _L, _R
    for sep in [".", "_"]:
        if len(bone_name) > 2 and bone_name[-2] == sep:
            side_token = bone_name[-1]
            norm = naming.normalize_side(side_token)
            if norm:
                return bone_name[:-2], norm
    return bone_name, None


def _build_direct_tweaker(armature_obj, def_name, ctrl_name, parent_name, collection_name):
    return core_framework.duplicate_bone(
        armature_obj, def_name, ctrl_name,
        collection_name=collection_name, parent_name=parent_name, use_deform=False
    )


@base_component.register_component("DirectTweaker")
class DirectTweakerComponent(base_component.BaseRigComponent):
    """
    Direct Tweaker controls with weighted following and optional aim tracking against target sockets.
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
        explicit_ctrl_name = self.params.get("custom_ctrl_name")
        self.tweakers = []

        for item in self.params.get("targets", []):
            if isinstance(item, str):
                def_name = core_framework.find_bone_name(self.armature_obj, item)
                follow_spec = None
                follow_socket = None
                aim_target = False
                aim_influence = 1.0
                track_axis = "TRACK_Y"
                item_ctrl_name = explicit_ctrl_name
            else:
                def_name = core_framework.find_bone_name(self.armature_obj, item.get("deform_bone"))
                follow_spec = item.get("mouth_corner_follow", item.get("jaw_follow"))
                follow_socket = item.get("follow_target", self.params.get("jaw_socket"))
                aim_target = item.get("aim_target", False)
                aim_influence = item.get("aim_influence", 1.0)
                track_axis = item.get("track_axis", "TRACK_Y")
                item_ctrl_name = item.get("ctrl_name", explicit_ctrl_name)

            # Resolve naming and side tokens
            base_def_name, side = _parse_bone_side(def_name)

            if item_ctrl_name:
                ctrl_name = item_ctrl_name
            else:
                # e.g., "tweaker_cheek_ctrl.L" or "tweaker_nose_ctrl"
                ctrl_name = naming.format_name(
                    name=f"{self.name}_{base_def_name}",
                    role=naming.ROLE_CTRL,
                    side=side
                )

            if follow_spec is not None:
                # e.g., "tweaker_cheek_follow_mch.L"
                mch_name = naming.format_name(
                    name=f"{self.name}_{base_def_name}_follow",
                    role=naming.ROLE_MCH,
                    side=side
                )
                created_mch = core_framework.duplicate_bone(
                    self.armature_obj, def_name, mch_name,
                    collection_name="MCH", parent_name="", use_deform=False
                )
                
                # Intermediate Aim Bone
                aim_mch_name = None
                ctrl_parent = created_mch
                if aim_target:
                    # e.g., "tweaker_cheek_aim_mch.L"
                    aim_mch_name = naming.format_name(
                        name=f"{self.name}_{base_def_name}_aim",
                        role=naming.ROLE_MCH,
                        side=side
                    )
                    ctrl_parent = core_framework.duplicate_bone(
                        self.armature_obj, def_name, aim_mch_name,
                        collection_name="MCH", parent_name=created_mch, use_deform=False
                    )

                created_ctrl = core_framework.duplicate_bone(
                    self.armature_obj, def_name, ctrl_name,
                    collection_name=collection, parent_name=ctrl_parent, use_deform=False
                )
                self.tweakers.append({
                    "def": def_name, "ctrl": created_ctrl, "mch": created_mch, "aim_mch": aim_mch_name,
                    "follow": follow_spec, "follow_socket": follow_socket,
                    "aim_target": aim_target, "aim_influence": aim_influence, "track_axis": track_axis
                })
            else:
                created_ctrl = _build_direct_tweaker(
                    self.armature_obj, def_name, ctrl_name, parent_bone, collection
                )
                self.tweakers.append({
                    "def": def_name, "ctrl": created_ctrl, "mch": None, "aim_mch": None, "follow": None
                })

            self.register_output(def_name, created_ctrl)
            self.register_control(created_ctrl)
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
            aim_mch_name = t.get("aim_mch")
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

                # Setup Aim Constraint on Intermediate Aim Bone
                if aim_mch_name and t.get("aim_target"):
                    p_aim_mch = pose_bones[aim_mch_name]
                    core_framework.create_custom_property(
                        p_ctrl, "Aim_Weight", default=t.get("aim_influence", 1.0), min_val=0.0, max_val=1.0,
                        description="Influence of aiming at follow target"
                    )
                    aim_con = p_aim_mch.constraints.new(type='DAMPED_TRACK')
                    aim_con.target = self.armature_obj
                    aim_con.subtarget = follow_target
                    aim_con.track_axis = t.get("track_axis", "TRACK_Y")

                    core_framework.add_driver(
                        target_id=aim_con, target_datapath="influence",
                        source_id=self.armature_obj,
                        source_prop_path=f'pose.bones["{ctrl_name}"]["Aim_Weight"]',
                        expression="aim", var_name="aim"
                    )

                p_def = pose_bones[def_name]
                for c in list(p_def.constraints):
                    p_def.constraints.remove(c)
                core_framework.add_constraint(p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ctrl_name)
                core_framework.assign_bone_shape(p_ctrl, shapes.get(shape_type, shapes['Sphere']), scale=(scale, scale, scale))
            else:
                p_def = pose_bones[def_name]
                for c in list(p_def.constraints):
                    p_def.constraints.remove(c)
                core_framework.add_constraint(p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ctrl_name)
                core_framework.assign_bone_shape(pose_bones[ctrl_name], shapes.get(shape_type, shapes['Sphere']), scale=(scale, scale, scale))