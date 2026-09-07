import math
import mathutils
from typing import List, Tuple, Optional
from .. import core_framework, systems_framework, base_component, naming


def solve_blender_pole_angle(arm_obj, base_bone_name, pole_target_name):
    """
    Computes the exact pole angle in radians from the root bone of the IK chain
    by projecting the pole vector onto the bone's local XZ plane.
    """
    p_base = arm_obj.pose.bones[base_bone_name]
    p_pole = arm_obj.pose.bones[pole_target_name]
    p_child = p_base.children[0]

    base_head = p_base.bone.head_local
    base_tail = p_base.bone.tail_local
    ik_tail = p_child.bone.tail_local
    pole_pos = p_pole.bone.head_local

    pole_normal = (ik_tail - base_head).cross(pole_pos - base_head).normalized()
    if pole_normal.length < 1e-4:
        return 0.0

    base_y_axis = (base_tail - base_head).normalized()
    projected_pole_axis = pole_normal.cross(base_y_axis).normalized()
    base_x_axis = p_base.bone.matrix_local.col[0].to_3d().normalized()

    dot = max(-1.0, min(1.0, base_x_axis.dot(projected_pole_axis)))
    angle = math.acos(dot)

    if base_x_axis.cross(projected_pole_axis).dot(base_y_axis) > 0:
        angle = -angle

    return angle


