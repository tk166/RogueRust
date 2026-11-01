//! 一局的规范文本与指纹（§163）。
//!
//! # 为什么需要它
//!
//! 回放的判据是"同一串动作之后局面**逐字节**相同"。没有指纹，这句话就只能靠 `PartialEq` 一次性比
//! 整个结构体 —— 那样能说"不一样"，但说不出**从第几步开始不一样**，而那正是唯一有用的信息。
//!
//! # 覆盖什么、不覆盖什么
//!
//! 覆盖：种子/等级/楼层/游标/血/金/幕/待决/已结算位图/牌组/遗物/药水/掉率/稀有度偏移/三条 `?` 房计数/
//! **七个随机流计数**/商店货架/奖励屏/事件/上一场遭遇/开局两次祝福/两个后续动作/**整张地图**。
//!
//! 不覆盖：**日志**（`journal` 在 wasm 侧，是宿主产物，不是游戏状态）与 `error` 字符串（诊断）。
//! 这两样与 `CombatState` 的 `beat_log` 同类：它们记的是"发生过什么/为什么失败"，不是"以后会怎样"。
//!
//! # 与 `rd-core` 的分工
//!
//! `rd-core` 的指纹是**参考引擎逐字节复刻**（`hash_golden`），所以它连行序都不能动。这里没有那个
//! 约束 —— 参考引擎根本没有运行层（`run-layer.md` §2 G6）—— 所以本文件只要求"自己的格式稳定"，
//! 并且**故意**不用任何参考实现没有的行名。

use crate::map::NodeKind;
use crate::state::{Pending, RunState};
use crate::streams::RunStream;
use rd_core::writer::TextWriter;

/// 一局的规范文本缓冲。实测 ~2.5 KB（15 行地图 + 10 张牌），8 KB 是"内容翻几倍也不会撞上"。
pub const MAX_TEXT: usize = 8192;

