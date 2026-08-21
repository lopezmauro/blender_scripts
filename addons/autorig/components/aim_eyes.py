import mathutils
from typing import List
from .. import core_framework, base_component


@base_component.register_component("AimEyes")
class AimEyesComponent(base_component.BaseRigComponent):
    """
    Binocular/Multi-eye Aim tracking setup.
    Creates individual eye aim targets parented under a master aim controller.
    """
    def validate(self) -> List[str]:
        errors = []
        eyes = self.params.get("eyes", {})
        if not eyes:
            errors.append("No 'eyes' dictionary provided.")
        for side_key, b in eyes.items():
            if not core_framework.find_bone_name(self.armature_obj, b):
                errors.append(f"Eye deform bone '{b}' for side '{side_key}' not found.")
        return errors

    def build_edit(self) -> None:
        edit_bones = self.armature_obj.data.edit_bones
        parent_bone = self.resolve_parent_socket()
        collection = self.params.get("collection", "CTRL_Face")
        distance_mult = self.params.get("aim_distance_multiplier", 5.0)
        raw_eyes = self.params.get("eyes", {})
        self.eye_bindings = {}
        aim_positions = {}
        master_pos = mathutils.Vector((0.0, 0.0, 0.0))

        for key, raw_bone in raw_eyes.items():
            def_name = core_framework.find_bone_name(self.armature_obj, raw_bone)
            eb = edit_bones[def_name]
            aim_vec = (eb.tail - eb.head)
            locator_pos = eb.head + (aim_vec * distance_mult)
            aim_positions[key] = (def_name, locator_pos)
            master_pos += locator_pos
        master_pos /= len(raw_eyes)

        # 1. Master Aim Control
        ctrl_aim_master = core_framework.create_bone(
            self.armature_obj, f"CTRL_Aim_{self.name}_Master",
            head=master_pos, tail=master_pos + mathutils.Vector((0.0, 0.0, 0.06)),
            parent_name=parent_bone, collection_name=collection
        )
        self.ctrl_aim_master = ctrl_aim_master
        self.register_output("master", ctrl_aim_master)
        self.register_control(ctrl_aim_master)

        # 2. Individual Locators
        for key, (def_name, loc_pos) in aim_positions.items():
            ctrl_aim_locator = core_framework.create_bone(
                self.armature_obj, f"CTRL_Aim_{self.name}_{key}",
                head=loc_pos, tail=loc_pos + mathutils.Vector((0.0, 0.0, 0.04)),
                parent_name=ctrl_aim_master, collection_name=collection
            )
            self.eye_bindings[key] = {"def": def_name, "aim": ctrl_aim_locator}
            self.register_output(f"aim_{key}", ctrl_aim_locator)
            self.register_control(ctrl_aim_locator)

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        shapes = self.context.shapes

        if self.ctrl_aim_master:
            for ctrl_name in self.controls:
                if ctrl_name in pose_bones and ctrl_name != self.ctrl_aim_master:
                    pose_bones[ctrl_name]["_settings_bone"] = self.ctrl_aim_master

        # Assign master shape
        core_framework.assign_bone_shape(
            pose_bones[self.ctrl_aim_master], shapes['Box'], scale=(0.15, 0.15, 0.15)
        )

        # Constrain deform eye bones to aim locators
        for key, info in self.eye_bindings.items():
            p_def = pose_bones[info["def"]]
            for c in list(p_def.constraints):
                p_def.constraints.remove(c)

            core_framework.add_constraint(
                p_def, 'DAMPED_TRACK', self.armature_obj,
                subtarget_bone=info["aim"], track_axis='TRACK_Y'
            )
            core_framework.assign_bone_shape(
                pose_bones[info["aim"]], shapes['Sphere'], scale=(0.075, 0.075, 0.075)
            )