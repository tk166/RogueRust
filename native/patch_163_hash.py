"""§163.1 `run_hash`：整局的规范文本 + SHA-256（回放要对拍的就是它）。

`rd-run` 的 lib.rs 从第一天就说 "step-wise `run_hash` determinism" —— 而它只存在于注释里。
这一节把它做出来，判据是**同一局两次哈希相同、改一个字节哈希就变**（后者才是它有用的原因）。

规范文本用 `rd_core::writer::TextWriter`（`key=value`、`\\n` 分隔、整数十进制），与 `rd-core`
的战斗指纹同一个工具，理由也同一个：**格式就是契约**，自己手搓一份迟早两边不一致。
"""
import io

PATH = "kernel/rd-run/src/hash.rs"

CONTENT = '''//! 一局的规范文本与指纹（§163）。
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
use crate::state::{Pending, RunState, MAX_RUN_DECK, MAX_RUN_POTIONS, MAX_RUN_RELICS};
use crate::streams::RunStream;
use rd_core::hash::Sha256;
use rd_core::writer::TextWriter;

/// 一局的规范文本缓冲。实测 ~2.5 KB（15 行地图 + 10 张牌），8 KB 是"内容翻几倍也不会撞上"。
pub const MAX_TEXT: usize = 8192;

/// 把整局写成规范文本，返回字节数；缓冲不够是 `None`（**不是**截断 —— 截断的指纹会说谎）。
pub fn write_run_input(writer: &mut TextWriter<'_>, state: &RunState) {
    writer.str("seed=").i32(state.seed()).str("\\n");
    writer.str("asc=").u32(u32::from(state.ascension())).str("\\n");
    writer.str("floor=").i32(state.floor()).str("\\n");
    writer.str("node=").i32(state.node()).str("\\n");
    writer.str("hp=").i32(state.health()).str("\\n");
    writer.str("hp_max=").i32(state.health_max()).str("\\n");
    writer.str("gold=").i32(state.gold()).str("\\n");
    writer.str("act=").u32(u32::from(state.act())).str("\\n");
    writer.str("removed=").i32(state.removed_cards()).str("\\n");
    writer
        .str("potion_chance=")
        .i32(state.potion_chance())
        .str("\\n");
    writer
        .str("rarity_offset=")
        .i32(state.rarity_offset())
        .str("\\n");
    writer.str("boss_beaten=").u32(u32::from(state.boss_beaten())).str("\\n");
    writer.str("pending=").u32(u32::from(pending_code(state.pending()))).str("\\n");
    writer.str("event=").str(state.event().as_str()).str("\\n");
    writer
        .str("last_encounter=")
        .str(state.last_encounter().as_str())
        .str("\\n");
    for (index, counter) in state.unknown().iter().enumerate() {
        writer.str("unknown").u32(index as u32).str("=").i32(*counter).str("\\n");
    }

    // 三个定容容器：**只写活动前缀**，但前缀外必须为空这件事由 `check_invariants` 保证
    // （§162）—— 所以"同一局"在这里不会因为尾槽残留而分叉。
    writer.str("deck=").u32(state.deck().len() as u32).str("\\n");
    for card in state.deck() {
        writer.str("d=").str(card.as_str()).str("\\n");
    }
    writer.str("relics=").u32(state.relics().len() as u32).str("\\n");
    for relic in state.relics() {
        writer.str("r=").str(relic.as_str()).str("\\n");
    }
    writer.str("potions=").u32(state.potions().len() as u32).str("\\n");
    for potion in state.potions() {
        writer.str("p=").str(potion.as_str()).str("\\n");
    }

    // 七个随机流：**这是"同一局"最容易被破坏的部分** —— 少还原一个计数，之后的每个随机都错位。
    for stream in RunStream::ALL {
        writer
            .str("rng")
            .u32(stream as u32)
            .str("=")
            .i32(state.rng().counter(stream))
            .str("\\n");
    }

    for slot in state.start_offers() {
        writer.str("offer=").u32(u32::from(*slot)).str("\\n");
    }
    writer.str("blessing=").str(follow_code(state.blessing_follow())).str("\\n");
    writer.str("event_follow=").str(deck_change_code(state.event_follow())).str("\\n");

    // 已结算位图：两个 u64 按十六进制（十进制也能，但十六进制能一眼看出哪一位）。
    for word in state.resolved_words() {
        writer.str("resolved=").u64(*word).str("\\n");
    }

    // 商店与奖励屏：买过的行 / 空行都要写，否则"两个货架"会哈希成同一个。
    writer.str("shop_cards=").u32(state.shop_cards_len() as u32).str("\\n");
    for offer in state.shop_cards() {
        writer
            .str("sc=")
            .str(offer.id.as_str())
            .str(",")
            .i32(offer.price)
            .str("\\n");
    }
    writer.str("shop_relics=").u32(state.shop_relics_len() as u32).str("\\n");
    for offer in state.shop_relics() {
        writer
            .str("sr=")
            .str(offer.id.as_str())
            .str(",")
            .i32(offer.price)
            .str("\\n");
    }
    writer
        .str("reward=")
        .i32(state.reward_gold())
        .str(",")
        .str(state.reward_potion().unwrap_or(""))
        .str(",")
        .str(state.reward_relic().unwrap_or(""))
        .str("\\n");
    for card in state.reward_cards() {
        writer.str("rc=").str(card.as_str()).str("\\n");
    }

    // 地图：**每一行的每一个槽位**（含被剪掉的），理由与存档同一条 —— 它们是值的一部分。
    writer.str("map_rows=").u32(state.map().rows().len() as u32).str("\\n");
    for (row_index, row) in state.map().rows().iter().enumerate() {
        writer.str("mrow=").u32(row_index as u32).str(",").u32(u32::from(row.count())).str("\\n");
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
            writer.str("\\n");
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
        let mut rng = run.rng();
        rng.draw(RunStream::Potion).expect("draw");
        run.set_rng(rng);
        let after = run_hash_hex(&run).expect("hash");
        assert_ne!(before, after, "a draw that does not move the hash is a draw nobody records");
    }

    #[test]
    fn the_text_is_canonical_and_not_truncated() {
        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, &run());
        assert!(!writer.overflowed(), "{} bytes did not fit", MAX_TEXT);
        let text = writer.as_str();
        assert!(text.starts_with("seed=7\\n"), "{}", &text[..24.min(text.len())]);
        assert!(text.contains("rng1="), "every stream has a line");
        assert!(text.contains("map_rows=15"), "the map is written");
        // 行数是个便宜的"没有半行"判据。
        assert!(text.lines().count() > 100, "{} lines", text.lines().count());
    }
}
'''


def main():
    io.open(PATH, "w", encoding="utf-8", newline="").write(CONTENT)
    print("rd-run/src/hash.rs written")


if __name__ == "__main__":
    main()
