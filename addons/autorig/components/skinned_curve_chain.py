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


def _build_skinned_cv_curve(curve_name: str, armature_obj: bpy.types.Object,
                            point_rest_positions: List[mathutils.Vector],
                            anchor_bone_map: List[Tuple[str, str, str]],
                            w_start: List[float], w_mid: List[float], w_end: List[float]):
    """
    Creates an N+1 CV NURBS curve whose points are driven by the world space
    transforms of anchor bones parented to the master controls.
    """
    existing = bpy.data.objects.get(curve_name)
    if existing:
        bpy.data.objects.remove(existing, do_unlink=True)

    curve_data = bpy.data.curves.new(curve_name, type='CURVE')
    curve_data.dimensions = '3D'
    spline = curve_data.splines.new('NURBS')

    num_pts = len(point_rest_positions)
    spline.points.add(num_pts - 1)
    spline.use_endpoint_u = True
    spline.order_u = min(4, num_pts)

    for i, rest_world_pos in enumerate(point_rest_positions):
        pt = spline.points[i]
        pt.co[0] = rest_world_pos.x
        pt.co[1] = rest_world_pos.y
        pt.co[2] = rest_world_pos.z
        pt.co[3] = 1.0

        ws = float(w_start[i])
        wm = float(w_mid[i])
        we = float(w_end[i])

        anchors = anchor_bone_map[i]  # (anchor_start, anchor_mid, anchor_end)

        for axis_idx, transform_type in enumerate(('LOC_X', 'LOC_Y', 'LOC_Z')):
            fc = pt.driver_add("co", axis_idx)
            drv = fc.driver
            drv.type = 'SCRIPTED'

            for v in list(drv.variables):
                drv.variables.remove(v)

            expr_terms = []
            if ws > 0.0:
                expr_terms.append(f"({ws:.4f} * s_loc)")
                vs = drv.variables.new()
                vs.name = "s_loc"
                vs.type = 'TRANSFORMS'
                vs.targets[0].id = armature_obj
                vs.targets[0].bone_target = anchors[0]
                vs.targets[0].transform_type = transform_type
                vs.targets[0].transform_space = 'WORLD_SPACE'

            if wm > 0.0:
                expr_terms.append(f"({wm:.4f} * m_loc)")
                vm = drv.variables.new()
                vm.name = "m_loc"
                vm.type = 'TRANSFORMS'
                vm.targets[0].id = armature_obj
                vm.targets[0].bone_target = anchors[1]
                vm.targets[0].transform_type = transform_type
                vm.targets[0].transform_space = 'WORLD_SPACE'

            if we > 0.0:
                expr_terms.append(f"({we:.4f} * e_loc)")
                ve = drv.variables.new()
                ve.name = "e_loc"
                ve.type = 'TRANSFORMS'
                ve.targets[0].id = armature_obj
                ve.targets[0].bone_target = anchors[2]
                ve.targets[0].transform_type = transform_type
                ve.targets[0].transform_space = 'WORLD_SPACE'

            drv.expression = " + ".join(expr_terms) if expr_terms else "0.0"

    curve_obj = bpy.data.objects.new(curve_name, curve_data)
    wgt_col = core_framework.get_or_create_widget_collection()
    wgt_col.objects.link(curve_obj)
    curve_obj.hide_render = True
    curve_obj.hide_select = True
    return curve_obj


