import bpy
import mathutils
from typing import List, Tuple, Optional
from .. import core_framework, base_component, naming


def _parse_bone_side(bone_name: str) -> Tuple[str, Optional[str]]:
    """Extracts base name and normalized side suffix from bone token."""
    for sep in [".", "_"]:
        if len(bone_name) > 2 and bone_name[-2] == sep:
            side_token = bone_name[-1]
            norm = naming.normalize_side(side_token)
            if norm:
                return bone_name[:-2], norm
    return bone_name, None


def _create_bone_proxy_empty(proxy_name, armature_obj, bone_name):
    existing = bpy.data.objects.get(proxy_name)
    if existing:
        return existing
    empty = bpy.data.objects.new(proxy_name, None)
    empty.empty_display_size = 0.01
    proxy_col = core_framework._get_or_create_proxy_collection()
    proxy_col.objects.link(empty)
    empty.hide_render = True
    empty.hide_select = True
    con = empty.constraints.new(type='COPY_LOCATION')
    con.target = armature_obj
    con.subtarget = bone_name
    return empty


def _create_cubic_nurbs_curve(curve_name, control_bone_names, armature_obj, side=None, mid_ctrl_name=None):
    """
    Builds a 5-point Cubic (order 4) NURBS curve with blended tangent drivers.
    Interpolates rest curvature cleanly while providing wide falloff propagation.
    """
    existing = bpy.data.objects.get(curve_name)
    if existing:
        return existing

    # Master bone proxies: [Start, Mid, End]
    proxies = [
        _create_bone_proxy_empty(
            naming.format_name(f"{curve_name}_proxy", side=side, index=idx),
            armature_obj,
            bone_name
        )
        for idx, bone_name in enumerate(control_bone_names)
    ]

    curve_data = bpy.data.curves.new(curve_name, type='CURVE')
    curve_data.dimensions = '3D'
    spline = curve_data.splines.new('NURBS')
    
    # 5 CV points for cubic curve: [0: Start, 1: Tangent_In, 2: Mid, 3: Tangent_Out, 4: End]
    spline.points.add(4)
    spline.use_endpoint_u = True
    spline.order_u = 4

    p_start, p_mid, p_end = proxies[0], proxies[1], proxies[2]

    # Initialize weights
    for pt in spline.points:
        pt.co[3] = 1.0

    # 1. Drive Point 0 (Start) directly from Start Proxy
    for axis_idx, transform_type in enumerate(('LOC_X', 'LOC_Y', 'LOC_Z')):
        fc = spline.points[0].driver_add("co", axis_idx)
        drv = fc.driver
        drv.type = 'SCRIPTED'
        drv.expression = "val"
        var = drv.variables.new()
        var.name = "val"
        var.type = 'TRANSFORMS'
        var.targets[0].id = p_start
        var.targets[0].transform_type = transform_type
        var.targets[0].transform_space = 'WORLD_SPACE'

    # 2. Drive Point 1 (Tangent In: Blend between Start and Mid with Falloff)
    for axis_idx, transform_type in enumerate(('LOC_X', 'LOC_Y', 'LOC_Z')):
        fc = spline.points[1].driver_add("co", axis_idx)
        drv = fc.driver
        drv.type = 'SCRIPTED'
        drv.expression = "start_loc + (mid_loc - start_loc) * (0.5 * falloff)"

        v_s = drv.variables.new()
        v_s.name = "start_loc"
        v_s.type = 'TRANSFORMS'
        v_s.targets[0].id = p_start
        v_s.targets[0].transform_type = transform_type
        v_s.targets[0].transform_space = 'WORLD_SPACE'

        v_m = drv.variables.new()
        v_m.name = "mid_loc"
        v_m.type = 'TRANSFORMS'
        v_m.targets[0].id = p_mid
        v_m.targets[0].transform_type = transform_type
        v_m.targets[0].transform_space = 'WORLD_SPACE'

        v_f = drv.variables.new()
        v_f.name = "falloff"
        v_f.type = 'SINGLE_PROP'
        v_f.targets[0].id_type = 'OBJECT'
        v_f.targets[0].id = armature_obj
        v_f.targets[0].data_path = f'pose.bones["{mid_ctrl_name}"]["Falloff"]'

    # 3. Drive Point 2 (Mid) directly from Mid Proxy
    for axis_idx, transform_type in enumerate(('LOC_X', 'LOC_Y', 'LOC_Z')):
        fc = spline.points[2].driver_add("co", axis_idx)
        drv = fc.driver
        drv.type = 'SCRIPTED'
        drv.expression = "val"
        var = drv.variables.new()
        var.name = "val"
        var.type = 'TRANSFORMS'
        var.targets[0].id = p_mid
        var.targets[0].transform_type = transform_type
        var.targets[0].transform_space = 'WORLD_SPACE'

    # 4. Drive Point 3 (Tangent Out: Blend between End and Mid with Falloff)
    for axis_idx, transform_type in enumerate(('LOC_X', 'LOC_Y', 'LOC_Z')):
        fc = spline.points[3].driver_add("co", axis_idx)
        drv = fc.driver
        drv.type = 'SCRIPTED'
        drv.expression = "end_loc + (mid_loc - end_loc) * (0.5 * falloff)"

        v_e = drv.variables.new()
        v_e.name = "end_loc"
        v_e.type = 'TRANSFORMS'
        v_e.targets[0].id = p_end
        v_e.targets[0].transform_type = transform_type
        v_e.targets[0].transform_space = 'WORLD_SPACE'

        v_m = drv.variables.new()
        v_m.name = "mid_loc"
        v_m.type = 'TRANSFORMS'
        v_m.targets[0].id = p_mid
        v_m.targets[0].transform_type = transform_type
        v_m.targets[0].transform_space = 'WORLD_SPACE'

        v_f = drv.variables.new()
        v_f.name = "falloff"
        v_f.type = 'SINGLE_PROP'
        v_f.targets[0].id_type = 'OBJECT'
        v_f.targets[0].id = armature_obj
        v_f.targets[0].data_path = f'pose.bones["{mid_ctrl_name}"]["Falloff"]'

    # 5. Drive Point 4 (End) directly from End Proxy
    for axis_idx, transform_type in enumerate(('LOC_X', 'LOC_Y', 'LOC_Z')):
        fc = spline.points[4].driver_add("co", axis_idx)
        drv = fc.driver
        drv.type = 'SCRIPTED'
        drv.expression = "val"
        var = drv.variables.new()
        var.name = "val"
        var.type = 'TRANSFORMS'
        var.targets[0].id = p_end
        var.targets[0].transform_type = transform_type
        var.targets[0].transform_space = 'WORLD_SPACE'

    curve_obj = bpy.data.objects.new(curve_name, curve_data)
    wgt_col = core_framework.get_or_create_widget_collection()
    wgt_col.objects.link(curve_obj)
    curve_obj.hide_render = True
    curve_obj.hide_select = True
    return curve_obj


