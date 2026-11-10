//! The canonical serialiser: `CombatState` -> the exact text the reference engine hashes.
//!
//! Ported from `CombatStateHasher.AppendSnapshot` / `AppendCombatant` / `AppendStatus` /
//! `AppendCardZones` / `AppendCards` (`CombatStateHasher.cs:26-164`) at commit
//! `fd43e68ab91f40b475b745725abb17134b951c51`. Frozen in `docs/spec/SEMANTICS-v1.md` §6.1.
//!
//! The reference builds this text with a `StringBuilder`, then does
//! `SHA256(UTF8(text))` and returns lowercase hex. `hash_golden` is therefore **byte equality of
//! this text**, which is why nothing here is "cleaned up": not the newlines, not the conditional
//! suffixes, not the two different spellings of "no value".
//!
//! # The line vocabulary, in write order
//!
//! | # | line(s) | notes |
//! |---|---|---|
//! | 1 | `id=` `seed=` `step=` `result=` `round=` `turn=` `phase=` | enums as `(int)` |
//! | 2 | `active=` | blank when there is no active combatant |
//! | 3 | `status_num=` `card_num=` `chain_num=` `exec_num=` | **no `summon_num`** - see below |
//! | 4 | `turn_order=` | ids, each followed by `,`; empty stays an empty line |
//! | 5 | `gs=` + status line | one per global status, list order |
//! | 6 | `c=` block | one per combatant, **in turn order** |
//! | 7 | `res=` / `dp=` | `<key> <cur>/<max or null>` |
//! | 8 | `s=` + status line | **`AllStatuses`, including pending**, list order |
//! | 9 | `tags=` / `cnt=` | tags each followed by `,`; counters as `<key>=<value>` |
//! | 10 | `cz=` blocks | one per combatant with piles, in turn order, after **all** `c=` blocks |
//! | 11 | card lines | `<zone>=<id> <def>[ m:..][ mc:..][ msrc:..][ qat:..]` |
//! | 12 | `tr=` | temporary rules, sorted by id |
//!
//! Three things that look like details and are not:
//!
//! 1. **`'\n'`, never `Environment.NewLine`.** The reference appends `'\n'` explicitly
//!    (`CombatStateHasher.cs:28`), so the fingerprint does not depend on the host OS. Writing
//!    `\r\n` here would change every hash on Windows and no test on Linux would notice.
//! 2. **An absent conditional field is part of the format.** `pending`/`dead`/`ownerbound` and a
//!    card's `m:`/`mc:`/`msrc:`/`qat:` appear only when there is something to say. "Absent" is not
//!    the same as "empty": a status with `pending_turns == 0` must not write `pend=0`.
//! 3. **Three different spellings of "no value", and they are not interchangeable**
//!    (`active=` blank, `res=`/`dp=` `null`, `owner=` `none`, plus `act=`/`expR=`/`expT=`'s
//!    `inf`/`none`). [`TextWriter`] provides `opt_i32_blank`, `opt_i32_null` and `opt_str_none`;
//!    the `tr=` line's `int? -> "inf"/"none"` idiom is not among them, so [`opt_i32_or`] spells it
//!    out locally rather than reaching into the writer's accepted API.
//!
//! # What is deliberately NOT written
//!
//! The reference hashes a **subset** of the snapshot, and the snapshot is a subset of the live
//! state. A rewrite that "helpfully" hashes more would diverge silently, so this file's omissions
//! are listed here on purpose.
//!
//! ## A. In the snapshot but not in the hash (spec §3-D12, §6.3) - `hash_full` must cover these
//!
//! 1. `NextSummonedCombatantNumber` (snapshot `CombatStateSnapshot.cs:130`; the hasher has no
//!    `summon_num` line at `:36-39`). A summon-id fork is invisible to `hash_golden`.
//! 2. `CardPlayTurnStats` - the entire per-combatant block (cards played this turn and last,
//!    counts by definition/tag, draws, damage, hits, resources gained and spent, claims, the
//!    whole-fight play table). The documented real accident: "more than last turn" rules read 0
//!    after a restore and the hash says nothing is wrong.
//! 3. `TriggerActivity` - how often each trigger has paid out.
//! 4. `CurrentPhaseTeam` / `_endedThisPhase` - in neither the snapshot nor the hash
//!    (spec §2.1.2), which is why a mid-fight save in simultaneous-team mode can never be
//!    restored faithfully.
//!
//! ## B. In the snapshot, skipped by the hasher (so not modelled here either)
//!
//! 5. `PoolSnapshot.CanExceedMax` (`CombatStateSnapshot.cs:6`; the hasher writes only `cur/max`).
//! 6. A status's `Tags`, `Counters`, `SourceCardId`, `AppliedRound`, `AppliedTurn`, `Visibility`
//!    (`AppendStatus` writes `id def stk dur chg pol [pend]` and nothing else, `:108-119`), and its
//!    `OwnerCombatantId`.
//!
//!    ⚠️ **`SourceCombatantId` 曾经也在这条里，现在不在** —— 它**仍然不进指纹**，但**进模型**
//!    （`state::StatusInstance::source_combatant_id`）：伤害的 Source 阶段要靠它认出"这一跳毒
//!    是谁下的"（`StatusEffects.cs:501-509` 把它塞进 `DealDamageEffectRequest`，而
//!    `PassiveModifiers.cs:242-254` 按它读出手方身上的 `DamageDealt` spec）。
//!    它与 `CardInstance` 的 `marks` / `mark_source_combatant_id` 同属"**状态里有、指纹里没有**"
//!    的那一类字段 —— 那一类字段正是 `hash_full` 存在的理由（§A 的 1-3 条是同一件事的另外三个
//!    例子）。⇒ 加它**不动任何指纹**：85 份语料不用重生、`write_hash_input` 一个字节都不变
//!    （`host.rs` 的 `source_combatant_id_does_not_enter_the_fingerprint` 把这条钉住）。
//! 7. `CardInstanceSnapshot.Zone` - the hasher writes the zone as the line's *key*.
//! 8. `TemporaryTriggeredProgramSnapshot.HasExpiryEffects` - a restore guard signal
//!    (`CombatStateSnapshot.cs:110-112`), not state.
//!
//! ## C. Live state out of scope for this deliverable
//!
//! 9. The transient execution state: the effect/event/continuation queues and their parallel
//!    metadata queues, active program frames, action scopes, `_resolvingQueuedCards`,
//!    `CurrentEffectChain` (`CombatState.cs:5-11,96-132,140-148`). The queue processor (later W1
//!    work) owns them; the reference excludes them from snapshots by design (`:718-723`).
//! 10. `CombatLog` - observational only (spec §1.2/B3); §3-D10 plans a ring buffer plus counters.
//! 11. The trace stream (`TraceListener`, and with it the fields of `CombatTraceEvent`).
//! 12. Configuration and host collaborators: `MaximumTriggerDepth`, `CellExclusive`,
//!     `SimultaneousTeamTurns`, `DefinitionRegistry`, `CardChooser`, `OptionChooser`,
//!     `UpcomingIntentKind`.
//! 13. Combatant `DisplayNameKey`, `OwnerId`, `ControllerId`, `Position`, `IntentKey`.
//! 14. `EffectsEnqueued` and the action-scope claim ledger.
//! 15. Card/id allocation (`CreateNextCardInstanceId` -> `card_%06d`,
//!     `CreateNextSummonedCombatantId` -> `summoned_%06d`): the model stores ids, it does not mint
//!     them.
//! 16. The zones' *behaviour*: draw-from-index-0, `ZonePlacement::Top`, `MoveCardToZone`,
//!     `AddCard`'s de-duplication by card id, `AllCards`' concatenation order. Those are rules of
//!     the live engine; this model only has to lay the piles out in the right order.
//! 17. ~~`hash_full` itself (§3-D4)~~ - **§334 已做**：`write_full_hash_input` 就是
//!     `write_hash_input`（逐字节）+ `--full--` 之后一段模型文本，覆盖 §A 的 1-3 条与
//!     `SourceCombatantId`。它**不改变**本文件的输出（`write_hash_input` 一个字节都没动）。
//! 18. Everything OUT of v1 as a whole (spec §2.2): the run layer (map/rooms/rewards/shop/events),
//!     runtime JSON, the positional system, simultaneous-team turns, consumables, Shred/Recipe,
//!     the Blazor sandbox and the bot/FightPlanner.
//!
//! # Which of these line classes are verified against the engine, and which are not
//!
//! Worth stating plainly, because the two halves carry different weight:
//!
//! * **Engine-verified**: `corpus/hash_cases/*.txt` — **85 canonical texts captured from the real C#
//!   engine** — exercise **every one of the 29 line headers `CombatStateHasher` can write**, plus
//!   the five suffixes `m:`/`mc:`/`msrc:`/`qat:`/`pend=`, and
//!   `every_corpus_hash_case_round_trips` requires each file to come back byte for byte.
//!   `the_engines_own_canonical_text_matches_byte_for_byte` additionally pins one text's SHA-256 to
//!   the engine's own value.
//!
//!   ⚠️ 这一段曾经写的是"48 份只覆盖 `id/seed/step/result/round/turn/phase`、`active`、四个计数器、
//!   `turn_order`、`c=`、`res=`、`tags=`、`cz=` 与卡行，而 `dp=`/`s=`/`gs=`/`cnt=`/`tr=`/
//!   `queue`/`aside`/卡后缀 **一份都没出现**"。那是当时的实情，现在**已经不成立**：
//!   37 份富状态语料（`case_0100`-`case_0136`）把那 12 类全部补上了，
//!   而且 `cargo test` 里那份 glob 会逐份比对，所以"补上了"是被测试钉住的，不是声称的。
//!
//! * **Known-weak spots that REMAIN**（这些仍然值得警惕，不要当它们已经验过）:
//!   1. `gs=` 只有 **restore 路径**的实证 —— 全引擎 `_globalStatuses` 唯一的写者是
//!      `CombatState.Restore`（`CombatState.cs:818`）。没有任何 effect / blueprint / interceptor /
//!      开场路径会加全局状态，所以那两份语料证明的是"还原路径写得出这行"，**不是"战斗路径写得出"**。
//!      要真正可达得给引擎加一个运行时写者。
//!   2. `tr=` 的 `dead` 后缀**在任何观测点都不存在** —— 规则过期与
//!      `RemoveExpiredTemporaryTriggeredPrograms()` 的剪除发生在同一次调用里。
//!   3. `res=` 的 `null` 上限拼法到不了（能量池总有 max）；`null` 这个拼法由 `dp=… 3/null` 覆盖，
//!      `res=` 覆盖了数字侧的 `3/3`。
//!   4. 值级细节只有一种取值：`tr=` 的 `inst=R.T` 只有 `1.1`；`dp=` 的上限一直是 `null`。


