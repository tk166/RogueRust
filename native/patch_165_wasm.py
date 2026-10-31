"""§161.5 rd-wasm: the offered-candidate potions (Attack / Skill).

Four pieces:

  1. the atom `choice_offered:<tag>` -- filter the card pool by tag, ask the run for three distinct
     ids, open an `Offered` question;
  2. `rd_env_choice_confirm` builds `ChoiceAnswer::Offered` for that source and prices the *chosen*
     card from its definition (there is no instance before resolve);
  3. the pile readers learn zone 3 = "the question's options", which for `Offered` are definitions;
  4. `rd_env_choice_source` -- the page's sentence depends on the source, not only on the `then`.
"""
import io

LIB = "kernel/rd-wasm/src/lib.rs"
RUN = "kernel/rd-wasm/src/run.rs"


def sub(path, text, old, new):
    assert text.count(old) == 1, (path, text.count(old), old[:70])
    return text.replace(old, new)


def main():
    lib = io.open(LIB, encoding="utf-8").read()
    run = io.open(RUN, encoding="utf-8").read()

    # ---- 1. pile_zone / pile_card_id learn the offered shape --------------------------------
    lib = sub(
        LIB,
        lib,
        """/// Id 3 is dynamic on purpose: the picker renders the same card faces the pile viewer does, and a
/// fourth static pile would have to be kept in sync with "which pile is the question about". The
/// one thing a caller must know is that id 3 answers **nothing** when no choice is pending, which
/// is why it returns `None` instead of an empty pile.
fn pile_zone(session: &Session, zone: i32) -> Option<CardZone> {
    match zone {
        0 => Some(CardZone::DrawPile),
        1 => Some(CardZone::DiscardPile),
        2 => Some(CardZone::ExhaustPile),
        3 => session.state.pending_choice().map(|choice| choice.source.zone()),
        _ => None,
    }
}""",
        """/// Id 3 is dynamic on purpose: the picker renders the same card faces the pile viewer does, and a
/// fourth static pile would have to be kept in sync with "which pile is the question about". The
/// one thing a caller must know is that id 3 answers **nothing** when no choice is pending, which
/// is why it returns `None` instead of an empty pile.
///
/// §161.5: an `Offered` question has **no pile** -- its options are three card *definitions* that do
/// not exist as instances yet. So id 3 answers `None` for it here, and the readers below take the
/// offered branch **before** asking this function. Keeping the two apart is what stops "no pile"
/// from decaying into "an empty pile".
fn pile_zone(session: &Session, zone: i32) -> Option<CardZone> {
    match zone {
        0 => Some(CardZone::DrawPile),
        1 => Some(CardZone::DiscardPile),
        2 => Some(CardZone::ExhaustPile),
        3 => session.state.pending_choice().and_then(|choice| choice.source.zone()),
        _ => None,
    }
}""",
    )

    lib = sub(
        LIB,
        lib,
        """fn pile_card_id(zone: i32, index: i32) -> Option<&'static str> {
    if index < 0 {
        return None;
    }
    let session = ensure_session().ok()?;
    let zone = pile_zone(session, zone)?;
    let hero = session.hero_id()?;
    let (_, card) = session
        .state
        .zone_cards(&hero, zone)
        .enumerate()
        .find(|(position, _)| *position == index as usize)?;
    Some(card.definition_id.as_str())
}""",
        """/// The definition id of option `index` in pile `zone`.
///
/// §161.5: `zone == 3` answers the **pending question's** options, and those are two different
/// kinds of thing -- instances from a pile, or (for `Offered`) definitions that have no instance.
/// The returned `String` is what lets one function serve both without pretending a definition is a
/// pile entry.
fn pile_card_id(zone: i32, index: i32) -> Option<std::string::String> {
    if index < 0 {
        return None;
    }
    let session = ensure_session().ok()?;
    // The offered branch comes first: `pile_zone` legitimately answers `None` for it.
    if zone == 3 {
        if let Ok(offered) = session.state.choice_offered() {
            return offered
                .get(index as usize)
                .map(|definition| definition.as_str().to_string());
        }
    }
    let zone = pile_zone(session, zone)?;
    let hero = session.hero_id()?;
    let (_, card) = session
        .state
        .zone_cards(&hero, zone)
        .enumerate()
        .find(|(position, _)| *position == index as usize)?;
    Some(card.definition_id.as_str().to_string())
}""",
    )

    # the three readers must take the String now
    lib = sub(
        LIB,
        lib,
        """pub extern "C" fn rd_env_pile_card_id_len(zone: i32, index: i32) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => id.len() as i32,
        None => -1,
    }
}""",
        """pub extern "C" fn rd_env_pile_card_id_len(zone: i32, index: i32) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => id.len() as i32,
        None => -1,
    }
}""",
    )
    lib = sub(
        LIB,
        lib,
        """pub extern "C" fn rd_env_pile_card_title_len(zone: i32, index: i32) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => card_display_title(id).len() as i32,
        None => -1,
    }
}""",
        """pub extern "C" fn rd_env_pile_card_title_len(zone: i32, index: i32) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => card_display_title(&id).len() as i32,
        None => -1,
    }
}""",
    )
    lib = sub(
        LIB,
        lib,
        """pub unsafe extern "C" fn rd_env_pile_card_title_into(zone: i32, index: i32, ptr: *mut u8) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => {
            let title = card_display_title(id);""",
        """pub unsafe extern "C" fn rd_env_pile_card_title_into(zone: i32, index: i32, ptr: *mut u8) -> i32 {
    match pile_card_id(zone, index) {
        Some(id) => {
            let title = card_display_title(&id);""",
    )

    # `rd_env_pile_len(3)` must answer the offered count too
    lib = sub(
        LIB,
        lib,
        """pub extern "C" fn rd_env_pile_len(zone: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    let Some(zone) = pile_zone(session, zone) else {
        return -1;
    };""",
        """pub extern "C" fn rd_env_pile_len(zone: i32) -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    // §161.5: the offered question has no pile, so it is answered **before** `pile_zone` -- and
    // only when no pile question is pending (the two can never be pending at once).
    if zone == 3 {
        if let Ok(offered) = session.state.choice_offered() {
            return offered.len() as i32;
        }
    }
    let Some(zone) = pile_zone(session, zone) else {
        return -1;
    };""",
    )

    # ---- 2. rd_env_choice_source -------------------------------------------------------------
    lib = sub(
        LIB,
        lib,
        """/// Lower bound on how many cards may be picked; `-1` when nothing is pending.""",
        """/// Where the options come from: `1` a pile of cards, `2` three offered card definitions,
/// `0` nothing pending, `-1` no session.
///
/// §161.5: the page's sentence depends on **both** halves -- "discard pile" vs "three random
/// attack cards" is the source, "exhaust" vs "take into hand" is the `then`. Writing the sentence
/// from `kind` alone forced the page to guess, and it guessed "discard pile" for an offered
/// question.
#[no_mangle]
pub extern "C" fn rd_env_choice_source() -> i32 {
    let Ok(session) = ensure_session() else {
        return -1;
    };
    match session.state.pending_choice() {
        Some(choice) => match choice.source {
            rd_core::state::ChoiceSource::Hand
            | rd_core::state::ChoiceSource::DiscardPile => 1,
            rd_core::state::ChoiceSource::Offered => 2,
        },
        None => 0,
    }
}

/// Lower bound on how many cards may be picked; `-1` when nothing is pending.""",
    )

    # ---- 3. confirm: offered answers by index, priced from the definition --------------------
    lib = sub(
        LIB,
        lib,
        """    let mut picks: Vec<rd_core::state::CardInstanceId> = Vec::with_capacity(session.choice_picks.len());""",
        """    // §161.5: an `Offered` question is answered by **index**, and the card it names does not exist
    // until `resolve_choice` makes it -- so the price has to come from the **definition**.
    if choice.source == ChoiceSource::Offered {
        let mut indices = session.choice_picks.clone();
        indices.sort_unstable();
        indices.dedup();
        let Ok(offered) = session.state.choice_offered() else {
            return refuse_with_text("候选清单读不出来");
        };
        let mut total = 0i32;
        for index in &indices {
            let Some(definition) = offered.get(*index) else {
                return refuse_with_text(&std::format!("候选 {index} 不存在"));
            };
            match priced_delta(session, definition.as_str()) {
                Ok(delta) => total = total.saturating_add(delta),
                Err(message) => return refuse_with_text(&message),
            }
        }
        return match session.state.resolve_choice(
            rd_core::state::ChoiceAnswer::Offered(&indices),
            total,
        ) {
            Ok(_) => {
                session.choice_picks.clear();
                session.reobserve_after_external_change();
                0
            }
            Err(e) => refuse_with_text(&std::format!("选牌被拒：{e}")),
        };
    }
    let mut picks: Vec<rd_core::state::CardInstanceId> = Vec::with_capacity(session.choice_picks.len());""",
    )

    # the existing per-instance pricing becomes one helper used by both branches
    lib = sub(
        LIB,
        lib,
        """    let mut cost_delta = 0i32;
    if choice.then == ChoiceThen::ToHand {
        let mut total = 0i32;
        for id in &picks {
            let Some(card) = session.state.find_card(&choice.chooser, id).and_then(|(_, slot)| {
                session.state.card(slot)
            }) else {
                return refuse_with_text("选中的牌不在牌区里");
            };
            let printed = session.printed_energy_cost(card.definition_id.as_str());
            // `X_COST_DISPLAY` is a **sentinel**, not a price: an X-cost card pays "all your energy"
            // and never touches the `Costs` table, so a delta on it is invisible -- the card would be
            // handed over advertised as free and then charge everything. Refusing keeps the question
            // open (nothing changes), so the page can say "pick another one".
            if printed <= 0 || printed == X_COST_DISPLAY {
                return refuse_with_text(&std::format!(
                    "这张牌没有可取消的印刷费用（X 费牌按全部能量结算），换一张"
                ));
            }
            total = total.saturating_add(-printed);
        }
        cost_delta = total;
    }""",
        """    let mut cost_delta = 0i32;
    if choice.then == ChoiceThen::ToHand {
        let mut total = 0i32;
        for id in &picks {
            let Some(card) = session.state.find_card(&choice.chooser, id).and_then(|(_, slot)| {
                session.state.card(slot)
            }) else {
                return refuse_with_text("选中的牌不在牌区里");
            };
            match priced_delta(session, card.definition_id.as_str()) {
                Ok(delta) => total = total.saturating_add(delta),
                Err(message) => return refuse_with_text(&message),
            }
        }
        cost_delta = total;
    }""",
    )

    lib = sub(
        LIB,
        lib,
        """/// Is the kernel waiting for a card choice? `1` yes, `0` no, `-1` no session.""",
        """/// The per-copy price that makes one card free: `-printed`, or a **refusal** when that cannot be
/// said.
///
/// `X_COST_DISPLAY` is a **sentinel, not a price**: an X-cost card pays "all your energy" and never
/// touches the `Costs` table, so a delta on it is invisible -- the card would be handed over
/// advertised as free and then charge everything. Refusing keeps the question open (nothing
/// changes), so the page can say "pick another one".
fn priced_delta(session: &Session, definition: &str) -> Result<i32, std::string::String> {
    let printed = session.printed_energy_cost(definition);
    if printed <= 0 || printed == X_COST_DISPLAY {
        return Err(std::format!(
            "这张牌没有可取消的印刷费用（X 费牌按全部能量结算），换一张"
        ));
    }
    Ok(-printed)
}

/// Is the kernel waiting for a card choice? `1` yes, `0` no, `-1` no session.""",
    )

    io.open(LIB, "w", encoding="utf-8", newline="").write(lib)
    io.open(RUN, "w", encoding="utf-8", newline="").write(run)
    print("rd-wasm: offered readers + confirm + choice_source")


if __name__ == "__main__":
    main()
