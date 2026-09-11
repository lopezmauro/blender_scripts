import bpy
import os
import json
from mathutils import Vector
from mathutils.kdtree import KDTree
from bpy.props import FloatProperty, IntProperty, StringProperty, PointerProperty
from bpy.types import Operator, PropertyGroup


# -------------------------------------------------------------------------
# Core Extraction & Math Logic
# -------------------------------------------------------------------------

def extract_curve_data(eval_obj):
    pts = []
    tangents = []
    world_mat = eval_obj.matrix_world
    geom = eval_obj.data

    if eval_obj.type == 'CURVES':
        points = [world_mat @ p.position for p in geom.points]
        start_idx = 0
        for curve in geom.curves:
            strand_len = curve.points_length
            end_idx = start_idx + strand_len

            if strand_len >= 2:
                for p_idx in range(start_idx, end_idx):
                    if p_idx == start_idx:
                        t = (points[p_idx + 1] - points[p_idx]).normalized()
                    elif p_idx == end_idx - 1:
                        t = (points[p_idx] - points[p_idx - 1]).normalized()
                    else:
                        t = (points[p_idx + 1] - points[p_idx - 1]).normalized()

                    if t.length_squared > 1e-6:
                        pts.append(points[p_idx])
                        tangents.append(t)
            start_idx = end_idx
        return pts, tangents

    if eval_obj.type == 'CURVE':
        for spline in geom.splines:
            coords = []
            if spline.type == 'BEZIER':
                coords = [world_mat @ bp.co for bp in spline.bezier_points]
            elif spline.type in {'POLY', 'NURBS'}:
                coords = [world_mat @ p.co.to_3d() for p in spline.points]

            s_len = len(coords)
            if s_len < 2:
                continue

            for i in range(s_len):
                if i == 0:
                    t = (coords[1] - coords[0]).normalized()
                elif i == s_len - 1:
                    t = (coords[-1] - coords[-2]).normalized()
                else:
                    t = (coords[i + 1] - coords[i - 1]).normalized()

                if t.length_squared > 1e-6:
                    pts.append(coords[i])
                    tangents.append(t)
        return pts, tangents

    return pts, tangents


def execute_curve_flow_to_vcol(mesh_obj, curve_obj, max_search_radius, attr_name, depsgraph):
    if not mesh_obj or mesh_obj.type != 'MESH':
        raise RuntimeError("Target Mesh must be assigned and must be a Mesh object.")
    if not curve_obj or curve_obj.type not in {'CURVES', 'CURVE'}:
        raise RuntimeError("Curve Object must be assigned and must be a Curve or Hair object.")

    eval_curve = curve_obj.evaluated_get(depsgraph)
    curve_pts, curve_tangents = extract_curve_data(eval_curve)

    if not curve_pts:
        raise RuntimeError("No valid points or segments found.")

    kd = KDTree(len(curve_pts))
    for i, pt in enumerate(curve_pts):
        kd.insert(pt, i)
    kd.balance()

    mesh = mesh_obj.data
    mesh.calc_tangents()

    world_to_obj_rot = mesh_obj.matrix_world.to_3x3().inverted()

    # Use CORNER domain so UV seam edges receive split, matching projections
    color_attr = mesh.color_attributes.get(attr_name)
    if not color_attr or color_attr.domain != 'CORNER' or color_attr.data_type != 'FLOAT_COLOR':
        if color_attr:
            mesh.color_attributes.remove(color_attr)
        color_attr = mesh.color_attributes.new(name=attr_name, type='FLOAT_COLOR', domain='CORNER')

    loop_count = len(mesh.loops)
    flow_colors = [(0.5, 0.5, 0.0, 1.0)] * loop_count

    for poly in mesh.polygons:
        for loop_idx in poly.loop_indices:
            loop = mesh.loops[loop_idx]
            v_idx = loop.vertex_index
            vert = mesh.vertices[v_idx]

            vert_world = mesh_obj.matrix_world @ vert.co
            co, idx, dist = kd.find(vert_world)

            if dist <= max_search_radius and idx is not None:
                curve_t_world = curve_tangents[idx]
                curve_t_obj = (world_to_obj_rot @ curve_t_world).normalized()

                mesh_u = loop.tangent
                mesh_v = loop.bitangent

                proj_u = curve_t_obj.dot(mesh_u)
                proj_v = curve_t_obj.dot(mesh_v)

                remap_u = (proj_u * 0.5) + 0.5
                remap_v = (proj_v * 0.5) + 0.5

                flow_colors[loop_idx] = (
                    max(0.0, min(1.0, remap_u)),
                    max(0.0, min(1.0, remap_v)),
                    0.0,
                    1.0
                )

    for i, col in enumerate(flow_colors):
        color_attr.data[i].color = col

    mesh.free_tangents()
    mesh.update()

