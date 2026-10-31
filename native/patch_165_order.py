"""Move the offered branch of `rd_env_choice_confirm` **before** the pile reads.

The first version put it after `let Some(zone) = choice.source.zone()`, which for an offered
question answers `None` -- so every offered answer was refused with "the options are not in a pile"
before the branch that handles exactly that could run. The comment claiming "the offered branch
returned above" was a lie; this is that comment made true.
"""
import io

PATH = "kernel/rd-wasm/src/lib.rs"

PILE_HEAD = """    let Some(zones) = session.state.card_zones(&choice.chooser) else {
        return refuse_with_text("待决选牌的战斗员没有牌区");
    };
    // The offered branch returned above, so this question really does name a pile.
    let Some(zone) = choice.source.zone() else {
        return refuse_with_text("这个问句的选项不在牌区里");
    };
    let count = zones.count(zone);
    // Same enumeration the picker used (`rd_env_pile_len(3)`), and a loud cross-check that the slot
    // table and the card pool still line up. A silent `zip` over two lists of different lengths
    // would resolve a *different* question than the one that was asked.
    let ids: Vec<rd_core::state::CardInstanceId> = session
        .state
        .zone_cards(&choice.chooser, zone)
        .map(|card| card.id)
        .collect();
    if ids.len() != count {
        return refuse_with_text("牌的槽位表与卡池不一致：选牌清单不完整");
    }
"""

MARK = """    // §161.5: an `Offered` question is answered by **index**, and the card it names does not exist
    // until `resolve_choice` makes it -- so the price has to come from the **definition**."""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(PILE_HEAD) == 1, text.count(PILE_HEAD)
    assert text.count(MARK) == 1, text.count(MARK)

    start = text.index(MARK)
    end = text.index("    let mut picks: Vec<rd_core::state::CardInstanceId>", start)
    offered_block = text[start:end]

    # take the offered block out …
    text = text[:start] + text[end:]
    # … and put it in front of the pile reads
    text = text.replace(PILE_HEAD, offered_block + PILE_HEAD)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("offered branch moved to the front")


if __name__ == "__main__":
    main()
