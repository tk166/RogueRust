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
use crate::state::{Pending, PoolCard, RunMark, RunState};
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
    // §259：新的**运行期状态**必须进指纹，否则"两局只差一次 Lift"会哈希相同。
    writer.str("girya=").i32(i32::from(state.girya_lifts())).str("\n");
    writer
        .str("ruby=")
        .i32(i32::from(state.ruby_key()))
        .str("\n");
    writer
        .str("potion_chance=")
        .i32(state.potion_chance())
        .str("\n");
    writer
        .str("rarity_offset=")
        .i32(state.rarity_offset())
        .str("\n");
    // §270：两件遗物各自的**计数器**。不进指纹的话，"`omamori` 还剩 1 次"与"还剩 2 次"、
    // "`maw_bank` 已经失效"与"还有效"都会哈希相同 —— 而那正是两条规则的**全部**区别。
    writer
        .str("omamori=")
        .u32(u32::from(state.omamori_charges()))
        .str("\n");
    writer
        .str("maw_bank=")
        .u32(u32::from(state.maw_bank_broken()))
        .str("\n");
    // §303：`wing_boots` 还能飞几次（它会改变后面每一次 `reachable()`）。
    writer
        .str("wb=")
        .u32(u32::from(state.wing_boots_left()))
        .str("\n");
    // §301：已经打过几场 —— `neows_lament` 的"前 3 场"就靠这个数。
    writer
        // §343：这家店的删卡服务用掉没有。它是**可观察**的（"删一张牌"按钮灰了），
        // 而且它决定下一步的合法动作集 ⇒ 必须进指纹。
        .str("removal_used=")
        .u32(u32::from(state.removed_this_shop))
        // §344：幕尽（G2）。它一旦成立这一局就结束了，所以它决定下一步的合法动作集。
        .str("ended_out_of_map=")
        .u32(u32::from(state.ended_out_of_map))
        .str("fights=")
        .u32(u32::from(state.fights()))
        .str("\n");
    // §271：`ancient_tea_set` 欠着的那一场（进篝火之后、下一场战斗之前）。
    writer
        .str("tea_set=")
        .u32(u32::from(state.tea_set_pending()))
        .str("\n");
    // §272：`?` 房的分流结果与 `tiny_chest` 的计数。
    // 结果**必须**进指纹：它决定"这一格开事件还是开一场战斗"，是两局之间真实的行为差异。
    writer
        .str("unknown_room=")
        .u32(u32::from(state.unknown_room() as u8))
        .str("\n");
    writer
        .str("tiny_chest=")
        .u32(u32::from(state.tiny_chest_rooms()))
        .str("\n");
    // §274：拾取时欠着的牌组编辑（`empty_cage` / `astrolabe`）。不进指纹的话，
    // "还欠 2 次"与"还欠 1 次"会哈希相同 —— 而那正是这两件遗物的全部区别。
    writer
        .str("pickup=")
        .str(deck_change_code(state.pickup_change()))
        .str("/")
        .u32(u32::from(state.pickup_picks()))
        .str("\n");
    // §293：欠着的"加牌"次数与**这一手是哪三张**。后者也要进：同一局、同一个欠账次数，
    // 换一手候选就是换了一次选择（而"挑到哪张"决定牌组）。
    writer
        .str("pickup_add=")
        .u32(u32::from(state.pickup_add()))
        .str("/")
        .u32(state.pickup_offer().len() as u32)
        .str("/");
    for card in state.pickup_offer() {
        writer.str(card.as_str()).str(",");
    }
    writer.str("\n");
    writer.str("boss_beaten=").u32(u32::from(state.boss_beaten())).str("\n");
    writer.str("pending=").u32(u32::from(pending_code(state.pending()))).str("\n");
    // `RunId` **就是** `Ident<CAP>`，所以 `event()` 已经是 `&str`（再 `.as_str()` 会掉进
    // `str_as_str` 那个不稳定 feature）。
    writer.str("event=").str(state.event()).str("\n");
    // §278：事件的**第几段**。同一句 `event=golden_idol` 可以是两个完全不同的屏幕
    // （"拿走神像" vs "巨石追来，三选一"），而只有这一段文字能把它俩分开。
    writer.str("event_step=").str(state.event_step()).str("\n");
    // §331：事件掷出的遗物候选。它决定"点哪个按钮会失去哪件遗物"，所以是**会改变以后**的事实。
    // §332：商店四排（价格也是事实：打折/加价都改"以后会怎样"）。
    for (label, offers) in [
        ("shop_cards", state.shop.cards()),
        ("shop_colorless", state.shop.colorless()),
        ("shop_potions", state.shop.potions()),
        ("shop_relics", state.shop.relics()),
    ] {
        writer.str(label).str("=");
        for offer in offers {
            writer.str(offer.id.as_str()).str(":").u32(offer.price as u32).str(",");
        }
        writer.str("\n");
    }
    writer.str("event_relics=");
    for slot in 0..usize::from(state.event_relic_offer_len) {
        writer.str(state.event_relic_offer_ids[slot].as_str()).str(",");
    }
    writer.str("\n");
    // ══ §308：审阅报告 §2 的另一半 —— 上面那些字段进了存档，**也必须进指纹**。
    // 理由只有一个：它们都改变"以后会怎样"。`Ritual Dagger` 的成长尤其明显：
    // 不入指纹的话，"同一串动作"能长出两种牌组（伤害不同、哈希相同），
    // 而回放判据正是"同一串动作 ⇒ 同一局"。
    writer.str("bosses_fought=").u32(u32::from(state.bosses_fought())).str("\n");
    // §308：地图生成失败是个**行为差异**（没有地图可走），而"空白地图"不是它唯一的证据。
    writer
        .str("map_failed=")
        .u32(u32::from(state.map_generation_failed()))
        .str("\n");
    // §303：`wing_boots` 已经飞过几次。派生值 `wing_boots_left()` 已经进指纹，但**用过的次数**
    // 是它自己的事实（`wing_boots` 丢掉再捡回来会重置），所以两个都写。
    writer
        .str("wb_used=")
        .u32(u32::from(state.wing_boots_used()))
        .str("\n");
    writer
        .str("chest=")
        .u32(u32::from(state.chest_extra_remaining()))
        .str("/")
        .u32(u32::from(state.chest_empty_remaining()))
        .str("\n");
    writer
        .str("pickup_owed=")
        .u32(u32::from(state.pickup_relics()))
        .str("/")
        .u32(u32::from(state.pickup_potions()))
        .str("\n");
    writer.str("event_resume=").str(state.event_resume().as_str()).str("\n");
    writer.str("event_next=").str(state.event_next().as_str()).str("\n");
    writer
        .str("event_fight=")
        .u32(u32::from(state.event_fight()))
        .str("/")
        .str(state.event_fight_pool())
        .str("\n");
    writer
        .str("fight_next=")
        .i32(i32::from(state.fight_gold_bonus()))
        .str("/")
        .i32(i32::from(state.fight_gold_set()))
        .str("/")
        .u32(u32::from(state.fight_relic_rarity()))
        .str("/")
        .u32(u32::from(state.fight_extra_relic()))
        .str("/")
        .u32(u32::from(state.fight_potion_chance()))
        .str("/")
        .str(state.fight_relic().as_str())
        .str("/")
        .u32(u32::from(u8::from(state.fight_no_relic())))
        .str("\n");
    // 每副本 mark：与 `deck` 同下标，**只写有值的那几格**（`Ritual Dagger` 在一局里通常只有一格）。
    // 带下标是必须的："第 3 张有 5 点成长"与"第 7 张有 5 点成长"是两局。空数组时这一行是
    // `marks=0` —— 于是"没有 mark"与"mark 全被清掉"仍然是同一局（清掉就是没有）。
    writer.str("marks=").u32(state.marks().iter().filter(|m| !m.is_none()).count() as u32);
    writer.str("\n");
    for (index, mark) in state.marks().iter().enumerate() {
        if mark.is_none() {
            continue;
        }
        writer
            .str("m")
            .u32(index as u32)
            .str("=")
            .str(mark.key.as_str())
            .str(",")
            .i32(mark.value)
            .str("\n");
    }
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
    writer
        .str("boss_relic_offer_len=")
        .u32(state.boss_relic_offer().len() as u32)
        .str("\n");
    for relic in state.boss_relic_offer() {
        writer.str("bo=").str(relic.as_str()).str("\n");
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
    // §320：事件候选列表。**不写**会让"同一局的两条分支"（20 选 1 的不同候选）哈希成同一串 ——
    // 而候选是玩家看得见的局面（选哪张由它决定）。
    writer.str("event_offer=").u32(state.event_offer_len() as u32).str("\n");
    for slot in 0..state.event_offer_len() {
        writer.str("of=").str(state.event_offer_card(slot).unwrap_or("")).str("\n");
    }

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
        // §320：候选列表（`The Library` / `Sensory Stone`）。
        Pending::EventOffer => 9,
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
        // §274：`astrolabe` 用得到它（恩惠里目前不用，但映射要穷尽 —— 这是编译器的闸门）。
        Some(crate::state::BlessingFollowUp::Deck(
            crate::state::DeckChange::TransformAndUpgrade,
        )) => "transform_and_upgrade",
        // §292：`dollys_mirror`（恩惠目前不用它，映射要穷尽 —— 编译器的闸门）。
        Some(crate::state::BlessingFollowUp::Deck(crate::state::DeckChange::Duplicate)) => {
            "duplicate"
        }
    }
}

