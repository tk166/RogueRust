"""web/index.html: the §161.3 card-choice picker.

Three edits:
  * a CSS rule for a ticked option,
  * `maybeShowChoice()` + the wiring in `act`,
  * `closeModal` learns that one modal cannot be dismissed (the choice), because the action table
    is empty until it is answered -- closing it would leave a page with no way forward.
"""
import io

PATH = "web/index.html"


def sub(text, old, new):
    assert text.count(old) == 1, (text.count(old), old[:70])
    return text.replace(old, new)


def main():
    text = io.open(PATH, encoding="utf-8").read()

    # ---- pileId: the picker shows both the title and the id (the deck picker does) ----------
    text = sub(
        text,
        """const pileTitle = (zone, index) =>
  readText((k) => ex.rd_env_pile_card_title_len(zone, k),
           (p, k) => ex.rd_env_pile_card_title_into(zone, k, p), index);""",
        """const pileTitle = (zone, index) =>
  readText((k) => ex.rd_env_pile_card_title_len(zone, k),
           (p, k) => ex.rd_env_pile_card_title_into(zone, k, p), index);
// §161.3: the choice picker shows the id under the title, like the deck picker does -- two cards
// with the same `NameKey` (a `+` row reuses it) are otherwise indistinguishable.
const pileId = (zone, index) =>
  readText((k) => ex.rd_env_pile_card_id_len(zone, k),
           (p, k) => ex.rd_env_pile_card_id_into(zone, k, p), index);""",
    )

    # ---- CSS ---------------------------------------------------------------------------------
    text = sub(
        text,
        """  button.card.pick:hover { background: #2b3648; border-color: var(--energy); }""",
        """  button.card.pick:hover { background: #2b3648; border-color: var(--energy); }
  /* A ticked option in the card-choice picker (§161.3). The border is the *only* signal, so it has
     to be strong: `.picking` is the same colour the hand uses for "armed", which is the gesture
     players already know from targeting. */
  button.card.pick[data-ticked="1"] { border-color: var(--energy); background: #2b3648;
                                      box-shadow: inset 0 0 0 1px var(--energy); }""",
    )

    # ---- closeModal cannot close a pending choice -------------------------------------------
    text = sub(
        text,
        """function closeModal() {
  document.getElementById("modal").hidden = true;
}""",
        """function closeModal() {
  // §161.3: one modal **cannot** be dismissed. The kernel's action table is empty while a card
  // choice is pending, so a player who closed the picker would be looking at a page with no way
  // forward -- the "dead button" failure in its purest form. The three dismissal affordances all
  // come through here (`port-plan.md` §151), which is why one guard is enough.
  if (ex.rd_env_choice_pending() === 1) return;
  document.getElementById("modal").hidden = true;
}""",
    )

    # ---- the picker itself ------------------------------------------------------------------
    text = sub(
        text,
        """function showDeckPicker(title, onPick) {""",
        """/// §161.3: the kernel is waiting for a card choice (Elixir / Gambler's Brew).
///
/// Options are the **source pile**, so they are read through the existing pile exports with zone
/// id `3`; the card faces, the titles and the id chips are the ones the pile viewer already uses.
/// Ticks go to `rd_env_choice_pick` and the answer is handed over in one call
/// (`rd_env_choice_confirm`), which the kernel either takes whole or refuses whole.
///
/// Called from `act` after every action, because a potion is what opens one.
function maybeShowChoice() {
  if (ex.rd_env_choice_pending() !== 1) return;
  const kind = ex.rd_env_choice_kind();
  const count = ex.rd_env_choice_count();
  const min = ex.rd_env_choice_min();
  const max = ex.rd_env_choice_max();
  const titles = {
    1: "消耗任意张手牌",
    2: "弃掉任意张手牌，然后抽同样多张",
  };
  document.getElementById("modalTitle").textContent =
    `${titles[kind] || "选牌"}（0–${max} 张）`;
  const body = document.getElementById("modalBody");
  body.innerHTML = "";

  const confirm = document.createElement("button");
  confirm.className = "card pick";
  confirm.dataset.panelAction = "choice-confirm";
  const only = min > 0 ? `至少 ${min} 张` : "不选";
  confirm.textContent = min > 0 ? `确认（${min}–${max} 张）` : `确认（${only}也可以）`;
  const ticks = [];
  const refresh = () => {
    const picked = ticks.filter(Boolean).length;
    // `min == 0` is both of today's consumers, so "confirm nothing" is a legal answer and the
    // button must stay pressable: a disabled primary button with no visible reason is the other
    // way this screen can dead-end.
    confirm.disabled = picked < min || picked > max;
    confirm.textContent = picked === 0 && min === 0
      ? "确认（一张也不选）"
      : `确认 ${picked} 张`;
    for (const index in ticks) {
      const button = body.querySelector(`[data-choice="${index}"]`);
      if (button) button.dataset.ticked = ticks[index] ? "1" : "0";
    }
  };

  for (let index = 0; index < count; index++) {
    ticks.push(ex.rd_env_choice_selected(index) === 1);
    const button = document.createElement("button");
    button.className = "card pick";
    button.dataset.choice = String(index);
    // One writer per element: the tick state lives in `ticks` and this loop is the only place that
    // paints it (`refresh`), so a second copy cannot drift.
    button.dataset.ticked = ticks[index] ? "1" : "0";
    button.innerHTML = `${esc(pileTitle(3, index) || pileId(3, index))} ` +
      `<span>${esc(pileId(3, index))}</span>`;
    button.onclick = () => {
      const next = !ticks[index];
      ticks[index] = next;
      ex.rd_env_choice_pick(index, next ? 1 : 0);
      refresh();
    };
    body.appendChild(button);
  }
  confirm.onclick = () => {
    closeModal();
    act(() => {
      const verdict = ex.rd_env_choice_confirm();
      ex.rd_env_choice_clear();
      return verdict;
    }, "选牌");
  };
  body.appendChild(confirm);
  document.getElementById("modal").hidden = false;
  refresh();
}

function showDeckPicker(title, onPick) {""",
    )

    # ---- act() shows the picker ---------------------------------------------------------------
    text = sub(
        text,
        """  renderTopBar();
  if (mode === "run") {
    renderMap(verdict);
    renderNode();
  } else {
    obs = readObservation();
    render(undefined, 0);
  }
}""",
        """  renderTopBar();
  if (mode === "run") {
    renderMap(verdict);
    renderNode();
  } else {
    obs = readObservation();
    render(undefined, 0);
  }
  // §161.3: a potion can open a question instead of resolving. It is shown **last**, after the
  // screen behind it is up to date, so that confirming it lands on a page that already agrees with
  // the kernel.
  maybeShowChoice();
}""",
    )

    # the refusal branch re-renders too, and a refused action must not hide an open question
    text = sub(
        text,
        """    // Re-render anyway: a refusal must never eat a pending choice. The player clicked something the
    // kernel would not take, and the panel it replaced (a blessing, a shop, an event) has to come
    // back -- otherwise the only way out is a reload.
    renderNode();
    return;""",
        """    // Re-render anyway: a refusal must never eat a pending choice. The player clicked something the
    // kernel would not take, and the panel it replaced (a blessing, a shop, an event) has to come
    // back -- otherwise the only way out is a reload.
    renderNode();
    maybeShowChoice();
    return;""",
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("index.html: choice picker wired")


if __name__ == "__main__":
    main()