def execute_bake_vcol(mesh_obj, context, attr_name, resolution, filename):
    if not mesh_obj or mesh_obj.type != 'MESH':
        raise RuntimeError("Target Mesh must be assigned and must be a Mesh object.")

    mesh = mesh_obj.data
    if attr_name not in mesh.color_attributes:
        raise RuntimeError(f"Attribute '{attr_name}' not found on mesh.")

    if not bpy.data.is_saved:
        raise RuntimeError("Save your .blend file before baking to resolve relative export path.")

    blend_dir = bpy.path.abspath("//")
    export_path = os.path.join(blend_dir, filename)

    scene = context.scene
    original_engine = scene.render.engine
    scene.render.engine = 'CYCLES'

    orig_active = context.view_layer.objects.active
    orig_selected = [o for o in context.selected_objects]

    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    context.view_layer.objects.active = mesh_obj

    original_materials = [slot.material for slot in mesh_obj.material_slots]
    mesh_obj.data.materials.clear()

    bake_mat = bpy.data.materials.new(name="__TEMP_BAKE_FLOWMAP__")
    bake_mat.use_nodes = True
    nodes = bake_mat.node_tree.nodes
    links = bake_mat.node_tree.links
    nodes.clear()

    node_out = nodes.new(type='ShaderNodeOutputMaterial')
    node_emit = nodes.new(type='ShaderNodeEmission')
    node_attr = nodes.new(type='ShaderNodeAttribute')
    node_tex = nodes.new(type='ShaderNodeTexImage')

    node_attr.attribute_name = attr_name
    node_attr.attribute_type = 'GEOMETRY'

    links.new(node_attr.outputs['Color'], node_emit.inputs['Color'])
    links.new(node_emit.outputs['Emission'], node_out.inputs['Surface'])

    bake_img = bpy.data.images.new(
        name="__TEMP_FLOWMAP_IMG__",
        width=resolution,
        height=resolution,
        alpha=True,
        float_buffer=False
    )
    node_tex.image = bake_img
    nodes.active = node_tex
    node_tex.select = True

    mesh_obj.data.materials.append(bake_mat)

    scene.render.bake.use_selected_to_active = False
    scene.cycles.bake_type = 'EMIT'

    try:
        bpy.ops.object.bake(type='EMIT')
        bake_img.filepath_raw = export_path
        bake_img.file_format = 'PNG'
        bake_img.save()
    finally:
        mesh_obj.data.materials.clear()
        for mat in original_materials:
            mesh_obj.data.materials.append(mat)
        bpy.data.materials.remove(bake_mat)
        bpy.data.images.remove(bake_img)
        scene.render.engine = original_engine

        bpy.ops.object.select_all(action='DESELECT')
        for o in orig_selected:
            if o.name in bpy.data.objects:
                o.select_set(True)
        if orig_active and orig_active.name in bpy.data.objects:
            context.view_layer.objects.active = orig_active

    return export_path


# -------------------------------------------------------------------------
# JSON Serialization / Deserialization
# -------------------------------------------------------------------------

def execute_export_json(mesh_obj, attr_name, filename):
    if not mesh_obj or mesh_obj.type != 'MESH':
        raise RuntimeError("Target Mesh must be assigned and must be a Mesh object.")

    mesh = mesh_obj.data
    color_attr = mesh.color_attributes.get(attr_name)
    if not color_attr:
        raise RuntimeError(f"Attribute '{attr_name}' not found on mesh '{mesh_obj.name}'.")

    if not bpy.data.is_saved:
        raise RuntimeError("Save your .blend file before exporting to resolve relative export path.")

    blend_dir = bpy.path.abspath("//")
    export_path = os.path.join(blend_dir, filename)

    # Convert color data to list of 4-element arrays rounded for precision and file size
    color_data = [[round(c, 6) for c in item.color] for item in color_attr.data]

    payload = {
        "source_mesh": mesh_obj.name,
        "domain": color_attr.domain,
        "data_type": color_attr.data_type,
        "element_count": len(color_attr.data),
        "attribute_name": attr_name,
        "colors": color_data
    }

    with open(export_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)

    return export_path