use crate::state::{
    CardInstance, CardZones, CombatState, Combatant, Pool, StatusInstance, TemporaryRule, CardZone,
};
use crate::writer::TextWriter;

/// Writes the exact bytes the reference hashes.
///
/// Returns nothing on purpose: [`TextWriter`] never writes half a field, so the only thing a
/// caller can do with a failure is notice it via [`TextWriter::overflowed`]. A truncated
/// fingerprint is worse than no fingerprint - it looks like a fingerprint.
/// §334：`hash_full` 的输入文本 = [`write_hash_input`]（逐字节）+ `--full--` 之后的模型段。
///
/// 为什么是**追加**而不是另写一份：`hash_golden` 是参考规范文本的复刻，任何"顺手多写一行"
/// 都会移动 85 份语料。追加段让两个指纹各自回答各自的问题 ——
/// "与参考一致吗"（`hash_golden`）与"这一局真的相同吗"（`hash_full`）。
///
/// 段内顺序是**契约**（改顺序就换指纹），而且每条都写"有没有值"——`Option` 用 `none`/值，
/// 与规范文本里三种"没有值"的拼法无关（那三种是**参考**的格式，这里是本移植自己的）。
#[cfg(test)]
mod full_hash_tests {
    use super::*;
    use crate::hash::{full_hash_hex, sha256, to_hex_lower};
    use crate::state::{
        CardDefinitionId, ChoiceSource, ChoiceThen, Combatant, CombatantDefinitionId, CombatantId,
        StatusDefinitionId, StatusInstance, StatusInstanceId, StatusPolarity, TeamId,
    };

    fn arena() -> CombatState {
        let id = |name: &str| CombatantId::new(name).unwrap();
        let unit = |name: &str, team: &str| {
            Combatant::new(
                id(name),
                CombatantDefinitionId::new(name).unwrap(),
                TeamId::new(team).unwrap(),
                40,
                40,
            )
        };
        let mut state = CombatState::new(crate::state::CombatId::new("c1").unwrap(), 7);
        state.add_combatant(unit("hero", "player")).unwrap();
        state.add_combatant(unit("ogre", "enemy")).unwrap();
        state
    }

    fn golden(state: &CombatState) -> [u8; 64] {
        let mut buf = [0u8; 1 << 16];
        let text = {
            let mut w = TextWriter::new(&mut buf);
            write_hash_input(&mut w, state);
            assert!(!w.overflowed());
            w.as_str().to_string()
        };
        let mut hex = [0u8; 64];
        to_hex_lower(&mut hex, &sha256(text.as_bytes()));
        hex
    }

    fn full(state: &CombatState) -> [u8; 64] {
        let mut buf = [0u8; 1 << 16];
        let text = {
            let mut w = TextWriter::new(&mut buf);
            write_full_hash_input(&mut w, state);
            assert!(!w.overflowed());
            w.as_str().to_string()
        };
        let mut hex = [0u8; 64];
        full_hash_hex(&mut hex, &text);
        hex
    }

    /// ★ 这条是 `hash_full` 的全部理由：只在 `PendingChoice` 上不同的两个局面。
    ///
    /// `hash_golden` 相同（参考没有这个字段）而 `hash_full` 不同 —— 于是"同一串动作 ⇒
    /// 同一局"这条回放判据终于能看见"选牌答案不一样"。
    #[test]
    fn a_pending_choice_moves_the_full_hash_but_not_the_golden_one() {
        let mut bare = arena();
        let mut choosing = arena();
        let chooser = CombatantId::new("hero").unwrap();
        let mut offered = crate::state::Bounded::new();
        offered
            .push(
                CardDefinitionId::new("strike").unwrap(),
                crate::state::Container::ChoiceOptions,
            )
            .unwrap();
        choosing
            .begin_choice(crate::state::PendingChoice {
                chooser,
                source: ChoiceSource::Offered,
                min: 1,
                max: 1,
                then: ChoiceThen::ToHand,
                offered,
                candidates: crate::state::Bounded::new(),
            })
            .expect("the question opens");
        assert!(bare.pending_choice().is_none());

        assert_eq!(
            golden(&bare),
            golden(&choosing),
            "hash_golden must NOT see PendingChoice (the reference has no such field)"
        );
        assert_ne!(
            full(&bare),
            full(&choosing),
            "hash_full must see it -- that is the whole point"
        );
    }

    /// 状态的 `source_combatant_id`（DoT 的出手方）也只在 `hash_full` 里。
    #[test]
    fn a_status_source_moves_the_full_hash_but_not_the_golden_one() {
        let mut plain = arena();
        let mut sourced = arena();
        let hero = CombatantId::new("hero").unwrap();
        let mut instance = StatusInstance::new(
            StatusInstanceId::new("st_poison").unwrap(),
            StatusDefinitionId::new("standard.poison").unwrap(),
            StatusPolarity::Debuff,
        )
        .with_stacks(3);
        instance.source_combatant_id = Some(hero);
        sourced
            .combatant_mut(&CombatantId::new("ogre").unwrap())
            .unwrap()
            .push_status(instance)
            .unwrap();
        let mut bare_instance = instance;
        bare_instance.source_combatant_id = None;
        plain
            .combatant_mut(&CombatantId::new("ogre").unwrap())
            .unwrap()
            .push_status(bare_instance)
            .unwrap();

        assert_eq!(golden(&plain), golden(&sourced), "the hasher writes seven fields only");
        assert_ne!(full(&plain), full(&sourced), "hash_full carries the source");
    }

    /// 本移植的 model-only 战斗事实（`ascension` / `heal_blocked` / `gold_gained` / `encounter`）。
    #[test]
    fn the_model_only_fight_facts_move_the_full_hash_only() {
        let cases: &[fn(&mut CombatState)] = &[
            |state| state.set_ascension(17),
            |state| state.set_heal_blocked(true),
            |state| state.gold_gained = 20,
            |state| state.encounter = 3,
        ];
        for (index, mutate) in cases.iter().enumerate() {
            let mut plain = arena();
            let mut changed = arena();
            mutate(&mut changed);
            assert_eq!(
                golden(&plain),
                golden(&changed),
                "case {index}: hash_golden must not move"
            );
            assert_ne!(
                full(&plain),
                full(&changed),
                "case {index}: hash_full must move"
            );
        }
    }

    /// 超集的另一半：**改变 `hash_golden` 的变化，`hash_full` 也必须变**。
    ///
    /// 少了这条，"`hash_full` 只在模型段上有区别"就可能退化成"它根本不看规范文本"。
    #[test]
    fn everything_that_moves_the_golden_hash_also_moves_the_full_one() {
        let mut plain = arena();
        let mut changed = arena();
        changed.random_seed = 99;
        assert_ne!(golden(&plain), golden(&changed));
        assert_ne!(full(&plain), full(&changed), "the full hash is a superset");

        let mut round = arena();
        round.current_round = 5;
        assert_ne!(golden(&plain), golden(&round));
        assert_ne!(full(&plain), full(&round));
    }

    /// `hash_full` 的文本以 `hash_golden` 的文本为**前缀**（追加而不是重写）。
    #[test]
    fn the_full_text_is_the_golden_text_plus_a_section() {
        let state = arena();
        let mut golden_buf = [0u8; 1 << 16];
        let golden_text = {
            let mut w = TextWriter::new(&mut golden_buf);
            write_hash_input(&mut w, &state);
            w.as_str().to_string()
        };
        let mut full_buf = [0u8; 1 << 16];
        let full_text = {
            let mut w = TextWriter::new(&mut full_buf);
            write_full_hash_input(&mut w, &state);
            w.as_str().to_string()
        };
        assert!(
            full_text.starts_with(&golden_text),
            "the full text must start with the golden text (append, not rewrite)"
        );
        assert!(full_text.contains("--full--\n"), "and then the model section");
        assert!(full_text.contains("choice=none"), "with no pending choice, say so");
    }
}

