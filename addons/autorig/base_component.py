import abc
import bpy
from typing import Dict, Any, Optional, List, Type
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
        role: Optional[str] = None,
        index: Optional[Union[int, str]] = None,
    ) -> str:
        """Helper to build element names within this component's scope and side."""
        full_base = f"{self.name}_{sub_name}" if sub_name else self.name
        return naming.format_name(
            name=full_base, role=role, side=self.side, index=index
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