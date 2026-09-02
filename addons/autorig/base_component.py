import abc
import bpy
import re
from typing import Dict, Any, Optional, List, Type, Union
from . import core_framework, naming

# --- GLOBAL COMPONENT REGISTRY ---
COMPONENT_REGISTRY: Dict[str, Type['BaseRigComponent']] = {}


def register_component(type_name: str):
    """Decorator to register rig components into the global registry."""
    def decorator(cls: Type['BaseRigComponent']):
        COMPONENT_REGISTRY[type_name] = cls
        return cls
    return decorator

class RigContext:
    def __init__(self, armature_obj: bpy.types.Object, config: Dict[str, Any]):
        self.armature_obj: bpy.types.Object = armature_obj
        self.config: Dict[str, Any] = config
        self.sockets: Dict[str, str] = {}
        self.shapes: Dict[str, bpy.types.Object] = {}
        self.components: Dict[str, 'BaseRigComponent'] = {}

    def register_socket(self, socket_path: str, bone_name: str) -> None:
        self.sockets[socket_path] = bone_name

    def resolve_socket(self, socket_path: Optional[str]) -> Optional[str]:
        if not socket_path:
            return None
        if socket_path in self.sockets:
            return self.sockets[socket_path]
        resolved = core_framework.find_bone_name(self.armature_obj, socket_path)
        return resolved if resolved else socket_path


class BaseRigComponent(abc.ABC):
    def __init__(self, name: str, params: Dict[str, Any], context: RigContext, side: Optional[str] = None):
        self.name: str = name
        self.side = naming.normalize_side(side)
        self.params: Dict[str, Any] = params
        self.context: RigContext = context
        self.armature_obj: bpy.types.Object = context.armature_obj
        self.outputs: Dict[str, str] = {}
        self.edit_data = {}
        self._controls: List[str] = []

    @property
    def controls(self) -> List[str]:
        """Returns the list of animation control bone names created by this component."""
        return list(dict.fromkeys(self._controls))



    def format_name(
        self,
        sub_name: Optional[str] = None,
        extra: Optional[str] = None,
        index: Optional[Union[int, str]] = None,
        role: Optional[str] = None,
        side: Optional[str] = None,
    ) -> str:
        """
        Builds standardized bone names: {name}_{extra}_{index}_{role}.{side}
        """
        # 1. Base component name normalized (e.g. "hair_clumps" -> "hairClump", "ear_r" -> "ear")
        clean_comp = re.sub(r'_[lrLR]$', '', self.name).strip("._-")
        clean_comp_singular = re.sub(r's$', '', clean_comp)
        
        comp_flat = clean_comp.lower().replace("_", "").rstrip("s")
        comp_pattern = re.compile(
            rf"^(?:{re.escape(clean_comp)}|{re.escape(clean_comp_singular)}|{re.escape(comp_flat)})_?",
            re.IGNORECASE
        )

        base_name = clean_comp_singular
        parsed_extra_parts = []
        parsed_index = index
        target_side = side if side is not None else self.side

        if sub_name:
            # Normalize camelCase/PascalCase to snake_case for token extraction
            s_clean = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', sub_name.strip("._-")).lower()
            s_clean = re.sub(r'_[lrLR]$', '', s_clean)

            # Strip redundant 'finger' tag in finger chains
            s_clean = re.sub(r'finger', '', s_clean)

            # Extract trailing numeric index
            if parsed_index is None:
                num_match = re.search(r'(\d+)$', s_clean)
                if num_match:
                    parsed_index = num_match.group(1)
                    s_clean = s_clean[:num_match.start()].rstrip("._-")

            # Clean anatomical affixes (e.g. 'upperarm' -> 'up', 'lowerarm' -> 'low')
            if s_clean.startswith("upper") or s_clean.startswith("up_"):
                s_clean = "up"
            elif s_clean.startswith("lower") or s_clean.startswith("low_"):
                s_clean = "low"

            # Check if sub_name shares compound tokens (e.g. "neck" in "neck_head")
            comp_tokens = [t.lower().rstrip("s") for t in clean_comp.split("_") if t]
            sub_tokens = [t for t in s_clean.split("_") if t]

            matched_compound_token = None
            remaining_sub_tokens = []
            for st in sub_tokens:
                st_norm = st.rstrip("s")
                if st_norm in comp_tokens:
                    matched_compound_token = st_norm
                else:
                    remaining_sub_tokens.append(st)

            if matched_compound_token and len(comp_tokens) > 1:
                base_name = matched_compound_token
                if remaining_sub_tokens:
                    parsed_extra_parts.extend(remaining_sub_tokens)
            else:
                # Safely strip component prefix
                stripped_sub = comp_pattern.sub('', s_clean).strip("._-")
                if stripped_sub and stripped_sub != comp_flat:
                    parsed_extra_parts.append(stripped_sub)

        if extra:
            parsed_extra_parts.append(extra.strip("._-"))

        # Convert combined extra tokens into clean camelCase
        joined_extra = naming.to_camel_case("_".join(filter(None, parsed_extra_parts))) or None

        return naming.format_name(
            name=base_name,
            extra=joined_extra,
            index=parsed_index,
            role=role,
            side=target_side,
        )


    def register_control(self, bone_name: Optional[str]) -> Optional[str]:
        """Registers a bone name as an animation control."""
        if bone_name and bone_name not in self._controls:
            self._controls.append(bone_name)
        return bone_name

    def register_output(self, key: str, bone_name: str) -> None:
        self.outputs[key] = bone_name
        self.context.register_socket(f"{self.name}.{key}", bone_name)

    def resolve_parent_socket(self, param_key: str = "parent_socket") -> Optional[str]:
        socket_target = self.params.get(param_key)
        return self.context.resolve_socket(socket_target)

    @abc.abstractmethod
    def validate(self) -> List[str]:
        pass

    @abc.abstractmethod
    def build_edit(self) -> None:
        pass

    @abc.abstractmethod
    def build_pose(self) -> None:
        pass