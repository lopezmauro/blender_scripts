import bpy
import mathutils
from typing import List, Tuple, Optional
from .. import core_framework, base_component, naming


def _parse_bone_side(bone_name: str) -> Tuple[str, Optional[str]]:
    """
    Extracts the base name and normalized side from a bone name.
    e.g., 'eyebrow_01.L' -> ('eyebrow_01', 'L')
          'spine_01'     -> ('spine_01', None)
    """
    for sep in [".", "_"]:
        if len(bone_name) > 2 and bone_name[-2] == sep:
            side_token = bone_name[-1]
            norm = naming.normalize_side(side_token)
            if norm:
                return bone_name[:-2], norm
    return bone_name, None


@base_component.register_component("DirectWeightChain")
class DirectWeightChainComponent(base_component.BaseRigComponent):
    """
    Direct skin-weighted chain component replicating Maya skinned curve behavior.
    Uses Blender's ARMATURE constraint for multi-target weight normalization.
    """

    def validate(self) -> List[str]:
        errors = []
        chain = self.params.get("deform_chain", [])
        if len(chain) < 2:
            errors.append("DirectWeightChain requires at least 2 bones in 'deform_chain'.")
        for b in chain:
            if not core_framework.find_bone_name(self.armature_obj, b):
                errors.append(f"Deform bone '{b}' not found.")
        return errors

    def _calculate_default_weights(self, count: int):
        weights_start, weights_mid, weights_end = [], [], []
        mid_idx = (count - 1) / 2.0

        for i in range(count):
            if i <= mid_idx:
                t = i / mid_idx if mid_idx > 0 else 0.0
                weights_start.append(round(1.0 - t, 4))
                weights_mid.append(round(t, 4))
                weights_end.append(0.0)
            else:
                t = (i - mid_idx) / (count - 1 - mid_idx) if (count - 1 - mid_idx) > 0 else 0.0
                weights_start.append(0.0)
                weights_mid.append(round(1.0 - t, 4))
                weights_end.append(round(t, 4))

        return weights_start, weights_mid, weights_end

    def build_edit(self) -> None:
        edit_bones = self.armature_obj.data.edit_bones
        def_chain = [core_framework.find_bone_name(self.armature_obj, b) for b in self.params["deform_chain"]]
        parent_bone = self.resolve_parent_socket()
        collection = self.params.get("collection", "CTRL_Face")

        # Derive side token from component side param or inspect first chain bone
        comp_side = self.params.get("side")
        if comp_side is not None:
            side = naming.normalize_side(comp_side)
        else:
            _, side = _parse_bone_side(def_chain[0])

        start_master = self.context.resolve_socket(self.params.get("start_master"))
        mid_master = self.context.resolve_socket(self.params.get("mid_master"))
        end_master = self.context.resolve_socket(self.params.get("end_master"))

        # Master Controls
        if not start_master:
            start_name = naming.format_name(
                name=f"{self.name}_start",
                role=naming.ROLE_CTRL,
                side=side
            )
            start_master = core_framework.create_bone(
                self.armature_obj, start_name,
                head=edit_bones[def_chain[0]].head.copy(),
                tail=edit_bones[def_chain[0]].head.copy() + mathutils.Vector((0.0, 0.0, 0.025)),
                parent_name=parent_bone, collection_name=collection
            )
            self.register_control(start_master)

        if not mid_master:
            mid_idx = len(def_chain) // 2
            mid_pos = edit_bones[def_chain[mid_idx]].head.copy()
            mid_name = naming.format_name(
                name=f"{self.name}_mid",
                role=naming.ROLE_CTRL,
                side=side
            )
            mid_master = core_framework.create_bone(
                self.armature_obj, mid_name,
                head=mid_pos, tail=mid_pos + mathutils.Vector((0.0, 0.0, 0.025)),
                parent_name=parent_bone, collection_name=collection
            )
            self.register_control(mid_master)

        if not end_master:
            end_name = naming.format_name(
                name=f"{self.name}_end",
                role=naming.ROLE_CTRL,
                side=side
            )
            end_master = core_framework.create_bone(
                self.armature_obj, end_name,
                head=edit_bones[def_chain[-1]].tail.copy(),
                tail=edit_bones[def_chain[-1]].tail.copy() + mathutils.Vector((0.0, 0.0, 0.025)),
                parent_name=parent_bone, collection_name=collection
            )
            self.register_control(end_master)

        self.master_ctrls = [start_master, mid_master, end_master]
        self.mch_bones = []
        self.ctrl_bones = []
        self.def_bones = def_chain

        for def_name in def_chain:
            base_def_name, bone_side = _parse_bone_side(def_name)
            target_side = bone_side or side

            mch_name = naming.format_name(
                name=f"{self.name}_{base_def_name}",
                role=naming.ROLE_MCH,
                side=target_side
            )
            created_mch = core_framework.duplicate_bone(
                self.armature_obj, def_name, mch_name,
                collection_name="MCH", parent_name=parent_bone, use_deform=False
            )

            ctrl_name = naming.format_name(
                name=f"{self.name}_{base_def_name}",
                role=naming.ROLE_CTRL,
                side=target_side
            )
            created_ctrl = core_framework.duplicate_bone(
                self.armature_obj, def_name, ctrl_name,
                collection_name=collection, parent_name=created_mch, use_deform=False
            )

            self.mch_bones.append(created_mch)
            self.ctrl_bones.append(created_ctrl)

        self.register_output("start", start_master)
        self.register_output("mid", mid_master)
        self.register_output("end", end_master)
        self.register_output("tip", self.ctrl_bones[-1])
        for idx, c_b in enumerate(self.ctrl_bones):
            self.register_output(f"detail_{idx:02d}", c_b)
            self.register_control(c_b)

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        shapes = self.context.shapes
        ctrl_scale = self.params.get("ctrl_scale", 0.05)
        count = len(self.def_bones)

        w_start = self.params.get("weights_start")
        w_mid = self.params.get("weights_mid")
        w_end = self.params.get("weights_end")

        if not (w_start and w_mid and w_end and len(w_start) == count):
            w_start, w_mid, w_end = self._calculate_default_weights(count)

        p_start, p_mid, p_end = self.master_ctrls

        for idx, (mch, ctrl, def_b) in enumerate(zip(self.mch_bones, self.ctrl_bones, self.def_bones)):
            p_mch = pose_bones[mch]
            p_ctrl = pose_bones[ctrl]
            p_def = pose_bones[def_b]

            # Clear existing constraints
            for c in list(p_mch.constraints):
                p_mch.constraints.remove(c)
            for c in list(p_def.constraints):
                p_def.constraints.remove(c)

            # 1. Multi-target Armature Constraint (Direct Skinning)
            arm_con = p_mch.constraints.new(type='ARMATURE')
            arm_con.use_deform_preserve_volume = False

            targets = [
                (p_start, float(w_start[idx])),
                (p_mid, float(w_mid[idx])),
                (p_end, float(w_end[idx]))
            ]

            for bone_name, weight in targets:
                if weight > 0.0:
                    t = arm_con.targets.new()
                    t.target = self.armature_obj
                    t.subtarget = bone_name
                    t.weight = weight

            # 2. Deform Bone Binding for Unity export
            core_framework.add_constraint(
                p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ctrl
            )

            # 3. Widget assignment
            core_framework.assign_bone_shape(
                p_ctrl, shapes['Sphere'], scale=(ctrl_scale, ctrl_scale, ctrl_scale)
            )

        for m_ctrl in self.master_ctrls:
            if m_ctrl in pose_bones:
                core_framework.assign_bone_shape(
                    pose_bones[m_ctrl], shapes['Box'], scale=(ctrl_scale * 1.2, ctrl_scale * 1.2, ctrl_scale * 1.2)
                )