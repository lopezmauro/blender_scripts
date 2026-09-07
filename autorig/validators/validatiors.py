import re
from typing import Optional, Dict, Any, List, Set
from .. import naming
from .config_validator import ValidationResult

def check_component_uniqueness(config: Dict[str, Any]) -> ValidationResult:
    """Ensures all components declare unique, non-empty names."""
    res = ValidationResult("Component Name Uniqueness")
    seen: Dict[str, int] = {}

    components = config.get("components", [])
    if not components:
        res.add_error("Configuration contains no components.")
        return res

    for idx, comp in enumerate(components):
        name = comp.get("name")
        if not name:
            res.add_error(f"Component at index {idx} has no 'name' defined.")
            continue

        if name in seen:
            res.add_error(
                f"Duplicate component name '{name}' at index {idx} (first defined at index {seen[name]})."
            )
        else:
            seen[name] = idx

    return res


def check_bone_name_collisions_and_length(config: Dict[str, Any]) -> ValidationResult:
    """
    Predicts control bone names, ensuring no collisions and adhering to 
    Blender's 63-character limit.
    """
    res = ValidationResult("Bone Collision & Character Limit (<=63)")
    seen_bones: Dict[str, str] = {}

    for comp in config.get("components", []):
        comp_name = comp.get("name", "")
        comp_type = comp.get("type", "")
        params = comp.get("params", {})
        comp_side = params.get("side")

        predicted_bones: List[str] = []

        # Predict controls based on common component patterns
        if comp_type == "Root":
            predicted_bones.append(
                naming.derive_component_bone_name(
                    comp_name=comp_name, role=naming.ROLE_CTRL, side=comp_side
                )
            )

        elif comp_type == "FKChain":
            for b in params.get("deform_chain", []):
                base_b, b_side = naming.parse_bone_side(b)
                predicted_bones.append(
                    naming.derive_component_bone_name(
                        comp_name=comp_name,
                        sub_name=base_b,
                        extra="fk",
                        role=naming.ROLE_CTRL,
                        side=b_side or comp_side,
                    )
                )

        elif comp_type == "DirectTweaker":
            explicit_ctrl = params.get("custom_ctrl_name")
            for t in params.get("targets", []):
                t_name = t if isinstance(t, str) else t.get("deform_bone", "")
                ctrl_override = explicit_ctrl if isinstance(t, str) else t.get("ctrl_name", explicit_ctrl)
                if ctrl_override:
                    predicted_bones.append(ctrl_override)
                else:
                    base_b, b_side = naming.parse_bone_side(t_name)
                    predicted_bones.append(
                        naming.derive_component_bone_name(
                            comp_name=comp_name,
                            sub_name=base_b,
                            role=naming.ROLE_CTRL,
                            side=b_side or comp_side,
                        )
                    )

        elif comp_type == "MacroChain":
            chains = params.get("chains", {})
            for ch_name in chains:
                predicted_bones.append(
                    naming.derive_component_bone_name(
                        comp_name=comp_name, sub_name=ch_name, role=naming.ROLE_CTRL, side=comp_side
                    )
                )

        elif comp_type == "SettingsNode":
            ctrl = params.get("custom_ctrl_name", f"{comp_name}_ctrl")
            predicted_bones.append(ctrl)

        for bone in predicted_bones:
            # 1. 63-char Blender limit
            if len(bone) > 63:
                res.add_error(
                    f"Component '{comp_name}' generated bone '{bone}' "
                    f"exceeding Blender's 63-char limit ({len(bone)} chars)."
                )

            # 2. Collision check
            if bone in seen_bones:
                res.add_error(
                    f"Bone collision: Component '{comp_name}' predicts bone '{bone}', "
                    f"which was already declared by component '{seen_bones[bone]}'."
                )
            else:
                seen_bones[bone] = comp_name

    return res


