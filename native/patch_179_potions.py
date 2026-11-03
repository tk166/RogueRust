"""§179 potion part 1: Blessing of the Forge, Snecko Oil, Smoke Bomb.

Three potions, three small mechanisms:

* **Blessing of the Forge** -- "Upgrade all cards in your hand for the rest of combat." Our `+` rows
  are **separate `CARD` rows**, so upgrading a *card instance* is a definition-id swap. That works
  because the program is looked up by definition id at play time -- an upgraded hand card really is
  the upgraded card, not a display trick.
* **Snecko Oil** -- "Draw 5 cards. Randomize the costs of all cards in your hand for the rest of the
  combat." The existing per-copy price (`standard.card_cost_delta`) **is consumed by the play**
  (`CardPlay.cs:176-183`), so it cannot express "for the rest of combat". This adds a second
  per-copy counter, `standard.card_cost_override`, read first in the same pricing stage and **never
  consumed**.
* **Smoke Bomb** -- "Escape from a non-boss combat. Receive no rewards." Fleeing is a **run-layer**
  outcome (`result = 3`), not a combat result: the kernel has three results that match the reference
  byte for byte, and inventing a fourth would move the golden hash.
"""
import io

STATE = "kernel/rd-core/src/state.rs"
PLAY = "kernel/rd-core/src/play.rs"
WASM = "kernel/rd-wasm/src/run.rs"

# ---------------------------------------------------------------- state.rs: the second counter

STATE_ANCHOR = """pub const CARD_COST_DELTA_COUNTER: &str = "standard.card_cost_delta";"""
STATE_NEW = '''pub const CARD_COST_DELTA_COUNTER: &str = "standard.card_cost_delta";

/// 一张牌**自己的、不被出牌消费的**价格（§179：Snecko Oil）。
///
/// 和 [`CARD_COST_DELTA_COUNTER`] 的区别只有一条，但那一条就是全部：**它不随出牌清零**。
/// 参考的 delta 是"一次性承诺"（`CardPlay.cs:176-183`），而 wiki 的 Snecko Oil 说
/// "Randomize the costs of all cards in your hand **for the rest of combat**" —— 一张 0 费的牌
/// 第二次抽到手里也还是 0 费。用 delta 表达会让这条药水的效果在第一次出牌后消失。
///
/// 它是**绝对价**而不是增量：随机出来的就是那张牌这一场战斗的价格，`Amount` 与全局修饰器
/// （Snecko Eye 之类）都在这之上照常折叠 —— 顺序见 `play.rs` 的 `CostStage::CardInstance`。
pub const CARD_COST_OVERRIDE_COUNTER: &str = "standard.card_cost_override";'''

# ---------------------------------------------------------------- play.rs: read it first

PLAY_ANCHOR = """fn mark_counter(instance: &crate::state::CardInstance, key: &str) -> i32 {"""
PLAY_NEW2 = """/// 同 [`mark_counter`]，但能区分「没有这个计数器」与「计数器是 0」（§179）。
///
/// 价格覆盖**必须**用这个版本：一张被随机成 **0 费**的牌，和一张没有覆盖的牌，是两件事。
fn mark_counter_opt(instance: &crate::state::CardInstance, key: &str) -> Option<i32> {
    for counter in instance.mark_counters() {
        if counter.key.as_str() == key {
            return Some(counter.value);
        }
    }
    None
}

fn mark_counter(instance: &crate::state::CardInstance, key: &str) -> i32 {"""

PLAY_ANCHOR2 = """            let delta = mark_counter(instance, CARD_COST_DELTA_COUNTER);
            if delta == 0 {
                return Ok(current);
            }
            Ok(current.max(0) + delta)"""
PLAY_NEW = """            // §179: an **absolute** per-copy price wins over the delta. Both live in the same
            // stage because they answer the same question ("what does THIS copy cost"), and the
            // reference has exactly one stage for it.
            if let Some(absolute) = mark_counter_opt(instance, CARD_COST_OVERRIDE_COUNTER) {
                return Ok(absolute.max(0));
            }
            let delta = mark_counter(instance, CARD_COST_DELTA_COUNTER);
            if delta == 0 {
                return Ok(current);
            }
            Ok(current.max(0) + delta)"""

# ---------------------------------------------------------------- wasm: the three atoms

