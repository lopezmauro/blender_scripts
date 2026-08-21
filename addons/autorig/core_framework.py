import math
import bpy
import mathutils

# ==============================================================================
# 1. BONE COLLECTIONS & INFRASTRUCTURE
# ==============================================================================

STANDARD_COLLECTIONS = [
    "DEF",
    "MCH",
    "GUIDE",
    "CTRL_Root",
    "CTRL_Spine",
    "CTRL_IK_Arms",
    "CTRL_FK_Arms",
    "CTRL_IK_Legs",
    "CTRL_FK_Legs",
    "CTRL_Fingers",
    "CTRL_Tail_Ears",
    "CTRL_Face"
]

def ensure_bone_collections(armature_data):
    """Creates standard collections if they do not exist and sets them visible."""
    for col_name in STANDARD_COLLECTIONS:
        col = armature_data.collections.get(col_name)
        if not col:
            col = armature_data.collections.new(col_name)
        col.is_visible = True
    return armature_data.collections

def assign_bone_to_collection(armature_obj, bone_name, collection_name):
    """
    Assigns a bone to a collection in either Edit Mode or Pose/Object Mode.
    Automatically creates the collection if it doesn't exist.
    """
    arm_data = armature_obj.data
    ensure_bone_collections(arm_data)
    
    target_col = arm_data.collections.get(collection_name)
    if not target_col:
        target_col = arm_data.collections.new(collection_name)
        target_col.is_visible = True

    in_edit_mode = (armature_obj.mode == 'EDIT')
    bone_ref = arm_data.edit_bones.get(bone_name) if in_edit_mode else arm_data.bones.get(bone_name)

    if not bone_ref:
        raise KeyError(f"Bone '{bone_name}' not found in mode '{armature_obj.mode}'.")

    # Unassign from all other collections without reading col.bones in Edit Mode
    if in_edit_mode:
        # EditBone.collections contains the collections currently assigned to this edit bone
        for col in list(bone_ref.collections):
            col.unassign(bone_ref)
    else:
        for col in arm_data.collections:
            if bone_name in col.bones:
                col.unassign(bone_ref)

    target_col.assign(bone_ref)

def organize_initial_deform_bones(armature_obj):
    """Ensures existing bones are set to deform and placed into the DEF collection."""
    original_mode = armature_obj.mode
    bpy.context.view_layer.objects.active = armature_obj
    
    if original_mode != 'EDIT':
        bpy.ops.object.mode_set(mode='EDIT')

    arm_data = armature_obj.data
    ensure_bone_collections(arm_data)

    for eb in arm_data.edit_bones:
        eb.use_deform = True
        assign_bone_to_collection(armature_obj, eb.name, "DEF")

    if original_mode != 'EDIT':
        bpy.ops.object.mode_set(mode=original_mode)

# ==============================================================================
# 2. BONE RESOLVER & CREATION HELPERS
# ==============================================================================

def find_bone_name(armature_obj, target_name):
    bones = armature_obj.data.edit_bones if armature_obj.mode == 'EDIT' else armature_obj.data.bones
    if target_name in bones:
        return target_name

    target_clean = target_name.strip().lower()
    for b in bones:
        if b.name.strip().lower() == target_clean:
            return b.name
    return None

def create_bone(armature_obj, bone_name, head, tail, roll=0.0, parent_name=None, collection_name=None, use_deform=False):
    if bpy.context.active_object != armature_obj or armature_obj.mode != 'EDIT':
        bpy.context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = armature_obj.data.edit_bones
    # If the bone already exists from a previous generation run, remove it to prevent .001
    if bone_name in edit_bones:
        edit_bones.remove(edit_bones[bone_name])

    eb = edit_bones.new(bone_name)
    eb.head = mathutils.Vector(head)
    eb.tail = mathutils.Vector(tail)
    eb.roll = roll
    eb.use_deform = use_deform

    if parent_name:
        resolved_parent = find_bone_name(armature_obj, parent_name)
        if resolved_parent:
            eb.parent = edit_bones[resolved_parent]

    actual_name = eb.name
    if collection_name:
        assign_bone_to_collection(armature_obj, actual_name, collection_name)

    return actual_name

def duplicate_bone(armature_obj, source_name, new_name, collection_name=None, use_deform=False, parent_name=None):
    if bpy.context.active_object != armature_obj or armature_obj.mode != 'EDIT':
        bpy.context.view_layer.objects.active = armature_obj
        bpy.ops.object.mode_set(mode='EDIT')

    edit_bones = armature_obj.data.edit_bones
    resolved_source = find_bone_name(armature_obj, source_name)
    if not resolved_source or resolved_source not in edit_bones:
        raise KeyError(f"Source bone '{source_name}' not found.")

    src = edit_bones[resolved_source]
    return create_bone(
        armature_obj=armature_obj,
        bone_name=new_name,
        head=src.head.copy(),
        tail=src.tail.copy(),
        roll=src.roll,
        parent_name=parent_name,
        collection_name=collection_name,
        use_deform=use_deform
    )