/// 把整局写成规范文本，返回字节数；缓冲不够是 `None`（**不是**截断 —— 截断的指纹会说谎）。
pub fn write_run_input(writer: &mut TextWriter<'_>, state: &RunState) {
    writer.str("seed=").i32(state.seed()).str("\n");
    writer.str("asc=").u32(u32::from(state.ascension())).str("\n");
    writer.str("floor=").i32(state.floor()).str("\n");
    writer.str("node=").i32(state.node()).str("\n");
    writer.str("hp=").i32(state.health()).str("\n");
    writer.str("hp_max=").i32(state.health_max()).str("\n");
    writer.str("gold=").i32(state.gold()).str("\n");
    writer.str("act=").u32(u32::from(state.act())).str("\n");
    writer.str("removed=").i32(state.removed_cards()).str("\n");
    writer
        .str("potion_chance=")
        .i32(state.potion_chance())
        .str("\n");
    writer
        .str("rarity_offset=")
        .i32(state.rarity_offset())
        .str("\n");
    writer.str("boss_beaten=").u32(u32::from(state.boss_beaten())).str("\n");
    writer.str("pending=").u32(u32::from(pending_code(state.pending()))).str("\n");
    // `RunId` **就是** `Ident<CAP>`，所以 `event()` 已经是 `&str`（再 `.as_str()` 会掉进
    // `str_as_str` 那个不稳定 feature）。
    writer.str("event=").str(state.event()).str("\n");
    writer
        .str("last_encounter=")
        .str(state.last_encounter().as_str())
        .str("\n");
    for (index, counter) in state.unknown().iter().enumerate() {
        writer.str("unknown").u32(index as u32).str("=").i32(*counter).str("\n");
    }

    // 三个定容容器：**只写活动前缀**，但前缀外必须为空这件事由 `check_invariants` 保证
    // （§162）—— 所以"同一局"在这里不会因为尾槽残留而分叉。
    writer.str("deck=").u32(state.deck().len() as u32).str("\n");
    for card in state.deck() {
        writer.str("d=").str(card.as_str()).str("\n");
    }
    writer.str("relics=").u32(state.relics().len() as u32).str("\n");
    for relic in state.relics() {
        writer.str("r=").str(relic.as_str()).str("\n");
    }
    writer.str("potions=").u32(state.potions().len() as u32).str("\n");
    for potion in state.potions() {
        writer.str("p=").str(potion.as_str()).str("\n");
    }

    // 七个随机流：**这是"同一局"最容易被破坏的部分** —— 少还原一个计数，之后的每个随机都错位。
    for stream in RunStream::ALL {
        writer
            .str("rng")
            .u32(stream as u32)
            .str("=")
            .i32(state.rng().counter(stream))
            .str("\n");
    }

    // `start_offers()` 只在**开局祝福**那一段有值（`Option<[StartOffer; 2]>`）—— 所以"没有"要写成
    // `offers=none`，而不是两行零（否则"还没开局"和"祝福是 0 号"会哈希成同一个）。
    match state.start_offers() {
        None => {
            writer.str("offers=none\n");
        }
        Some(offers) => {
            for slot in offers {
                // 用**名字**而不是下标：日志里一眼看得懂，而且祝福表一旦重排也不会假装是同一局。
                writer.str("offer=").str(slot.id).str("\n");
            }
        }
    }
    writer.str("blessing=").str(follow_code(state.blessing_follow())).str("\n");
    writer.str("event_follow=").str(deck_change_code(state.event_follow())).str("\n");

    // 已结算位图：两个 u64 按十六进制（十进制也能，但十六进制能一眼看出哪一位）。
    for word in state.resolved_words() {
        writer.str("resolved=").u64(*word).str("\n");
    }

    // 商店与奖励屏：买过的行 / 空行都要写，否则"两个货架"会哈希成同一个。
    writer.str("shop_cards=").u32(state.shop_cards_len() as u32).str("\n");
    for offer in state.shop_cards() {
        writer
            .str("sc=")
            .str(offer.id.as_str())
            .str(",")
            .i32(offer.price)
            .str("\n");
    }
    writer.str("shop_relics=").u32(state.shop_relics_len() as u32).str("\n");
    for offer in state.shop_relics() {
        writer
            .str("sr=")
            .str(offer.id.as_str())
            .str(",")
            .i32(offer.price)
            .str("\n");
    }
    writer
        .str("reward=")
        .i32(state.reward_gold())
        .str(",")
        .str(state.reward_potion().unwrap_or(""))
        .str(",")
        .str(state.reward_relic().unwrap_or(""))
        .str("\n");
    for card in state.reward_cards() {
        writer.str("rc=").str(card.as_str()).str("\n");
    }

    // 地图：**每一行的每一个槽位**（含被剪掉的），理由与存档同一条 —— 它们是值的一部分。
    writer.str("map_rows=").u32(state.map().rows().len() as u32).str("\n");
    for (row_index, row) in state.map().rows().iter().enumerate() {
        writer.str("mrow=").u32(row_index as u32).str(",").u32(u32::from(row.count())).str("\n");
        for node in row.slots() {
            writer
                .str("n=")
                .u32(u32::from(node.col))
                .str(",")
                .u32(u32::from(kind_code(node.kind)))
                .str(",");
            for target in node.out_targets() {
                writer.u32(u32::from(*target)).str(",");
            }
            writer.str("\n");
        }
    }
}

const fn pending_code(pending: Pending) -> u8 {
    match pending {
        Pending::None => 0,
        Pending::Rest => 1,
        Pending::Shop => 2,
        Pending::Chest => 3,
        Pending::Reward => 4,
        Pending::Event => 5,
        Pending::Start => 6,
        Pending::BlessingCard => 7,
        Pending::EventCard => 8,
    }
}

const fn kind_code(kind: NodeKind) -> u8 {
    match kind {
        NodeKind::Combat => 0,
        NodeKind::Elite => 1,
        NodeKind::Rest => 2,
        NodeKind::Shop => 3,
        NodeKind::Unknown => 4,
        NodeKind::Treasure => 5,
        NodeKind::Boss => 6,
        NodeKind::Unassigned => 7,
    }
}

