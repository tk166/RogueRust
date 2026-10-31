"""§161.7: the offered pool must not contain `+` rows.

Found while adding the power cards: `choice_offered:attack` could hand out `twin_strike+`. StS's
Attack Potion gives the **printed** card -- upgraded copies are not in the card pool, they are made
by upgrading. Handing out a stronger card than the potion promises is the quiet kind of wrong.

Our upgrade convention is the `+` suffix (`RunState::upgrade_at` appends it), so the filter is on
the id, and the power cards are what made it visible: with three base power cards and their three
`+` rows, the offered three would otherwise have been a mix.
"""
import io

RUN = "kernel/rd-wasm/src/run.rs"
CONTENT = "kernel/rd-core/src/content.rs"


def main():
    run = io.open(RUN, encoding="utf-8").read()
    old = """                let Some(id) = image.string(row.id()) else {
                    continue;
                };
                if image.card_has_tag(id, tag) != Some(true) {
                    continue;
                }"""
    new = """                let Some(id) = image.string(row.id()) else {
                    continue;
                };
                // §161.7: a `+` row is a **different** card (our upgrade convention appends `+`),
                // and StS's potion gives the printed card, not an upgraded one. Without this the
                // pool would sometimes hand out `twin_strike+`.
                if id.ends_with('+') {
                    continue;
                }
                if image.card_has_tag(id, tag) != Some(true) {
                    continue;
                }"""
    assert run.count(old) == 1, run.count(old)
    run = run.replace(old, new)
    io.open(RUN, "w", encoding="utf-8", newline="").write(run)

    # ---- the potion-content test: 26 potions, C15, one new id -------------------------------
    text = io.open(CONTENT, encoding="utf-8").read()

    def sub(old, new):
        nonlocal text
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)

    sub(
        "            25,\n"
        '            "\u00a7158: eleven after \u00a7157, plus nine that need no new mechanic, plus the five whose \\\n'
        "             effect is a card choice (\u00a7161.3 / \u00a7161.4 / \u00a7161.5)\"",
        "            26,\n"
        '            "\u00a7158: eleven after \u00a7157, plus nine that need no new mechanic, plus the five whose \\\n'
        "             effect is a card choice, plus \u00a7161.7's Power Potion\"",
    )
    sub("            [14, 7, 4],", "            [15, 7, 4],")
    sub('                "regen_potion",', '                "power_potion",\n                "regen_potion",')
    io.open(CONTENT, "w", encoding="utf-8", newline="").write(text)
    print("'+-filter added; potion test at 26 / C15")


if __name__ == "__main__":
    main()