def _build_spline_detail_chain(armature_obj, chain_defs, root_parent, label,
                               mch_collection, ctrl_collection, side=None):
    mch_bones = []
    ctrl_bones = []
    current_parent = root_parent
    for def_name in chain_defs:
        base_def_name, bone_side = _parse_bone_side(def_name)
        target_side = bone_side or side

        mch_name = naming.format_name(
            name=f"{label}_{base_def_name}",
            role=naming.ROLE_MCH,
            side=target_side
        )
        created_mch = core_framework.duplicate_bone(
            armature_obj, def_name, mch_name,
            collection_name=mch_collection, parent_name=current_parent, use_deform=False
        )
        current_parent = created_mch

        ctrl_name = naming.format_name(
            name=f"{label}_{base_def_name}",
            role=naming.ROLE_CTRL,
            side=target_side
        )
        created_ctrl = core_framework.duplicate_bone(
            armature_obj, def_name, ctrl_name,
            collection_name=ctrl_collection, parent_name=created_mch, use_deform=False
        )
        mch_bones.append(created_mch)
        ctrl_bones.append(created_ctrl)
    return {"defs": list(chain_defs), "mch": mch_bones, "ctrl": ctrl_bones}


def _finalize_spline_chain(armature_obj, curve_obj, chain_data, shapes, ctrl_scale=0.08):
    pose_bones = armature_obj.pose.bones
    mch_bones = chain_data["mch"]
    tip_pbone = pose_bones[mch_bones[-1]]
    for c in list(tip_pbone.constraints):
        if c.type == 'SPLINE_IK':
            tip_pbone.constraints.remove(c)
    
    con = core_framework.add_constraint(
        tip_pbone, 'SPLINE_IK', curve_obj,
        chain_count=len(mch_bones),
        use_curve_radius=False
    )
    # Disabled so joints keep their original chord distances along the curvature
    con.use_even_divisions = False

    for def_name, ctrl_name in zip(chain_data["defs"], chain_data["ctrl"]):
        p_def = pose_bones[def_name]
        for c in list(p_def.constraints):
            p_def.constraints.remove(c)
        core_framework.add_constraint(p_def, 'COPY_TRANSFORMS', armature_obj, subtarget_bone=ctrl_name)
        core_framework.assign_bone_shape(
            pose_bones[ctrl_name], shapes['Sphere'], scale=(ctrl_scale, ctrl_scale, ctrl_scale)
        )


