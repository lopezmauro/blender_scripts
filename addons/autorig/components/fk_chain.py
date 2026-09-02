from typing import List, Tuple, Optional
from .. import core_framework, base_component, naming





@base_component.register_component("FKChain")
class FKChainComponent(base_component.BaseRigComponent):
    """
    Builds an arbitrary-length sequential FK control chain.
    Usable for Spine, Neck, Head, or simple appendage setups.
    """

    def validate(self) -> List[str]:
        errors = []
        chain = self.params.get("deform_chain", [])
        if not chain:
            errors.append("No 'deform_chain' specified.")
        for b in chain:
            if not core_framework.find_bone_name(self.armature_obj, b):
                errors.append(f"Deform bone '{b}' not found.")
        return errors

    def build_edit(self) -> None:
        raw_chain = self.params.get("deform_chain", [])
        collection = self.params.get("collection", "CTRL_Spine")
        parent_socket = self.resolve_parent_socket()

        self.deform_chain = [core_framework.find_bone_name(self.armature_obj, b) for b in raw_chain]
        
        comp_side = self.params.get("side")
        if comp_side is not None:
            side = naming.normalize_side(comp_side)
        else:
            _, side = naming.parse_bone_side(self.deform_chain[0])

        self.ctrl_bones = []
        current_parent = parent_socket

        # Build sequential FK Chain using standardized naming
        for idx, def_name in enumerate(self.deform_chain):
            base_def_name, bone_side = naming.parse_bone_side(def_name)
            target_side = bone_side or side

            # Call self.format_name so component name deduplication occurs
            ctrl_name = self.format_name(
                sub_name=base_def_name,
                extra="fk",
                role=naming.ROLE_CTRL,
                side=target_side
            )

            created_ctrl = core_framework.duplicate_bone(
                self.armature_obj,
                def_name,
                ctrl_name,
                collection_name=collection,
                parent_name=current_parent,
                use_deform=False,
            )

            self.ctrl_bones.append(created_ctrl)
            self.register_control(created_ctrl)
            current_parent = created_ctrl

        # Expose sockets
        self.register_output("root", self.ctrl_bones[0])
        self.register_output("tip", self.ctrl_bones[-1])
        for idx, ctrl_b in enumerate(self.ctrl_bones):
            self.register_output(f"segment_{idx:02d}", ctrl_b)

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        widget_shape = self.params.get("widget_shape", "Circle")
        widget_scale = self.params.get("widget_scale", 1.0)
        shape_obj = self.context.shapes.get(widget_shape)

        # Wire deform constraints and custom shapes
        for def_name, ctrl_name in zip(self.deform_chain, self.ctrl_bones):
            p_def = pose_bones[def_name]
            p_ctrl = pose_bones[ctrl_name]

            for c in list(p_def.constraints):
                p_def.constraints.remove(c)
            core_framework.add_constraint(p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ctrl_name)

            if shape_obj:
                scale_vec = (widget_scale, widget_scale, widget_scale)
                core_framework.assign_bone_shape(p_ctrl, shape_obj, scale=scale_vec)

        # Optional Rotation Isolation on the tip bone (e.g. Head isolate)
        if self.params.get("enable_isolate_rotation", False):
            tip_ctrl = self.ctrl_bones[-1]
            p_tip = pose_bones[tip_ctrl]
            core_framework.create_custom_property(
                target=p_tip, prop_name="isolate_rotation",
                default=0.0, min_val=0.0, max_val=1.0,
                description="0.0 = Follows Parent, 1.0 = World/Root Rotation"
            )
            isolate_space_bone = self.context.resolve_socket(self.params.get("isolate_target", "root.main"))
            if isolate_space_bone:
                rot_con = core_framework.add_constraint(
                    p_tip, 'COPY_ROTATION', self.armature_obj,
                    subtarget_bone=isolate_space_bone, influence=0.0,
                    owner_space='WORLD', target_space='WORLD'
                )
                core_framework.add_driver(
                    target_id=rot_con, target_datapath="influence",
                    source_id=self.armature_obj,
                    source_prop_path=f'pose.bones["{tip_ctrl}"]["isolate_rotation"]',
                    expression="iso", var_name="iso"
                )