WASM_ANCHOR = """        other => return refuse(&std::format!("未知的药水效果 `{other}`")),"""
WASM_NEW = '''        // ── §179: the three potions whose effect the engine had no verb for. ──────────────────────
        "combat_upgrade_hand" => {
            // Blessing of the Forge: "Upgrade all cards in your hand for the rest of combat."
            //
            // `+` rows are separate `CARD` rows, and `play` looks the program up by **definition
            // id**, so swapping the instance's id *is* the upgrade -- no display-side special case.
            // A card without a `+` row (already upgraded, or not upgradable) is left alone: the
            // wiki's card is silent about it, and silently doing nothing is what StS does too.
            let Some(zones) = session.state.card_zones(&hero) else {
                return refuse("英雄没有牌区");
            };
            // Snapshot the hand first: `card_mut` borrows the state, and the loop needs `image`.
            let mut slots = [0u32; 32];
            let mut count = 0usize;
            for slot in zones.slots(rd_core::state::CardZone::Hand) {
                if count == slots.len() {
                    break;
                }
                slots[count] = *slot;
                count += 1;
            }
            let _ = &mut count;
            let mut upgraded = 0;
            for slot in &slots[..count] {
                let Some(card) = session.state.card(rd_core::state::CardSlot::from_index(*slot))
                else {
                    continue;
                };
                let base = card.definition_id.as_str();
                let mut buffer = [0u8; 64];
                if base.len() + 1 > buffer.len() {
                    continue;
                }
                buffer[..base.len()].copy_from_slice(base.as_bytes());
                buffer[base.len()] = b'+';
                let Ok(text) = core::str::from_utf8(&buffer[..base.len() + 1]) else {
                    continue;
                };
                // `lookup_in(..., EK_CARD)` is the content's own id index: asking it is the only
                // honest way to know whether an upgraded row exists (`None` = no such row).
                if image.lookup_in(text, rd_core::content::EK_CARD).is_none() {
                    continue;
                }
                let Ok(upgraded_id) = rd_core::state::CardDefinitionId::new(text) else {
                    continue;
                };
                if let Some(card) =
                    session.state.card_mut(rd_core::state::CardSlot::from_index(*slot))
                {
                    card.definition_id = upgraded_id;
                    upgraded += 1;
                }
            }
            if upgraded == 0 {
                // Nothing to upgrade is **not** an error (an empty hand is a legal hand), but the
                // potion still gets drunk -- the same rule Elixir follows for an empty hand.
                continue;
            }
        }
        "combat_randomize_costs" => {
            // Snecko Oil, part 2. Part 1 is the `combat_draw` atom next to it in the content
            // (`Effect: "combat_draw,combat_randomize_costs"`).
            //
            // The draw is `amount` (5); the randomized price is **0..=3** -- that is the whole
            // content of this rule, so it is a constant here rather than a field nobody could
            // source from the wiki ("Randomize the costs" gives no range; StS uses 0-3).
            let Some(zones) = session.state.card_zones(&hero) else {
                return refuse("英雄没有牌区");
            };
            let mut slots = [0u32; 32];
            let mut count = 0usize;
            for slot in zones.slots(rd_core::state::CardZone::Hand) {
                if count == slots.len() {
                    break;
                }
                slots[count] = *slot;
                count += 1;
            }
            let Ok(key) = rd_core::state::CounterId::new(rd_core::state::CARD_COST_OVERRIDE_COUNTER)
            else {
                return refuse("价格覆盖的计数器名不合法");
            };
            for slot in &slots[..count] {
                // One draw per card, each advancing `random_step` by one -- the same convention the
                // shuffle uses (`state.rs`: "洗完之后 `random_step += 1`"), so a replay of the same
                // seed randomizes the same ways.
                let mut seed = session.state.random_seed as u32;
                let roll = rd_core::rng::next_u32(&mut seed) % 4;
                session.state.random_seed = seed as i32;
                session.state.random_step = session.state.random_step.saturating_add(1);
                if let Some(card) =
                    session.state.card_mut(rd_core::state::CardSlot::from_index(*slot))
                {
                    if card.set_mark_counter(key, roll as i32).is_err() {
                        return refuse("这张牌装不下价格覆盖");
                    }
                }
            }
        }
        "combat_flee" => {
            // Smoke Bomb: "Escape from a non-boss combat. Receive no rewards."
            //
            // A **run-layer** outcome, not a `CombatResult`: the kernel's three results match the
            // reference byte for byte (and `result=` is hashed), so a fourth would move the golden
            // corpus. `FightOutcome`'s high bits already carry the result, and `3` is free there.
            let boss_fight = run_slot().as_ref().is_some_and(|s| s.boss_fight);
            if boss_fight {
                return refuse("Boss 战不能脱战（Smoke Bomb：non-boss combat）");
            }
            let outcome = flee_fight(slot);
            if outcome < 0 {
                return refuse("脱战失败：这一场结算不下来");
            }
            // The fight is over, so the tail below must not run against a session that is gone.
            return outcome;
        }
        other => return refuse(&std::format!("未知的药水效果 `{other}`")),'''

# The tail `consume_used_potion` is skipped by the early return above, so `flee_fight` consumes it.
WASM_FLEE_ANCHOR = """/// The run-layer effect of a finished fight (extracted from `rd_run_fight_end`, §163)."""
WASM_FLEE_NEW = '''/// Smoke Bomb's tail (§179): drop the fight and settle the run as **fled** (`result = 3`).
///
/// It mirrors `rd_run_fight_end` on purpose -- same borrow dance, same `session.log` so a replay
/// reproduces the escape -- because "the fight ended some other way" must not be a second, private
/// path into the run state. The potion is consumed here: `apply_fight_outcome` does not know about
/// the belt, and the early return in `rd_env_use_potion` skips its usual tail.
fn flee_fight(slot: i32) -> i32 {
    if slot < 0 {
        return -1;
    }
    let slot_index = slot as usize;
    let Some(hero_hp) = crate::combat_hero_health() else {
        return -1;
    };
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    let elite_fight = session.elite_fight;
    let boss_fight = session.boss_fight;
    let _ = (elite_fight, boss_fight);
    crate::take_session();
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    if let Err(e) = session.state.drop_potion(slot_index) {
        let message = describe(&e);
        return fail(session, &message);
    }
    session.log(K_FIGHT_END, hero_hp, 3 << 4, "");
    let verdict = apply_fight_outcome(session, hero_hp, 3, false, false);
    session.stamp();
    verdict
}

/// The run-layer effect of a finished fight (extracted from `rd_run_fight_end`, §163).'''


def patch(path, edits):
    text = io.open(path, encoding="utf-8").read()
    for old, new in edits:
        assert text.count(old) == 1, (path, text.count(old), old[:70])
        text = text.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("patched", path)


patch(STATE, [(STATE_ANCHOR, STATE_NEW)])
patch(PLAY, [(PLAY_ANCHOR, PLAY_NEW2), (PLAY_ANCHOR2, PLAY_NEW)])
patch(WASM, [(WASM_ANCHOR, WASM_NEW), (WASM_FLEE_ANCHOR, WASM_FLEE_NEW)])