fn follow_code(follow: Option<crate::state::BlessingFollowUp>) -> &'static str {
    match follow {
        None => "none",
        Some(crate::state::BlessingFollowUp::None) => "nothing",
        Some(crate::state::BlessingFollowUp::GainThreeCards) => "three_cards",
        Some(crate::state::BlessingFollowUp::Deck(crate::state::DeckChange::Remove)) => "remove",
        Some(crate::state::BlessingFollowUp::Deck(crate::state::DeckChange::Upgrade)) => "upgrade",
        Some(crate::state::BlessingFollowUp::Deck(crate::state::DeckChange::Transform)) => {
            "transform"
        }
    }
}

fn deck_change_code(change: Option<crate::state::DeckChange>) -> &'static str {
    match change {
        None => "none",
        Some(crate::state::DeckChange::Remove) => "remove",
        Some(crate::state::DeckChange::Upgrade) => "upgrade",
        Some(crate::state::DeckChange::Transform) => "transform",
    }
}

/// 一局的指纹：`SHA-256(规范文本)`。
///
/// 返回 `None` 只有一种原因：规范文本超出 [`MAX_TEXT`]。那是**不响亮的静默**，所以它必须是 `Option`
/// 而不是"用截断的文本算一个哈希"。
#[must_use]
pub fn run_hash(state: &RunState) -> Option<[u8; 32]> {
    let mut buffer = [0u8; MAX_TEXT];
    let mut writer = TextWriter::new(&mut buffer);
    write_run_input(&mut writer, state);
    if writer.overflowed() {
        return None;
    }
    Some(rd_core::hash::sha256(writer.as_str().as_bytes()))
}

