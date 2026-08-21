import abc
import bpy
from typing import Dict, Any, Optional, List, Type
from . import core_framework

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
    def __init__(self, name: str, params: Dict[str, Any], context: RigContext):
        self.name: str = name
        self.params: Dict[str, Any] = params
        self.context: RigContext = context
        self.armature_obj: bpy.types.Object = context.armature_obj
        self.outputs: Dict[str, str] = {}

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