def check_socket_references_and_order(config: Dict[str, Any]) -> ValidationResult:
    """
    Validates socket dot-notation syntax and verifies that socket targets 
    are declared prior to being consumed (preventing forward-reference cycles).
    """
    res = ValidationResult("Socket References & Dependency Order")
    declared_components: Set[str] = set()

    for comp in config.get("components", []):
        comp_name = comp.get("name", "")
        params = comp.get("params", {})

        # Collect all socket references declared in params
        socket_keys = ["parent_socket", "root_socket", "follow_target", "isolate_target"]
        target_sockets = [params.get(k) for k in socket_keys if params.get(k)]

        # Handle nested dictionary parent sockets (e.g. finger chains)
        parent_sockets_dict = params.get("parent_sockets", {})
        if isinstance(parent_sockets_dict, dict):
            target_sockets.extend(parent_sockets_dict.values())

        # DirectTweaker target follow sockets
        for item in params.get("targets", []):
            if isinstance(item, dict) and item.get("follow_target"):
                target_sockets.append(item.get("follow_target"))

        for socket_str in target_sockets:
            if not isinstance(socket_str, str):
                continue

            # Must follow format: <component_name>.<socket_key>
            if "." not in socket_str:
                res.add_error(
                    f"Component '{comp_name}' declares invalid socket format '{socket_str}'. "
                    f"Sockets must follow '<component>.<output>' syntax."
                )
                continue

            provider_comp = socket_str.split(".")[0]

            if provider_comp not in declared_components:
                res.add_error(
                    f"Component '{comp_name}' references undeclared or forward socket provider "
                    f"'{provider_comp}' in socket '{socket_str}'."
                )

        declared_components.add(comp_name)

    return res


def check_side_token_consistency(config: Dict[str, Any]) -> ValidationResult:
    """
    Flags mismatches where a component's explicit side parameter conflicts 
    with individual bone target side tokens.
    """
    res = ValidationResult("Side Token Consistency")

    for comp in config.get("components", []):
        comp_name = comp.get("name", "")
        params = comp.get("params", {})
        comp_side = params.get("side")

        if not comp_side:
            continue

        normalized_comp_side = naming.normalize_side(comp_side)

        # Collect all bones defined inside the component
        target_bones: List[str] = []
        if "deform_chain" in params:
            target_bones.extend(params["deform_chain"])
        if "targets" in params:
            for t in params["targets"]:
                target_bones.append(t if isinstance(t, str) else t.get("deform_bone", ""))
        if "chains" in params and isinstance(params["chains"], dict):
            for chain_list in params["chains"].values():
                target_bones.extend(chain_list)

        for bone in target_bones:
            _, bone_side = naming.parse_bone_side(bone)
            if bone_side and bone_side != naming.SIDE_CENTER and bone_side != normalized_comp_side:
                res.add_error(
                    f"Side mismatch in '{comp_name}': Component has side='{normalized_comp_side}', "
                    f"but targeted bone '{bone}' has opposing side='{bone_side}'."
                )

    return res


def check_driver_targets(config: Dict[str, Any]) -> ValidationResult:
    res = ValidationResult("Driver Target Integrity")
    declared_components = {c.get("name") for c in config.get("components", []) if c.get("name")}

    def extract_component(path: str) -> Optional[str]:
        if not path:
            return None
        parts = path.split(".")
        # If there is only one dot and the second token is a side suffix (e.g. 'up_eyelid.L'),
        # it is a standalone bone name, not a socket path.
        if len(parts) == 2 and parts[1].upper() in {"L", "R", "C"}:
            return None
        return parts[0]

    for driver in config.get("drivers", []):
        d_name = driver.get("name", "<unnamed>")

        source_comp = extract_component(driver.get("source", {}).get("bone", ""))
        if source_comp and source_comp not in declared_components:
            res.add_error(
                f"Driver '{d_name}' source points to undeclared component '{source_comp}'."
            )

        for d in driver.get("drivens", []):
            driven_comp = extract_component(d.get("bone", ""))
            if driven_comp and driven_comp not in declared_components:
                res.add_error(
                    f"Driver '{d_name}' driven target points to undeclared component '{driven_comp}'."
                )

    return res

