"""§190: turn the saved wikitext into a per-move table of `(base, ascension values)`.

`{{Asc|2|12}}` means "at Ascension 2 this number is 12"; the wiki uses level `2`/`3`/`4` for the
damage tiers of normal/elite/boss moves and `17`/`18`/`19` for the move-set tiers. This script does
**not** decide which of those apply to us (that is `port-plan.md` §187's kind-based rule); it only
reports what the page says, grouped by section, so the transcription is a reading exercise instead of
a guessing one.
"""
import io
import os
import re

DIR = os.path.join("native", "wiki_asc")

ROW = re.compile(r"\{\{Intents Table/row([\s\S]*?)\}\}", re.S)
ASC = re.compile(r"\{\{Asc\|(\d+)\|([^}|]*)\}\}")


def expand(effect: str) -> str:
    def repl(match):
        return "{A%s:%s}" % (match.group(1), match.group(2).strip())

    return ASC.sub(repl, effect).replace("\n", " ").strip()


def main():
    for name in sorted(os.listdir(DIR)):
        if not name.endswith(".txt"):
            continue
        text = io.open(os.path.join(DIR, name), encoding="utf-8").read()
        print("=" * 70)
        print(name[:-4])
        # Section headings: `== Pattern ==` / `=== Gremlin Wizard ===` style, so a page holding three
        # monsters reports which rows belong to which.
        section = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("=="):
                section = stripped.strip("= ")
            elif stripped.startswith("| Name") and "=" in stripped and section:
                pass
        for match in ROW.finditer(text):
            body = match.group(1)
            name_field = re.search(r"\|\s*Name\s*=\s*([^|\n]+)", body)
            effect = re.search(r"\|\s*Effect\s*=\s*([\s\S]+?)(?:\n\s*\||\Z)", body)
            if not (name_field and effect):
                continue
            # Which infobox this row belongs to: the closest `| Type = ` above it.
            prefix = text[: match.start()]
            kind = ""
            for box in re.finditer(r"\{\{Enemy Infobox([\s\S]*?)\}\}", prefix):
                pass
            boxes = list(re.finditer(r"\{\{Enemy Infobox([\s\S]*?)\}\}", prefix))
            if boxes:
                box = boxes[-1].group(1)
                kind = (re.search(r"\|\s*Type\s*=\s*([^|\n]+)", box) or [None, "?"])[1].strip()
                box_name = (re.search(r"\|\s*Name\s*=\s*([^|\n]+)", box) or [None, "?"])[1].strip()
                kind = box_name + " [" + kind + "]"
            print(
                "  %-22s %-28s %s"
                % (name_field.group(1).strip(), kind, expand(effect.group(1))[:150])
            )


if __name__ == "__main__":
    main()
