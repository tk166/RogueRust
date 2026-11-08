"""§294 A1 判据：`DeckShuffled` 真的会在洗牌那一刻派发，两件遗物都吃得到。

判据在 `rd-core`（洗牌是内核的事）与 `rd-wasm`（遗物挂状态 + 真打一场）两层各一条：
* 内核层：洗牌 → `the_abacus` 的状态给 6 格挡；`sundial` 每第 3 次给 2 能量；
  **空弃牌堆不算洗过**（`sundial` 的"每 3 次"不能被空洗凑数）。
* wasm 层：遗物 → 开战挂状态 → 真洗一次 → 格挡/能量真的变了。
"""
import io

CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

TESTS = r'''
    /// §294：`DeckShuffled` —— 洗牌那一刻派发，`the_abacus` 与 `sundial` 都吃得到。
    ///
    /// 这条判据读的是**真实镜像**（`content.sts.rdcf`）：两件遗物的整条规则都是内容程序，
    /// 所以"内核有没有那条触发器"只能这样验 —— 抄一份程序到测试里就变成了第二份合同。
    #[test]
    fn the_deck_shuffled_trigger_pays_the_two_relics() {
        use crate::battle;
        use crate::state::{CardZone, CombatEvent};

        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = Content::parse(&bytes).expect("the image parses");

        // 两件遗物各自的状态必须**存在且只有一条 `DeckShuffled` 触发器** ——
        // 这一半钉住"内容真的把它们挂上去了"（与内容门的期望表互为第二意见）。
        for id in ["standard.the_abacus", "standard.sundial"] {
            let row = (0..content.status_count())
                .filter_map(|index| content.status(index))
                .find(|status| content.string(status.id()) == Some(id))
                .unwrap_or_else(|| panic!("`{id}` is in the image"));
            let triggers = crate::host::Host::new(&content)
                .triggers_of(id, &mut [crate::host::empty_trigger(&content); 4])
                .expect("the trigger decodes");
            assert!(triggers > 0, "`{id}` has a trigger");
            assert_eq!(
                content.string(row.id()),
                Some(id),
                "the row is the one we asked for"
            );
        }

        // 一场**真的**战斗：英雄牌组 10 张，第一回合抽 5 张 ⇒ 弃牌堆里放 2 张，
        // 然后直接调 `reshuffle_discard_into_draw`（三条洗牌路都经过它）。
        let deck = ["strike", "defend", "bash", "strike", "defend"];
        let mut heroes = [None; 4];
        heroes[0] = Some(battle::CombatantSpec {
            id: "hero",
            health: 80,
            statuses: &[],
        });
        let mut enemies = [None; 4];
        enemies[0] = Some(battle::CombatantSpec {
            id: "enemy",
            health: 44,
            statuses: &[],
        });
        let spec = battle::BattleSpec {
            seed: 7,
            heroes,
            enemies,
            deck: &[],
            hand_size: 5,
        };
        let mut state = battle::start(&content, &spec).expect("a fight");
        let hero = crate::state::CombatantId::new("hero").expect("the id");

        // 把两件遗物的状态挂上（状态 id 就是遗物在开战时挂的那一条）。
        for id in ["standard.the_abacus", "standard.sundial"] {
            state
                .apply_status_external(&hero, id, 1)
                .expect("the status lands");
        }

        // 弃牌堆里塞两张（用状态自己的搬牌 API，不手改槽位）。
        let hand: std::vec::Vec<_> = state
            .card_zones(&hero)
            .expect("zones")
            .slots(CardZone::Hand)
            .to_vec();
        assert!(hand.len() >= 2, "the opening hand dealt");
        for slot in hand.iter().take(2) {
            state
                .move_card_slot(*slot, CardZone::DiscardPile)
                .expect("to the discard pile");
        }

        let block_before = state
            .defensive_pool(&hero, "standard.block")
            .unwrap_or(0);
        let energy_before = state.resource(&hero, "standard.energy").unwrap_or(0);
        let shuffled = state
            .reshuffle_discard_into_draw(&hero)
            .expect("the shuffle");
        assert_eq!(shuffled, 2, "two cards were shuffled back");
        // 事件是**入队**的，解析要跑一次事件循环。
        state
            .run_events(&content)
            .expect("the triggers resolve");

        // `the_abacus`：+6 格挡。
        let block_after = state
            .defensive_pool(&hero, "standard.block")
            .unwrap_or(0);
        assert_eq!(block_after - block_before, 6, "the_abacus pays 6 block");
        // `sundial`：**第一次**洗牌还不够（每 3 次）⇒ 能量不动。
        let energy_after = state.resource(&hero, "standard.energy").unwrap_or(0);
        assert_eq!(
            energy_after, energy_before,
            "sundial must not pay on the first shuffle"
        );

        // 再洗两次（第 3 次才付 2 能量）。
        for shuffle in 2..=3 {
            let hand: std::vec::Vec<_> = state
                .card_zones(&hero)
                .expect("zones")
                .slots(CardZone::DrawPile)
                .iter()
                .copied()
                .take(1)
                .collect();
            for slot in hand {
                state
                    .move_card_slot(slot, CardZone::DiscardPile)
                    .expect("to the discard pile");
            }
            let before_energy = state.resource(&hero, "standard.energy").unwrap_or(0);
            state
                .reshuffle_discard_into_draw(&hero)
                .expect("the shuffle");
            state
                .run_events(&content)
                .expect("the triggers resolve");
            let after_energy = state.resource(&hero, "standard.energy").unwrap_or(0);
            if shuffle == 3 {
                assert_eq!(after_energy - before_energy, 2, "sundial pays on the 3rd");
            } else {
                assert_eq!(after_energy, before_energy, "but not on the 2nd");
            }
        }
        // 事件队列必须空（没有漏解析的 `DeckShuffled`）。
        assert_eq!(state.pending_event_count(), 0, "the event queue is drained");
        let _ = CombatEvent::DeckShuffled { combatant: hero };
    }
'''


def main():
    s = io.open(CORE, encoding='utf-8').read()
    assert s.rstrip('\n').endswith('}')
    cut = s.rstrip('\n').rfind('\n}')
    s = s[:cut] + '\n' + TESTS + s[cut:]
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(s)
    print('core test appended')


main()