def check_deform_and_guide_naming_smells(config: Dict[str, Any]) -> ValidationResult:
    """
    Audits deform bone and guide names for styling inconsistencies, 
    missing side tags on sided components, and anti-patterns.
    """
    res = ValidationResult("Deform Joints & Guides Naming Smells")

    casing_styles: Dict[str, List[str]] = {"snake_case": [], "camelCase": []}
    suspected_typo_patterns = [
        (re.compile(r"eyerobital", re.IGNORECASE), "Did you mean 'eye_orbital' or 'orbital'?"),
    ]

    for comp in config.get("components", []):
        comp_name = comp.get("name", "")
        params = comp.get("params", {})
        comp_side = params.get("side")

        # 1. Collect all input deform targets
        deform_bones: List[str] = []
        if "deform_bone" in params:
            deform_bones.append(params["deform_bone"])
        if "deform_chain" in params:
            deform_bones.extend(params["deform_chain"])
        if "targets" in params:
            for t in params["targets"]:
                deform_bones.append(t if isinstance(t, str) else t.get("deform_bone", ""))
        if "chains" in params and isinstance(params["chains"], dict):
            for chain_list in params["chains"].values():
                deform_bones.extend(chain_list)

        for b in filter(None, deform_bones):
            base_b, bone_side = naming.parse_bone_side(b)

            # Smell: Target bone in a sided component missing side suffix (.L / .R)
            if comp_side and not bone_side:
                res.add_warning(
                    f"Component '{comp_name}' is sided ({comp_side}), but deform bone "
                    f"'{b}' lacks an explicit side suffix (.L or .R)."
                )

            # Smell: Deform joint containing explicit rigging role tokens
            for role_token in [naming.ROLE_CTRL, naming.ROLE_MCH, naming.ROLE_GUIDE, naming.ROLE_ORG]:
                if re.search(rf"(?:^|[_\.]){role_token}(?:[_\.]|$)", base_b, re.IGNORECASE):
                    res.add_warning(
                        f"Deform joint '{b}' in '{comp_name}' contains rigging role token "
                        f"'{role_token}'. Deform sources should avoid controller/mechanism affixes."
                    )

            # Smell: Known anatomical typos
            for pattern, suggestion in suspected_typo_patterns:
                if pattern.search(base_b):
                    res.add_warning(
                        f"Deform joint '{b}' in '{comp_name}' matched suspected spelling smell: {suggestion}"
                    )

            # Track casing style across bones
            clean_base = re.sub(r'\d+$', '', base_b)
            if "_" in clean_base and clean_base.islower():
                casing_styles["snake_case"].append(b)
            elif re.search(r'[a-z][A-Z]', clean_base):
                casing_styles["camelCase"].append(b)

        # 2. Guide-specific checks
        guide_keys = ["pole_guide", "guide", "guide_bone"]
        for g_key in guide_keys:
            guide_bone = params.get(g_key)
            if not guide_bone:
                continue

            base_g, g_side = naming.parse_bone_side(guide_bone)

            # Smell: Sided guide missing side token
            if comp_side and not g_side:
                res.add_warning(
                    f"Guide bone '{guide_bone}' in sided component '{comp_name}' "
                    f"lacks an explicit side suffix."
                )

            # Smell: Guide missing guide role or descriptor tag
            if "guide" not in base_g.lower() and naming.ROLE_GUIDE not in base_g.lower():
                res.add_warning(
                    f"Guide bone '{guide_bone}' in '{comp_name}' lacks a 'guide' descriptor "
                    f"in its base name."
                )

    # 3. Rig-wide casing consistency check
    snake_count = len(casing_styles["snake_case"])
    camel_count = len(casing_styles["camelCase"])
    if snake_count > 0 and camel_count > 0:
        res.add_warning(
            f"Mixed casing conventions detected across deform bones: "
            f"{snake_count} snake_case vs {camel_count} camelCase. "
            f"(e.g., '{casing_styles['snake_case'][0]}' vs '{casing_styles['camelCase'][0]}')."
        )

    return res