fn deck_change_code(change: Option<crate::state::DeckChange>) -> &'static str {
    match change {
        None => "none",
        Some(crate::state::DeckChange::Remove) => "remove",
        Some(crate::state::DeckChange::Upgrade) => "upgrade",
        Some(crate::state::DeckChange::Transform) => "transform",
        Some(crate::state::DeckChange::TransformAndUpgrade) => "transform_and_upgrade",
        Some(crate::state::DeckChange::Duplicate) => "duplicate",
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
        probe.push_card(PoolCard::plain("anger")).expect("deck room");
        probes.push(("deck", probe));
        let mut probe = run();
        probe.push_relic("anchor", &[]).expect("relic room");
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

    /// §170 `P1-4` / §172：**量一遍能从真实内容到达的最大局**，并且**证明夹具就是它自称的那个**。
    ///
    /// 第一版这条测试是错的（外部评审 §P1-1 抓到）：它用 `let _ = state.push_relic(...)` 循环 24 次，
    /// 而 `push_relic` 对手写规则表之外的 id 返回 `UnsupportedRelic` —— 24 次**全部失败**，一件遗物
    /// 都没进去；又在 Ascension 20 上塞 5 瓶药水，而那等级只有 2 个槽。它于是报出一个**看起来像上界**
    /// 的数字（4186 B），实际只是一个残缺夹具的测量值。
    ///
    /// 现在：
    /// * 每一次 `push_*` 都 `expect`，静默拒绝会**让测试红**而不是让夹具变小；
    /// * 测量之前先断言元素个数（牌 60、遗物 = 镜像里全部、药水 = 腰带容量），"夹具就是它自称的
    ///   那个"本身就是一条判据；
    /// * id 取自**内容镜像**（与 `rd-wasm` 嵌入的是同一份），所以量的是"**内容可达**的最大局"。
    ///
    /// **这条测试证明不了的事，写在这里**：*结构*上界比它大 —— 遗物 id 只要不超过 `ID_CAP` 就能存进
    /// `RunId`，但 `push_relic` 只接受手写规则表里的 id，所以那个状态**用公开 API 构造不出来**，
    /// 这里也就不测。保护那种情况的是 §171 的**响亮拒绝**（`hash_failed`），不是这条测量。
    #[test]
    fn the_largest_run_reachable_from_the_content_fits_the_hash_buffer() {
        let image = read_core_image();
        let content = rd_core::content::Content::parse(&image).expect("the content image");

        // 镜像里最长的卡 / 药水 / 每件遗物：**从表里取**，不抄字符串，也不走 `IDX`
        // （`IDX` 不含每种实体 —— 药水与事件各有自己的列表，见 `Table::from_entity_kind`）。
        let mut longest_card = "";
        let mut index = 0u32;
        while let Some(row) = content.row(rd_core::content::Table::Card, index) {
            if let Some(card) = rd_core::content::CardRow::new(row) {
                if let Some(id) = content.string(card.id()) {
                    if id.len() > longest_card.len() {
                        longest_card = id;
                    }
                }
            }
            index += 1;
        }

        let mut longest_potion = "";
        for index in 0..content.potion_count() {
            let Some(potion) = content.potion(index) else {
                continue;
            };
            if potion.id.len() > longest_potion.len() {
                longest_potion = potion.id;
            }
        }

        let mut relics: std::vec::Vec<&str> = std::vec::Vec::new();
        let mut index = 0u32;
        while let Some(row) = content.row(rd_core::content::Table::Relic, index) {
            if let Some(relic) = rd_core::content::RelRow::new(row) {
                if let Some(id) = content.string(relic.id()) {
                    if RunState::relic_effect(id).is_some() && !relics.contains(&id) {
                        relics.push(id);
                    }
                }
            }
            index += 1;
        }

        assert!(!longest_card.is_empty(), "no card in the image");
        assert!(!longest_potion.is_empty(), "no potion in the image");
        assert!(!relics.is_empty(), "no relic in the image that the rule table knows");

        // 两个口径，分开量、分开断言 —— 这正是评审要求的"不要把两者混用"。
        let padded_card = "z".repeat(rd_core::state::ID_CAP);
        let padded_potion = "z".repeat(rd_core::state::ID_CAP);
        let reachable = measure(&build(&relics, longest_card, longest_potion));
        let represented = measure(&build(&relics, &padded_card, &padded_potion));

        // 实测（2026-11-02，内容 sts 镜像）：reachable 2815 B（34%），representable 4495 B（55%）。
        // ⇒ **两倍余量不成立**（4495 × 2 > 8192），真实余量 1.82 倍，所以判据取 1.5 倍。
        // 把这条线写成"两倍"就是拿一个更好听的数字换掉一个真的数字。
        println!(
            "reachable (ids from the image): {reachable} B of {MAX_TEXT} B · \
             representable (deck/potions padded to ID_CAP): {represented} B"
        );
        for (label, len) in [("reachable", reachable), ("representable", represented)] {
            let percent = (len * 100) / MAX_TEXT;
            assert!(
                len * 3 / 2 < MAX_TEXT,
                "the {label} maximum uses {len} of {MAX_TEXT} B ({percent}%): under 1.5x headroom"
            );
        }
        // 这两条是"测试真的在量大局面"的判据 —— 第一版把它标定在坏夹具的数字上（> 4096），
        // 那是拿错答案校准的尺子。现在它只说"比 `run()` 那副 10 张牌大得多"。
        assert!(reachable > 2_000, "only {reachable} B: this is not the large state");
        assert!(
            represented > reachable,
            "padding the ids to ID_CAP must make the text longer ({represented} vs {reachable})"
        );
    }

    /// 一局"尽可能满"的局面：满牌组、镜像里**每一件**遗物、药水塞到槽满。
    ///
    /// Ascension 0 on purpose: A11 takes a slot away and the belt only gives two back —— 上界要的是
    /// **尽可能多**的槽，不是"最难的等级"。每一次 push 都 `expect`：静默拒绝会**让测试红**，
    /// 而不是让夹具悄悄变小（这正是上一版出错的形状）。
    fn build(relics: &[&str], card: &str, potion: &str) -> RunState {
        let deck: std::vec::Vec<&str> = std::vec![card; crate::state::MAX_RUN_DECK];
        let mut state =
            RunState::new_with_ascension(7, 80, i32::MAX, &deck, 0).expect("a maximal run");
        // §260: push **as many as fit**. The fixture is "a run as full as the capacity allows",
        // not "a run holding every relic in the image" -- the latter turns every content batch into
        // a red fixture, and the failure it produces (`Capacity`) is about the *fixture*, not about
        // the hash. The `assert_eq!` below still pins that the belt ended up exactly full.
        let take = relics.len().min(crate::state::MAX_RUN_RELICS);
        for relic in &relics[..take] {
            state
                .push_relic(relic, &[])
                .unwrap_or_else(|error| panic!("pushing relic {relic} must work: {error:?}"));
        }
        let slots = usize::from(state.potion_slots());
        for slot in 0..slots {
            state
                .push_potion(potion)
                .unwrap_or_else(|error| panic!("pushing potion {slot} must work: {error:?}"));
        }
        // 夹具就是它自称的那个 —— 这三条是这次修复的核心。
        assert_eq!(state.deck().len(), crate::state::MAX_RUN_DECK, "the deck is not full");
        assert_eq!(
            state.relics().len(),
            relics.len().min(crate::state::MAX_RUN_RELICS),
            "a relic push was refused"
        );
        assert_eq!(state.potions().len(), slots, "a potion push was refused");
        state
    }

    /// 规范文本的长度（顺带断言没溢出）。
    fn measure(state: &RunState) -> usize {
        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, state);
        assert!(!writer.overflowed(), "the text did not fit {MAX_TEXT} B");
        writer.as_str().len()
    }

    /// 内容镜像：与 `rd-wasm` 嵌入的是同一份（`tools/contentc/packages/sts/out/content.sts.rdcf`）。
    fn read_core_image() -> std::vec::Vec<u8> {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tools/contentc/packages/sts/out/content.sts.rdcf");
        std::fs::read(&path).unwrap_or_else(|error| {
            panic!(
                "内容镜像读不到：{}\n  {error}\n  它是 tools/contentc 的构建产物：\n                     python tools/contentc/compile.py\n  （`rd-wasm` 嵌入的就是这一份）",
                path.display()
            )
        })
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

    /// §308：**同一个动作序列、只有某一张牌的成长不同** ⇒ 指纹必须不同。
    ///
    /// 这是审阅报告的最小复现 #5。`Ritual Dagger` 的"永久成长"是跨战斗的（`RunMark`），
    /// 不进指纹的话，回放判据"同一串动作 ⇒ 同一局"就漏掉了整张牌的伤害。
    #[test]
    fn a_per_copy_mark_is_visible_in_the_fingerprint() {
        let mut run = RunState::new_with_ascension(7, 80, 99, &["strike", "bash"], 0)
            .expect("a run");
        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, &run);
        let first = writer.as_str().to_owned();
        run.set_mark(0, "standard.ritual_dagger_bonus", 3).expect("slot 0");
        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, &run);
        let second = writer.as_str().to_owned();
        assert_ne!(first, second, "a mark must change the fingerprint");
        // 值不同也算不同局：键一样、值不一样同样是"那张牌不一样"。
        run.set_mark(0, "standard.ritual_dagger_bonus", 6).expect("slot 0");
        let mut buffer = [0u8; MAX_TEXT];
        let mut writer = TextWriter::new(&mut buffer);
        write_run_input(&mut writer, &run);
        let third = writer.as_str().to_owned();
        assert_ne!(second, third, "a different mark value is a different run");
    }
}
