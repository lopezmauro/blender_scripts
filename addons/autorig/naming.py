"""addons/autorig/naming.py

Standardized naming convention module for rigging components.
Format:
  {name}_{extra}_{index}_{role}.{side}
  - Prefix separator is strictly underscore '_'.
  - Multi-word sub-elements (name, extra) are camelCase.
  - Suffix is separated by a period: .{side} (.L, .R, .C)
"""

from typing import Optional, Union, Tuple

SIDE_LEFT = "L"
SIDE_RIGHT = "R"
SIDE_CENTER = "C"

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
    "c": SIDE_CENTER,
    "center": SIDE_CENTER,
    "mid": SIDE_CENTER,
    "m": SIDE_CENTER,
    "": SIDE_CENTER,
    None: SIDE_CENTER,
}


def to_camel_case(text: str) -> str:
    """Converts snake_case or delimited tokens into camelCase."""
    tokens = [t for t in text.replace("-", "_").replace(".", "_").split("_") if t]
    if not tokens:
        return ""
    return tokens[0].lower() + "".join(t.capitalize() for t in tokens[1:])

def normalize_side(side: Optional[str]) -> str:
    """Normalizes side strings to 'L', 'R', or 'C' for center/omitted."""
    if not side:
        return SIDE_CENTER
    side_clean = str(side).strip().lower().lstrip("._-")
    return VALID_SIDES.get(side_clean, SIDE_CENTER)


def format_name(
    name: str,
    extra: Optional[str] = None,
    index: Optional[Union[int, str]] = None,
    role: Optional[str] = None,
    side: Optional[str] = None,
) -> str:
    """
    Formats a standardized bone name: {name}_{extra}_{index}_{role}.{side}
    """
    tokens = [to_camel_case(name)]

    if extra:
        camel_extra = to_camel_case(extra)
        if camel_extra:
            tokens.append(camel_extra)

    if index is not None:
        if isinstance(index, int):
            tokens.append(f"{index:02d}")
        else:
            idx_str = str(index).strip("._-")
            if idx_str.isdigit():
                tokens.append(f"{int(idx_str):02d}")
            elif idx_str:
                tokens.append(idx_str)

    if role:
        tokens.append(role.strip("._-").lower())

    base_name = "_".join(tokens)
    norm_side = normalize_side(side)

    return f"{base_name}.{norm_side}"


def get_mirror_name(name: str) -> str:
    """Returns the mirrored counterpart of a given name (.L <-> .R)."""
    if name.endswith(f".{SIDE_LEFT}"):
        return f"{name[:-2]}.{SIDE_RIGHT}"
    if name.endswith(f".{SIDE_RIGHT}"):
        return f"{name[:-2]}.{SIDE_LEFT}"
    return name

def parse_bone_side(bone_name: str) -> Tuple[str, Optional[str]]:
    """
    Extracts the base name and normalized side from a bone name.
    e.g., 'lip_upper.L' -> ('lip_upper', 'L')
          'nose_bridge'  -> ('nose_bridge', None)
    """
    # Clean possible suffixes like .L, .R, _L, _R
    for sep in [".", "_"]:
        if sep not in bone_name:
            continue
        tokens = bone_name.split(sep)
        side_token = tokens[-1]
        norm = normalize_side(side_token)
        if norm:
            return sep.join(tokens[:-1]), norm
    return bone_name, None