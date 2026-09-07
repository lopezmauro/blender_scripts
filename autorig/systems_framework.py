import math
import bpy
import mathutils
from typing import Dict, Any, List, Optional
from . import core_framework


def build_fk_chain(armature_obj, deform_chain, prefix, collection_name, parent_name):
    fk_bones = []
    current_parent = parent_name
    for def_name in deform_chain:
        # Preserve original bone casing exactly instead of capitalising
        fk_name = f"{prefix}{def_name}"
        created = core_framework.duplicate_bone(
            armature_obj, def_name, fk_name,
            collection_name=collection_name, parent_name=current_parent
        )
        fk_bones.append(created)
        current_parent = created
    return fk_bones


def build_ik_chain(armature_obj, deform_chain, ik_ctrl_name, pole_name, collection_name, parent_name, guide_pos):
    edit_bones = armature_obj.data.edit_bones
    mch_bones = []
    current_parent = parent_name
    for def_name in deform_chain[:2]:
        mch_name = f"MCH_IK_{def_name.capitalize()}"
        created = core_framework.duplicate_bone(
            armature_obj, def_name, mch_name,
            collection_name="MCH", parent_name=current_parent
        )
        mch_bones.append(created)
        current_parent = created

    eb_upper = edit_bones[mch_bones[0]]
    eb_lower = edit_bones[mch_bones[1]]
    roll_upper = eb_upper.roll
    roll_lower = eb_lower.roll

    joint_mid = (eb_upper.tail + eb_lower.head) * 0.5
    bend_dir = (guide_pos - joint_mid).normalized()
    eb_upper.tail += bend_dir * 0.005
    eb_lower.head += bend_dir * 0.005

    eb_upper.roll = roll_upper
    eb_lower.roll = roll_lower
    return mch_bones


def build_reverse_foot(armature_obj, side, foot_def, ball_def, ik_foot_ctrl, collection_name):
    edit_bones = armature_obj.data.edit_bones
    eb_foot = edit_bones[foot_def]
    foot_head = eb_foot.head.copy()

    heel_tw_name = f"GUIDE_Heel_Twist{side}"
    toe_tw_name = f"GUIDE_Toe_Twist{side}"
    bank_in_name = f"GUIDE_Bank_In{side}"
    bank_out_name = f"GUIDE_Bank_Out{side}"

    heel_pos = edit_bones[heel_tw_name].head.copy() if heel_tw_name in edit_bones else foot_head + mathutils.Vector((0, -0.08, 0))
    toe_pos = edit_bones[toe_tw_name].head.copy() if toe_tw_name in edit_bones else (edit_bones[ball_def].tail.copy() if ball_def else foot_head + mathutils.Vector((0, 0.15, 0)))
    ball_pos = edit_bones[ball_def].head.copy() if ball_def else (foot_head + toe_pos) * 0.5

    bank_in_pos = edit_bones[bank_in_name].head.copy() if bank_in_name in edit_bones else foot_head + mathutils.Vector((0.1, 0, 0))
    bank_out_pos = edit_bones[bank_out_name].head.copy() if bank_out_name in edit_bones else foot_head + mathutils.Vector((-0.1, 0, 0))

    pivots = [
        ("MCH_Bank_In", bank_in_pos),
        ("MCH_Bank_Out", bank_out_pos),
        ("MCH_Heel_Twist", heel_pos.copy()),
        ("MCH_Heel_Pivot", heel_pos),
        ("MCH_Toe_Tip_Pivot", toe_pos),
        ("MCH_Toe_Twist", toe_pos.copy()),
        ("MCH_Ball_Pivot", ball_pos),
        ("MCH_IK_Foot_Socket", foot_head)
    ]
    parent = ik_foot_ctrl
    created_pivots = []

    for name, pos in pivots:
        full_name = f"{name}{side}"
        b = core_framework.create_bone(armature_obj, full_name, pos, pos + mathutils.Vector((0, 0.1, 0)), parent_name=parent, collection_name="MCH")
        source = edit_bones[b]
        target = edit_bones[foot_def]
        source.tail = source.head + target.vector.normalized() * 0.05
        source.roll = target.roll
        created_pivots.append(b)
        parent = b

    mch_target = core_framework.create_bone(armature_obj, f"MCH_IK_Leg_Target{side}", foot_head, foot_head + mathutils.Vector((0, 0.05, 0)), parent_name=created_pivots[-1], collection_name="MCH")
    return created_pivots + [mch_target]


