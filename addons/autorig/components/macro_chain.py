from typing import List, Dict, Any
from blender_scripts.autorig import core_framework
from blender_scripts.autorig.base_component import BaseRigComponent, register_component


@register_component("MacroChain")
class MacroChainComponent(BaseRigComponent):
    """
    Clean alternating hierarchy (MCH -> CTRL -> MCH -> CTRL).
    Generates declarative driver specifications for curls, twists, spreads, and shape scales.
    """
    def validate(self) -> List[str]:
        errors = []
        chains = self.params.get("chains", {})
        if not chains:
            errors.append("No 'chains' dictionary specified.")
        for k, b_list in chains.items():
            for b in b_list:
                if not core_framework.find_bone_name(self.armature_obj, b):
                    errors.append(f"Chain '{k}' references missing bone '{b}'.")
        return errors

    def build_edit(self) -> None:
        chains = self.params.get("chains", {})
        fallback_parent = self.resolve_parent_socket()
        per_chain_parents = self.params.get("parent_sockets", {})
        collection = self.params.get("collection", "CTRL_Fingers")

        self.built_chains = {}
        for chain_key, bone_names in chains.items():
            socket_target = per_chain_parents.get(chain_key)
            parent_bone = self.context.resolve_socket(socket_target) if socket_target else fallback_parent

            ctrl_bones, mch_bones, def_bones = [], [], []
            current_parent = parent_bone

            for idx, raw_name in enumerate(bone_names):
                resolved_def = core_framework.find_bone_name(self.armature_obj, raw_name)
                mch_name = f"MCH_{self.name}_{resolved_def}"
                created_mch = core_framework.duplicate_bone(
                    self.armature_obj, resolved_def, mch_name,
                    collection_name="MCH", parent_name=current_parent, use_deform=False
                )
                ctrl_name = f"CTRL_{self.name}_{resolved_def}"
                created_ctrl = core_framework.duplicate_bone(
                    self.armature_obj, resolved_def, ctrl_name,
                    collection_name=collection, parent_name=created_mch, use_deform=False
                )
                ctrl_bones.append(created_ctrl)
                mch_bones.append(created_mch)
                def_bones.append(resolved_def)
                current_parent = created_ctrl

            self.built_chains[chain_key] = {
                "ctrls": ctrl_bones, "mchs": mch_bones, "defs": def_bones
            }

        settings_target = self.params.get("settings_bone")
        first_chain = list(chains.keys())[0]
        self.settings_bone_name = self.context.resolve_socket(settings_target) if settings_target else self.built_chains[first_chain]["ctrls"][0]
        self.register_output("settings", self.settings_bone_name)

    def build_pose(self) -> None:
        pose_bones = self.armature_obj.pose.bones
        p_settings = pose_bones[self.settings_bone_name]
        shapes = self.context.shapes
        side_mult = self.params.get("side_mult", 1.0)
        rules = self.params.get("rules", {})

        is_hand = any(k in ("thumb", "index", "middle", "pinky") for k in self.built_chains.keys())

        # 1. Register UI properties
        if is_hand:
            for p, d, mn, mx in [
                ("Fist", 0.0, -2.0, 2.0),
                ("Finger_Spread", 0.0, -2.0, 2.0),
                ("Thumb_Abduct", 0.0, -2.0, 2.0),
                ("Thumb_Spread", 0.0, -2.0, 2.0),
                ("Show_Controls", 1.0, 0.0, 1.0)
            ]:
                if p not in p_settings:
                    core_framework.create_custom_property(p_settings, p, default=d, min_val=mn, max_val=mx)

        for chain_key in self.built_chains.keys():
            prefix = chain_key.capitalize()
            for action in ("Curl", "Twist", "Bend"):
                prop = f"{prefix}_{action}"
                if prop not in p_settings:
                    core_framework.create_custom_property(p_settings, prop, default=0.0, min_val=-2.0, max_val=2.0)

        # 2. Assign shapes and constraint bindings
        driver_specs = []
        for chain_key, cdata in self.built_chains.items():
            rule = rules.get(chain_key, {})
            fist_curl = rule.get("fist_curl", 1.0)
            fist_twist = rule.get("fist_twist", 0.0)
            fist_spread = rule.get("fist_spread", 0.0)
            spread_factor = rule.get("spread_factor", 0.0)

            prefix = chain_key.capitalize()
            prop_curl = f"{prefix}_Curl"
            prop_twist = f"{prefix}_Twist"
            prop_bend = f"{prefix}_Bend"

            for idx, (c_name, m_name, d_name) in enumerate(zip(cdata["ctrls"], cdata["mchs"], cdata["defs"])):
                p_ctrl = pose_bones[c_name]
                p_mch = pose_bones[m_name]
                p_def = pose_bones[d_name]

                p_ctrl.rotation_mode = 'XYZ'
                p_mch.rotation_mode = 'XYZ'

                base_scale = 0.35 if idx == 0 else 0.2
                core_framework.assign_bone_shape(p_ctrl, shapes['Circle'], scale=(base_scale, base_scale, base_scale))

                for c in list(p_def.constraints):
                    p_def.constraints.remove(c)
                core_framework.add_constraint(p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=c_name)

                # Generate dynamic multi-source driver specifications
                # Scale visibility
                for a_idx in range(3):
                    driver_specs.append({
                        "source": {"bone": self.settings_bone_name, "prop": "Show_Controls", "min": 0.0, "max": 1.0, "default": 1.0},
                        "drivens": [{
                            "bone": c_name,
                            "channel": "custom_shape_scale_xyz",
                            "index": a_idx,
                            "rest": 0.0,
                            "target": base_scale,
                            "curve": "linear"
                        }]
                    })

                # Rotation X (Bend / Spread)
                if is_hand and idx == 0 and chain_key == "thumb":
                    driver_specs.append({
                        "sources": [
                            {"bone": self.settings_bone_name, "prop": "Thumb_Spread", "var_name": "t_spread"},
                            {"bone": self.settings_bone_name, "prop": "Fist", "var_name": "fist"}
                        ],
                        "drivens": [{
                            "bone": m_name, "channel": "rotation_euler", "index": 0,
                            "expression": f"(t_spread + (fist * {fist_spread})) * {-0.35 * side_mult:.4f}"
                        }]
                    })
                elif is_hand and idx == 0 and spread_factor != 0.0:
                    driver_specs.append({
                        "source": {"bone": self.settings_bone_name, "prop": "Finger_Spread", "min": 0.0, "max": 1.0, "default": 0.0},
                        "drivens": [{
                            "bone": m_name, "channel": "rotation_euler", "index": 0,
                            "rest": 0.0, "target": spread_factor * side_mult, "curve": "linear"
                        }]
                    })
                else:
                    driver_specs.append({
                        "source": {"bone": self.settings_bone_name, "prop": prop_bend, "min": 0.0, "max": 1.0, "default": 0.0},
                        "drivens": [{
                            "bone": m_name, "channel": "rotation_euler", "index": 0,
                            "rest": 0.0, "target": 0.5 * side_mult, "curve": "linear"
                        }]
                    })

                # Rotation Y (Twist)
                if is_hand:
                    driver_specs.append({
                        "sources": [
                            {"bone": self.settings_bone_name, "prop": prop_twist, "var_name": "twist"},
                            {"bone": self.settings_bone_name, "prop": "Fist", "var_name": "fist"}
                        ],
                        "drivens": [{
                            "bone": m_name, "channel": "rotation_euler", "index": 1,
                            "expression": f"(twist + (fist * {fist_twist})) * {0.5 * side_mult:.4f}"
                        }]
                    })
                else:
                    driver_specs.append({
                        "source": {"bone": self.settings_bone_name, "prop": prop_twist, "min": 0.0, "max": 1.0, "default": 0.0},
                        "drivens": [{
                            "bone": m_name, "channel": "rotation_euler", "index": 1,
                            "rest": 0.0, "target": 0.5 * side_mult, "curve": "linear"
                        }]
                    })

                # Rotation Z (Curl / Abduct)
                if is_hand and chain_key == "thumb" and idx == 0:
                    driver_specs.append({
                        "source": {"bone": self.settings_bone_name, "prop": "Thumb_Abduct", "min": 0.0, "max": 1.0, "default": 0.0},
                        "drivens": [{
                            "bone": m_name, "channel": "rotation_euler", "index": 2,
                            "rest": 0.0, "target": 0.5 * side_mult, "curve": "linear"
                        }]
                    })
                elif is_hand:
                    driver_specs.append({
                        "sources": [
                            {"bone": self.settings_bone_name, "prop": prop_curl, "var_name": "curl"},
                            {"bone": self.settings_bone_name, "prop": "Fist", "var_name": "fist"}
                        ],
                        "drivens": [{
                            "bone": m_name, "channel": "rotation_euler", "index": 2,
                            "expression": f"((fist * {fist_curl}) + curl) * 0.75"
                        }]
                    })
                else:
                    driver_specs.append({
                        "source": {"bone": self.settings_bone_name, "prop": prop_curl, "min": 0.0, "max": 1.0, "default": 0.0},
                        "drivens": [{
                            "bone": m_name, "channel": "rotation_euler", "index": 2,
                            "rest": 0.0, "target": 0.75, "curve": "linear"
                        }]
                    })

        # Append generated driver specs into params for the driver pass
        if "drivers" not in self.params:
            self.params["drivers"] = []
        self.params["drivers"].extend(driver_specs)