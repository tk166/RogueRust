"""§158 negative control: make the Dexterity spec's pipeline string wrong.

`status_bind.rs` names this exact trap: the wire string is `BlockGain`, and the kernel's *folder*
enum calls the same thing `Block`. A spec written with the wrong string is a spec that never
matches -- Dexterity applies, Block does not move, and nothing says so. So: flip it, rebuild, run
`dexterity_from_the_content_scales_a_real_defend`, and it must go **red**. Then run the same script
again with `--restore`.
"""

import json
import pathlib
import sys

PATH = pathlib.Path("tools/contentc/packages/sts/sts.roguedeck.json")
WRONG = "BlockGained"
RIGHT = "BlockGain"


def main():
    restore = "--restore" in sys.argv
    doc = json.loads(PATH.read_bytes().decode("utf-8"))
    row = next(status for status in doc["Statuses"] if status["Id"] == "standard.dexterity")
    spec = row["PassiveModifiers"][0]
    before = spec["Pipeline"]
    spec["Pipeline"] = RIGHT if restore else WRONG
    PATH.write_bytes((json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    print("standard.dexterity pipe:", before, "->", spec["Pipeline"])


if __name__ == "__main__":
    main()
