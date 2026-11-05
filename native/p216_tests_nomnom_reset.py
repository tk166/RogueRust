"""§216 tests #2: `Nom Nom` on **real** rounds, and the three fields `reset_in_place` forgot.

The old `Nom Nom` test forged `state.current_turn = 1..=6`. That variable is the **actor's index
inside a round** (`turn.rs:970` resets it to 1 when a new round starts), so in a solo fight the Maw
always acts at 2 -- the forged values are unreachable in real play, which is exactly why the bug
survived an "honest" test. The replacement drives turns through the session's own step machine.
"""
import io

W = 'kernel/rd-wasm/src/lib.rs'
S = 'kernel/rd-core/src/state.rs'


def one(path, old, new, what):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))
    print('patched', path, '-', what)


# ── rd-wasm：真推进轮次 ───────────────────────────────────────────────────────────────────────
one(W, '''    /// 用**第 1..6 回合**各打一次：N 必须是 `1,1,2,2,3,3`，也就是 5,5,10,10,15,15 点。
    /// 这条测试专门钉三个容易错的写法：
    /// * 向下取整（`turn / 2`）⇒ 第 1 回合就是 0 点（`repeat` 跑 0 次，**静默无伤害**）；
    /// * 读成"用了几次"而不是"第几回合" ⇒ 序列会变成 5,10,15…；
    /// * 把 `repeat` 写成一次乘好的伤害 ⇒ 那就不是多段（格挡/荆棘的行为会不同）。
    #[test]
    fn nom_nom_hits_five_damage_ceil_turn_over_two_times() {''',
    '''    /// 用**第 1..6 轮**各打一次：N 必须是 `1,1,2,2,3,3`，也就是 5,5,10,10,15,15 点。
    ///
    /// ⚠️ §216 起这一条**真的推进轮次**（`Session::exec(EndOneTurn)` 走回合机），不再写
    /// `state.current_turn = turn`。旧写法测的是"一轮内行动者序号"—— 那个量在单怪场景里
    /// **恒为 2**（绕回时置 1，`turn.rs:970`），所以旧公式 `ceil(turn/2)` 在真实玩法里永远 1 击，
    /// 而测试却因为它伪造了 1..6 而全绿。这正是 review P1-B。
    ///
    /// 这条测试钉三个容易错的写法：
    /// * 向下取整（`round / 2`）⇒ 第 1 轮就是 0 点（`repeat` 跑 0 次，**静默无伤害**）；
    /// * 读成"用了几次"而不是"第几轮" ⇒ 序列会变成 5,10,15…；
    /// * 把 `repeat` 写成一次乘好的伤害 ⇒ 那就不是多段（格挡/荆棘的行为会不同）。
    #[test]
    fn nom_nom_hits_five_damage_ceil_round_over_two_times() {''',
    'test header')

one(W, '''        let mut dealt = Vec::new();
        for turn in 1..=6 {
            let before = {
                let session = slot().as_ref().expect("session");
                hp(&session.state)
            };
            {
                let session = slot().as_mut().expect("session");
                session.state.current_turn = turn;
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("maw"),
                    action_row,
                    Some(hero),
                )
                .unwrap_or_else(|e| panic!("turn {turn}: {e:?}"));
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                hp(&session.state)
            };
            dealt.push(before - after);
        }
        assert_eq!(dealt, vec![5, 5, 10, 10, 15, 15], "5 x ceil(turn/2)");
        take_session();''',
    '''        let mut dealt = Vec::new();
        for round in 1..=6 {
            let before = {
                let session = slot().as_ref().expect("session");
                assert_eq!(
                    session.state.current_round, round,
                    "round counter really advanced (no forging)"
                );
                hp(&session.state)
            };
            {
                let session = slot().as_mut().expect("session");
                // 英雄结束回合 ⇒ Maw 上场（这一步只走一格回合，不让 AI 出招）。
                session.exec(&[Step::EndOneTurn]).expect("the hero ends the turn");
                rd_core::intent::execute_action(
                    &mut session.state,
                    &content,
                    &cid_in("maw"),
                    action_row,
                    Some(hero),
                )
                .unwrap_or_else(|e| panic!("round {round}: {e:?}"));
                rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
                // Maw 结束回合 ⇒ 下一轮、又轮到英雄。
                session.exec(&[Step::EndOneTurn]).expect("the maw ends its turn");
            }
            let after = {
                let session = slot().as_ref().expect("session");
                hp(&session.state)
            };
            dealt.push(before - after);
        }
        assert_eq!(dealt, vec![5, 5, 10, 10, 15, 15], "5 x ceil(round/2)");
        take_session();''',
    'test body')

# ── state.rs：三个字段也归 `reset_scalars` 管 ──────────────────────────────────────────────────
one(S, '''    pub fn reset_in_place(&mut self, id: CombatId, random_seed: i32) {
        self.reset_scalars(id, random_seed);''',
    '''    pub fn reset_in_place(&mut self, id: CombatId, random_seed: i32) {
        self.reset_scalars(id, random_seed);''',
    'no-op check')

one(S, '''        self.next_status_instance_number = 1;
        self.next_card_instance_number = 1;
        self.next_effect_chain_number = 1;
        self.next_program_execution_id = 1;
    }''',
    '''        self.next_status_instance_number = 1;
        self.next_card_instance_number = 1;
        self.next_effect_chain_number = 1;
        self.next_program_execution_id = 1;
        // §216（review P1-C）：这三个字段是后加的，`reset_scalars` 一度**没有**它们 ——
        // `new()` / `Empty::EMPTY` 给了默认值，而"先打过一场（有人逃跑、掉了钱、A20）再复用"
        // 的状态会带着上一场的 `gold_carried_away` 进新战斗，`apply_fight_outcome` 会按它
        // **重复扣**一次金币（`run.rs:3491` 是 `adjust_gold(-carried)`）。
        self.vacated_seat = None;
        self.gold_carried_away = 0;
        self.ascension = 0;
    }''',
    'reset_scalars')