def setup_ik_fk_blending(armature_obj, def_chain, fk_chain, ik_chain, settings_ctrl):
    pose_bones = armature_obj.pose.bones
    for def_b, fk_b, ik_b in zip(def_chain, fk_chain, ik_chain):
        pbone = pose_bones[def_b]
        for c in list(pbone.constraints):
            pbone.constraints.remove(c)
        core_framework.add_constraint(pbone, 'COPY_TRANSFORMS', armature_obj, subtarget_bone=fk_b)
        c_ik = core_framework.add_constraint(pbone, 'COPY_TRANSFORMS', armature_obj, subtarget_bone=ik_b)
        drv = c_ik.driver_add("influence").driver
        drv.type = 'SCRIPTED'
        drv.expression = "ik_fk"
        v = drv.variables.new()
        v.name = "ik_fk"
        v.type = 'SINGLE_PROP'
        v.targets[0].id = armature_obj
        v.targets[0].data_path = f'pose.bones["{settings_ctrl}"]["IK_FK"]'


# ==============================================================================
# UNIVERSAL CONFIGURABLE DRIVER ENGINE
# ==============================================================================

def build_curve_expression(curve_type: str, mid_val: Optional[float] = None) -> str:
    ctype = curve_type.lower()
    if ctype == "linear":
        return "u"
    elif ctype == "ease_in":
        y_mid = 0.25 if mid_val is None else mid_val
        a = 2.0 - (4.0 * y_mid)
        b = 1.0 - a
        return f"(({a:.4f} * (u**2)) + ({b:.4f} * u))"
    elif ctype == "ease_out":
        y_mid = 0.75 if mid_val is None else mid_val
        a = 2.0 - (4.0 * y_mid)
        b = 1.0 - a
        return f"(({a:.4f} * (u**2)) + ({b:.4f} * u))"
    elif ctype in ("ease_in_out", "ease_inout", "smoothstep"):
        if mid_val is None or abs(mid_val - 0.5) < 1e-4:
            return "((u**2) * (3.0 - (2.0 * u)))"
        else:
            k_in = 8.0 * mid_val
            k_out = 8.0 * (1.0 - mid_val)
            return f"({k_in:.4f} * (u**2) if u <= 0.5 else 1.0 - ({k_out:.4f} * ((1.0 - u)**2)))"
    return "u"


