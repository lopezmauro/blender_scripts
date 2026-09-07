import os
import json
import bpy
from typing import Dict, Any, Type, List
from . import core_framework, systems_framework, base_component
from .validators import config_validator, validatiors

class RigBuilder:
    def __init__(self, armature_obj: bpy.types.Object, config: Dict[str, Any]):
        self.armature_obj = armature_obj
        self.config = config
        self.context = base_component.RigContext(armature_obj, config)
        self.component_instances: List[base_component.BaseRigComponent] = []

    def _instantiate_components(self) -> List[str]:
        errors = []
        raw_components = self.config.get("components", [])
        for comp_spec in raw_components:
            comp_type = comp_spec.get("type")
            comp_name = comp_spec.get("name")
            params = comp_spec.get("params", {})
            cls = base_component.COMPONENT_REGISTRY.get(comp_type)
            if not cls:
                errors.append(f"Component type '{comp_type}' not found in COMPONENT_REGISTRY.")
                continue
            instance = cls(name=comp_name, params=params, context=self.context)
            print(comp_type, comp_name, instance)
            self.component_instances.append(instance)
            self.context.components[comp_name] = instance
        return errors

    def build(self) -> bool:
        if not self.armature_obj or self.armature_obj.type != 'ARMATURE':
            print("[RigBuilder Error] Active object is not a valid armature.")
            return False

        # 1. Setup collections & shapes
        core_framework.ensure_bone_collections(self.armature_obj.data)
        self.context.shapes = core_framework.build_shape_library()

        # 2. Instantiate and validate
        instantiation_errors = self._instantiate_components()
        if instantiation_errors:
            for err in instantiation_errors:
                print(f"[RigBuilder Error] {err}")
            return False

        validation_errors = []
        for comp in self.component_instances:
            errs = comp.validate()
            if errs:
                validation_errors.extend([f"[{comp.name}] {e}" for e in errs])

        if validation_errors:
            print("[RigBuilder Validation Failed]")
            for err in validation_errors:
                print(f"  - {err}")
            return False

        # 3. EDIT MODE PASS (Batched)
        bpy.context.view_layer.objects.active = self.armature_obj
        bpy.ops.object.mode_set(mode='EDIT')
        for comp in self.component_instances:
            print('==========',comp.name, '==========')
            comp.build_edit()

        edit_bones = self.armature_obj.data.edit_bones
        print("FINAL PARENT CHECK:")
        for b_name in ["root_ctrl.C", "pelvis_fk_ctrl.C", "spine_fk_01_ctrl.C", "leg_footik_ctrl.R"]:
            eb = edit_bones.get(b_name)
            p_name = eb.parent.name if (eb and eb.parent) else None
            print(f"  {b_name} -> {p_name}")

        # 4. POSE MODE PASS (Batched)
        bpy.ops.object.mode_set(mode='POSE')
        for comp in self.component_instances:
            comp.build_pose()

        # 5. CONFIGURABLE DRIVERS PASS (Component-scoped & Global)
        all_driver_specs = []
        for comp in self.component_instances:
            comp_drivers = comp.params.get("drivers", [])
            if comp_drivers:
                all_driver_specs.extend(comp_drivers)

        global_drivers = self.config.get("drivers", [])
        if global_drivers:
            all_driver_specs.extend(global_drivers)

        if all_driver_specs:
            systems_framework.apply_configurable_drivers(
                self.armature_obj, self.context, all_driver_specs
            )

        # 6. FINALIZATION PASS
        core_framework.apply_color_coding(self.armature_obj)
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        self.armature_obj["autorig_version"] = "1.0"
        self.armature_obj["autorig_type"] = self.config.get("rig_name", "Biped_Character_Rig")

        core_framework.apply_color_coding(self.armature_obj)
        bpy.ops.object.mode_set(mode='OBJECT')
        print(f"[RigBuilder] Successfully built '{self.config.get('rig_name', 'Rig')}' with {len(self.component_instances)} components.")
        return True

def execute_rig_build(armature_obj: bpy.types.Object, config_filepath: str):
    if not os.path.exists(config_filepath):
        print(f"[Build Error] Config file not found: {config_filepath}")
        return

    print(f"[RigBuilder] Loaded components in registry: {list(base_component.COMPONENT_REGISTRY.keys())}")

    with open(config_filepath, 'r') as f:
        config_data = json.load(f)

    validator = config_validator.ConfigValidator(config_data)
    validator.register_check(validatiors.check_component_uniqueness)
    validator.register_check(validatiors.check_bone_name_collisions_and_length)
    validator.register_check(validatiors.check_socket_references_and_order)
    validator.register_check(validatiors.check_side_token_consistency)
    validator.register_check(validatiors.check_driver_targets)
    validator.register_check(validatiors.check_deform_and_guide_naming_smells)
    # 2. Run static validation (aborts if any error occurs)
    validator.run()

    builder = RigBuilder(armature_obj=armature_obj, config=config_data)
    success = builder.build()

    if success:
        print(f"[Build Complete] '{config_data.get('rig_name')}' generated successfully.")