@base_component.register_component("Limb")
class LimbComponent(base_component.BaseRigComponent):
    """
    Full stretchy limb with dedicated tweak controls, isolated scale inheritance,
    and STRETCH_TO deform bones (Joey C-quel technique).
    """
    def validate(self) -> List[str]:
        errors = []
        chain = self.params.get("deform_chain", [])
        if len(chain) < 3:
            errors.append("Limb component requires at least 3 bones in 'deform_chain' [upper, lower, end].")
        for b in chain:
            if not core_framework.find_bone_name(self.armature_obj, b):
                errors.append(f"Deform bone '{b}' not found.")
        return errors

    def build_edit(self) -> None:
        edit_bones = self.armature_obj.data.edit_bones
        def_chain = [core_framework.find_bone_name(self.armature_obj, b) for b in self.params["deform_chain"]]
        
        # Derive normalized side
        comp_side = self.params.get("side")
        if comp_side is not None:
            side = naming.normalize_side(comp_side)
        else:
            _, side = naming.parse_bone_side(def_chain[0])

        limb_type = self.params.get("limb_type", "Arm").lower()
        has_foot = self.params.get("has_reverse_foot", False)
        ball_def = core_framework.find_bone_name(self.armature_obj, self.params.get("ball_bone", ""))
        parent_bone = self.resolve_parent_socket()
        root_socket = self.context.resolve_socket(self.params.get("root_socket", "root.main"))

        # 1. Root collar/hip bone
        collar_def = core_framework.find_bone_name(self.armature_obj, self.params.get("collar_bone", ""))
        ctrl_collar = None
        if collar_def:
            collar_type = "clavicle" if limb_type == "arm" else "hip"
            collar_name = self.format_name(
                extra=collar_type,
                role=naming.ROLE_CTRL,
                side=side
            )
            ctrl_collar = self.register_control(core_framework.duplicate_bone(
                self.armature_obj, collar_def, collar_name,
                collection_name=f"CTRL_IK_{limb_type.capitalize()}s", parent_name=parent_bone
            ))
            limb_parent = ctrl_collar
            self.register_output("collar", ctrl_collar)
        else:
            limb_parent = parent_bone

        # 2. Intermediate ORG Switch Chain (MCH - not controls)
        org_chain = []
        curr_org_parent = limb_parent
        for d_name in def_chain[:2]:
            base_d, d_side = naming.parse_bone_side(d_name)
            org_name = self.format_name(
                sub_name=base_d,
                role=naming.ROLE_ORG,
                side=d_side or side
            )
            org_b = core_framework.duplicate_bone(
                self.armature_obj, d_name, org_name,
                collection_name="MCH", parent_name=curr_org_parent, use_deform=False
            )
            org_chain.append(org_b)
            curr_org_parent = org_b

        # 3. FK Chain Controls
        fk_chain = []
        curr_fk_parent = limb_parent
        for d_name in def_chain:
            base_d, d_side = naming.parse_bone_side(d_name)
            fk_name = self.format_name(
                    sub_name=base_d,
                    extra="fk",
                    role=naming.ROLE_CTRL,
                    side=d_side or side
                )
            fk_b = core_framework.duplicate_bone(
                self.armature_obj, d_name, fk_name,
                collection_name=f"CTRL_FK_{limb_type.capitalize()}s",
                parent_name=curr_fk_parent,
                use_deform=False
            )
            fk_chain.append(fk_b)
            self.register_control(fk_b)
            curr_fk_parent = fk_b

        ctrl_fk_ball = None
        if has_foot and ball_def:
            ball_name = self.format_name(
                sub_name=self.name,
                extra="fk",
                role=naming.ROLE_CTRL,
                side=side
            )

            ctrl_fk_ball = self.register_control(core_framework.duplicate_bone(
                self.armature_obj, ball_def, ball_name,
                collection_name=f"CTRL_FK_{limb_type.capitalize()}s", parent_name=fk_chain[2]
            ))

        # 4. IK Target & Pole Controls
        ik_end_type = "foot" if limb_type == "leg" else "hand"
        if has_foot:
            
            heel_tw_name = self.format_name(sub_name="heel_twist", extra=limb_type, role=naming.ROLE_GUIDE, side=side)
            toe_tw_name = self.format_name(sub_name="toe_twist", extra=limb_type, role=naming.ROLE_GUIDE, side=side)
            foot_head = edit_bones[def_chain[2]].head.copy()
            g_heel = edit_bones[heel_tw_name].head.copy() if heel_tw_name in edit_bones else foot_head + mathutils.Vector((0, -0.08, 0))
            g_toe = edit_bones[toe_tw_name].head.copy() if toe_tw_name in edit_bones else foot_head + mathutils.Vector((0, 0.15, 0))
            ik_target_head = (g_heel + g_toe) * 0.5
            
            ik_name = self.format_name(
                                        sub_name=ik_end_type,
                                        extra="ik",
                                        role=naming.ROLE_CTRL,
                                        side=side
                                    )
            ctrl_ik_target = self.register_control(core_framework.create_bone(
                self.armature_obj, ik_name,
                head=ik_target_head, tail=ik_target_head + mathutils.Vector((0.0, 0.2, 0.0)),
                parent_name=root_socket, collection_name=f"CTRL_IK_{limb_type.capitalize()}s"
            ))
        else:
            ik_name = self.format_name(
                                        sub_name=ik_end_type,
                                        extra="ik",
                                        role=naming.ROLE_CTRL,
                                        side=side
                                    )
            ctrl_ik_target = self.register_control(core_framework.duplicate_bone(
                self.armature_obj, def_chain[2], ik_name,
                collection_name=f"CTRL_IK_{limb_type.capitalize()}s", parent_name=root_socket
            ))
        guide_name = self.params.get("pole_guide")
        if not guide_name:
            guide_name = self.format_name(
                                        extra=f"pole_{limb_type}",
                                        role=naming.ROLE_GUIDE,
                                        side=side
                                        )
        eb_u, eb_l = edit_bones[def_chain[0]], edit_bones[def_chain[1]]
        if guide_name in edit_bones:
            guide_pos = edit_bones[guide_name].head.copy()
        else:
            offset = mathutils.Vector((0.0, 0.35, 0.0)) if limb_type == "leg" else mathutils.Vector((0.0, -0.3, 0.0))
            guide_pos = (eb_u.tail + eb_l.head) * 0.5 + offset

        pole_name = self.format_name(
            extra="pole",
            role=naming.ROLE_CTRL,
            side=side
        )
        ctrl_pole = self.register_control(core_framework.create_bone(
            self.armature_obj, pole_name,
            head=guide_pos, tail=guide_pos + mathutils.Vector((0.0, 0.0, 0.08)),
            parent_name=root_socket, collection_name=f"CTRL_IK_{limb_type.capitalize()}s"
        ))

        # 5. Settings Control
        total_chain_len = eb_u.length + eb_l.length
        end_head = edit_bones[def_chain[2]].head
        settings_pos = mathutils.Vector((end_head.x, end_head.y, end_head.z + (total_chain_len * 0.2)))
        settings_name = self.format_name(
            extra="settings",
            role=naming.ROLE_CTRL,
            side=side
        )
        ctrl_settings = self.register_control(core_framework.create_bone(
            self.armature_obj, settings_name,
            head=settings_pos, tail=settings_pos + mathutils.Vector((0.0, 0.0, 0.06)),
            parent_name=ctrl_ik_target, collection_name=f"CTRL_IK_{limb_type.capitalize()}s"
        ))

        # 6. MCH IK Bones (MCH - not controls)
        mch_ik = systems_framework.build_ik_chain(
            self.armature_obj, def_chain, ctrl_ik_target, ctrl_pole,
            "MCH", limb_parent, guide_pos
        )

        # 7. Tweak Controls Layer
        tweak_col = f"CTRL_IK_{limb_type.capitalize()}s"
        twk_u_name = self.format_name(extra="tweak_up", role=naming.ROLE_CTRL, side=side)
        ctrl_tweak_upper = self.register_control(core_framework.create_bone(
            self.armature_obj, twk_u_name,
            head=eb_u.head.copy(), tail=eb_u.head.copy() + mathutils.Vector((0.0, 0.04, 0.0)),
            parent_name=limb_parent, collection_name=tweak_col, use_deform=False
        ))

        twk_m_name = self.format_name(extra="tweak_mid", role=naming.ROLE_CTRL, side=side)
        ctrl_tweak_mid = self.register_control(core_framework.create_bone(
            self.armature_obj, twk_m_name,
            head=eb_u.tail.copy(), tail=eb_u.tail.copy() + mathutils.Vector((0.0, 0.04, 0.0)),
            parent_name=org_chain[0], collection_name=tweak_col, use_deform=False
        ))

        twk_e_name = self.format_name(extra="tweak_end", role=naming.ROLE_CTRL, side=side)
        ctrl_tweak_end = self.register_control(core_framework.create_bone(
            self.armature_obj, twk_e_name,
            head=eb_l.tail.copy(), tail=eb_l.tail.copy() + mathutils.Vector((0.0, 0.04, 0.0)),
            parent_name=org_chain[1], collection_name=tweak_col, use_deform=False
        ))

        rf_pivots = []
        mch_ik_ball = None
        if has_foot:
            rf_pivots = systems_framework.build_reverse_foot(
                self.armature_obj, side, def_chain[2], ball_def, ctrl_ik_target, f"CTRL_IK_{limb_type.capitalize()}s"
            )
            if ball_def:
                mch_ball_name = self.format_name(sub_name=self.name, extra="ball_ik", role=naming.ROLE_MCH, side=side)
                mch_ik_ball = core_framework.duplicate_bone(
                    self.armature_obj, ball_def, mch_ball_name,
                    collection_name="MCH", parent_name=rf_pivots[7]
                )

        self.edit_data = {
            "collar_def": collar_def, "ctrl_collar": ctrl_collar,
            "def_chain": def_chain, "ball_def": ball_def, "fk_chain": fk_chain,
            "org_chain": org_chain, "ctrl_fk_ball": ctrl_fk_ball,
            "ctrl_ik_target": ctrl_ik_target, "ctrl_pole": ctrl_pole,
            "ctrl_settings": ctrl_settings, "mch_ik": mch_ik, "limb_parent": limb_parent,
            "ctrl_tweaks": [ctrl_tweak_upper, ctrl_tweak_mid, ctrl_tweak_end],
            "rf_pivots": rf_pivots, "mch_ik_ball": mch_ik_ball,
            "total_chain_len": total_chain_len, "has_foot": has_foot
        }
        self.register_output("settings", ctrl_settings)
        self.register_output("ik_target", ctrl_ik_target)
        self.register_output("pole", ctrl_pole)
        self.register_output("hand_socket", def_chain[2])

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        settings_bone_name = self.edit_data["ctrl_settings"]
        for ctrl_name in self.controls:
            if ctrl_name in pose_bones and ctrl_name != settings_bone_name:
                pose_bones[ctrl_name]["_settings_bone"] = settings_bone_name
        d = self.edit_data
        shapes = self.context.shapes
        ik_endpoint = d["rf_pivots"][7] if d["has_foot"] else d["ctrl_ik_target"]
        ik_subtarget = d["rf_pivots"][8] if d["has_foot"] else d["ctrl_ik_target"]
        p_set = pose_bones[d["ctrl_settings"]]

        # ======================================================================
        # SNAPPING METADATA REGISTRATION
        # ======================================================================
        limb_type_str = self.params.get("limb_type", "Arm").capitalize()
        fk_list = [d["fk_chain"][0], d["fk_chain"][1], d["fk_chain"][2]]
        ik_sources = [d["mch_ik"][0], d["mch_ik"][1], ik_endpoint]

        # Include ball / toe if present
        if d["has_foot"] and d["ctrl_fk_ball"] and d["mch_ik_ball"]:
            fk_list.append(d["ctrl_fk_ball"])
            ik_sources.append(d["mch_ik_ball"])

        p_set["_snap_limb_type"] = limb_type_str
        p_set["_snap_fk_chain"] = ",".join(fk_list)
        p_set["_snap_ik_sources"] = ",".join(ik_sources)
        p_set["_snap_ik_ctrl"] = d["ctrl_ik_target"]
        p_set["_snap_pole_ctrl"] = d["ctrl_pole"]
        p_set["_snap_tweaks"] = ",".join(d["ctrl_tweaks"])
        # ======================================================================

        # 1. Register UI properties
        core_framework.create_custom_property(p_set, "IK_FK", default=1.0, min_val=0.0, max_val=1.0)
        core_framework.create_custom_property(p_set, "Stretch", default=0.0, min_val=0.0, max_val=1.0)
        core_framework.create_custom_property(p_set, "Show_Tweaks", default=0.0, min_val=0.0, max_val=1.0)

        if d["has_foot"] and d["rf_pivots"]:
            core_framework.create_custom_property(p_set, "Foot_Roll", default=0.0, min_val=-10.0, max_val=10.0)
            core_framework.create_custom_property(p_set, "Bank", default=0.0, min_val=-10.0, max_val=10.0)
            core_framework.create_custom_property(p_set, "Heel_Twist", default=0.0, min_val=-10.0, max_val=10.0)
            core_framework.create_custom_property(p_set, "Toe_Twist", default=0.0, min_val=-10.0, max_val=10.0)

        # 2. Collar / Hip Setup
        if d["collar_def"] and d["ctrl_collar"]:
            p_collar_ctrl = pose_bones[d["ctrl_collar"]]
            p_collar_def = pose_bones[d["collar_def"]]
            for c in list(p_collar_def.constraints):
                p_collar_def.constraints.remove(c)
            core_framework.add_constraint(p_collar_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=d["ctrl_collar"])
            core_framework.assign_bone_shape(p_collar_ctrl, shapes['Circle'], scale=(0.8, 0.8, 0.8))

        # 3. Setup IK/FK Blending onto the ORG Switch Chain
        systems_framework.setup_ik_fk_blending(
            self.armature_obj, d["org_chain"], d["fk_chain"][:2],
            d["mch_ik"][:2], d["ctrl_settings"]
        )

        # 4. End Joint (Hand/Foot) Binding
        p_def_end = pose_bones[d["def_chain"][2]]
        for c in list(p_def_end.constraints):
            p_def_end.constraints.remove(c)
        core_framework.add_constraint(p_def_end, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=d["fk_chain"][2])
        c_ik_end = core_framework.add_constraint(p_def_end, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ik_endpoint)
        core_framework.add_driver(c_ik_end, "influence", self.armature_obj, f'pose.bones["{d["ctrl_settings"]}"]["IK_FK"]')

        # 5. Widget shapes
        core_framework.assign_bone_shape(p_set, shapes['Gear'], scale=(0.4, 0.4, 0.4))
        core_framework.assign_bone_shape(pose_bones[d["ctrl_ik_target"]], shapes['Box'], scale=(0.8, 0.8, 0.8))
        core_framework.assign_bone_shape(pose_bones[d["ctrl_pole"]], shapes['Sphere'], scale=(0.3, 0.3, 0.3))
        for fk_c in d["fk_chain"]:
            core_framework.assign_bone_shape(pose_bones[fk_c], shapes['Circle'], scale=(0.7, 0.7, 0.7))
        if d["ctrl_fk_ball"]:
            core_framework.assign_bone_shape(pose_bones[d["ctrl_fk_ball"]], shapes['Circle'], scale=(0.5, 0.5, 0.5))

        for twk in d["ctrl_tweaks"]:
            core_framework.assign_bone_shape(pose_bones[twk], shapes['Sphere'], scale=(0.25, 0.25, 0.25))

        # 6. Dynamic Visibility Drivers (IK/FK & Tweaks)
        vis_drivers = []
        for ik_ctrl, base_s in [(d["ctrl_ik_target"], 0.8), (d["ctrl_pole"], 0.3)]:
            for a_idx in range(3):
                vis_drivers.append({
                    "source": {"bone": d["ctrl_settings"], "prop": "IK_FK", "min": 0.0, "max": 1.0, "default": 1.0},
                    "drivens": [{"bone": ik_ctrl, "channel": "custom_shape_scale_xyz", "index": a_idx, "rest": 0.0, "target": base_s, "curve": "linear"}]
                })

        fk_list = list(d["fk_chain"])
        if d["ctrl_fk_ball"]:
            fk_list.append(d["ctrl_fk_ball"])
        for fk_ctrl in fk_list:
            base_s = 0.5 if "ball" in fk_ctrl.lower() else 0.7
            for a_idx in range(3):
                vis_drivers.append({
                    "source": {"bone": d["ctrl_settings"], "prop": "IK_FK", "min": 1.0, "max": 0.0, "default": 1.0},
                    "drivens": [{"bone": fk_ctrl, "channel": "custom_shape_scale_xyz", "index": a_idx, "rest": 0.0, "target": base_s, "curve": "linear"}]
                })

        for twk_ctrl in d["ctrl_tweaks"]:
            for a_idx in range(3):
                vis_drivers.append({
                    "source": {"bone": d["ctrl_settings"], "prop": "Show_Tweaks", "min": 0.0, "max": 1.0, "default": 0.0},
                    "drivens": [{"bone": twk_ctrl, "channel": "custom_shape_scale_xyz", "index": a_idx, "rest": 0.0, "target": 0.25, "curve": "linear"}]
                })

        if "drivers" not in self.params:
            self.params["drivers"] = []
        self.params["drivers"].extend(vis_drivers)

        # 7. Solve IK Constraint
        pole_angle = solve_blender_pole_angle(self.armature_obj, d["mch_ik"][0], d["ctrl_pole"])
        ik_con = core_framework.add_constraint(
            pose_bones[d["mch_ik"][1]], 'IK', self.armature_obj,
            subtarget_bone=ik_subtarget, chain_count=2
        )
        ik_con.pole_target = self.armature_obj
        ik_con.pole_subtarget = d["ctrl_pole"]
        ik_con.pole_angle = pole_angle

        # 8. Drive IK Stretch natively on the MCH solving chain
        for mch_b in d["mch_ik"]:
            p_b = pose_bones[mch_b]
            p_b.bone.inherit_scale = 'NONE'
            core_framework.add_driver(
                target_id=p_b,
                target_datapath="ik_stretch",
                source_id=self.armature_obj,
                source_prop_path=f'pose.bones["{d["ctrl_settings"]}"]["Stretch"]',
                expression="stretch * 0.1",
                var_name="stretch"
            )

        # 9. Deform Bones: STRETCH_TO Tweak Targets
        twk_u, twk_m, twk_e = d["ctrl_tweaks"]
        def_u = pose_bones[d["def_chain"][0]]
        def_l = pose_bones[d["def_chain"][1]]

        def_u.bone.inherit_scale = 'NONE'
        def_l.bone.inherit_scale = 'NONE'
        pose_bones[d["def_chain"][2]].bone.inherit_scale = 'NONE'

        for c in list(def_u.constraints):
            def_u.constraints.remove(c)
        core_framework.add_constraint(def_u, 'COPY_LOCATION', self.armature_obj, subtarget_bone=twk_u)
        core_framework.add_constraint(def_u, 'STRETCH_TO', self.armature_obj, subtarget_bone=twk_m)

        for c in list(def_l.constraints):
            def_l.constraints.remove(c)
        core_framework.add_constraint(def_l, 'COPY_LOCATION', self.armature_obj, subtarget_bone=twk_m)
        core_framework.add_constraint(def_l, 'STRETCH_TO', self.armature_obj, subtarget_bone=twk_e)

        # 10. Reverse Foot Setup
        if d["has_foot"] and d["rf_pivots"]:
            self._setup_foot_mechanics(d)

    def _setup_foot_mechanics(self, d: dict) -> None:
        pose_bones = self.armature_obj.pose.bones

        for p_name in d["rf_pivots"][:-2]:
            pose_bones[p_name].rotation_mode = 'XYZ'

        # Toe blending & Counter-Rotation
        if d["ball_def"] and d["ctrl_fk_ball"] and d["mch_ik_ball"]:
            pbone_b = pose_bones[d["ball_def"]]
            for c in list(pbone_b.constraints):
                pbone_b.constraints.remove(c)
            core_framework.add_constraint(pbone_b, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=d["ctrl_fk_ball"])
            c_ik = core_framework.add_constraint(pbone_b, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=d["mch_ik_ball"])
            core_framework.add_driver(c_ik, "influence", self.armature_obj, f'pose.bones["{d["ctrl_settings"]}"]["IK_FK"]')
            pose_bones[d["mch_ik_ball"]].rotation_mode = 'XYZ'

        foot_drivers = [
            {"source": {"bone": d["ctrl_settings"], "prop": "Bank", "min": 0.0, "max": 10.0, "default": 0.0}, "drivens": [{"bone": d["rf_pivots"][0], "channel": "rotation_euler", "index": 1, "rest": 0.0, "target": 1.0, "curve": "linear"}]},
            {"source": {"bone": d["ctrl_settings"], "prop": "Bank", "min": 0.0, "max": -10.0, "default": 0.0}, "drivens": [{"bone": d["rf_pivots"][1], "channel": "rotation_euler", "index": 1, "rest": 0.0, "target": -1.0, "curve": "linear"}]},
            {"source": {"bone": d["ctrl_settings"], "prop": "Heel_Twist", "min": 0.0, "max": 10.0, "default": 0.0}, "drivens": [{"bone": d["rf_pivots"][2], "channel": "rotation_euler", "index": 0, "rest": 0.0, "target": 1.0, "curve": "linear"}]},
            {"source": {"bone": d["ctrl_settings"], "prop": "Toe_Twist", "min": 0.0, "max": 10.0, "default": 0.0}, "drivens": [{"bone": d["rf_pivots"][5], "channel": "rotation_euler", "index": 0, "rest": 0.0, "target": 1.0, "curve": "linear"}]},
            {"source": {"bone": d["ctrl_settings"], "prop": "Foot_Roll", "min": 0.0, "max": -10.0, "default": 0.0}, "drivens": [{"bone": d["rf_pivots"][3], "channel": "rotation_euler", "index": 2, "rest": 0.0, "target": 1.0, "curve": "linear"}]},
            {"source": {"bone": d["ctrl_settings"], "prop": "Foot_Roll", "min": 0.0, "max": 5.0, "default": 0.0}, "drivens": [{"bone": d["rf_pivots"][6], "channel": "rotation_euler", "index": 2, "rest": 0.0, "target": -0.5, "curve": "linear"}, *([{"bone": d["mch_ik_ball"], "channel": "rotation_euler", "index": 2, "rest": 0.0, "target": 0.5, "curve": "linear"}] if d["mch_ik_ball"] else [])]},
            {"source": {"bone": d["ctrl_settings"], "prop": "Foot_Roll", "min": 5.0, "max": 10.0, "default": 0.0}, "drivens": [{"bone": d["rf_pivots"][4], "channel": "rotation_euler", "index": 2, "rest": 0.0, "target": -0.5, "curve": "linear"}]}
        ]

        self.params["drivers"].extend(foot_drivers)