def execute_import_json(mesh_obj, attr_name, filename):
    if not mesh_obj or mesh_obj.type != 'MESH':
        raise RuntimeError("Target Mesh must be assigned and must be a Mesh object.")

    if not bpy.data.is_saved:
        raise RuntimeError("Save your .blend file to resolve relative import path.")

    blend_dir = bpy.path.abspath("//")
    import_path = os.path.join(blend_dir, filename)

    if not os.path.isfile(import_path):
        raise RuntimeError(f"JSON file not found: {import_path}")

    with open(import_path, 'r', encoding='utf-8') as f:
        payload = json.load(f)

    domain = payload.get("domain", "CORNER")
    data_type = payload.get("data_type", "FLOAT_COLOR")
    expected_count = payload.get("element_count", payload.get("vertex_count", 0))
    colors = payload.get("colors", [])
    
    mesh = mesh_obj.data
    actual_count = len(mesh.loops) if domain == 'CORNER' else len(mesh.vertices)

    if actual_count != len(colors):
        raise RuntimeError(
            f"Count mismatch: Mesh '{mesh_obj.name}' has {actual_count} {domain.lower()} elements, "
            f"but JSON expects {len(colors)}."
        )

    color_attr = mesh.color_attributes.get(attr_name)
    if not color_attr or color_attr.domain != domain or color_attr.data_type != data_type:
        if color_attr:
            mesh.color_attributes.remove(color_attr)
        color_attr = mesh.color_attributes.new(name=attr_name, type=data_type, domain=domain)

    for i, col in enumerate(colors):
        color_attr.data[i].color = col

    mesh.update()
    return import_path

# -------------------------------------------------------------------------
# Property Group (Stored on Scene)
# -------------------------------------------------------------------------

def filter_mesh_objects(self, object):
    return object.type == 'MESH'

def filter_curve_objects(self, object):
    return object.type in {'CURVES', 'CURVE'}

def update_mesh_filenames(self, context):
    if self.target_mesh:
        self.filename = f"{self.target_mesh.name}_FlowMap.png"
        self.json_filename = f"{self.target_mesh.name}_FlowData.json"

class FlowMapSettings(PropertyGroup):
    target_mesh: PointerProperty(
        name="Target Mesh",
        type=bpy.types.Object,
        poll=filter_mesh_objects,
        update=update_mesh_filenames,
        description="Mesh object that receives vertex colors and baking"
    )
    curve_obj: PointerProperty(
        name="Groom Curves",
        type=bpy.types.Object,
        poll=filter_curve_objects,
        description="Hair or spline curves defining flow direction"
    )
    max_search_radius: FloatProperty(
        name="Search Radius",
        description="World-space search radius for curve points",
        default=1.0,
        min=0.001,
        soft_max=10.0
    )
    attribute_name: StringProperty(
        name="Attribute",
        default="flowMap_data"
    )
    resolution: IntProperty(
        name="Resolution",
        default=2048,
        min=256,
        max=8192
    )
    filename: StringProperty(
        name="Texture File",
        default="T_FlowMap.png"
    )
    json_filename: StringProperty(
        name="JSON File",
        default="FlowData.json"
    )


# -------------------------------------------------------------------------
# Dedicated Operators
# -------------------------------------------------------------------------

class OBJECT_OT_flow_generate_vcol(Operator):
    bl_idname = "object.flow_generate_vcol"
    bl_label = "Generate Vertex Colors"
    bl_description = "Calculates flow vector projections and stores in vertex color attribute"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.flow_map_settings
        if not settings.target_mesh:
            self.report({'ERROR'}, "Please assign a Target Mesh.")
            return {'CANCELLED'}
        if not settings.curve_obj:
            self.report({'ERROR'}, "Please assign Groom Curves.")
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        try:
            execute_curve_flow_to_vcol(
                mesh_obj=settings.target_mesh,
                curve_obj=settings.curve_obj,
                max_search_radius=settings.max_search_radius,
                attr_name=settings.attribute_name,
                depsgraph=depsgraph
            )
            self.report({'INFO'}, f"Saved flow vectors to '{settings.attribute_name}'.")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