pub fn write_full_hash_input(w: &mut TextWriter<'_>, s: &CombatState) {
    write_hash_input(w, s);
    w.str("--full--\n");

    // ① 本移植的 model-only 战斗事实。它们改变"以后会怎样"，参考没有这些字段。
    w.str("ascension=").i32(i32::from(s.ascension)).char('\n');
    w.str("encounter=").u32(s.encounter).char('\n');
    w.str("heal_blocked=").u32(u32::from(s.heal_blocked)).char('\n');
    w.str("summon_num=").i32(s.next_combatant_number).char('\n');
    w.str("gold_carried=").i32(s.gold_carried_away).char('\n');
    w.str("gold_gained=").i32(s.gold_gained).char('\n');

    // ② 回合机的三个瞬时段。它们"看起来是瞬时"，但都会改变下一次选意图/推进回合的结果：
    //    `vacated_seat` 决定席位交给谁、`extra_turn_for` 决定谁再来一次、
    //    `forced_turn_ends` 是页面读的计数。所以进 `hash_full`。
    w.str("vacated_seat=").opt_i32_blank(s.vacated_seat.map(i32::from)).char('\n');
    w.str("extra_turn=").opt_str_none(s.extra_turn_for.as_ref().map(|id| id.as_str())).char('\n');
    w.str("forced_ends=").i32(s.forced_turn_ends).char('\n');

    // ③ 每回合的出牌数（§128 的 `cardsPlayedThisTurn` / `LastTurn`）。
    w.str("played_this=").i32(s.cards_played_this_turn).char('\n');
    w.str("played_last=").i32(s.cards_played_last_turn).char('\n');

    // ④ 状态实例的 `source_combatant_id`（DoT 的出手方）。规范文本不写它（`AppendStatus`
    //    只写七个字段），而"这一跳毒是谁下的"会改变力量加伤 ⇒ 它属于 `hash_full`。
    //    按 `(combatant, 实例 id)` 逐条写，**顺序 = 状态表顺序**（与 `s=` 行一致）。
    w.str("status_src=");
    for combatant in s.combatants().iter() {
        for instance in combatant.statuses() {
            w.str(instance.id.as_str()).char('@');
            match &instance.source_combatant_id {
                Some(source) => {
                    w.str(source.as_str());
                }
                None => {
                    w.str("none");
                }
            }
            w.char(',');
        }
    }
    w.char('\n');

    // ⑤ **待决的选牌**（§161.3）—— 这一条是 `hash_full` 存在的主要理由。
    //
    //    `PendingChoice` 决定"玩家现在能选什么、选完发生什么"。两个只在它上面不同的局面，
    //    `hash_golden` 完全一样，而下一步的合法动作集不同 —— 回放判据看不见这种分叉。
    match s.pending_choice() {
        None => {
            w.str("choice=none\n");
        }
        Some(choice) => {
            w.str("choice=")
                .str(choice.chooser.as_str())
                .char(':')
                .i32(i32::from(choice.source as u8))
                .char(':')
                .i32(i32::from(choice.min))
                .char(':')
                .i32(i32::from(choice.max))
                .char(':')
                .i32(choice_then_code(&choice.then))
                .char('\n');
            // `Offered` 的候选是**卡定义**；`candidates` 是收窄后的合法实例清单（§226）。
            // 两个都写：前者决定"问什么"，后者决定"哪些能选"。
            w.str("choice_offered=");
            for definition in choice.offered.as_slice() {
                w.str(definition.as_str()).char(',');
            }
            w.char('\n');
            w.str("choice_candidates=");
            for candidate in choice.candidates.as_slice() {
                w.str(candidate.as_str()).char(',');
            }
            w.char('\n');
        }
    }
}

/// [`crate::state::ChoiceThen`] 的稳定编号（写进 `hash_full`，所以**不许重排**）。
///
/// `Copy` 带两个参数（`copies` / `into`），所以它比别的变体多写两格 —— 但为了指纹稳定，
/// 这里把参数**编码进同一个数**：`code = 变体号 * 256 + copies`，`into` 单独一行。
fn choice_then_code(then: &crate::state::ChoiceThen) -> i32 {
    use crate::state::ChoiceThen;
    match then {
        ChoiceThen::Exhaust => 1,
        ChoiceThen::DiscardThenDraw => 2,
        ChoiceThen::ToHand => 3,
        ChoiceThen::Copy { copies, .. } => 4 * 256 + i32::from(*copies),
        ChoiceThen::ToHandPrinted => 5,
        ChoiceThen::Upgrade => 6,
        ChoiceThen::PlayChosen => 7,
        ChoiceThen::ToHandFree => 8,
        ChoiceThen::ToDrawPileBottomFree => 9,
        ChoiceThen::ToDrawPileTop => 10,
    }
}

pub fn write_hash_input(w: &mut TextWriter<'_>, s: &CombatState) {
    // 1. Scalars. Enums are always `(int)`, never names.
    w.str("id=").str(s.id.as_str()).char('\n');
    w.str("seed=").i32(s.random_seed).char('\n');
    w.str("step=").i32(s.random_step).char('\n');
    w.str("result=").i32(s.result as i32).char('\n');
    w.str("round=").i32(s.current_round).char('\n');
    w.str("turn=").i32(s.current_turn).char('\n');
    w.str("phase=").i32(s.turn_phase as i32).char('\n');

    // 2. `active=` uses the BLANK idiom (`?.value ?? ""`), not `null` and not `none`.
    w.str("active=");
    if let Some(id) = &s.active_combatant_id {
        w.str(id.as_str());
    }
    w.char('\n');

    // 3. Generators. `chain_num` and `exec_num` are `long`; status/card counters are `int`.
    //    There is deliberately no `summon_num` - see the module header, item A1.
    w.str("status_num=").i32(s.next_status_instance_number).char('\n');
    w.str("card_num=").i32(s.next_card_instance_number).char('\n');
    w.str("chain_num=").i64(s.next_effect_chain_number).char('\n');
    w.str("exec_num=").i64(s.next_program_execution_id).char('\n');

    // 4. Turn order: every id followed by a comma, so the line always ends in `,` (or is empty).
    w.str("turn_order=");
    for id in s.turn_order() {
        w.str(id.as_str()).char(',');
    }
    w.char('\n');

    // 5. Global statuses, in list order.
    for status in s.global_statuses() {
        w.str("gs=");
        write_status(w, status);
    }

    // 6-9. Every combatant's whole block, in turn order, before any card zone is written.
    // The lookup mirrors the snapshot builder's `TurnOrder.Select(id => GetCombatant(id))`
    // (`CombatStateSnapshotter.cs:12-14`); the reference would throw for an unknown id, and the
    // model cannot produce one (`set_turn_order` refuses ids it does not hold), so the `None` arm
    // is unreachable rather than lenient.
    for id in s.turn_order() {
        if let Some(combatant) = s.combatant(id) {
            write_combatant(w, combatant);
        }
    }

    // 10-11. Card zones, also in turn order; a combatant without piles writes no `cz=` line
    // (`CombatStateSnapshotter.cs:16-19` filters on the dictionary actually having an entry).
    for id in s.turn_order() {
        if let Some(zones) = s.card_zones(id) {
            w.str("cz=").str(id.as_str()).char('\n');
            write_card_zones(w, s, zones);
        }
    }

    // 12. Temporary rules, sorted by id (the snapshot builder sorts them).
    for rule in s.temporary_rules() {
        write_temporary_rule(w, rule);
    }
}

/// One `c=` block, then its pools, statuses, tags and counters - the order of
/// `AppendCombatant` (`CombatStateHasher.cs:74-106`).
fn write_combatant(w: &mut TextWriter<'_>, c: &Combatant) {
    w.str("c=")
        .str(c.id.as_str())
        .str(" def=")
        .str(c.definition_id.as_str())
        .str(" team=")
        .str(c.team_id.as_str())
        .str(" lc=")
        .i32(c.lifecycle_state as i32)
        .str(" hp=")
        .i32(c.health_current)
        .char('/')
        .i32(c.health_max)
        .char('\n');

    // Already sorted by key by the model (the snapshot builder sorts; the hasher does not).
    for pool in c.resources() {
        w.str("res=").str(pool.key.as_str()).char(' ');
        write_pool(w, &pool.pool);
        w.char('\n');
    }
    for pool in c.defensive_pools() {
        w.str("dp=").str(pool.key.as_str()).char(' ');
        write_pool(w, &pool.pool);
        w.char('\n');
    }

    // `AllStatuses` - pending instances included, in instance order, NOT sorted.
    for status in c.statuses() {
        w.str("s=");
        write_status(w, status);
    }

    // Always written, even when empty: `tags=` on its own line.
    w.str("tags=");
    for tag in c.tags() {
        w.str(tag.as_str()).char(',');
    }
    w.char('\n');

    for counter in c.counters() {
        w.str("cnt=")
            .str(counter.key.as_str())
            .char('=')
            .i32(counter.value)
            .char('\n');
    }
}

/// `<current>/<max or null>`. The `null` spelling, not blank and not `none`.
fn write_pool(w: &mut TextWriter<'_>, pool: &Pool) {
    w.i32(pool.current).char('/').opt_i32_null(pool.max);
}

/// One status line, without its key (`gs=` / `s=` are written by the caller) but *with* its
/// terminating newline. `pend=` appears only when the status is actually waiting.
fn write_status(w: &mut TextWriter<'_>, s: &StatusInstance) {
    w.str(s.id.as_str())
        .char(' ')
        .str(s.definition_id.as_str())
        .str(" stk=")
        .i32(s.stacks)
        .str(" dur=")
        .i32(s.duration_turns)
        .str(" chg=")
        .i32(s.charges)
        .str(" pol=")
        .i32(s.polarity as i32);
    if s.pending_turns > 0 {
        w.str(" pend=").i32(s.pending_turns);
    }
    w.char('\n');
}

/// The seven piles. `draw`/`hand`/`disc`/`exh`/`ban` are always walked (and write nothing when
/// empty, so an empty pile leaves no trace at all); `queue`/`aside` are skipped outright when
/// empty, which is what kept every hash recorded before those two zones existed unchanged
/// (`CombatStateHasher.cs:128-135`).
fn write_card_zones(w: &mut TextWriter<'_>, s: &CombatState, zones: &CardZones) {
    for zone in CardZone::ALL {
        let optional = matches!(zone, CardZone::QueuePile | CardZone::SetAsidePile);
        if optional && zones.is_empty(zone) {
            continue;
        }
        for card in s.zone_cards(zones.combatant_id(), zone) {
            write_card(w, zone, card);
        }
    }
}

