"""§274 判据：拾取类 7 件。

每组两面：该生效的生效、**不该生效的不动**。特别是：
* `war_paint` 不碰 Attack（那是 `whetstone` 的活），反之亦然；
* 已经升级过的牌**不吃名额**（否则"随机升级 2 张"会悄悄变成"升 1 张"）；
* `pandoras_box` 只动 Strike/Defend，不动别的牌；
* `astrolabe` / `empty_cage` **不碰 `pending`**（那正是它们能叠在奖励屏上的原因）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
ANCHOR = '''    /// §273：`?` 房掷出商人 ⇒ 与商店节点**同一条**进门路径'''

TESTS = r'''    /// §274：`old_coin` / `lee's_waffle` —— 两件"改数字"的拾取。
    #[test]
    fn the_pickup_number_relics_change_only_their_own_number() {
        // ---- `old_coin`：+300 金币。
        let mut run = ironclad();
        let gold = run.gold();
        run.push_relic("old_coin", &TYPED_CARDS).expect("old_coin");
        assert_eq!(run.gold(), gold + 300, "old_coin: +300 gold on pickup");

        // 与 `ectoplasm` 一起：金币被拦 ⇒ 一分不给（"gain Gold" 那条规则只有一处）。
        let mut blocked = ironclad();
        blocked.push_relic("ectoplasm", &TYPED_CARDS).expect("ectoplasm");
        let gold = blocked.gold();
        blocked.push_relic("old_coin", &TYPED_CARDS).expect("old_coin");
        assert_eq!(blocked.gold(), gold, "ectoplasm blocks the coin's gold too");

        // ---- `lee's_waffle`：上限 +7 **且回满**（不是"回 7 点"）。
        let mut run = ironclad();
        run.adjust_health(-50);
        let max_before = run.health_max();
        assert!(run.health() < max_before - 20, "the hero must be hurt for this to mean anything");
        run.push_relic("lee's_waffle", &TYPED_CARDS).expect("lee's_waffle");
        assert_eq!(run.health_max(), max_before + 7, "lee's_waffle: +7 max HP");
        assert_eq!(run.health(), run.health_max(), "…and heal **all** of it");
    }

    /// §274：`war_paint` / `whetstone` —— 随机升级 2 张**自己那一类**的牌。
    #[test]
    fn the_upgrade_eggs_upgrade_two_of_their_own_kind() {
        // 池子里给足"可升的攻击/技能"，并让它们都有 `+` 行。
        const POOL: [PoolCard<'static>; 6] = [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: Some("strike+") },
            PoolCard { id: "bash", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: Some("bash+") },
            PoolCard { id: "anger", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: Some("anger+") },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Skill, upgraded: Some("defend+") },
            PoolCard { id: "flex", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: Some("flex+") },
            PoolCard { id: "clash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: Some("clash+") },
        ];
        let attacks = |run: &RunState| {
            run.deck()
                .iter()
                .filter(|id| {
                    let base = id.as_str().trim_end_matches('+');
                    POOL.iter().any(|c| c.id == base && c.kind == CardKind::Attack)
                })
                .filter(|id| id.as_str().ends_with('+'))
                .count()
        };
        let skills = |run: &RunState| {
            run.deck()
                .iter()
                .filter(|id| {
                    let base = id.as_str().trim_end_matches('+');
                    POOL.iter().any(|c| c.id == base && c.kind == CardKind::Skill)
                })
                .filter(|id| id.as_str().ends_with('+'))
                .count()
        };

        // ---- `whetstone`：攻击牌 +2，**技能一张都不动**。
        let mut run = RunState::new(11, 80, i32::MAX, &["strike", "strike", "strike", "defend", "defend"]).expect("a run");
        run.push_relic("whetstone", &POOL).expect("whetstone");
        assert_eq!(attacks(&run), 2, "whetstone upgrades exactly 2 Attacks");
        assert_eq!(skills(&run), 0, "…and no Skills (that is war_paint's job)");

        // ---- `war_paint`：技能牌 +2，攻击不动。
        let mut run = RunState::new(11, 80, i32::MAX, &["strike", "strike", "defend", "defend", "defend"]).expect("a run");
        run.push_relic("war_paint", &POOL).expect("war_paint");
        assert_eq!(skills(&run), 2, "war_paint upgrades exactly 2 Skills");
        assert_eq!(attacks(&run), 0, "…and no Attacks");

        // ---- 只有 1 张可升时只升 1 张（"2 张"不是硬指标）。
        let mut run = RunState::new(11, 80, i32::MAX, &["strike", "defend", "defend", "defend", "defend"]).expect("a run");
        run.push_relic("whetstone", &POOL).expect("whetstone");
        assert_eq!(attacks(&run), 1, "with one Attack the relic upgrades one");

        // ---- 已经升级过的牌**不吃名额**：牌组全是 `strike+` ⇒ 一张都不再加。
        let mut run = RunState::new(11, 80, i32::MAX, &["strike+", "strike+", "defend"]).expect("a run");
        let before: Vec<RunId> = run.deck().to_vec();
        run.push_relic("whetstone", &POOL).expect("whetstone");
        assert_eq!(run.deck(), &before[..], "nothing to upgrade ⇒ the deck is untouched");
    }

    /// §274：`pandoras_box` —— 把**所有** Strike / Defend 改造掉，**别的牌不动**。
    #[test]
    fn pandoras_box_transforms_every_staple_and_nothing_else() {
        const POOL: [PoolCard<'static>; 3] = [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: Some("strike+") },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Skill, upgraded: Some("defend+") },
            // 改造的**来源**：内容里能抽出什么。`bash` 不是 Strike/Defend，所以它只会**出现**
            // 在结果里，不会被当成目标。
            PoolCard { id: "bash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: Some("bash+") },
        ];
        let mut run = RunState::new(7, 80, i32::MAX, &["strike", "strike", "defend", "bash", "clash"]).expect("a run");
        run.push_relic("pandoras_box", &POOL).expect("pandoras_box");
        let deck: Vec<&str> = run.deck().iter().map(RunId::as_str).collect();
        assert_eq!(deck.len(), 5, "transform replaces, it does not remove");
        assert!(
            !deck.iter().any(|id| *id == "strike" || *id == "defend"),
            "every Strike and Defend is gone: {deck:?}"
        );
        assert_eq!(
            deck.iter().filter(|id| **id == "bash").count(),
            1,
            "a non-staple card is not transformed"
        );
        assert_eq!(
            deck.iter().filter(|id| **id == "clash").count(),
            1,
            "…and neither is another one"
        );
    }

    /// §274：`astrolabe` / `empty_cage` —— 它们**欠着**牌组编辑，而不抢 `pending`。
    ///
    /// 这条判据钉的正是"叠在奖励屏上"的能力：拾取发生在 `Pending::Reward` 里，
    /// 拿完遗物之后那一屏必须**还在**（否则玩家会丢掉还没拿的卡牌奖励）。
    #[test]
    fn the_pickup_picks_do_not_take_over_the_screen() {
        // ---- `empty_cage`：欠 2 次"移除"。
        let mut run = ironclad();
        run.pending = Pending::Reward;
        run.push_relic("empty_cage", &TYPED_CARDS).expect("empty_cage");
        assert_eq!(run.pending(), Pending::Reward, "the screen behind must survive");
        assert_eq!(run.pickup_picks(), 2, "empty_cage owes two removals");
        assert_eq!(run.pickup_change(), Some(DeckChange::Remove));

        let before = run.deck().len();
        run.pickup_card(0, &TYPED_CARDS).expect("first removal");
        assert_eq!(run.deck().len(), before - 1);
        assert_eq!(run.pickup_picks(), 1, "one left");
        assert_eq!(run.pending(), Pending::Reward, "still not touching the screen");
        run.pickup_card(0, &TYPED_CARDS).expect("second removal");
        assert_eq!(run.deck().len(), before - 2);
        assert_eq!(run.pickup_picks(), 0, "done");
        assert_eq!(run.pickup_change(), None, "and the debt is cleared");
        assert_eq!(run.pending(), Pending::Reward, "the reward screen is still there");

        // 拒绝不消耗额度：越界的下标不许把 `pickup_picks` 吃掉。
        let mut run = ironclad();
        run.push_relic("empty_cage", &TYPED_CARDS).expect("empty_cage");
        assert_eq!(
            run.pickup_card(99, &TYPED_CARDS),
            Err(RunError::BadCard(99u8)),
            "an out-of-range pick is refused"
        );
        assert_eq!(run.pickup_picks(), 2, "a refused pick must not spend the debt");

        // ---- `astrolabe`：欠 3 次"改造并升级"，而且**改造出来的那张被升级了**。
        const POOL: [PoolCard<'static>; 4] = [
            PoolCard { id: "strike", rarity: Rarity::Basic, kind: CardKind::Attack, upgraded: Some("strike+") },
            PoolCard { id: "defend", rarity: Rarity::Basic, kind: CardKind::Skill, upgraded: Some("defend+") },
            PoolCard { id: "bash", rarity: Rarity::Common, kind: CardKind::Attack, upgraded: Some("bash+") },
            PoolCard { id: "flex", rarity: Rarity::Common, kind: CardKind::Skill, upgraded: Some("flex+") },
        ];
        let mut run = RunState::new(7, 80, i32::MAX, &["strike", "strike", "defend", "bash", "clash"]).expect("a run");
        run.push_relic("astrolabe", &POOL).expect("astrolabe");
        assert_eq!(run.pickup_picks(), 3, "astrolabe owes three transforms");
        assert_eq!(run.pickup_change(), Some(DeckChange::TransformAndUpgrade));
        for _ in 0..3 {
            run.pickup_card(0, &POOL).expect("transform and upgrade");
        }
        assert_eq!(run.pickup_picks(), 0);
        let deck: Vec<&str> = run.deck().iter().map(RunId::as_str).collect();
        assert_eq!(deck.len(), 5, "transform keeps the count");
        // 前三张都被改造过 ⇒ 它们现在是 `bash`/`flex` 之一，而且**是升级版**。
        for id in &deck[..3] {
            assert!(
                id.ends_with('+'),
                "astrolabe upgrades what it transforms: {deck:?} (offender {id})"
            );
        }
    }

'''


def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_pickup_number_relics_change_only_their_own_number' not in src
    src = src.replace(ANCHOR, TESTS + ANCHOR)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src)
    print('§274 tests appended')


main()