class OBJECT_OT_flow_bake_texture(Operator):
    bl_idname = "object.flow_bake_texture"
    bl_label = "Bake Map to Texture"
    bl_description = "Bakes the existing vertex color attribute to a PNG file"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.flow_map_settings
        if not settings.target_mesh:
            self.report({'ERROR'}, "Please assign a Target Mesh.")
            return {'CANCELLED'}

        try:
            path = execute_bake_vcol(
                mesh_obj=settings.target_mesh,
                context=context,
                attr_name=settings.attribute_name,
                resolution=settings.resolution,
                filename=settings.filename
            )
            self.report({'INFO'}, f"Baked texture saved to {path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


class OBJECT_OT_flow_export_json(Operator):
    bl_idname = "object.flow_export_json"
    bl_label = "Export JSON"
    bl_description = "Exports vertex color attribute data to a JSON file"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.flow_map_settings
        if not settings.target_mesh:
            self.report({'ERROR'}, "Please assign a Target Mesh.")
            return {'CANCELLED'}

        try:
            path = execute_export_json(
                mesh_obj=settings.target_mesh,
                attr_name=settings.attribute_name,
                filename=settings.json_filename
            )
            self.report({'INFO'}, f"Color data exported to {path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


class OBJECT_OT_flow_import_json(Operator):
    bl_idname = "object.flow_import_json"
    bl_label = "Import JSON"
    bl_description = "Loads JSON color data into the target mesh (must have matching vertex count)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.flow_map_settings
        if not settings.target_mesh:
            self.report({'ERROR'}, "Please assign a Target Mesh.")
            return {'CANCELLED'}

        try:
            path = execute_import_json(
                mesh_obj=settings.target_mesh,
                attr_name=settings.attribute_name,
                filename=settings.json_filename
            )
            self.report({'INFO'}, f"Color data imported onto {settings.target_mesh.name} from {path}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}


# -------------------------------------------------------------------------
# Unified Modal Dialog Interface
# -------------------------------------------------------------------------

class OBJECT_OT_flow_map_dialog(Operator):
    bl_idname = "object.flow_map_dialog"
    bl_label = "Flow Map Tools"
    bl_description = "Open configuration dialog for flow map generation, baking, and JSON exchange"
    bl_options = {'REGISTER'}

    def invoke(self, context, event):
        settings = context.scene.flow_map_settings
        for obj in context.selected_objects:
            if obj.type == 'MESH' and not settings.target_mesh:
                settings.target_mesh = obj
            elif obj.type in {'CURVES', 'CURVE'} and not settings.curve_obj:
                settings.curve_obj = obj

        return context.window_manager.invoke_props_dialog(self, width=340)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.flow_map_settings

        # 1. Object Slots
        box = layout.box()
        box.label(text="Object Assignment:", icon='EYEDROPPER')
        box.prop(settings, "target_mesh")
        box.prop(settings, "curve_obj")

        # 2. Parameters
        col = layout.column(align=True)
        col.prop(settings, "max_search_radius")
        col.prop(settings, "attribute_name")

        # 3. Generation & Baking
        layout.separator()
        layout.label(text="Mesh & Texture Pipeline:", icon='TEXTURE')
        layout.operator("object.flow_generate_vcol", text="Generate Color Map", icon='COLOR')

        col_bake = layout.column(align=True)
        col_bake.prop(settings, "resolution")
        col_bake.prop(settings, "filename")
        col_bake.operator("object.flow_bake_texture", text="Export Baked Map", icon='IMAGE_DATA')

        # 4. JSON Serialization
        layout.separator()
        layout.label(text="JSON Vertex Data Exchange:", icon='FILE_TEXT')
        col_json = layout.column(align=True)
        col_json.prop(settings, "json_filename")
        row = col_json.row(align=True)
        row.operator("object.flow_export_json", text="Export JSON", icon='EXPORT')
        row.operator("object.flow_import_json", text="Import JSON", icon='IMPORT')

    def execute(self, context):
        # Dismiss dialog cleanly on OK
        return {'FINISHED'}


# -------------------------------------------------------------------------
# Menu Integration & Registration
# -------------------------------------------------------------------------

def menu_entry(self, context):
    self.layout.separator()
    self.layout.operator("object.flow_map_dialog", text="Flow Map Tools...", icon='COLOR')

classes = (
    FlowMapSettings,
    OBJECT_OT_flow_generate_vcol,
    OBJECT_OT_flow_bake_texture,
    OBJECT_OT_flow_export_json,
    OBJECT_OT_flow_import_json,
    OBJECT_OT_flow_map_dialog,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.flow_map_settings = PointerProperty(type=FlowMapSettings)
    bpy.types.VIEW3D_MT_object.append(menu_entry)

def unregister():
    bpy.types.VIEW3D_MT_object.remove(menu_entry)
    del bpy.types.Scene.flow_map_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