/// One card line. The zone is the *key*; everything after the definition id is optional, and an
/// absent suffix is not the same as an empty one.
fn write_card(w: &mut TextWriter<'_>, zone: CardZone, card: &CardInstance) {
    w.str(zone.wire_name())
        .char('=')
        .str(card.id.as_str())
        .char(' ')
        .str(card.definition_id.as_str());

    for mark in card.marks() {
        w.str(" m:").str(mark.as_str());
    }
    for counter in card.mark_counters() {
        w.str(" mc:")
            .str(counter.key.as_str())
            .char('=')
            .i32(counter.value);
    }
    if let Some(source) = &card.mark_source_combatant_id {
        w.str(" msrc:").str(source.as_str());
    }
    // Only a waiting card has a target, so no hash already on the wire moves.
    if let Some(aimed) = &card.queued_target_id {
        w.str(" qat:").str(aimed.as_str());
    }
    w.char('\n');
}

/// One `tr=` line.
fn write_temporary_rule(w: &mut TextWriter<'_>, rule: &TemporaryRule) {
    w.str("tr=")
        .str(rule.id.as_str())
        .char(' ')
        .str(rule.event_type.as_str())
        .str(" act=");
    opt_i32_or(w, rule.remaining_activations, "inf");
    w.str(" expR=");
    opt_i32_or(w, rule.expires_after_round, "none");
    w.str(" expT=");
    opt_i32_or(w, rule.expires_after_turn, "none");
    // `owner=` uses the `none` spelling (`rule.OwnerCombatantId ?? "none"`).
    w.str(" owner=")
        .opt_str_none(rule.owner_combatant_id.as_ref().map(|id| id.as_str()));
    w.when(rule.expires_when_owner_removed, " ownerbound");
    w.str(" inst=")
        .i32(rule.installed_round)
        .char('.')
        .i32(rule.installed_turn);
    w.when(rule.is_expired, " dead");
    w.char('\n');
}

