"""§161.4 on the wasm side: Liquid Memories.

Three pieces:

  1. the potion atom `choice_discard_to_hand` (a `PendingChoice` from the discard pile, `then =
     ToHand`, `min = max = 1` -- the wiki says "choose A card");
  2. `rd_env_choice_confirm` computes the **delta** for a `ToHand` question: minus the printed
     cost, and it **refuses** for an X-cost card rather than applying a discount that the price
     walk can never see (X-cost cards bypass the cost table entirely);
  3. the observation's `cost` column adds the delta, or the page shows 2 while the kernel charges 0.
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

    # ---- 1. the display cost ---------------------------------------------------------------
    lib = sub(
        LIB,
        lib,
        """            let def_id = instance.definition_id.as_str().to_string();
            let cost = self.printed_energy_cost(&def_id);
            self.hand_costs.push(cost);
            self.hand_defs.push(def_id);""",
        """            let def_id = instance.definition_id.as_str().to_string();
            let mut cost = self.printed_energy_cost(&def_id);
            // §161.4: 一张带**每副本价格**的牌，屏幕上必须显示它真的要付的数字，否则玩家看到 2 而
            // 内核收 0 —— 那正是"视图不是状态的投影"那一类谎。钳到 0 与 `play.rs` 的每阶段钳位一致。
            //
            // ⚠️ 这是**显示侧**的第二份定价：`hand_costs` 本来就是"印刷价"的显示副本
            // （`printed_energy_cost` 也自己读了一遍 `Costs`）。它**不**覆盖别的费用修饰器（"下一张
            // 免费"之类），`the_discount_follows_the_copy...` 那条测试把这个差距钉在**可观察**的
            // 层面：显示 0 与真的收 0 必须同时成立。
            if cost > 0 {
                if let Ok(key) = rd_core::state::CounterId::new(
                    rd_core::state::CARD_COST_DELTA_COUNTER,
                ) {
                    let delta = instance
                        .mark_counters()
                        .iter()
                        .find(|counter| counter.key == key)
                        .map_or(0, |counter| counter.value);
                    if delta != 0 {
                        cost = (cost + delta).max(0);
                    }
                }
            }
            self.hand_costs.push(cost);
            self.hand_defs.push(def_id);""",
    )

    # ---- 2. the delta at answer time ---------------------------------------------------------
    lib = sub(
        LIB,
        lib,
        """    let mut picks: Vec<rd_core::state::CardInstanceId> = Vec::with_capacity(session.choice_picks.len());""",
        """    let mut picks: Vec<rd_core::state::CardInstanceId> = Vec::with_capacity(session.choice_picks.len());""",
    )

    lib = sub(
        LIB,
        lib,
        """    match session.state.resolve_choice(&picks) {""",
        """    // §161.4: "free this turn" is a **per-copy price** of `-printed`, and only the content can
    // say what "printed" is. Computed here, at answer time, because the delta depends on **which**
    // card was picked -- a question cannot carry it.
    let mut cost_delta = 0i32;
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
    }
    match session.state.resolve_choice(&picks, cost_delta) {""",
    )

    # ---- 3. the potion atom ------------------------------------------------------------------
    run = sub(
        RUN,
        run,
        """        other if other.starts_with("combat_status") => {""",
        """        "choice_discard_to_hand" => {
            // §161.4: Liquid Memories -- "Choose a card in your discard pile and return it to your
            // hand. It costs 0 this turn." One card, exactly (`min = max = 1`), so `confirm` with
            // nothing ticked is refused and the picker cannot be dismissed into the void.
            let Some(zones) = session.state.card_zones(&hero) else {
                return refuse("英雄没有牌区");
            };
            if zones.count(rd_core::state::CardZone::DiscardPile) == 0 {
                // Nothing to choose: the question has no answers, so asking it would only put an
                // empty picker on screen whose confirm button is disabled forever. Same rule as the
                // empty hand for Elixir.
                continue;
            }
            let question = rd_core::state::PendingChoice {
                chooser: hero.clone(),
                source: rd_core::state::ChoiceSource::DiscardPile,
                min: 1,
                max: 1,
                then: rd_core::state::ChoiceThen::ToHand,
            };
            if let Err(e) = session.state.begin_choice(question) {
                return refuse(&std::format!("这次选牌问不出口：{e}"));
            }
            session.choice_picks.clear();
        }
        other if other.starts_with("combat_status") => {""",
    )

    io.open(LIB, "w", encoding="utf-8", newline="").write(lib)
    io.open(RUN, "w", encoding="utf-8", newline="").write(run)
    print("rd-wasm: liquid memories + the display cost")


if __name__ == "__main__":
    main()
