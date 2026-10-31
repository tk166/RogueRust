"""soak_test.mjs: report the choice coverage and count the empty answers.

`choiceEmpty` was declared and never incremented -- a dead counter is worse than no counter (the
gate prints a number that means nothing).
"""
import io

PATH = "web/soak_test.mjs"


def sub(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    text = sub(
        text,
        """        if (confirm) {
          groups[0].push({ kind: "choice-confirm", el, label: text(confirm) });
        }""",
        """        if (confirm) {
          // "Answer with nothing" is a real choice (both potions say "any number"), so it is
          // counted separately from "ticked something": a picker whose ticks never reach the
          // kernel and one nobody ever ticked look identical from the outside otherwise.
          if (!options.some((el) => el.dataset.ticked === "1")) out.choiceEmpty += 1;
          groups[0].push({ kind: "choice-confirm", el, label: text(confirm) });
        }""",
    )

    text = sub(
        text,
        """console.log("  screens           " + report.screens.join(" / "));""",
        """console.log("  screens           " + report.screens.join(" / "));
console.log(
  "  choices           " + (report.choices || 0) + " card question(s) · " +
    (report.choiceTicked || 0) + " tick(s) · " + (report.choiceEmpty || 0) + " answered with nothing"
);""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("soak_test.mjs: choice coverage reported")


if __name__ == "__main__":
    main()