/// `int?.ToString() ?? fallback` - the idiom `CombatStateHasher.cs:64-66` uses three times.
///
/// `TextWriter` has the `""` and `null` spellings of this but not `"inf"`/`"none"`, and its API
/// is frozen, so the third spelling lives here.
fn opt_i32_or(w: &mut TextWriter<'_>, value: Option<i32>, fallback: &str) {
    match value {
        Some(n) => {
            w.i32(n);
        }
        None => {
            w.str(fallback);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::state::{
        CardDefinitionId, CardInstanceId, CombatId, CombatResult, CombatTurnPhase, CombatantId,
        CombatantDefinitionId, CombatantLifecycleState, CounterId, DefensivePoolId, EventTypeName,
        ResourceId, StatusDefinitionId, StatusInstanceId, StatusPolarity, TagId, TeamId,
        TriggeredEffectDefinitionId,
    };

    fn cid(s: &str) -> CombatantId {
        CombatantId::new(s).unwrap()
    }
    fn def(s: &str) -> CombatantDefinitionId {
        CombatantDefinitionId::new(s).unwrap()
    }
    fn team(s: &str) -> TeamId {
        TeamId::new(s).unwrap()
    }
    fn rid(s: &str) -> ResourceId {
        ResourceId::new(s).unwrap()
    }
    fn dpid(s: &str) -> DefensivePoolId {
        DefensivePoolId::new(s).unwrap()
    }
    fn sdid(s: &str) -> StatusDefinitionId {
        StatusDefinitionId::new(s).unwrap()
    }
    fn siid(s: &str) -> StatusInstanceId {
        StatusInstanceId::new(s).unwrap()
    }
    fn cdid(s: &str) -> CardDefinitionId {
        CardDefinitionId::new(s).unwrap()
    }
    fn ciid(s: &str) -> CardInstanceId {
        CardInstanceId::new(s).unwrap()
    }
    fn tag(s: &str) -> TagId {
        TagId::new(s).unwrap()
    }
    fn cnt(s: &str) -> CounterId {
        CounterId::new(s).unwrap()
    }

    /// Runs `f` against a buffer and returns what was written. A too-small buffer is a broken
    /// test, not a passing one, so it panics.
    fn text(f: impl FnOnce(&mut TextWriter<'_>)) -> String {
        let mut buf = [0u8; 4096];
        let mut w = TextWriter::new(&mut buf);
        f(&mut w);
        assert!(!w.overflowed(), "test buffer too small");
        w.as_str().to_string()
    }

    fn render(s: &CombatState) -> String {
        text(|w| write_hash_input(w, s))
    }

    /// Equality with a diagnosis, because "these two strings look the same" is how a fingerprint
    /// bug survives a test suite: `assert_eq!` prints both, and an invisible byte is invisible.
    fn assert_text(actual: &str, expected: &str, what: &str) {
        if actual == expected {
            return;
        }
        match actual.bytes().zip(expected.bytes()).position(|(a, b)| a != b) {
            Some(i) => panic!(
                "{what}: first difference at byte {i}: actual 0x{:02X}, expected 0x{:02X} ({} vs {} bytes)",
                actual.as_bytes()[i],
                expected.as_bytes()[i],
                actual.len(),
                expected.len()
            ),
            None => panic!(
                "{what}: one text is a prefix of the other ({} vs {} bytes)",
                actual.len(),
                expected.len()
            ),
        }
    }

    fn hero() -> Combatant {
        Combatant::new(cid("hero"), def("bureaucrat"), team("player"), 61, 70)
    }

    /// The hand-built state the end-to-end test pins down, reused by the line-level tests.
    fn example() -> CombatState {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 42);
        s.random_step = 3;
        s.result = CombatResult::Ongoing;
        s.current_round = 2;
        s.current_turn = 1;
        s.turn_phase = CombatTurnPhase::TurnInProgress;
        s.next_status_instance_number = 7;
        s.next_card_instance_number = 13;
        s.next_effect_chain_number = 5;
        s.next_program_execution_id = 9;

        let mut hero = hero();
        hero.set_resource(rid("standard.energy"), 2, Some(3)).unwrap();
        hero.set_defensive_pool(dpid("standard.block"), 6, Some(999)).unwrap();
        hero.push_status(
            StatusInstance::new(siid("status_000002"), sdid("standard.poison"), StatusPolarity::Debuff)
                .with_stacks(4),
        )
        .unwrap();
        hero.push_status(
            StatusInstance::new(siid("status_000003"), sdid("standard.weak"), StatusPolarity::Debuff)
                .with_stacks(1)
                .with_duration_turns(2)
                .with_pending_turns(1),
        )
        .unwrap();
        hero.set_counter(cnt("standard.attacks_played"), 2).unwrap();
        s.add_combatant(hero).unwrap();

        s.add_combatant(
            Combatant::new(cid("ogre"), def("ogre"), team("enemy"), 0, 30)
                .with_lifecycle_state(CombatantLifecycleState::Downed),
        )
        .unwrap();
        s.active_combatant_id = Some(cid("hero"));

        s.push_global_status(
            StatusInstance::new(siid("status_000001"), sdid("standard.artifact"), StatusPolarity::Buff)
                .with_stacks(1),
        )
        .unwrap();

        s.push_card(
            &cid("hero"),
            CardZone::DrawPile,
            CardInstance::new(ciid("card_000001"), cdid("standard.strike")),
        )
        .unwrap();
        let mut hand = CardInstance::new(ciid("card_000002"), cdid("standard.defend"));
        hand.add_mark(tag("zzz")).unwrap();
        hand.add_mark(tag("aaa")).unwrap();
        hand.set_mark_counter(cnt("standard.card_cost_delta"), -2).unwrap();
        hand.set_mark_counter(cnt("aaa"), 1).unwrap();
        let hand = hand
            .with_mark_source(cid("hero"))
            .with_queued_target(cid("ogre"));
        s.push_card(&cid("hero"), CardZone::Hand, hand).unwrap();
        s.push_card(
            &cid("hero"),
            CardZone::QueuePile,
            CardInstance::new(ciid("card_000003"), cdid("standard.strike")).with_queued_target(cid("ogre")),
        )
        .unwrap();
        s.push_card(
            &cid("hero"),
            CardZone::SetAsidePile,
            CardInstance::new(ciid("card_000004"), cdid("standard.defend")),
        )
        .unwrap();

        s.add_temporary_rule(
            TemporaryRule::new(
                TriggeredEffectDefinitionId::new("rule.a").unwrap(),
                EventTypeName::new("RogueDeck.Core.Combat.TurnStartedCombatEvent").unwrap(),
                2,
                1,
            )
            .with_remaining_activations(2)
            .with_expires_after_turn(5)
            .with_owner(cid("hero"))
            .owner_bound(),
        )
        .unwrap();
        s
    }

    // ---------------------------------------------------------------- line classes 1-4

    #[test]
    fn scalar_lines_are_written_in_order_with_enums_as_integers() {
        let s = example();
        let rendered = render(&s);
        let lines: Vec<&str> = rendered.lines().take(7).collect();
        assert_eq!(
            lines,
            [
                "id=c1",
                "seed=42",
                "step=3",
                "result=0",
                "round=2",
                "turn=1",
                "phase=1",
            ]
        );

        // A finished fight reports the enum, not its name.
        let mut finished = CombatState::new(CombatId::new("").unwrap(), -7);
        finished.result = CombatResult::Defeat;
        finished.turn_phase = CombatTurnPhase::WaitingToStartTurn;
        let text = render(&finished);
        assert!(text.contains("\nresult=2\n"), "{text}");
        assert!(text.contains("\nphase=0\n"), "{text}");
        // The id line is the first line, so an empty combat id leaves the very first value blank.
        assert!(
            text.starts_with("id=\n"),
            "an empty combat id writes an empty value: {text}"
        );
        assert!(text.contains("\nseed=-7\n"), "the minus sign is ASCII");
    }

    #[test]
    fn the_active_combatant_uses_the_blank_spelling() {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 1);
        // No combatant at all: the line is there, empty.
        assert!(render(&s).contains("\nactive=\n"));

        s.add_combatant(hero()).unwrap();
        s.active_combatant_id = None;
        assert!(render(&s).contains("\nactive=\n"), "None writes nothing after `active=`");

        s.active_combatant_id = Some(cid("hero"));
        assert!(render(&s).contains("\nactive=hero\n"));

        // `null` and `none` are OTHER idioms and must not appear here.
        let text = render(&s);
        assert!(!text.contains("active=null"));
        assert!(!text.contains("active=none"));
    }

    #[test]
    fn the_generator_lines_have_no_summon_counter() {
        let s = example();
        let text = render(&s);
        assert!(text.contains("status_num=7\n"));
        assert!(text.contains("card_num=13\n"));
        assert!(text.contains("chain_num=5\n"));
        assert!(text.contains("exec_num=9\n"));
        // NextSummonedCombatantNumber is in the snapshot but NOT in the hash (spec §3-D12), so a
        // line for it would be a divergence, not an omission.
        assert!(!text.contains("summon_num"), "{text}");

        // The chain/execution generators are `long`, so their range must not be `int`.
        let mut big = CombatState::new(CombatId::new("c1").unwrap(), 1);
        big.next_effect_chain_number = 5_000_000_000;
        big.next_program_execution_id = i64::MAX;
        let text = render(&big);
        assert!(text.contains("chain_num=5000000000\n"), "{text}");
        assert!(text.contains("exec_num=9223372036854775807\n"), "{text}");
    }

    #[test]
    fn turn_order_ends_every_id_with_a_comma_and_stays_empty_when_empty() {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 1);
        assert!(render(&s).contains("\nturn_order=\n"));

        s.add_combatant(hero()).unwrap();
        s.add_combatant(Combatant::new(cid("ogre"), def("ogre"), team("enemy"), 0, 30)).unwrap();
        assert!(render(&s).contains("\nturn_order=hero,ogre,\n"));
    }

    // ---------------------------------------------------------------- line class 5 (gs=)

    #[test]
    fn global_status_lines_use_the_gs_prefix_and_list_order() {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 1);
        s.push_global_status(
            StatusInstance::new(siid("status_000002"), sdid("standard.dexterity"), StatusPolarity::Buff)
                .with_stacks(2),
        )
        .unwrap();
        s.push_global_status(
            StatusInstance::new(siid("status_000001"), sdid("standard.artifact"), StatusPolarity::Buff)
                .with_stacks(1)
                .with_pending_turns(3),
        )
        .unwrap();
        let text = render(&s);
        assert!(text.contains(
            "gs=status_000002 standard.dexterity stk=2 dur=0 chg=0 pol=0\n\
             gs=status_000001 standard.artifact stk=1 dur=0 chg=0 pol=0 pend=3\n"
        ), "{text}");
        // `gs=` and the id are adjacent - no space after the key.
        assert!(!text.contains("gs= "));
    }

    // ---------------------------------------------------------------- line class 6 (c=)

    #[test]
    fn the_combatant_line_carries_def_team_lifecycle_and_hp() {
        let c = Combatant::new(cid("hero"), def("bureaucrat"), team("player"), 61, 70);
        assert_eq!(
            text(|w| write_combatant(w, &c)),
            "c=hero def=bureaucrat team=player lc=0 hp=61/70\ntags=\n"
        );

        let downed = Combatant::new(cid("ogre"), def("ogre"), team("enemy"), 0, 30)
            .with_lifecycle_state(CombatantLifecycleState::Banished);
        assert_eq!(
            text(|w| write_combatant(w, &downed)),
            "c=ogre def=ogre team=enemy lc=5 hp=0/30\ntags=\n"
        );
        // Lifecycle is a number even when it is the interesting one.
        assert!(!text(|w| write_combatant(w, &downed)).contains("Banished"));
    }

    // ---------------------------------------------------------------- line class 7 (res=, dp=)

    #[test]
    fn pool_lines_sort_by_key_and_spell_an_absent_max_as_null() {
        let mut c = hero();
        c.set_resource(rid("standard.energy"), 2, Some(3)).unwrap();
        c.set_resource(rid("aaa"), 1, None).unwrap();
        c.set_defensive_pool(dpid("standard.block"), 0, None).unwrap();
        assert_eq!(
            text(|w| write_combatant(w, &c)),
            "c=hero def=bureaucrat team=player lc=0 hp=61/70\n\
             res=aaa 1/null\n\
             res=standard.energy 2/3\n\
             dp=standard.block 0/null\n\
             tags=\n"
        );

        // Overfill is a legitimate state and must survive as data (spec §2.5).
        let mut over = hero();
        over.set_resource(rid("standard.energy"), 9, Some(3)).unwrap();
        assert!(text(|w| write_combatant(w, &over)).contains("res=standard.energy 9/3\n"));
    }

    // ---------------------------------------------------------------- line class 8 (s=)

    #[test]
    fn status_lines_append_pending_only_when_the_status_is_waiting() {
        let active = StatusInstance::new(siid("status_000001"), sdid("standard.vulnerable"), StatusPolarity::Debuff)
            .with_stacks(2)
            .with_duration_turns(3)
            .with_charges(1);
        assert_eq!(
            text(|w| write_status(w, &active)),
            "status_000001 standard.vulnerable stk=2 dur=3 chg=1 pol=1\n"
        );

        let pending = active.with_pending_turns(2);
        assert_eq!(
            text(|w| write_status(w, &pending)),
            "status_000001 standard.vulnerable stk=2 dur=3 chg=1 pol=1 pend=2\n"
        );

        // Zero pending must NOT write `pend=0` - absence is the format.
        let zero = active.with_pending_turns(0);
        assert_eq!(
            text(|w| write_status(w, &zero)),
            "status_000001 standard.vulnerable stk=2 dur=3 chg=1 pol=1\n"
        );

        // Negative numbers are spelled with an ASCII minus, and `pol` is the enum value.
        let odd = StatusInstance::new(siid("status_000009"), sdid("test.odd"), StatusPolarity::Neutral)
            .with_stacks(-1)
            .with_duration_turns(-2)
            .with_charges(-3);
        assert_eq!(
            text(|w| write_status(w, &odd)),
            "status_000009 test.odd stk=-1 dur=-2 chg=-3 pol=2\n"
        );
    }

    #[test]
    fn combatant_status_lines_keep_instance_order_and_include_pending() {
        let mut c = hero();
        c.push_status(StatusInstance::new(siid("status_000003"), sdid("standard.weak"), StatusPolarity::Debuff))
            .unwrap();
        c.push_status(
            StatusInstance::new(siid("status_000001"), sdid("standard.poison"), StatusPolarity::Debuff)
                .with_pending_turns(2),
        )
        .unwrap();
        let text = text(|w| write_combatant(w, &c));
        assert!(text.contains(
            "s=status_000003 standard.weak stk=0 dur=0 chg=0 pol=1\n\
             s=status_000001 standard.poison stk=0 dur=0 chg=0 pol=1 pend=2\n"
        ), "{text}");
        // List order, not sorted: status_000003 comes first even though its id sorts later.
        let first = text.find("s=status_000003").unwrap();
        let second = text.find("s=status_000001").unwrap();
        assert!(first < second);
    }

    // ---------------------------------------------------------------- line class 9 (tags=, cnt=)

    #[test]
    fn tag_and_counter_lines_follow_the_reference_spelling() {
        let mut c = hero();
        // No tags: the line is still written, with nothing after the `=`.
        assert!(text(|w| write_combatant(w, &c)).contains("\ntags=\n"));

        c.add_tag(tag("skill")).unwrap();
        c.add_tag(tag("attack")).unwrap();
        c.set_counter(cnt("zzz"), -2).unwrap();
        c.set_counter(cnt("aaa"), 1).unwrap();
        assert!(text(|w| write_combatant(w, &c)).contains("tags=attack,skill,\n"));
        assert!(text(|w| write_combatant(w, &c)).contains("cnt=aaa=1\ncnt=zzz=-2\n"));
    }

    // ---------------------------------------------------------------- line class 10 (cz=)

    #[test]
    fn card_zone_blocks_follow_turn_order_and_are_never_empty_lines() {
        let s = example();
        let text = render(&s);
        // Both combatants get a `cz=` line (the reference creates piles for every combatant on
        // `AddCombatant`), the second one with nothing under it.
        assert!(text.contains("\ncz=hero\ndraw=card_000001 standard.strike\n"), "{text}");
        assert!(text.ends_with("cz=ogre\ntr=rule.a RogueDeck.Core.Combat.TurnStartedCombatEvent act=2 expR=none expT=5 owner=hero ownerbound inst=2.1\n"), "{text}");
        // All `cz=` blocks come after all `c=` blocks.
        assert!(text.find("c=ogre").unwrap() < text.find("cz=hero").unwrap());
    }

    // ---------------------------------------------------------------- line class 11 (cards)

    #[test]
    fn card_lines_use_the_zone_as_key_and_the_optional_suffixes() {
        let plain = CardInstance::new(ciid("card_000001"), cdid("standard.strike"));
        assert_eq!(
            text(|w| write_card(w, CardZone::DrawPile, &plain)),
            "draw=card_000001 standard.strike\n"
        );

        let mut decorated = CardInstance::new(ciid("card_000002"), cdid("standard.defend"));
        decorated.add_mark(tag("zzz")).unwrap();
        decorated.add_mark(tag("aaa")).unwrap();
        decorated.set_mark_counter(cnt("standard.card_cost_delta"), -2).unwrap();
        decorated.set_mark_counter(cnt("aaa"), 1).unwrap();
        let decorated = decorated
            .with_mark_source(cid("hero"))
            .with_queued_target(cid("ogre"));
        let decorated_line = text(|w| write_card(w, CardZone::Hand, &decorated));
        assert_text(
            &decorated_line,
            "hand=card_000002 standard.defend m:aaa m:zzz mc:aaa=1 mc:standard.card_cost_delta=-2 msrc:hero qat:ogre\n",
            "a card line carrying every suffix",
        );

        // Each suffix independently absent; the writer's whole-write rule means a suffix is either
        // complete or missing.
        let mut marks_only = CardInstance::new(ciid("card_000003"), cdid("standard.strike"));
        marks_only.add_mark(tag("innate")).unwrap();
        assert_eq!(
            text(|w| write_card(w, CardZone::ExhaustPile, &marks_only)),
            "exh=card_000003 standard.strike m:innate\n"
        );
        let target_only = CardInstance::new(ciid("card_000004"), cdid("standard.strike"))
            .with_queued_target(cid("ogre"));
        assert_eq!(
            text(|w| write_card(w, CardZone::QueuePile, &target_only)),
            "queue=card_000004 standard.strike qat:ogre\n"
        );
        let source_only =
            CardInstance::new(ciid("card_000005"), cdid("standard.strike")).with_mark_source(cid("hero"));
        assert_eq!(
            text(|w| write_card(w, CardZone::BanishedPile, &source_only)),
            "ban=card_000005 standard.strike msrc:hero\n"
        );
        // A card never writes its zone as a value.
        assert!(!text(|w| write_card(w, CardZone::Hand, &plain)).contains(" zone="));
    }

    #[test]
    fn all_seven_zones_are_written_in_the_reference_order() {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 1);
        s.add_combatant(hero()).unwrap();
        for (i, zone) in CardZone::ALL.iter().enumerate() {
            s.push_card(
                &cid("hero"),
                *zone,
                CardInstance::new(
                    CardInstanceId::new(&format!("card_{:06}", i + 1)).unwrap(),
                    cdid("standard.strike"),
                ),
            )
            .unwrap();
        }
        let text = render(&s);
        let body = text.split_once("cz=hero\n").unwrap().1;
        let order: Vec<&str> = body
            .lines()
            .map(|l| l.split('=').next().unwrap())
            .collect();
        assert_eq!(order, ["draw", "hand", "disc", "exh", "ban", "queue", "aside"]);
    }

    #[test]
    fn an_empty_queue_and_set_aside_leave_no_trace_at_all() {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 1);
        s.add_combatant(hero()).unwrap();
        s.push_card(
            &cid("hero"),
            CardZone::Hand,
            CardInstance::new(ciid("card_000001"), cdid("standard.strike")),
        )
        .unwrap();
        let text = render(&s);
        assert!(text.contains("\ncz=hero\nhand=card_000001 standard.strike\n"), "{text}");
        assert!(!text.contains("queue"), "{text}");
        assert!(!text.contains("aside"), "{text}");
        // Not even a bare `queue=` with nothing after it.
        assert!(!text.contains("queue="));

        // With a single waiting card, the two zones appear after the five always-present ones.
        s.push_card(
            &cid("hero"),
            CardZone::QueuePile,
            CardInstance::new(ciid("card_000002"), cdid("standard.strike")),
        )
        .unwrap();
        let text = render(&s);
        let hand = text.find("hand=").unwrap();
        let queue = text.find("queue=").unwrap();
        assert!(hand < queue);
    }

    // ---------------------------------------------------------------- line class 12 (tr=)

    #[test]
    fn temporary_rule_lines_spell_inf_none_and_the_suffixes() {
        let event = EventTypeName::new("RogueDeck.Core.Combat.TurnStartedCombatEvent").unwrap();
        let bare = TemporaryRule::new(TriggeredEffectDefinitionId::new("rule.b").unwrap(), event, 2, 1);
        assert_eq!(
            text(|w| write_temporary_rule(w, &bare)),
            "tr=rule.b RogueDeck.Core.Combat.TurnStartedCombatEvent act=inf expR=none expT=none owner=none inst=2.1\n"
        );

        let full = TemporaryRule::new(TriggeredEffectDefinitionId::new("rule.a").unwrap(), event, 3, 4)
            .with_remaining_activations(1)
            .with_expires_after_round(6)
            .with_expires_after_turn(7)
            .with_owner(cid("hero"))
            .owner_bound()
            .expired();
        assert_eq!(
            text(|w| write_temporary_rule(w, &full)),
            "tr=rule.a RogueDeck.Core.Combat.TurnStartedCombatEvent act=1 expR=6 expT=7 owner=hero ownerbound inst=3.4 dead\n"
        );

        // The suffix tokens are absent when false - `ownerbound` and `dead` are not `false`.
        assert!(!text(|w| write_temporary_rule(w, &bare)).contains("ownerbound"));
        assert!(!text(|w| write_temporary_rule(w, &bare)).contains(" dead"));
        // `act=` is `inf`, never `null` or blank.
        assert!(!text(|w| write_temporary_rule(w, &bare)).contains("act=null"));
        // `owner=` is `none`, never blank.
        assert!(!text(|w| write_temporary_rule(w, &bare)).contains("owner= "));
    }

    #[test]
    fn temporary_rules_are_written_sorted_by_id() {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 1);
        let event = EventTypeName::new("RogueDeck.Core.Combat.TurnStartedCombatEvent").unwrap();
        for id in ["rule.c", "rule.a", "rule.b"] {
            s.add_temporary_rule(TemporaryRule::new(
                TriggeredEffectDefinitionId::new(id).unwrap(),
                event,
                1,
                1,
            ))
            .unwrap();
        }
        let text = render(&s);
        let ids: Vec<&str> = text
            .lines()
            .filter(|l| l.starts_with("tr="))
            .map(|l| l.split(' ').next().unwrap().trim_start_matches("tr="))
            .collect();
        assert_eq!(ids, ["rule.a", "rule.b", "rule.c"]);
    }

    // ---------------------------------------------------------------- ordering contracts

    #[test]
    fn combatants_and_zones_are_written_in_turn_order_not_insertion_order() {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 1);
        s.add_combatant(hero()).unwrap();
        s.add_combatant(Combatant::new(cid("ogre"), def("ogre"), team("enemy"), 0, 30)).unwrap();
        s.push_card(
            &cid("hero"),
            CardZone::Hand,
            CardInstance::new(ciid("card_000001"), cdid("standard.strike")),
        )
        .unwrap();
        s.push_card(
            &cid("ogre"),
            CardZone::Hand,
            CardInstance::new(ciid("card_000002"), cdid("standard.strike")),
        )
        .unwrap();
        assert!(render(&s).contains("turn_order=hero,ogre,"));

        // Reversed turn order: every section must follow it, not the storage order.
        s.set_turn_order(&[cid("ogre"), cid("hero")]).unwrap();
        let text = render(&s);
        assert!(text.contains("turn_order=ogre,hero,"));
        assert!(text.find("c=ogre").unwrap() < text.find("c=hero").unwrap());
        assert!(text.find("cz=ogre").unwrap() < text.find("cz=hero").unwrap());
        assert!(text.find("hand=card_000002").unwrap() < text.find("hand=card_000001").unwrap());
    }

    #[test]
    fn a_combatant_with_piles_detached_writes_no_cz_block() {
        let mut s = CombatState::new(CombatId::new("c1").unwrap(), 1);
        s.add_combatant(hero()).unwrap();
        s.add_combatant(Combatant::new(cid("ogre"), def("ogre"), team("enemy"), 0, 30)).unwrap();
        assert!(s.detach_card_zones(&cid("ogre")));
        let text = render(&s);
        assert!(text.contains("\ncz=hero\n"));
        assert!(!text.contains("cz=ogre"));
        // The combatant itself is still written, and still in the turn order.
        assert!(text.contains("\nc=ogre "));
        assert!(text.contains("turn_order=hero,ogre,"));
    }

    // ---------------------------------------------------------------- end to end

    #[test]
    fn a_full_document_matches_the_reference_line_for_line() {
        let expected = "\
id=c1
seed=42
step=3
result=0
round=2
turn=1
phase=1
active=hero
status_num=7
card_num=13
chain_num=5
exec_num=9
turn_order=hero,ogre,
gs=status_000001 standard.artifact stk=1 dur=0 chg=0 pol=0
c=hero def=bureaucrat team=player lc=0 hp=61/70
res=standard.energy 2/3
dp=standard.block 6/999
s=status_000002 standard.poison stk=4 dur=0 chg=0 pol=1
s=status_000003 standard.weak stk=1 dur=2 chg=0 pol=1 pend=1
tags=
cnt=standard.attacks_played=2
c=ogre def=ogre team=enemy lc=1 hp=0/30
tags=
cz=hero
draw=card_000001 standard.strike
hand=card_000002 standard.defend m:aaa m:zzz mc:aaa=1 mc:standard.card_cost_delta=-2 msrc:hero qat:ogre
queue=card_000003 standard.strike qat:ogre
aside=card_000004 standard.defend
cz=ogre
tr=rule.a RogueDeck.Core.Combat.TurnStartedCombatEvent act=2 expR=none expT=5 owner=hero ownerbound inst=2.1
";
        let actual = render(&example());
        assert_text(&actual, expected, "the full document");

        // Every line ends in LF, including the last, and no CR appears anywhere.
        assert!(actual.ends_with('\n'));
        assert!(!actual.contains('\r'));
        assert_eq!(actual.matches('\n').count(), expected.lines().count());
    }

    #[test]
    fn the_canonical_text_hashes_to_lowercase_hex() {
        // The whole point of the text: it is the SHA-256 input. Compose the pipeline here so a
        // change in either half shows up as a failing test in this module.
        let text = render(&example());
        let digest = crate::hash::sha256(text.as_bytes());
        let mut hex = [0u8; 64];
        crate::hash::to_hex_lower(&mut hex, &digest);
        let hex = core::str::from_utf8(&hex).unwrap();
        assert_eq!(hex.len(), 64);
        assert!(hex.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));

        // Same state, same text, same hash; a one-field change moves it.
        assert_eq!(render(&example()), text);
        assert_ne!(
            crate::hash::sha256(render(&example()).as_bytes()),
            {
                let mut other = example();
                other.random_step += 1;
                crate::hash::sha256(render(&other).as_bytes())
            }
        );
    }

    // ---------------------------------------------------------------- overflow

    #[test]
    fn an_undersized_buffer_is_reported_and_never_silently_truncated() {
        let s = example();
        let full = render(&s);

        for size in 1..full.len() {
            let mut buf = vec![0u8; size];
            let mut w = TextWriter::new(&mut buf);
            write_hash_input(&mut w, &s);
            assert!(
                w.overflowed(),
                "a {size}-byte buffer reported success for {}-byte text",
                full.len()
            );
            // What did fit is a genuine prefix: no half-written field.
            assert!(
                full.starts_with(w.as_str()),
                "size={size}: {:?} is not a prefix of the canonical text",
                w.as_str()
            );
        }

        // Exactly the right size is not an overflow, and produces the whole text.
        let mut exact = vec![0u8; full.len()];
        let mut w = TextWriter::new(&mut exact);
        write_hash_input(&mut w, &s);
        assert!(!w.overflowed());
        assert_eq!(w.as_str(), full);
    }

    #[test]
    fn overflow_is_noticed_at_field_granularity() {
        // `TextWriter` drops whole WRITES, and this serialiser writes field by field, so a short
        // buffer can hold a prefix of a LINE but never half a field. That is exactly why the flag
        // has to be checked: the text below is a plausible-looking fragment, not a fingerprint.
        let s = example();

        // Three bytes: `id=` exactly, and the id itself does not fit.
        let mut buf = [0u8; 3];
        let mut w = TextWriter::new(&mut buf);
        write_hash_input(&mut w, &s);
        assert!(w.overflowed());
        assert_eq!(w.as_str(), "id=");

        // Five bytes: `id=c1` fits (key 3 + value 2), the newline does not.
        let mut buf2 = [0u8; 5];
        let mut w2 = TextWriter::new(&mut buf2);
        write_hash_input(&mut w2, &s);
        assert!(w2.overflowed());
        assert_eq!(w2.as_str(), "id=c1");

        // Six bytes: the first line is complete and the second is not.
        let mut buf3 = [0u8; 6];
        let mut w3 = TextWriter::new(&mut buf3);
        write_hash_input(&mut w3, &s);
        assert!(w3.overflowed());
        assert_eq!(w3.as_str(), "id=c1\n");
    }

    #[test]
    fn an_empty_state_still_produces_a_fixed_frame() {
        let s = CombatState::new(CombatId::new("c0").unwrap(), 0);
        assert_eq!(
            render(&s),
            "\
id=c0
seed=0
step=0
result=0
round=1
turn=1
phase=0
active=
status_num=1
card_num=1
chain_num=1
exec_num=1
turn_order=
"
        );
    }

    // ---------------------------------------------------------------- the engine's own text
    //
    // Everything above pins the format against the reference SOURCE. The two tests below pin it
    // against the reference's OUTPUT: `corpus/hash_cases/*.txt` are canonical texts captured from
    // the real C# engine (via the oracle), each with its SHA-256. Re-serialising a state built from
    // one of those texts has to reproduce it byte for byte - which is what "hash_golden is byte
    // equality" means, and is the same acceptance the port's conformance harness applies.

    /// The engine's canonical text for `case_0000`, verbatim from
    /// `corpus/hash_cases/case_0000_v0_s1.txt` (375 bytes, 24 lines, every line LF-terminated).
    const ORACLE_CASE_0000: &str = "\
id=oracle
seed=1
step=0
result=0
round=1
turn=2
phase=1
active=ogre
status_num=1
card_num=4
chain_num=9
exec_num=3
turn_order=knight,ogre,
c=knight def=knight team=player lc=0 hp=25/30
res=standard.energy 2/3
tags=
c=ogre def=ogre team=enemy lc=0 hp=6/12
res=standard.energy 3/3
tags=
cz=knight
disc=card_000001 strike
disc=card_000002 strike
disc=card_000003 strike
cz=ogre
";

    /// The engine's own SHA-256 for that text.
    const ORACLE_CASE_0000_SHA256: &str =
        "f3298ef47264667185933a987ddd4c7cd42e096f60bacdc3b5e5fbc4d1a02a85";

    fn sha256_hex(text: &str) -> String {
        let mut hex = [0u8; 64];
        crate::hash::to_hex_lower(&mut hex, &crate::hash::sha256(text.as_bytes()));
        core::str::from_utf8(&hex).unwrap().to_string()
    }

    fn result_of(value: &str) -> CombatResult {
        match value {
            "0" => CombatResult::Ongoing,
            "1" => CombatResult::Victory,
            "2" => CombatResult::Defeat,
            "3" => CombatResult::Draw,
            "4" => CombatResult::Aborted,
            other => panic!("unknown result {other}"),
        }
    }

    fn phase_of(value: &str) -> CombatTurnPhase {
        match value {
            "0" => CombatTurnPhase::WaitingToStartTurn,
            "1" => CombatTurnPhase::TurnInProgress,
            other => panic!("unknown phase {other}"),
        }
    }

    fn lifecycle_of(value: &str) -> CombatantLifecycleState {
        match value {
            "0" => CombatantLifecycleState::Alive,
            "1" => CombatantLifecycleState::Downed,
            "2" => CombatantLifecycleState::Dead,
            "3" => CombatantLifecycleState::Removed,
            "4" => CombatantLifecycleState::Escaped,
            "5" => CombatantLifecycleState::Banished,
            other => panic!("unknown lifecycle {other}"),
        }
    }

    fn polarity_of(value: &str) -> StatusPolarity {
        match value {
            "0" => StatusPolarity::Buff,
            "1" => StatusPolarity::Debuff,
            "2" => StatusPolarity::Neutral,
            other => panic!("unknown polarity {other}"),
        }
    }

    fn zone_of(name: &str) -> CardZone {
        *CardZone::ALL
            .iter()
            .find(|zone| zone.wire_name() == name)
            .unwrap_or_else(|| panic!("unknown zone {name}"))
    }

    fn pool_of(value: &str) -> (i32, Option<i32>) {
        let (current, max) = value.split_once('/').unwrap_or_else(|| panic!("bad pool {value}"));
        let max = if max == "null" {
            None
        } else {
            Some(max.parse().unwrap())
        };
        (current.parse().unwrap(), max)
    }

    /// `hp=<cur>/<max>`: health is never `null` (unlike a pool's upper bound).
    fn hp_of(value: &str) -> (i32, i32) {
        let (current, max) = value.split_once('/').unwrap_or_else(|| panic!("bad hp {value}"));
        (current.parse().unwrap(), max.parse().unwrap())
    }

    /// `<id> <def> stk=<n> dur=<n> chg=<n> pol=<n>[ pend=<n>]`
    fn parse_status(value: &str) -> StatusInstance {
        let tokens: Vec<&str> = value.split(' ').collect();
        let mut status = StatusInstance::new(
            StatusInstanceId::new(tokens[0]).unwrap(),
            StatusDefinitionId::new(tokens[1]).unwrap(),
            StatusPolarity::Buff,
        );
        for token in &tokens[2..] {
            let (key, v) = token.split_once('=').unwrap_or_else(|| panic!("bad status field {token}"));
            match key {
                "stk" => status.stacks = v.parse().unwrap(),
                "dur" => status.duration_turns = v.parse().unwrap(),
                "chg" => status.charges = v.parse().unwrap(),
                "pol" => status.polarity = polarity_of(v),
                "pend" => status.pending_turns = v.parse().unwrap(),
                other => panic!("unknown status field {other}"),
            }
        }
        status
    }

    /// `<cardId> <def>[ m:<tag>][ mc:<key>=<n>][ msrc:<id>][ qat:<id>]`
    fn parse_card(value: &str) -> CardInstance {
        let tokens: Vec<&str> = value.split(' ').collect();
        let mut card = CardInstance::new(
            CardInstanceId::new(tokens[0]).unwrap(),
            CardDefinitionId::new(tokens[1]).unwrap(),
        );
        for token in &tokens[2..] {
            if let Some(mark) = token.strip_prefix("m:") {
                card.add_mark(TagId::new(mark).unwrap()).unwrap();
            } else if let Some(rest) = token.strip_prefix("mc:") {
                let (key, v) = rest.split_once('=').unwrap();
                card.set_mark_counter(CounterId::new(key).unwrap(), v.parse().unwrap())
                    .unwrap();
            } else if let Some(source) = token.strip_prefix("msrc:") {
                card.mark_source_combatant_id = Some(CombatantId::new(source).unwrap());
            } else if let Some(aimed) = token.strip_prefix("qat:") {
                card.queued_target_id = Some(CombatantId::new(aimed).unwrap());
            } else {
                panic!("unknown card field {token}");
            }
        }
        card
    }

    /// `tr=<id> <event> act=<n|inf> expR=<n|none> expT=<n|none> owner=<id|none>[ ownerbound] inst=<r>.<t>[ dead]`
    fn parse_rule(value: &str) -> TemporaryRule {
        let tokens: Vec<&str> = value.split(' ').collect();
        let mut rule = TemporaryRule::new(
            TriggeredEffectDefinitionId::new(tokens[0]).unwrap(),
            EventTypeName::new(tokens[1]).unwrap(),
            0,
            0,
        );
        for token in &tokens[2..] {
            match *token {
                "ownerbound" => rule.expires_when_owner_removed = true,
                "dead" => rule.is_expired = true,
                other => {
                    let (key, v) = other.split_once('=').unwrap_or_else(|| panic!("bad rule field {other}"));
                    match key {
                        "act" => {
                            rule.remaining_activations =
                                if v == "inf" { None } else { Some(v.parse().unwrap()) };
                        }
                        "expR" => {
                            rule.expires_after_round = if v == "none" { None } else { Some(v.parse().unwrap()) };
                        }
                        "expT" => {
                            rule.expires_after_turn = if v == "none" { None } else { Some(v.parse().unwrap()) };
                        }
                        "owner" => {
                            rule.owner_combatant_id =
                                if v == "none" { None } else { Some(CombatantId::new(v).unwrap()) };
                        }
                        "inst" => {
                            let (round, turn) = v.split_once('.').unwrap();
                            rule.installed_round = round.parse().unwrap();
                            rule.installed_turn = turn.parse().unwrap();
                        }
                        field => panic!("unknown rule field {field}"),
                    }
                }
            }
        }
        rule
    }

    /// Rebuilds a [`CombatState`] from canonical text.
    ///
    /// Test-only, and written against the REFERENCE's format rather than against
    /// [`write_hash_input`]: anything unrecognised panics. A lenient reader would make the
    /// round-trip test weaker than the format it is checking.
    fn parse_canonical(text: &str) -> CombatState {
        let mut state = CombatState::new(CombatId::new("").unwrap(), 0);
        let mut turn_order: Vec<CombatantId> = Vec::new();
        let mut current = CombatantId::EMPTY;
        let mut current_zone_owner = CombatantId::EMPTY;

        for line in text.lines() {
            let (key, value) = line
                .split_once('=')
                .unwrap_or_else(|| panic!("line without a key: {line:?}"));
            match key {
                "id" => state.id = CombatId::new(value).unwrap(),
                "seed" => state.random_seed = value.parse().unwrap(),
                "step" => state.random_step = value.parse().unwrap(),
                "result" => state.result = result_of(value),
                "round" => state.current_round = value.parse().unwrap(),
                "turn" => state.current_turn = value.parse().unwrap(),
                "phase" => state.turn_phase = phase_of(value),
                "active" => {
                    state.active_combatant_id = if value.is_empty() {
                        None
                    } else {
                        Some(CombatantId::new(value).unwrap())
                    };
                }
                "status_num" => state.next_status_instance_number = value.parse().unwrap(),
                "card_num" => state.next_card_instance_number = value.parse().unwrap(),
                "chain_num" => state.next_effect_chain_number = value.parse().unwrap(),
                "exec_num" => state.next_program_execution_id = value.parse().unwrap(),
                "turn_order" => {
                    turn_order = value
                        .split(',')
                        .filter(|id| !id.is_empty())
                        .map(|id| CombatantId::new(id).unwrap())
                        .collect();
                }
                "gs" => state.push_global_status(parse_status(value)).unwrap(),
                "c" => {
                    let tokens: Vec<&str> = value.split(' ').collect();
                    current = CombatantId::new(tokens[0]).unwrap();
                    let (mut def, mut team) = (CombatantDefinitionId::EMPTY, TeamId::EMPTY);
                    let (mut lc, mut hp) = (CombatantLifecycleState::Alive, (0i32, 0i32));
                    for token in &tokens[1..] {
                        let (field, v) = token.split_once('=').unwrap_or_else(|| panic!("bad combatant field {token}"));
                        match field {
                            "def" => def = CombatantDefinitionId::new(v).unwrap(),
                            "team" => team = TeamId::new(v).unwrap(),
                            "lc" => lc = lifecycle_of(v),
                            "hp" => hp = hp_of(v),
                            other => panic!("unknown combatant field {other}"),
                        }
                    }
                    state
                        .add_combatant(
                            Combatant::new(current, def, team, hp.0, hp.1).with_lifecycle_state(lc),
                        )
                        .unwrap();
                }
                "res" | "dp" => {
                    let (pool_key, pool) = value.split_once(' ').unwrap();
                    let (cur, max) = pool_of(pool);
                    let combatant = state.combatant_mut(&current).unwrap();
                    if key == "res" {
                        combatant.set_resource(ResourceId::new(pool_key).unwrap(), cur, max).unwrap();
                    } else {
                        combatant
                            .set_defensive_pool(DefensivePoolId::new(pool_key).unwrap(), cur, max)
                            .unwrap();
                    }
                }
                "s" => state
                    .combatant_mut(&current)
                    .unwrap()
                    .push_status(parse_status(value))
                    .unwrap(),
                "tags" => {
                    let combatant = state.combatant_mut(&current).unwrap();
                    for tag in value.split(',').filter(|t| !t.is_empty()) {
                        combatant.add_tag(TagId::new(tag).unwrap()).unwrap();
                    }
                }
                "cnt" => {
                    let (counter, v) = value.split_once('=').unwrap();
                    state
                        .combatant_mut(&current)
                        .unwrap()
                        .set_counter(CounterId::new(counter).unwrap(), v.parse().unwrap())
                        .unwrap();
                }
                "cz" => current_zone_owner = CombatantId::new(value).unwrap(),
                "draw" | "hand" | "disc" | "exh" | "ban" | "queue" | "aside" => {
                    state
                        .push_card(&current_zone_owner, zone_of(key), parse_card(value))
                        .unwrap();
                }
                "tr" => state.add_temporary_rule(parse_rule(value)).unwrap(),
                other => panic!("unknown line key {other:?}"),
            }
        }

        state.set_turn_order(&turn_order).unwrap();
        state
    }

    #[test]
    fn the_engines_own_canonical_text_matches_byte_for_byte() {
        // The text is the engine's; the state is rebuilt from it; the writer has to give the text
        // back exactly, and the hash has to be the engine's hash.
        assert_eq!(ORACLE_CASE_0000.len(), 375);
        assert_eq!(ORACLE_CASE_0000.matches('\n').count(), 24);
        assert!(!ORACLE_CASE_0000.contains('\r'));
        assert_eq!(sha256_hex(ORACLE_CASE_0000), ORACLE_CASE_0000_SHA256);

        let rebuilt = parse_canonical(ORACLE_CASE_0000);
        assert_eq!(render(&rebuilt), ORACLE_CASE_0000);
        assert_eq!(sha256_hex(&render(&rebuilt)), ORACLE_CASE_0000_SHA256);

        // Spot-check the structure that was rebuilt, so a reader that quietly dropped a section
        // cannot pass by reproducing its own mistake.
        assert_eq!(rebuilt.turn_order(), &[cid("knight"), cid("ogre")]);
        assert_eq!(rebuilt.card_count(), 3);
        assert_eq!(rebuilt.combatant(&cid("knight")).unwrap().health_current, 25);
        assert_eq!(
            rebuilt.combatant(&cid("knight")).unwrap().resources()[0].pool,
            Pool { current: 2, max: Some(3) }
        );
        assert_eq!(
            rebuilt.card_zones(&cid("ogre")).unwrap().count(CardZone::DrawPile),
            0
        );
    }

    /// Every canonical text captured from the engine, round-tripped.
    ///
    /// Skips (loudly) when the corpus is not next to the kernel, so the crate still tests cleanly
    /// on its own; when it is there, all of it has to round-trip.
    #[test]
    fn every_corpus_hash_case_round_trips() {
        let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../corpus/hash_cases");
        if !dir.is_dir() {
            std::println!("corpus not present at {}; skipping", dir.display());
            return;
        }

        let mut seen = 0usize;
        let mut entries: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .map(|e| e.unwrap().path())
            .filter(|p| p.extension().map(|e| e == "txt").unwrap_or(false))
            .filter(|p| {
                p.file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| n.starts_with("case_"))
                    .unwrap_or(false)
            })
            .collect();
        entries.sort();

        for path in entries {
            let text = std::fs::read_to_string(&path).unwrap();
            assert!(
                !text.contains('\r'),
                "{} is not LF-only; the canonical text never contains CR",
                path.display()
            );
            let rebuilt = parse_canonical(&text);
            assert_eq!(
                render(&rebuilt),
                text,
                "{} did not round-trip",
                path.display()
            );
            seen += 1;
        }
        std::println!("corpus round-trip: {seen} case(s) reproduced byte-for-byte");
        // ⚠️ 这个下限是**防止语料被意外删空**的，不是覆盖率证明 —— 逐份的 `render(parse(t)) == t`
        // 才是证明。所以它必须跟着语料一起长：曾经是 48，而语料涨到 80 之后 48 就成了空门槛
        // （删掉 32 份仍然通过）。加语料时**顺手把它抬上去**。
        assert!(seen >= 80, "expected the full corpus, saw {seen} case(s)");
    }
}