/// 指纹的十六进制（小写，64 字符），给日志与回放用。
#[must_use]
pub fn run_hash_hex(state: &RunState) -> Option<[u8; 64]> {
    let digest = run_hash(state)?;
    let mut out = [0u8; 64];
    rd_core::hash::to_hex_lower(&mut out, &digest);
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run() -> RunState {
        let deck = [
            "strike", "strike", "strike", "strike", "strike", "defend", "defend", "defend",
            "defend", "bash",
        ];
        RunState::new_with_ascension(7, 80, 99, &deck, 0).expect("a run")
    }

    #[test]
    fn the_same_state_hashes_the_same_and_a_change_moves_it() {
        let first = run();
        let hex_a = run_hash_hex(&first).expect("hash");
        let hex_b = run_hash_hex(&first).expect("hash");
        assert_eq!(hex_a, hex_b, "hashing is a function of the state");

        // 逐字段各改一处，每次哈希都必须变 —— 这是"覆盖到了"的判据，而不是"我列了清单"。
        let mut probes: std::vec::Vec<(&str, RunState)> = std::vec::Vec::new();
        let mut probe = run();
        probe.adjust_gold(1);
        probes.push(("gold", probe));
        let mut probe = run();
        probe.adjust_health(-1);
        probes.push(("health", probe));
        let mut probe = run();
        probe.push_card("anger").expect("deck room");
        probes.push(("deck", probe));
        let mut probe = run();
        probe.push_relic("anchor").expect("relic room");
        probes.push(("relics", probe));
        let mut probe = run();
        probe.push_potion("fire_potion").expect("belt room");
        probes.push(("potions", probe));
        let mut probe = run();
        probe.enter_node(0).expect("the first node");
        probes.push(("node", probe));

        for (what, probe) in probes {
            let hex = run_hash_hex(&probe).expect("hash");
            assert_ne!(hex_a, hex, "changing {what} did not move the hash");
        }
    }

    #[test]
    fn the_rng_counters_are_in_the_fingerprint() {
        // 少一个计数 ⇒ 之后的每一个随机都错位，而**局面看起来一模一样** —— 正是这一条把它钉住。
        let mut run = run();
        let before = run_hash_hex(&run).expect("hash");
        // 走一次真实的随机：`Potion` 那条流推进一步，其余六条不动。
        let mut rng = *run.rng();
        rng.draw(RunStream::Potion);
        run.replace_rng(rng);
        let after = run_hash_hex(&run).expect("hash");
        assert_ne!(before, after, "a draw that does not move the hash is a draw nobody records");
    }

    /// §170 `P1-4`: **量一遍最大合法局的规范文本**，而不是假设它装得下。
    ///
    /// 之前只有 `the_text_is_canonical_and_not_truncated`，用的是 `run()` 的 10 张牌 —— 那证明不了
    /// "一局真实的后盘会不会撑爆 8 KiB"。这里量的是**类型的上限**：每个牌位都放 `ID_CAP` 长的 id，
    /// 遗物/药水拉满、金币 `i32::MAX`、Ascension 20。内容以后怎么改都超不过这个数。
    ///
    /// **实测（2026-11-01）：4186 B / 8192 B = 51%**。所以"最大合法局装得下"是成立的，但**没有
    /// 两倍余量**（真实余量 1.96 倍）—— 我不能写一个自己都不成立的判据。这里钉的是：
    ///
    /// 1. 装得下（这正是 `run_hash` 返回 `None` 的唯一原因，也是 P1-4 的问题）；
    /// 2. 至少 **1.5 倍**余量；
    /// 3. 那份文本确实"很大"（> 4 KiB），否则这条测试可能只是在量一副 10 张牌。
    ///
    /// 以及一个必须写下来的事实：文本的约 90% 是 id 文本（60 张牌 + 24 遗物 + 5 药水）。
    /// **把 `MAX_RUN_DECK` 或遗物容量翻倍，就会溢出。** 那时 `run_hash` 返回 `None`，
    /// 而 `rd-wasm` 会**响亮拒绝**导出与回放（§170 `P1-4` 的另一半），不会拿 0 顶替。
    #[test]
    fn the_largest_legal_run_fits_the_hash_buffer() {
        let widest_card = "z".repeat(rd_core::state::ID_CAP);
        let widest_relic = "z".repeat(rd_core::state::ID_CAP);
        let widest_potion = "z".repeat(rd_core::state::ID_CAP);
        let deck: Vec<&str> = std::vec![widest_card.as_str(); crate::state::MAX_RUN_DECK];
        let state = big_run(&deck, &widest_relic, &widest_potion);

        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, &state);
        assert!(
            !writer.overflowed(),
            "the largest legal run did not fit {MAX_TEXT} B -- `run_hash` would return None"
        );
        let len = writer.as_str().len();
        let percent = (len * 100) / MAX_TEXT;
        println!("largest legal canonical text: {len} B of {MAX_TEXT} B ({percent}%)");
        // 2. 至少 1.5 倍余量（实测 1.96 倍；写 2 倍就会红，那是我一开始想当然的判据）。
        assert!(
            len * 3 / 2 < MAX_TEXT,
            "the largest legal run uses {len} of {MAX_TEXT} B ({percent}%): under 1.5x headroom"
        );
        // 3. 这条测试确实在量一个大局面，而不是 `run()` 那副 10 张牌。
        assert!(len > MAX_TEXT / 2, "only {len} B: this is not the maximal state");
    }

    /// 一局"尽可能大"的合法局面：满牌组、满遗物、满药水、金币拉满、Ascension 20。
    ///
    /// 商店/奖励屏在这个状态里是空的（它们由进入节点时生成，单测够不到），所以这个数字是**下界**；
    /// 两倍余量的判据就是替它们、以及替后续内容留的。
    fn big_run(deck: &[&str], relic: &str, potion: &str) -> RunState {
        let mut state = RunState::new_with_ascension(
            i32::MAX - 1,
            999,
            i32::MAX,
            deck,
            crate::state::MAX_ASCENSION,
        )
        .expect("a maximal run");
        state.adjust_gold(i32::MAX);
        for _ in 0..crate::state::MAX_RUN_RELICS {
            let _ = state.push_relic(relic);
        }
        for _ in 0..crate::state::MAX_RUN_POTIONS {
            let _ = state.push_potion(potion);
        }
        state
    }

    #[test]
    fn the_text_is_canonical_and_not_truncated() {
        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, &run());
        assert!(!writer.overflowed(), "{} bytes did not fit", MAX_TEXT);
        let text = writer.as_str();
        assert!(text.starts_with("seed=7\n"), "{}", &text[..24.min(text.len())]);
        assert!(text.contains("rng1="), "every stream has a line");
        assert!(text.contains("map_rows=15"), "the map is written");
        // 行数是个便宜的"没有半行"判据。
        assert!(text.lines().count() > 100, "{} lines", text.lines().count());
    }
}