def apply_configurable_drivers(armature_obj: bpy.types.Object, context, driver_specs: List[Dict[str, Any]]) -> None:
    """
    Universal driver compilation supporting single/multi sources, Shape Keys,
    bone transforms, constraint weights, and UI widget scale channels.
    """
    pose_bones = armature_obj.pose.bones

    for spec in driver_specs:
        sources = spec.get("sources", [])
        if not sources and "source" in spec:
            sources = [spec["source"]]

        # Ensure all required properties exist on source pose bones
        for src in sources:
            if src.get("type", "SINGLE_PROP") == "SINGLE_PROP":
                raw_src_bone = src.get("bone")
                resolved_src_bone = context.resolve_socket(raw_src_bone)
                if resolved_src_bone and resolved_src_bone in pose_bones:
                    p_src = pose_bones[resolved_src_bone]
                    prop_name = src.get("prop", "Param")
                    min_v = src.get("min", 0.0)
                    max_v = src.get("max", 1.0)
                    default_v = src.get("default", 0.0)
                    if prop_name not in p_src:
                        core_framework.create_custom_property(
                            p_src, prop_name, default=default_v,
                            min_val=min(min_v, max_v), max_val=max(min_v, max_v)
                        )

        # Process each driven channel definition
        for d in spec.get("drivens", []):
            target_mode = d.get("type", "BONE")  # 'BONE', 'SHAPE_KEY', or 'CONSTRAINT'
            target_id = None
            target_path = d.get("channel", "location")
            index = d.get("index", -1)

            if target_mode == "SHAPE_KEY":
                mesh_name = d.get("mesh")
                mesh_obj = bpy.data.objects.get(mesh_name) if mesh_name else None
                shape_name = d.get("shape_key")
                if mesh_obj and mesh_obj.data.shape_keys and shape_name in mesh_obj.data.shape_keys.key_blocks:
                    target_id = mesh_obj.data.shape_keys.key_blocks[shape_name]
                    target_path = "value"
                else:
                    continue

            elif target_mode == "CONSTRAINT":
                raw_bone = d.get("bone")
                resolved_bone = context.resolve_socket(raw_bone)
                con_name = d.get("constraint")
                if resolved_bone and resolved_bone in pose_bones:
                    p_bone = pose_bones[resolved_bone]
                    if con_name in p_bone.constraints:
                        target_id = p_bone.constraints[con_name]
                        target_path = d.get("property", "influence")
                if not target_id:
                    continue

            else:  # Standard PoseBone channel
                raw_driven_bone = d.get("bone")
                resolved_driven_bone = context.resolve_socket(raw_driven_bone)
                if not resolved_driven_bone or resolved_driven_bone not in pose_bones:
                    continue
                target_id = pose_bones[resolved_driven_bone]

            # Build multi-variable driver expression
            curve_type = d.get("curve", "linear")
            mid_val = d.get("mid_val", None)
            rest_val = d.get("rest", 0.0)
            target_val = d.get("target", 1.0)
            mult = d.get("multiplier", 1.0)

            # Determine whether single source or complex multi-variable expression
            if len(sources) == 1 and "expression" not in d:
                src = sources[0]
                min_v = src.get("min", 0.0)
                max_v = src.get("max", 1.0)
                if min_v == max_v:
                    continue
                elif min_v < max_v:
                    norm_u = f"max(0.0, min(1.0, (val - {min_v}) / {max_v - min_v}))"
                else:
                    norm_u = f"max(0.0, min(1.0, ({min_v} - val) / {min_v - max_v}))"

                curve_expr = build_curve_expression(curve_type, mid_val)
                evaluated_curve = curve_expr.replace("u", f"({norm_u})")
                delta = target_val - rest_val
                final_expr = f"({rest_val} + ({delta:.4f} * {evaluated_curve})) * {mult:.4f}"

                core_framework.add_driver(
                    target_id=target_id,
                    target_datapath=target_path,
                    source_id=armature_obj,
                    source_prop_path=f'pose.bones["{context.resolve_socket(src.get("bone"))}"]["{src.get("prop")}"]',
                    expression=final_expr,
                    var_name="val",
                    index=index
                )
            else:
                # Custom multi-variable scripted driver
                final_expr = d.get("expression", "0.0")
                driver_fcurve = target_id.driver_add(target_path, index) if index >= 0 else target_id.driver_add(target_path)
                drv = driver_fcurve.driver
                drv.type = 'SCRIPTED'
                drv.expression = final_expr

                for v in list(drv.variables):
                    drv.variables.remove(v)

                for src in sources:
                    v_name = src.get("var_name", "var")
                    v_type = src.get("type", "SINGLE_PROP")
                    var = drv.variables.new()
                    var.name = v_name

                    if v_type == "TRANSFORMS":
                        var.type = 'TRANSFORMS'
                        t = var.targets[0]
                        t.id = armature_obj
                        t.bone_target = context.resolve_socket(src.get("bone"))
                        t.transform_type = src.get("transform_type", 'ROT_X')
                        t.transform_space = src.get("transform_space", 'LOCAL_SPACE')
                    else:
                        var.type = 'SINGLE_PROP'
                        t = var.targets[0]
                        t.id = armature_obj
                        resolved_b = context.resolve_socket(src.get("bone"))
                        t.data_path = f'pose.bones["{resolved_b}"]["{src.get("prop")}"]'