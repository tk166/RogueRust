"""soak_test.mjs: teach the random walk about the §161.3 card-choice picker.

Three edits:
  * `out` gains the coverage counters,
  * `fingerprint()` counts the modal body (a tick must move something, or it is reported as a dead
    button -- correctly, by the gate's own rule),
  * `candidates()` answers the question instead of hunting for `[data-close]`.
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
        """    arrivals: {}, smithTries: 0, eliteWins: 0, hopsSeen: 0, hopsTaken: 0, plannedHop: -1,
  };""",
        """    arrivals: {}, smithTries: 0, eliteWins: 0, hopsSeen: 0, hopsTaken: 0, plannedHop: -1,
    // §161.3 coverage: the card-choice picker. `ticked` counts the runs that answered it with a
    // **non-empty** selection, which is the half a "just press confirm" walk never reaches.
    choices: 0, choiceTicked: 0, choiceEmpty: 0,
  };""",
    )

    text = sub(
        text,
        """      byId("log").innerText.length,
      text(byId("msg")).slice(0, 40),
      byId("modal").hidden,""",
        """      byId("log").innerText.length,
      text(byId("msg")).slice(0, 40),
      byId("modal").hidden,
      // §161.3: a tick is a real UI change, and it lives nowhere else -- without this the walk
      // reports every tick as a **dead button** (§150's shape) because the page around it did not
      // move. innerHTML, not length: "确认 1 张" and "确认 2 张" are the same length.
      byId("modalBody").innerHTML,""",
    )

    text = sub(
        text,
        """    if (!byId("modal").hidden) {
      // The deck picker (blessing "remove a card", smithing, an event's deck edit) lives in the
      // modal as [data-pick] buttons; the card-detail modal only has a close button. A soak that
      // forgets the picker is stuck at the very first blessing.
      for (const el of document.querySelectorAll("#modalBody [data-pick]")) {
        groups[0].push({ kind: "deck-pick", el, label: text(el) });
      }
      const close = document.querySelector("#modal [data-close]");
      if (close) groups[0].push({ kind: "modal-close", el: close });
      return groups;
    }""",
        """    if (!byId("modal").hidden) {
      // §161.3: a pending card choice is the **only** way forward -- the kernel's action table is
      // empty until it is answered, and `closeModal` refuses to close it. So it owns the candidate
      // list: tick (sometimes) and confirm. Offering `[data-close]` here would be a button that
      // provably does nothing, which is the exact shape this gate exists to catch.
      if (ex.rd_env_choice_pending() === 1) {
        out.choices += 1;
        const options = [...document.querySelectorAll("#modalBody [data-choice]")];
        const unticked = options.filter((el) => el.dataset.ticked !== "1");
        const confirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
        // Six in ten clicks tick: "answer with nothing" is legal for both potions and deserves
        // coverage too, but a walk that always answers "nothing" never proves the picker works.
        if (unticked.length && random() < 0.6) {
          const el = pick(unticked);
          out.choiceTicked += 1;
          groups[0].push({ kind: "choice-tick", el, label: text(el) });
        }
        if (confirm) {
          groups[0].push({ kind: "choice-confirm", el, label: text(confirm) });
        }
        return groups;
      }
      // The deck picker (blessing "remove a card", smithing, an event's deck edit) lives in the
      // modal as [data-pick] buttons; the card-detail modal only has a close button. A soak that
      // forgets the picker is stuck at the very first blessing.
      for (const el of document.querySelectorAll("#modalBody [data-pick]")) {
        groups[0].push({ kind: "deck-pick", el, label: text(el) });
      }
      const close = document.querySelector("#modal [data-close]");
      if (close) groups[0].push({ kind: "modal-close", el: close });
      return groups;
    }""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("soak_test.mjs: choice picker is a first-class candidate")


if __name__ == "__main__":
    main()
