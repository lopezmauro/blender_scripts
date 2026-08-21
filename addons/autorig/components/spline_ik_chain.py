import bpy
import mathutils
from typing import List
from .. import core_framework, base_component


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

def _create_driven_curve(curve_name, control_bone_names, armature_obj, spline_type="NURBS"):
    existing = bpy.data.objects.get(curve_name)
    if existing:
        return existing
    
    proxies = [
        _create_bone_proxy_empty(f"PROXY_{curve_name}_{idx:02d}", armature_obj, bone_name)
        for idx, bone_name in enumerate(control_bone_names)
    ]
    
    curve_data = bpy.data.curves.new(curve_name, type='CURVE')
    curve_data.dimensions = '3D'
    
    if spline_type.upper() == 'BEZIER':
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(len(proxies) - 1)
        arm_data = armature_obj.data
        for idx, proxy in enumerate(proxies):
            bp = spline.bezier_points[idx]
            bp.handle_left_type = 'AUTO'
            bp.handle_right_type = 'AUTO'
            b_name = control_bone_names[idx]
            if b_name in arm_data.bones:
                rest_pos = armature_obj.matrix_world @ arm_data.bones[b_name].head_local
                bp.co = rest_pos
                bp.handle_left = rest_pos
                bp.handle_right = rest_pos
            for axis_idx, transform_type in enumerate(('LOC_X', 'LOC_Y', 'LOC_Z')):
                fcurve = bp.driver_add("co", axis_idx)
                drv = fcurve.driver
                drv.type = 'SCRIPTED'
                drv.expression = "val"
                var = drv.variables.new()
                var.name = "val"
                var.type = 'TRANSFORMS'
                target = var.targets[0]
                target.id = proxy
                target.transform_type = transform_type
                target.transform_space = 'WORLD_SPACE'
    else:
        spline = curve_data.splines.new('NURBS')
        spline.points.add(len(proxies) - 1)
        spline.use_endpoint_u = True
        spline.order_u = min(3, len(proxies))
        for idx, proxy in enumerate(proxies):
            point = spline.points[idx]
            point.co[3] = 1.0
            for axis_idx, transform_type in enumerate(('LOC_X', 'LOC_Y', 'LOC_Z')):
                fcurve = point.driver_add("co", axis_idx)
                drv = fcurve.driver
                drv.type = 'SCRIPTED'
                drv.expression = "val"
                var = drv.variables.new()
                var.name = "val"
                var.type = 'TRANSFORMS'
                target = var.targets[0]
                target.id = proxy
                target.transform_type = transform_type
                target.transform_space = 'WORLD_SPACE'

    curve_obj = bpy.data.objects.new(curve_name, curve_data)
    wgt_col = core_framework.get_or_create_widget_collection()
    wgt_col.objects.link(curve_obj)
    curve_obj.hide_render = True
    curve_obj.hide_select = True
    return curve_obj

def _build_spline_detail_chain(armature_obj, chain_defs, root_parent, label,
                               mch_collection, ctrl_collection):
    mch_bones = []
    ctrl_bones = []
    current_parent = root_parent
    for def_name in chain_defs:
        mch_name = f"MCH_{label}_{def_name}"
        created_mch = core_framework.duplicate_bone(
            armature_obj, def_name, mch_name,
            collection_name=mch_collection, parent_name=current_parent, use_deform=False
        )
        current_parent = created_mch
        ctrl_name = f"CTRL_{label}_{def_name}"
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
    if hasattr(con, "use_even_divisions"):
        con.use_even_divisions = True

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
    Curve-driven Spline IK system connecting master hooks (start/mid/end)
    with intermediate detail FK controls.
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
        
        start_master = self.context.resolve_socket(self.params.get("start_master"))
        mid_master = self.context.resolve_socket(self.params.get("mid_master"))
        end_master = self.context.resolve_socket(self.params.get("end_master"))

        if not start_master:
            start_master = core_framework.create_bone(
                self.armature_obj, f"CTRL_{self.name}_Start",
                head=edit_bones[def_chain[0]].head.copy(),
                tail=edit_bones[def_chain[0]].head.copy() + mathutils.Vector((0.0, 0.0, 0.025)),
                parent_name=parent_bone, collection_name=collection
            )

        if not mid_master:
            mid_idx = len(def_chain) // 2
            mid_pos = edit_bones[def_chain[mid_idx]].head.copy()
            mid_master = core_framework.create_bone(
                self.armature_obj, f"CTRL_{self.name}_Mid",
                head=mid_pos, tail=mid_pos + mathutils.Vector((0.0, 0.0, 0.025)),
                parent_name=parent_bone, collection_name=collection
            )

        if not end_master:
            end_master = core_framework.create_bone(
                self.armature_obj, f"CTRL_{self.name}_End",
                head=edit_bones[def_chain[-1]].tail.copy(),
                tail=edit_bones[def_chain[-1]].tail.copy() + mathutils.Vector((0.0, 0.0, 0.025)),
                parent_name=parent_bone, collection_name=collection
            )

        self.master_ctrls = [start_master, mid_master, end_master]
        
        self.chain_data = _build_spline_detail_chain(
            self.armature_obj, def_chain, parent_bone, self.name, "MCH", collection
        )

        # Register master and detail sockets
        self.register_output("start", start_master)
        self.register_output("mid", mid_master)
        self.register_output("end", end_master)
        self.register_output("tip", self.chain_data["ctrl"][-1])
        for idx, c_b in enumerate(self.chain_data["ctrl"]):
            self.register_output(f"detail_{idx:02d}", c_b)

    def build_pose(self) -> None:
        ctrl_scale = self.params.get("ctrl_scale", 0.08)
        spline_type = self.params.get("spline_type", "NURBS")
        shapes = self.context.shapes
        pose_bones = self.armature_obj.pose.bones
        
        curve_name = f"CURVE_{self.name}"
        self.curve_obj = _create_driven_curve(curve_name, self.master_ctrls, self.armature_obj, spline_type=spline_type)
        
        _finalize_spline_chain(
            self.armature_obj, self.curve_obj, self.chain_data, shapes, ctrl_scale=ctrl_scale
        )
        
        for m_ctrl in self.master_ctrls:
            if m_ctrl in pose_bones:
                core_framework.assign_bone_shape(
                    pose_bones[m_ctrl], shapes['Box'], scale=(ctrl_scale * 1.2, ctrl_scale * 1.2, ctrl_scale * 1.2)
                )