# ==============================================================================
# 3. CONSTRAINTS & DRIVERS HELPERS
# ==============================================================================

def add_constraint(pose_bone, constraint_type, target_obj, subtarget_bone=None, influence=1.0, **kwargs):
    con = pose_bone.constraints.new(type=constraint_type)
    con.target = target_obj
    if subtarget_bone:
        con.subtarget = subtarget_bone
    con.influence = influence
    for key, value in kwargs.items():
        if hasattr(con, key):
            setattr(con, key, value)
    return con

def create_custom_property(target, prop_name, default=0.0, min_val=0.0, max_val=1.0, description=""):
    target[prop_name] = default
    ui_data = target.id_properties_ui(prop_name)
    ui_data.update(
        default=default,
        min=min_val,
        max=max_val,
        soft_min=min_val,
        soft_max=max_val,
        description=description
    )
    
    # Track creation order
    if "_prop_order" not in target:
        target["_prop_order"] = []
    
    order_list = list(target["_prop_order"])
    if prop_name not in order_list:
        order_list.append(prop_name)
        target["_prop_order"] = order_list

def add_driver(target_id, target_datapath, source_id, source_prop_path, expression="var", var_name="var", index=-1):
    # Pass index if targeting a specific array element (0, 1, 2)
    if index >= 0:
        driver_fcurve = target_id.driver_add(target_datapath, index)
    else:
        driver_fcurve = target_id.driver_add(target_datapath)

    drv = driver_fcurve.driver
    drv.type = 'SCRIPTED'
    drv.expression = expression
    
    for v in list(drv.variables):
        drv.variables.remove(v)

    var = drv.variables.new()
    var.name = var_name
    var.type = 'SINGLE_PROP'
    target_var = var.targets[0]
    target_var.id = source_id
    target_var.data_path = source_prop_path
    return driver_fcurve

# ==============================================================================
# 4. CUSTOM SHAPE GENERATOR
# ==============================================================================
def _get_or_create_proxy_collection():
    col_name = "RIG_Proxies"
    col = bpy.data.collections.get(col_name)
    if not col:
        col = bpy.data.collections.new(col_name)
        bpy.context.scene.collection.children.link(col)
        col.hide_render = True
    return col



def get_or_create_widget_collection():
    col_name = "WGT_Shapes"
    col = bpy.data.collections.get(col_name)
    if not col:
        col = bpy.data.collections.new(col_name)
        bpy.context.scene.collection.children.link(col)
        col.hide_render = True
    return col

def create_shape_mesh(shape_name, verts, edges):
    wgt_col = get_or_create_widget_collection()
    obj_name = f"WGT_{shape_name}"
    
    obj = bpy.data.objects.get(obj_name)
    if obj:
        mesh = obj.data
        mesh.clear_geometry()
        mesh.from_pydata(verts, edges, [])
        mesh.update()
        return obj

    mesh = bpy.data.meshes.new(f"{obj_name}_Mesh")
    mesh.from_pydata(verts, edges, [])
    mesh.update()

    obj = bpy.data.objects.new(obj_name, mesh)
    wgt_col.objects.link(obj)
    return obj

def build_shape_library():
    shapes = {}
    
    # 1. Box
    b_verts = [
        (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, -0.5,  0.5), (0.5, -0.5,  0.5), (0.5, 0.5,  0.5), (-0.5, 0.5,  0.5)
    ]
    b_edges = [
        (0,1), (1,2), (2,3), (3,0), (4,5), (5,6), (6,7), (7,4),
        (0,4), (1,5), (2,6), (3,7)
    ]
    shapes['Box'] = create_shape_mesh('Box', b_verts, b_edges)

    # 2. Transversal Circle (XZ Plane)
    num_pts = 16
    c_verts_xz = [
        (math.cos(i * 2 * math.pi / num_pts), 0.0, math.sin(i * 2 * math.pi / num_pts))
        for i in range(num_pts)
    ]
    c_edges = [(i, (i + 1) % num_pts) for i in range(num_pts)]
    shapes['Circle'] = create_shape_mesh('Circle', c_verts_xz, c_edges)

    # 3. Flat Circle (XY Plane)
    c_verts_xy = [
        (math.cos(i * 2 * math.pi / num_pts), math.sin(i * 2 * math.pi / num_pts), 0.0)
        for i in range(num_pts)
    ]
    shapes['Circle_Flat'] = create_shape_mesh('Circle_Flat', c_verts_xy, c_edges)

    # 4. Gear (Settings Cog)
    g_verts = []
    num_teeth = 8
    for i in range(num_teeth * 2):
        r = 1.0 if i % 2 == 0 else 0.7
        angle = i * math.pi / num_teeth
        g_verts.append((math.cos(angle) * r, 0.0, math.sin(angle) * r))
    g_edges = [(i, (i + 1) % (num_teeth * 2)) for i in range(num_teeth * 2)]
    shapes['Gear'] = create_shape_mesh('Gear', g_verts, g_edges)

    # 5. Sphere
    s_verts = []
    s_edges = []
    s_verts.extend([(math.cos(i * math.pi / 4), math.sin(i * math.pi / 4), 0.0) for i in range(8)])
    s_edges.extend([(i, (i + 1) % 8) for i in range(8)])
    s_verts.extend([(math.cos(i * math.pi / 4), 0.0, math.sin(i * math.pi / 4)) for i in range(8)])
    s_edges.extend([(8 + i, 8 + ((i + 1) % 8)) for i in range(8)])
    s_verts.extend([(0.0, math.cos(i * math.pi / 4), math.sin(i * math.pi / 4)) for i in range(8)])
    s_edges.extend([(16 + i, 16 + ((i + 1) % 8)) for i in range(8)])
    shapes['Sphere'] = create_shape_mesh('Sphere', s_verts, s_edges)

    return shapes