@base_component.register_component("SkinnedCurveChain")
class SkinnedCurveChainComponent(base_component.BaseRigComponent):
    """
    NURBS Skinned curve component with full matrix evaluation (Translate, Rotate, Scale).
    """

    def validate(self) -> List[str]:
        errors = []
        chain = self.params.get("deform_chain", [])
        if len(chain) < 2:
            errors.append("SkinnedCurveChain requires at least 2 bones in 'deform_chain'.")
        for b in chain:
            if not core_framework.find_bone_name(self.armature_obj, b):
                errors.append(f"Deform bone '{b}' not found.")
        return errors

    def _calculate_default_weights(self, num_points: int) -> Tuple[List[float], List[float], List[float]]:
        weights_start, weights_mid, weights_end = [], [], []
        mid_idx = (num_points - 1) / 2.0

        for i in range(num_points):
            if i <= mid_idx:
                t = i / mid_idx if mid_idx > 0 else 0.0
                weights_start.append(round(1.0 - t, 4))
                weights_mid.append(round(t, 4))
                weights_end.append(0.0)
            else:
                t = (i - mid_idx) / (num_points - 1 - mid_idx) if (num_points - 1 - mid_idx) > 0 else 0.0
                weights_start.append(0.0)
                weights_mid.append(round(1.0 - t, 4))
                weights_end.append(round(t, 4))

        return weights_start, weights_mid, weights_end

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

        # 1. Resolve Master Controls
        start_master = self.context.resolve_socket(self.params.get("start_master"))
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

        mid_master = self.context.resolve_socket(self.params.get("mid_master"))
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

        end_master = self.context.resolve_socket(self.params.get("end_master"))
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

        # 2. Duplicate deform bones to create MCH and CTRL chains
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

        # 3. Create MCH Anchor Bones for Matrix Skinning
        point_positions = [edit_bones[b].head.copy() for b in def_chain]
        point_positions.append(edit_bones[def_chain[-1]].tail.copy())

        self.anchor_map = []
        for i, pos in enumerate(point_positions):
            # Start Master Anchor
            a_start_name = naming.format_name(
                name=f"{self.name}_anchor_start",
                role=naming.ROLE_MCH,
                side=side,
                index=i
            )
            a_start = core_framework.create_bone(
                self.armature_obj, a_start_name,
                head=pos, tail=pos + mathutils.Vector((0.0, 0.0, 0.005)),
                parent_name=start_master, collection_name="MCH", use_deform=False
            )

            # Mid Master Anchor
            a_mid_name = naming.format_name(
                name=f"{self.name}_anchor_mid",
                role=naming.ROLE_MCH,
                side=side,
                index=i
            )
            a_mid = core_framework.create_bone(
                self.armature_obj, a_mid_name,
                head=pos, tail=pos + mathutils.Vector((0.0, 0.0, 0.005)),
                parent_name=mid_master, collection_name="MCH", use_deform=False
            )

            # End Master Anchor
            a_end_name = naming.format_name(
                name=f"{self.name}_anchor_end",
                role=naming.ROLE_MCH,
                side=side,
                index=i
            )
            a_end = core_framework.create_bone(
                self.armature_obj, a_end_name,
                head=pos, tail=pos + mathutils.Vector((0.0, 0.0, 0.005)),
                parent_name=end_master, collection_name="MCH", use_deform=False
            )
            self.anchor_map.append((a_start, a_mid, a_end))

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
        arm_matrix = self.armature_obj.matrix_world

        point_positions = [arm_matrix @ pose_bones[b].head for b in self.def_bones]
        point_positions.append(arm_matrix @ pose_bones[self.def_bones[-1]].tail)
        num_points = len(point_positions)

        w_start = self.params.get("weights_start")
        w_mid = self.params.get("weights_mid")
        w_end = self.params.get("weights_end")

        if not (w_start and w_mid and w_end and len(w_start) == num_points):
            w_start, w_mid, w_end = self._calculate_default_weights(num_points)

        # 1. Build Skinned Curve with Matrix Anchors
        curve_name = naming.format_name(name=f"{self.name}_curve", side=self.side)
        curve_obj = _build_skinned_cv_curve(
            curve_name, self.armature_obj, point_positions, self.anchor_map,
            w_start, w_mid, w_end
        )

        proxy_col = core_framework._get_or_create_proxy_collection()

        # 2. Build CV tracking Proxies
        cv_proxies = []
        for i in range(num_points):
            proxy_name = naming.format_name(
                name=f"{self.name}_proxy_cv",
                side=self.side,
                index=i
            )
            proxy = bpy.data.objects.get(proxy_name)
            if not proxy:
                proxy = bpy.data.objects.new(proxy_name, None)
                proxy.empty_display_size = 0.005
                proxy_col.objects.link(proxy)
                proxy.hide_render = True
                proxy.hide_select = True

            for a_idx in range(3):
                fc = proxy.driver_add("location", a_idx)
                drv = fc.driver
                drv.type = 'SCRIPTED'
                for v in list(drv.variables):
                    drv.variables.remove(v)

                drv.expression = "cv_co"
                v = drv.variables.new()
                v.name = "cv_co"
                v.type = 'SINGLE_PROP'
                v.targets[0].id_type = 'CURVE'
                v.targets[0].id = curve_obj.data
                v.targets[0].data_path = f"splines[0].points[{i}].co[{a_idx}]"

            cv_proxies.append(proxy)

        # 3. Constrain MCH to CV Positions + Tangents
        for idx, (mch, ctrl, def_b) in enumerate(zip(self.mch_bones, self.ctrl_bones, self.def_bones)):
            p_mch = pose_bones[mch]
            p_ctrl = pose_bones[ctrl]
            p_def = pose_bones[def_b]

            for c in list(p_mch.constraints):
                p_mch.constraints.remove(c)
            for c in list(p_def.constraints):
                p_def.constraints.remove(c)

            # Snap root to CV[idx]
            core_framework.add_constraint(
                p_mch, 'COPY_LOCATION', cv_proxies[idx]
            )

            # Aim Y-axis along curve tangent to CV[idx + 1]
            core_framework.add_constraint(
                p_mch, 'DAMPED_TRACK', cv_proxies[idx + 1],
                track_axis='TRACK_Y'
            )

            # Bind Deform joint to CTRL for FBX baking
            core_framework.add_constraint(
                p_def, 'COPY_TRANSFORMS', self.armature_obj, subtarget_bone=ctrl
            )

            core_framework.assign_bone_shape(
                p_ctrl, shapes['Sphere'], scale=(ctrl_scale, ctrl_scale, ctrl_scale)
            )

        # Shape Master Controls
        for m_ctrl in self.master_ctrls:
            if m_ctrl in pose_bones:
                core_framework.assign_bone_shape(
                    pose_bones[m_ctrl], shapes['Box'], scale=(ctrl_scale * 1.2, ctrl_scale * 1.2, ctrl_scale * 1.2)
                )