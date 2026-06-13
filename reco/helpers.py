"""
Ad-hoc helper functions to be used anywhere in the codebase.
"""


def csv_to_list(item):
    if item is None or not isinstance(item, str) or len(item) == 0:
        return []

    li = [str.strip() if len(
        str.strip()) > 0 else None for str in item.strip().split(",")]

    li = [str for str in li if str is not None]

    return li
