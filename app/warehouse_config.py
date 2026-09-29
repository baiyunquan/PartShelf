"""Declarative geometry and stable identifiers for warehouse cabinets."""


_DEFAULT_DRAWER_GROUPS = (
    {
        "typeCode": "S",
        "typeLabelKey": "drawer_type_small",
        "drawerWidthMm": 50,
        "drawerHeightMm": 36,
        "drawerDepthMm": 140,
        "rows": 5,
        "columns": 6,
        "gapMm": 2,
        "xMm": 42.5,
        "yMm": 45,
    },
    {
        "typeCode": "L",
        "typeLabelKey": "drawer_type_large",
        "drawerWidthMm": 110,
        "drawerHeightMm": 60,
        "drawerDepthMm": 140,
        "rows": 3,
        "columns": 3,
        "gapMm": 2,
        "xMm": 31.5,
        "yMm": 245,
    },
)

_DEFAULT_CABINET = {
    "widthMm": 395,
    "depthMm": 160,
    "heightMm": 485,
    "drawerGroups": _DEFAULT_DRAWER_GROUPS,
}

# Cabinet IDs are permanent; adding a cabinet never renumbers an existing one.
CABINET_SPECS = tuple(
    {**_DEFAULT_CABINET, "id": f"BOX-{number:03d}", "displayNumber": number}
    for number in range(3)
)


def get_cabinet_config():
    cabinets = []
    for spec in CABINET_SPECS:
        groups = []
        for group_spec in spec["drawerGroups"]:
            group = dict(group_spec)
            group["drawers"] = []
            drawer_count = group["rows"] * group["columns"]
            for sequence in range(1, drawer_count + 1):
                row = (sequence - 1) // group["columns"] + 1
                column = (sequence - 1) % group["columns"] + 1
                code = f"{group['typeCode']}-{sequence:02d}"
                group["drawers"].append(
                    {
                        "code": code,
                        "row": row,
                        "column": column,
                        "widthMm": group["drawerWidthMm"],
                        "heightMm": group["drawerHeightMm"],
                        "depthMm": group["drawerDepthMm"],
                        "xMm": group["xMm"]
                        + (column - 1) * (group["drawerWidthMm"] + group["gapMm"]),
                        "yMm": group["yMm"]
                        + (row - 1) * (group["drawerHeightMm"] + group["gapMm"]),
                        "qrPayload": f"PARTSHELF-WH:{spec['id']}:{code}",
                    }
                )
            groups.append(group)

        cabinets.append(
            {
                "id": spec["id"],
                "displayNumber": spec["displayNumber"],
                "widthMm": spec["widthMm"],
                "depthMm": spec["depthMm"],
                "heightMm": spec["heightMm"],
                "drawerGroups": groups,
            }
        )
    return cabinets
