"""battle.rs: the regression for `HeroPlaysInstance` (§161.4).

Two copies of one definition, one of them carrying a per-copy price. The reference-shaped step
(`HeroPlays`, by definition) can only reach the first; the page needs the second, and the point of
the test is that the two steps are **observably different** rather than "both work".
"""
import io

PATH = "kernel/rd-core/src/battle.rs"

ANCHOR = """    fn health(state: &CombatState, who: &str) -> i32 {"""

TEST = '''    /// §161.4：**两份同定义副本，打的是哪一张**。
    ///
    /// `Step::HeroPlays` 是参考的形状（按定义找**第一张**，`ScenarioRunner.cs:109-111`），
    /// `Step::HeroPlaysInstance` 是页面需要的形状（按实例）。两者的差别只有在副本**可区分**时
    /// 才看得见 —— §161.4 的每副本价格是第一个让它可区分的东西，而差别本身是一个死按钮：
    /// 一张带折扣的 `paper_cut` 排在普通 `paper_cut` 后面时，玩家点了它，引擎打了前面那张。
    ///
    /// 所以这条测试**同时**钉住两半：按定义打第一张（照旧）、按实例打指定的那一张（新的）。
    #[test]
    fn the_by_instance_step_plays_the_named_copy_not_the_first_one() {
        let blob = core_image();
        let content = parse(&blob);
        let enemies = [PlanCombatant {
            id: "queue_imp",
            max_health: 40,
        }];
        let deck = [DeckEntry {
            card: "paper_cut",
            count: 12,
        }];
        let res = resources();
        let refill = refills();
        let plan = FightPlan {
            combat_id: "copy_pick_01",
            seed: 7,
            hero: PlanCombatant {
                id: "hero",
                max_health: 70,
            },
            enemies: &enemies,
            deck: &deck,
            cards_drawn_per_turn: CARDS_DRAWN_PER_TURN,
            shuffle_draw_pile_on_start: true,
            resources: &res,
            turn_start_refills: &refill,
        };
        let mut state = CombatState::new(CombatId::new("scratch").expect("短 id"), 0);
        build_fight(&mut state, &content, &plan).expect("蓝图与镜像必须一致");
        let hero = cid("hero");
        // Get a hand, then take the **last** card in it as "the one the player clicked".
        let mut host = Host::new(&content);
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            &content,
            &plan,
            &[Step::NextRound],
            &mut host,
            &mut out,
        )
        .expect("开一回合");
        let hand: Vec<CardInstanceId> = state
            .card_zones(&hero)
            .expect("牌区")
            .slots(CardZone::Hand)
            .iter()
            .filter_map(|raw| state.card(CardSlot::from_index(*raw)))
            .map(|card| card.id)
            .collect();
        assert!(hand.len() >= 2, "手牌至少两张才能谈\"哪一张\": {}", hand.len());
        let last = *hand.last().expect("非空");

        // 给**最后那张**挂一个 -1 的每副本价格（= 免费，`paper_cut` 印刷 1）。
        let (_, slot) = {
            let mut found = None;
            for zone in CardZone::ALL {
                for index in 0..state.card_zones(&hero).expect("牌区").count(zone) {
                    let Some(candidate) = state
                        .card_zones(&hero)
                        .expect("牌区")
                        .slot_at(zone, index)
                    else {
                        continue;
                    };
                    if state.card(candidate).map(|card| card.id) == Some(last) {
                        found = Some((zone, candidate));
                    }
                }
            }
            found.expect("最后那张还在牌区里")
        };
        state
            .card_mut(slot)
            .expect("卡在")
            .set_mark_counter(
                CounterId::new(crate::state::CARD_COST_DELTA_COUNTER).expect("短"),
                -1,
            )
            .expect("写价格");

        let energy = |s: &CombatState| {
            s.combatant(&hero)
                .expect("英雄")
                .resources()
                .iter()
                .find(|pool| pool.key.as_str() == "standard.energy")
                .map_or(-1, |pool| pool.pool.current)
        };
        let before = energy(&state);

        // 按**实例**打那一张 ⇒ 免费（价格生效），所以能量不变。
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            &content,
            &plan,
            &[Step::HeroPlaysInstance {
                card: last,
                target: Some("queue_imp"),
            }],
            &mut host,
            &mut out,
        )
        .expect("按实例打牌不该坏");
        assert_eq!(
            energy(&state),
            before,
            "打的是那张带折扣的副本：每副本价格必须生效"
        );
        assert_eq!(
            state.card_zones(&hero).expect("牌区").count(CardZone::Hand),
            hand.len() - 1,
            "手牌少一张"
        );

        // 反面：按**定义**打，拿的是手里第一张（普通价）⇒ 能量必须掉 1。
        let before = energy(&state);
        let mut out = FightOutcome::new();
        run_fight(
            &mut state,
            &content,
            &plan,
            &[Step::HeroPlays {
                card: "paper_cut",
                target: Some("queue_imp"),
            }],
            &mut host,
            &mut out,
        )
        .expect("按定义打牌不该坏");
        assert_eq!(
            energy(&state),
            before - 1,
            "按定义走的是**第一张**（没有折扣），所以照付 —— 两种 step 确实不同"
        );
    }

    fn health(state: &CombatState, who: &str) -> i32 {'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "fn the_by_instance_step_plays_the_named_copy_not_the_first_one" not in text, "already inserted"
    text = text.replace(ANCHOR, TEST)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("battle.rs: instance-step regression")


if __name__ == "__main__":
    main()
