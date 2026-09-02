import bpy
import mathutils
from typing import List
from .. import core_framework, base_component, naming


@base_component.register_component("LipMasters")
class LipMastersComponent(base_component.BaseRigComponent):
    """
    Spawns Upper/Lower Lip master controls and Left/Right Mouth Corners with Jaw Follow.
    """
    def validate(self) -> List[str]:
        errors = []
        required = [
            "lip_up_center_L", "lip_up_center_R",
            "lip_down_center_L", "lip_down_center_R",
            "lip_corner_L", "lip_corner_R"
        ]
        for key in required:
            b_name = self.params.get(key)
            if not b_name or not core_framework.find_bone_name(self.armature_obj, b_name):
                errors.append(f"Required bone '{key}' ({b_name}) not found.")
        return errors

    def build_edit(self) -> None:
        edit_bones = self.armature_obj.data.edit_bones
        parent_uphead = self.context.resolve_socket(self.params.get("uphead_socket", self.params.get("head_socket")))
        parent_head = self.resolve_parent_socket("head_socket")
        parent_jaw = self.context.resolve_socket(self.params.get("jaw_socket"))
        collection = self.params.get("collection", "CTRL_Face")

        # 1. Upper Lip Master (Center - no side suffix) -> "lip_up_master_ctrl"
        up_l = core_framework.find_bone_name(self.armature_obj, self.params["lip_up_center_L"])
        up_r = core_framework.find_bone_name(self.armature_obj, self.params["lip_up_center_R"])
        up_pos = (edit_bones[up_l].head + edit_bones[up_r].head) * 0.5
        up_name = self.format_name(
            extra="master_up",
            role=naming.ROLE_CTRL,
            side="C"
        )
        ctrl_lip_up = core_framework.create_bone(
            self.armature_obj, up_name,
            head=up_pos, tail=up_pos + mathutils.Vector((0.0, 0.0, 0.03)),
            parent_name=parent_uphead, collection_name=collection
        )

        # 2. Lower Lip Master (Center - no side suffix) -> "lip_down_master_ctrl"
        down_l = core_framework.find_bone_name(self.armature_obj, self.params["lip_down_center_L"])
        down_r = core_framework.find_bone_name(self.armature_obj, self.params["lip_down_center_R"])
        down_pos = (edit_bones[down_l].head + edit_bones[down_r].head) * 0.5
        down_name = self.format_name(
            extra="master_down",
            role=naming.ROLE_CTRL,
            side="C"
        )
        ctrl_lip_down = core_framework.create_bone(
            self.armature_obj, down_name,
            head=down_pos, tail=down_pos + mathutils.Vector((0.0, 0.0, 0.03)),
            parent_name=parent_jaw, collection_name=collection
        )

        # 3. Left/Right Mouth Corners (Sided - with .L / .R suffix)
        corners = {}
        for side_token, param_key in (("L", "lip_corner_L"), ("R", "lip_corner_R")):
            norm_side = naming.normalize_side(side_token)
            c_def = core_framework.find_bone_name(self.armature_obj, self.params[param_key])
            c_pos = edit_bones[c_def].head.copy()

            mch_corner_name = self.format_name(
                extra="corner",
                role=naming.ROLE_MCH,
                side=norm_side
            )
            mch_corner = core_framework.create_bone(
                self.armature_obj, mch_corner_name,
                head=c_pos, tail=c_pos + mathutils.Vector((0.0, 0.0, 0.03)),
                parent_name="", collection_name="MCH"
            )

            ctrl_corner_name = self.format_name(
                extra="corner",
                role=naming.ROLE_CTRL,
                side=norm_side
            )
            ctrl_corner = core_framework.create_bone(
                self.armature_obj, ctrl_corner_name,
                head=c_pos, tail=c_pos + mathutils.Vector((0.0, 0.0, 0.03)),
                parent_name=mch_corner, collection_name=collection
            )
            corners[norm_side] = {"ctrl": ctrl_corner, "mch": mch_corner}

        self.edit_data = {
            "ctrl_up": ctrl_lip_up,
            "ctrl_down": ctrl_lip_down,
            "corners": corners,
            "head_parent": parent_head,
            "jaw_parent": parent_jaw
        }
        self.register_output("up_master", ctrl_lip_up)
        self.register_output("down_master", ctrl_lip_down)
        self.register_output("corner_L", corners[naming.SIDE_LEFT]["ctrl"])
        self.register_output("corner_R", corners[naming.SIDE_RIGHT]["ctrl"])
        self.register_control(ctrl_lip_up)
        self.register_control(ctrl_lip_down)
        self.register_control(corners[naming.SIDE_LEFT]["ctrl"])
        self.register_control(corners[naming.SIDE_RIGHT]["ctrl"])

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        shapes = self.context.shapes
        d = self.edit_data

        core_framework.assign_bone_shape(pose_bones[d["ctrl_up"]], shapes['Box'], scale=(0.1, 0.1, 0.1))
        core_framework.assign_bone_shape(pose_bones[d["ctrl_down"]], shapes['Box'], scale=(0.1, 0.1, 0.1))

        for norm_side, c_info in d["corners"].items():
            ctrl_name = c_info["ctrl"]
            mch_name = c_info["mch"]
            p_ctrl = pose_bones[ctrl_name]
            p_mch = pose_bones[mch_name]
            
            # Updated default to 0.3
            core_framework.create_custom_property(
                p_ctrl, "Jaw_Follow", default=0.3, min_val=0.0, max_val=1.0,
                description="Influence of the jaw on mouth corner"
            )
            core_framework.assign_bone_shape(p_ctrl, shapes['Box'], scale=(0.09, 0.09, 0.09))

            arm_con = p_mch.constraints.new(type='ARMATURE')
            t1 = arm_con.targets.new()
            t1.target = self.armature_obj
            t1.subtarget = d["head_parent"]
            t2 = arm_con.targets.new()
            t2.target = self.armature_obj
            t2.subtarget = d["jaw_parent"]
            core_framework.add_driver(
                target_id=t1, target_datapath="weight", source_id=self.armature_obj,
                source_prop_path=f'pose.bones["{ctrl_name}"]["Jaw_Follow"]',
                expression="1.0 - follow", var_name="follow"
            )
            core_framework.add_driver(
                target_id=t2, target_datapath="weight", source_id=self.armature_obj,
                source_prop_path=f'pose.bones["{ctrl_name}"]["Jaw_Follow"]',
                expression="follow", var_name="follow"
            )