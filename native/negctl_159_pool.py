"""§159b negative control for `every_pool_in_the_image_fits_the_pool_capacity`.

Appends two ids to `EncounterTables.Weak` (7 -> 9) so the 8-wide reader would silently truncate.
The test must go **red**; then run again with `--restore`.
"""
import json
import pathlib
import sys

PATH = pathlib.Path("tools/contentc/packages/sts/sts.roguedeck.json")
MARK = "__negctl_probe__"


def main():
    restore = "--restore" in sys.argv
    doc = json.loads(PATH.read_bytes().decode("utf-8"))
    weak = doc["EncounterTables"]["Weak"]
    if restore:
        doc["EncounterTables"]["Weak"] = [row for row in weak if not row["Id"].startswith(MARK)]
    else:
        assert not any(row["Id"].startswith(MARK) for row in weak), "already patched"
        for suffix in ("a", "b"):
            weak.append({"Id": MARK + suffix, "Weight": 1})
    PATH.write_bytes((json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print("Weak pool now", len(doc["EncounterTables"]["Weak"]), "entries")


if __name__ == "__main__":
    main()
