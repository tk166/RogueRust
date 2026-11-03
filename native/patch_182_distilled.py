"""§182: Distilled Chaos -- "Play the top 3 cards of your draw pile."

Mechanism: draw the top card into the hand, **make that copy free** with the per-copy override we
added for Snecko Oil (`standard.card_cost_override = 0`), then play it through the ordinary
`play_card` path. So the potion is not a second play pipeline: the card really is played (it lands in
its own `PlayedCardDestinationZone`, its `CardPlayed` event fires, its program runs).

Two documented deviations:
* StS picks the target **at random** for each card; here it is the first living enemy, because a
  replay of the same seed has to pick the same one.
* A card that refuses to play (an Unplayable curse) is moved to the discard pile and the potion
  carries on -- it was "played" as far as the draw pile is concerned.
"""
import io

RUN = "kernel/rd-wasm/src/run.rs"

ANCHOR = """        // ── §179: the three potions whose effect the engine had no verb for. ──────────────────────"""

NEW = r'''        // ── §182: Distilled Chaos -- "Play the top 3 cards of your draw pile." ────────────────────
        "combat_autoplay_top" => {
            // `amount` is the number of cards ("3", and 6 upgraded -- this content carries the
            // base value).
            let plays = amount.max(1);
            for _ in 0..plays {
                // The top of the draw pile is index 0 (`state::draw_card` moves `first()`), so the
                // potion and the draw rule cannot disagree about which end is the top.
                let top = {
                    let Some(zones) = session.state.card_zones(&hero) else {
                        return refuse("英雄没有牌区");
                    };
                    match zones.slots(rd_core::state::CardZone::DrawPile).first().copied() {
                        Some(slot) => slot,
                        None => break, // the pile ran out: fewer than 3 is not an error
                    }
                };
                let slot = rd_core::state::CardSlot::from_index(top);
                let Some(card) = session.state.card(slot) else {
                    break;
                };
                let instance = card.id;
                // Draw it into the hand first: `play_card` requires the card to be *in hand*, and
                // that is also where the effect puts it while it resolves.
                if let Err(e) = session.state.move_card(
                    &hero,
                    rd_core::state::CardZone::DrawPile,
                    rd_core::state::CardZone::Hand,
                    slot,
                    rd_core::state::ZonePlacement::Bottom,
                ) {
                    return refuse(&std::format!("自动打出的牌搬不到手牌：{e:?}"));
                }
                // Free: the potion pays, the player does not (§179's per-copy override is exactly
                // "this one copy costs N").
                if let Ok(key) =
                    rd_core::state::CounterId::new(rd_core::state::CARD_COST_OVERRIDE_COUNTER)
                {
                    if let Some(card) = session.state.card_mut(slot) {
                        let _ = card.set_mark_counter(key, 0);
                    }
                }
                // StS picks a random living enemy; ours is the first one, so a replay of the same
                // seed plays at the same target (see the module note in `port-plan.md` §182).
                let target = (0..session.plan.enemies.len())
                    .find(|index| {
                        let id = session.plan.enemies[*index].id;
                        rd_core::state::CombatantId::new(id)
                            .ok()
                            .and_then(|cid| session.state.combatant(&cid))
                            .is_some_and(|c| c.health_current > 0)
                    })
                    .and_then(|index| {
                        rd_core::state::CombatantId::new(session.plan.enemies[index].id).ok()
                    });
                let request = rd_core::play::PlayRequest::new(hero.clone(), instance, target);
                match rd_core::play::play_card(&mut session.state, Some(image), &request) {
                    Ok(_) => {}
                    Err(rd_core::play::PlayError::CardNotInHand) => break,
                    Err(e) => {
                        return refuse(&std::format!("自动打出的牌失败：{e:?}"));
                    }
                }
            }
        }
        // ── §179: the three potions whose effect the engine had no verb for. ──────────────────────'''

# The classifier + the content gate + the kernel's closed list all need the atom too.
CLASSIFY_OLD = """            || ["combat_upgrade_hand", "combat_randomize_costs", "combat_flee"].contains(&kind)"""
CLASSIFY_NEW = """            || ["combat_upgrade_hand", "combat_randomize_costs", "combat_flee"]
                .contains(&kind)
            // §182: auto-play is about the player's own piles, so no enemy target is picked by the
            // page (the potion picks for itself).
            || kind == "combat_autoplay_top\""""


def main():
    text = io.open(RUN, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    text = text.replace(ANCHOR, NEW)
    assert text.count(CLASSIFY_OLD) == 1, text.count(CLASSIFY_OLD)
    text = text.replace(CLASSIFY_OLD, CLASSIFY_NEW)
    io.open(RUN, "w", encoding="utf-8", newline="").write(text)
    print("§182 Distilled Chaos wired")


if __name__ == "__main__":
    main()