@base_component.register_component("SplineIKChain")
class SplineIKChainComponent(base_component.BaseRigComponent):
    """
    Cubic NURBS Spline IK system with falloff-driven tangent points to prevent rest offset drift.
    """
    def validate(self) -> List[str]:
        errors = []
        chain = self.params.get("deform_chain", [])
        if len(chain) < 2:
            errors.append("SplineIKChain requires at least 2 bones in 'deform_chain'.")
        for b in chain:
            if not core_framework.find_bone_name(self.armature_obj, b):
                errors.append(f"Deform bone '{b}' not found.")
        return errors

    def build_edit(self) -> None:
        edit_bones = self.armature_obj.data.edit_bones
        def_chain = [core_framework.find_bone_name(self.armature_obj, b) for b in self.params["deform_chain"]]
        parent_bone = self.resolve_parent_socket()
        collection = self.params.get("collection", "CTRL_Face")

        # Derive normalized side
        comp_side = self.params.get("side")
        if comp_side is not None:
            side = naming.normalize_side(comp_side)
        else:
            _, side = _parse_bone_side(def_chain[0])

        self.side = side
        
        start_master = self.context.resolve_socket(self.params.get("start_master"))
        mid_master = self.context.resolve_socket(self.params.get("mid_master"))
        end_master = self.context.resolve_socket(self.params.get("end_master"))

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
        
        self.chain_data = _build_spline_detail_chain(
            self.armature_obj, def_chain, parent_bone, self.name, "MCH", collection, side=side
        )

        self.register_output("start", start_master)
        self.register_output("mid", mid_master)
        self.register_output("end", end_master)
        self.register_output("tip", self.chain_data["ctrl"][-1])
        for idx, c_b in enumerate(self.chain_data["ctrl"]):
            self.register_output(f"detail_{idx:02d}", c_b)
            self.register_control(c_b)

    def build_pose(self) -> None:
        ctrl_scale = self.params.get("ctrl_scale", 0.08)
        default_falloff = self.params.get("default_falloff", 1.0)
        shapes = self.context.shapes
        pose_bones = self.armature_obj.pose.bones
        settings_bone_name = self.edit_data.get("ctrl_settings") if hasattr(self, "edit_data") else None
        if settings_bone_name:
            for ctrl_name in self.controls:
                if ctrl_name in pose_bones and ctrl_name != settings_bone_name:
                    pose_bones[ctrl_name]["_settings_bone"] = settings_bone_name

        mid_ctrl = self.master_ctrls[1]
        if mid_ctrl in pose_bones:
            core_framework.create_custom_property(
                pose_bones[mid_ctrl], "Falloff", default=default_falloff, min_val=0.1, max_val=2.0,
                description="Controls span breadth of the curve influence"
            )

        curve_name = naming.format_name(name=f"{self.name}_curve", side=self.side)
        self.curve_obj = _create_cubic_nurbs_curve(
            curve_name, self.master_ctrls, self.armature_obj, side=self.side, mid_ctrl_name=mid_ctrl
        )
        
        _finalize_spline_chain(
            self.armature_obj, self.curve_obj, self.chain_data, shapes, ctrl_scale=ctrl_scale
        )
        
        for m_ctrl in self.master_ctrls:
            if m_ctrl in pose_bones:
                core_framework.assign_bone_shape(
                    pose_bones[m_ctrl], shapes['Box'], scale=(ctrl_scale * 1.2, ctrl_scale * 1.2, ctrl_scale * 1.2)
                )