"""addons/autorig/naming.py

Standardized naming convention module for rigging components.
Format:
  - Sided elements:  {name}_{role}_{index}.{L|R}  (e.g., arm_ik_ctrl.L, finger_def_01.R)
  - Center elements: {name}_{role}_{index}        (e.g., spine_fk_ctrl_01, root_ctrl)
"""

from typing import Optional, Union

SIDE_LEFT = "L"
SIDE_RIGHT = "R"

# Role definitions
ROLE_CTRL = "ctrl"
ROLE_DEF = "def"
ROLE_MCH = "mch"
ROLE_GUIDE = "guide"
ROLE_ORG = "org"

VALID_SIDES = {
    "l": SIDE_LEFT,
    "left": SIDE_LEFT,
    "r": SIDE_RIGHT,
    "right": SIDE_RIGHT,
    "c": None,
    "center": None,
    "mid": None,
    "m": None,
    "": None,
    None: None,
}


def normalize_side(side: Optional[str]) -> Optional[str]:
    """Normalizes side strings to 'L', 'R', or None for center/omitted."""
    if not side:
        return None
    side_clean = side.strip().lower().lstrip("._-")
    return VALID_SIDES.get(side_clean, None)


def format_name(
    name: str,
    role: Optional[str] = None,
    side: Optional[str] = None,
    index: Optional[Union[int, str]] = None,
) -> str:
    """Formats a standardized bone or object name.

    Omits side suffixes for center/non-sided elements.
    """
    tokens = [name.strip("._-")]

    if role:
        tokens.append(role.strip("._-"))

    if index is not None:
        formatted_index = f"{index:02d}" if isinstance(index, int) else str(index)
        tokens.append(formatted_index)

    base_name = "_".join(tokens)
    norm_side = normalize_side(side)

    if norm_side:
        return f"{base_name}.{norm_side}"
    return base_name


def get_mirror_name(name: str) -> str:
    """Returns the mirrored counterpart of a given name (.L <-> .R)."""
    if name.endswith(f".{SIDE_LEFT}"):
        return f"{name[:-2]}.{SIDE_RIGHT}"
    if name.endswith(f".{SIDE_RIGHT}"):
        return f"{name[:-2]}.{SIDE_LEFT}"
    return name