def assign_bone_shape(pose_bone, shape_obj, scale=(1.0, 1.0, 1.0), translation=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0)):
    pose_bone.custom_shape = shape_obj
    pose_bone.use_custom_shape_bone_size = False
    pose_bone.custom_shape_scale_xyz = scale
    pose_bone.custom_shape_translation = translation
    pose_bone.custom_shape_rotation_euler = rotation

def apply_color_coding(armature_obj):
    """Assigns bone colors based on naming conventions and sides."""
    if armature_obj.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    for pbone in armature_obj.pose.bones:
        bname = pbone.name
        bname_lower = bname.lower()

        if bname.startswith(("DEF", "MCH", "GUIDE")):
            continue

        # Blender 4.0+ / 5.1 Color API: Side-based color precedence
        if bname_lower.endswith(".l") or bname_lower.endswith("_l") or ".l." in bname_lower:
            pbone.color.palette = 'THEME01'  # Red (Left)
        elif bname_lower.endswith(".r") or bname_lower.endswith("_r") or ".r." in bname_lower:
            pbone.color.palette = 'THEME04'  # Blue (Right)
        elif "ik" in bname_lower:
            pbone.color.palette = 'THEME09'  # Green (Center IK)
        else:
            pbone.color.palette = 'THEME03'  # Yellow (Center FK/Main)

# ==============================================================================
# 2. DYNAMIC SPACE SWITCHING (SETUP)
# ==============================================================================

def setup_space_switching(armature_obj):
    """Builds the properties and constraints for parent space switching."""
    if armature_obj.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
        
    pose_bones = armature_obj.pose.bones
    arm_data = armature_obj.data
    
    # Define targets
    spaces = {
        "World (Root)": find_bone_name(armature_obj, "CTRL_Root"),
        "Pelvis": find_bone_name(armature_obj, "CTRL_Pelvis"),
        "Chest": find_bone_name(armature_obj, "CTRL_Chest"),
        "Head": find_bone_name(armature_obj, "CTRL_Head")
    }
    
    targets_config = {
        "CTRL_IK_Hand.L": ["World (Root)", "Pelvis", "Chest", "Head"],
        "CTRL_IK_Hand.R": ["World (Root)", "Pelvis", "Chest", "Head"],
        "CTRL_IK_Foot.L": ["World (Root)", "Pelvis"],
        "CTRL_IK_Foot.R": ["World (Root)", "Pelvis"],
        "CTRL_Head": ["World (Root)", "Chest"]
    }

    for ctrl_name, space_names in targets_config.items():
        if ctrl_name not in pose_bones:
            continue
            
        pbone = pose_bones[ctrl_name]
        
        create_custom_property(
            target=pbone, 
            prop_name="Space", 
            default=0.0, 
            min_val=0.0, 
            max_val=len(space_names) - 1, 
            description="Switch parent space"
        )
        
        for idx, s_name in enumerate(space_names):
            target_bone_name = spaces.get(s_name)
            if not target_bone_name:
                continue
                
            # Use CHILD_OF to act as a dynamic parent rather than an absolute transform override
            con = pbone.constraints.new(type='CHILD_OF')
            con.name = f"SPACE_{s_name}"
            con.target = armature_obj
            con.subtarget = target_bone_name
            
            # Programmatically set the inverse matrix to maintain the bone's starting offset
            target_rest_matrix = arm_data.bones[target_bone_name].matrix_local
            con.inverse_matrix = target_rest_matrix.inverted()
            
            drv = con.driver_add("influence").driver
            drv.type = 'SCRIPTED'
            drv.expression = f"1.0 if space == {idx} else 0.0"
            v = drv.variables.new()
            v.name = "space"
            v.type = 'SINGLE_PROP'
            v.targets[0].id = armature_obj
            v.targets[0].data_path = f'pose.bones["{ctrl_name}"]["Space"]'
