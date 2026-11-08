"""§302 判据（第三版）：挪到 `rd-wasm`。

前两版都死在同一个事实上：`rd-core` 的测试镜像 `content.core.rdcf` 是**冻结的参考基线**
（`expected_sha.txt` 钉住），里面**没有** `standard.strange_spoon` 这一行。
`give_status` 再 `play_card` 会在 `STAT row` 上炸 —— 那不是遗物的问题，是"测试拿错了镜像"。

搬到 `rd-wasm` 反而**更强**：`crate::IMAGE` 是真实 sts 镜像，链路是**完整**的
（遗物 → 开战时的状态 → 落区），而"遗物给了状态"这一跳断掉时单元测试是绿的。
"""
import io

PLAY = 'D:/Vibe/sts-tui/kernel/rd-core/src/play.rs'
LIB = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TEST = r'''
    /// §302：`strange_spoon` —— 打出即消耗的牌有一半概率改去弃牌堆。
    ///
    /// 判据在**这一层**，不是 `rd-core` 的单元层：`rd-core` 的测试镜像是冻结的参考基线
    /// （`content.core.rdcf`），里面没有 `standard.strange_spoon` 那一行 STAT —— 拿它测这个
    /// 遗物只会在 `STAT row` 上炸。这里用的是真实 sts 镜像，所以**遗物 → 开战时的状态 → 落区**
    /// 三跳是连着的（单元层里中间那一跳断了也照样绿）。
    #[test]
    fn strange_spoon_turns_about_half_of_the_exhausts_into_discards() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
            vec![rd_core::battle::DeckEntry {
                card: "bandage_up", // 0 费、打出即消耗
                count: 20,
            }]
            .into_boxed_slice(),
        );

        /// 打完这一整场开头的 `handful` 张牌，返回每一张的落区（`true` = 进了消耗堆）。
        fn run(seed: i32, spoon: bool, handful: usize) -> Vec<bool> {
            let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
            let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
                vec![rd_core::battle::DeckEntry {
                    card: "bandage_up",
                    count: 20,
                }]
                .into_boxed_slice(),
            );
            let session =
                build_session_at_unstarted(seed, "enc_cultist", 200, Some(deck), 0, 0)
                    .expect("a session");
            install_session(session);
            if spoon {
                let session = slot().as_mut().expect("session");
                let item = rd_core::state::EffectItem {
                    request: rd_core::state::EffectRequest::ApplyStatus {
                        target: Some(cid_in("hero")),
                        definition: rd_core::state::StatusDefinitionId::new(
                            rd_core::play::STRANGE_SPOON_STATUS,
                        )
                        .expect("a status id"),
                        stacks: 1,
                        duration: 0,
                        charges: 0,
                        source: None,
                        source_card: None,
                    },
                    chain: rd_core::state::ChainSlot::NONE,
                    owner: None,
                };
                rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                    .expect("apply the carrier");
            }
            let standard = standard_turn_config().expect("standard turn config");
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");

            let mut landings = Vec::new();
            for _ in 0..handful {
                let session = slot().as_mut().expect("session");
                let hero = cid_in("hero");
                let Some(card) = session
                    .state
                    .zone_cards(&hero, rd_core::state::CardZone::Hand)
                    .next()
                    .map(|card| card.id)
                else {
                    break;
                };
                let instance = card;
                let request = rd_core::play::PlayRequest::new(hero, instance, None);
                // 打不动（能量不够 / 手牌没了）就停 —— 这条判据数的是**打出去的**那些。
                let Ok(_) = rd_core::play::play_card(&mut session.state, Some(&content), &request)
                else {
                    break;
                };
                let mut host = rd_core::host::Host::new(&content);
                host.try_resolve_pending_queues(&mut session.state)
                    .expect("drain");
                let session = slot().as_ref().expect("session");
                let exhausted = session
                    .state
                    .zone_cards(&hero, rd_core::state::CardZone::ExhaustPile)
                    .any(|card| card.id == instance);
                let discarded = session
                    .state
                    .zone_cards(&hero, rd_core::state::CardZone::DiscardPile)
                    .any(|card| card.id == instance);
                assert!(
                    exhausted ^ discarded,
                    "the card landed in exactly one pile"
                );
                landings.push(exhausted);
            }
            take_session();
            landings
        }

        let with_spoon = run(7, true, 8);
        assert!(with_spoon.len() >= 4, "enough plays: {with_spoon:?}");
        assert!(with_spoon.contains(&true), "it still exhausts sometimes: {with_spoon:?}");
        assert!(
            with_spoon.contains(&false),
            "and it saves sometimes: {with_spoon:?}"
        );
        assert_eq!(run(7, true, 8), with_spoon, "same seed, same sequence");

        // 没有遗物 ⇒ 一张都不被救。
        let without = run(7, false, 8);
        assert_eq!(without.len(), with_spoon.len(), "the same plays happen");
        assert!(
            without.iter().all(|exhausted| *exhausted),
            "without the relic every one of them exhausts: {without:?}"
        );
    }

    /// §302：**边界** —— 骰子只属于"打出即消耗"那一条路。
    ///
    /// * 打一张本来就不消耗的牌（`strike`）：不掷（否则每张牌都在偷随机流）；
    /// * 被效果直接搬进消耗堆（`Fiend Fire` / `Burning Pact` 那条路，这里是 `move_card`）：
    ///   照旧进消耗堆，也不掷。
    ///
    /// wiki 的原话是 *"Strange Spoon specifically only works on cards that Exhaust when played"*，
    /// 这两条就是那句话的两侧。
    #[test]
    fn strange_spoon_never_rolls_for_discards_or_forced_exhausts() {
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let deck: &'static [rd_core::battle::DeckEntry<'static>] = Box::leak(
            vec![
                rd_core::battle::DeckEntry {
                    card: "strike",
                    count: 10,
                },
                rd_core::battle::DeckEntry {
                    card: "bandage_up",
                    count: 10,
                },
            ]
            .into_boxed_slice(),
        );
        let session = build_session_at_unstarted(11, "enc_cultist", 200, Some(deck), 0, 0)
            .expect("a session");
        install_session(session);
        {
            let session = slot().as_mut().expect("session");
            let item = rd_core::state::EffectItem {
                request: rd_core::state::EffectRequest::ApplyStatus {
                    target: Some(cid_in("hero")),
                    definition: rd_core::state::StatusDefinitionId::new(
                        rd_core::play::STRANGE_SPOON_STATUS,
                    )
                    .expect("a status id"),
                    stacks: 1,
                    duration: 0,
                    charges: 0,
                    source: None,
                    source_card: None,
                },
                chain: rd_core::state::ChainSlot::NONE,
                owner: None,
            };
            rd_core::exec::resolve_effect(&mut session.state, &item, Some(&content))
                .expect("apply the carrier");
        }
        let standard = standard_turn_config().expect("standard turn config");
        {
            let session = slot().as_mut().expect("session");
            start_first_turn(&mut session.state, &standard, &mut session.host)
                .expect("start the first turn");
        }

        // ① `strike` ⇒ 弃牌堆，且随机步不动。
        let (hero, instance, step_before) = {
            let session = slot().as_ref().expect("session");
            let hero = cid_in("hero");
            let strike = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .find(|card| card.definition_id.as_str() == "strike")
                .map(|card| card.id)
                .expect("a strike in hand");
            (hero, strike, session.state.random_step)
        };
        let target = {
            let session = slot().as_ref().expect("session");
            session
                .state
                .combatants()
                .iter()
                .find(|c| c.team_id.as_str() == "enemy")
                .map(|c| c.id)
        };
        {
            let session = slot().as_mut().expect("session");
            let request = rd_core::play::PlayRequest::new(hero, instance, target);
            rd_core::play::play_card(&mut session.state, Some(&content), &request)
                .expect("strike is playable");
            let mut host = rd_core::host::Host::new(&content);
            host.try_resolve_pending_queues(&mut session.state)
                .expect("drain");
        }
        {
            let session = slot().as_ref().expect("session");
            assert!(
                session
                    .state
                    .zone_cards(&hero, rd_core::state::CardZone::DiscardPile)
                    .any(|card| card.id == instance),
                "strike lands in the discard pile"
            );
            assert_eq!(
                session.state.random_step, step_before,
                "a card that does not exhaust never rolls"
            );
        }

        // ② 被效果搬进消耗堆 ⇒ 不掷骰、照旧消耗。
        let (hero, instance, step_before, slot_index) = {
            let session = slot().as_ref().expect("session");
            let hero = cid_in("hero");
            let (index, card) = session
                .state
                .zone_cards(&hero, rd_core::state::CardZone::Hand)
                .enumerate()
                .find(|(_, card)| card.definition_id.as_str() == "bandage_up")
                .map(|(index, card)| (index, card.id))
                .expect("a bandage_up in hand");
            let slots = session
                .state
                .card_zones(&hero)
                .map(|zones| zones.slots(rd_core::state::CardZone::Hand))
                .expect("zones");
            (hero, card, session.state.random_step, slots[index])
        };
        {
            let session = slot().as_mut().expect("session");
            session
                .state
                .move_card(
                    &hero,
                    rd_core::state::CardZone::Hand,
                    rd_core::state::CardZone::ExhaustPile,
                    slot_index,
                    rd_core::state::ZonePlacement::Bottom,
                )
                .expect("a forced exhaust");
        }
        {
            let session = slot().as_ref().expect("session");
            assert!(
                session
                    .state
                    .zone_cards(&hero, rd_core::state::CardZone::ExhaustPile)
                    .any(|card| card.id == instance),
                "a forced exhaust is not the relic's business"
            );
            assert_eq!(
                session.state.random_step, step_before,
                "and it does not roll either"
            );
        }
        take_session();
    }
'''


def main():
    # ① 删掉 rd-core 里那三条（镜像里没有这个状态行）
    s = io.open(PLAY, encoding='utf-8').read()
    start = s.index('    // ── §302：`strange_spoon` ──')
    end = s.rstrip('\n').rfind('\n}')
    note = '''    // §302：`strange_spoon` 的判据在 `rd-wasm`（`strange_spoon_turns_about_half_of_the_exhausts_into_discards`）。
    //
    // 为什么不在这一层：本模块的测试镜像是 `content.core.rdcf` —— **冻结的参考基线**
    // （`expected_sha.txt` 钉住），里面没有 `standard.strange_spoon` 那一行 STAT。
    // 给它造一条会改基线字节；而"状态行不存在"这件事本身也不是遗物的规则。
'''
    io.open(PLAY, 'w', encoding='utf-8', newline='\n').write(s[:start] + note + s[end:])

    # ② 写进 rd-wasm
    t = io.open(LIB, encoding='utf-8').read()
    cut = t.rstrip('\n').rfind('\n}')
    io.open(LIB, 'w', encoding='utf-8', newline='\n').write(t[:cut] + TEST + t[cut:])
    print('tests moved to rd-wasm')


main()
