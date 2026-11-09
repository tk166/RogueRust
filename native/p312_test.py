"""§312（三）：Malleable 的判据 —— 每次挨打多 1 块、每回合开始清零。

四段，缺一段就会静默错一档：
1. 第一下给 **3**（层数），第二下 **4**、第三下 **5** —— "越挨越多"是这个状态的全部；
2. 累计值 3 → 7 → 12（**块是累加的**，不是覆盖）；
3. 回合开始清掉"+1 的增量" ⇒ 下一回合第一下又给 3；
4. **毒不算**（`damage.isAttack` 为假）—— 与 "attack damage" 这条措辞对齐。

⚠️ 第 2 段的伤害必须**大过已有的块**，否则块把伤害挡住 ⇒ `eventAmount == 0` ⇒ 不触发
（这正是 wiki 那句 "break Block with a larger attack, or Malleable will keep on generating
Block" 的机制）。判据用 50 点攻击，让每次都有血掉。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TESTS = '''
    /// §312：Snake Plant 的 `Malleable 3` —— 每次**掉血的攻击**多给 1 块，回合开始清零。
    ///
    /// 这是本轮唯一一个"纯内容实现的反应式状态"：`DamageTaken` 触发器 + `damage.isAttack` +
    /// 一个每战斗员计数器（`malleable_bonus`）。判据要同时证明"会长"和"会清"——只测会长，
    /// 一个忘了清零的实现也全绿（它只是每回合越来越猛）。
    #[test]
    fn malleable_grows_by_one_per_hit_and_resets_when_the_turn_starts() {
        use rd_core::status_bind::DamageKind;
        let session = build_session_at(17, "enc_snake_plant", 200, None, 0, 0)
            .expect("the snake plant fight builds");
        install_session(session);
        let content = rd_core::content::Content::parse(crate::IMAGE).expect("image");
        let block = |state: &rd_core::state::CombatState| -> i32 {
            state
                .combatant(&cid_in("snake_plant"))
                .map(|combatant| {
                    combatant
                        .defensive_pools()
                        .iter()
                        .find(|pool| pool.key.as_str() == "standard.block")
                        .map_or(0, |pool| pool.pool.current)
                })
                .unwrap_or(-1)
        };
        let hit = |kind: DamageKind| {
            let session = slot().as_mut().expect("session");
            let mut host = rd_core::host::Host::new(&content);
            let mut ctx = rd_core::exec::ExecContext::new(
                &mut session.state,
                Some(cid_in("hero")),
                Some(cid_in("snake_plant")),
                None,
                1024,
            )
            .with_content(&content);
            // 50 点：一定要打穿已有的块，否则 `eventAmount == 0` ⇒ 不触发（见文档）。
            rd_core::exec::resolve_damage_of_kind(&mut ctx, &cid_in("snake_plant"), 50, false, kind)
                .expect("an attack lands");
            rd_core::exec::drain(&mut session.state, Some(&content), None).expect("drain");
            host.resolve_pending_queues_with(&mut session.state, rd_core::host::QueueLimits::DEFAULT)
                .expect("dispatch DamageTaken");
        };

        // 1 + 2: 三下攻击 ⇒ 3 / 7 / 12。
        let mut seen = Vec::new();
        for _ in 0..3 {
            hit(DamageKind::Attack);
            let session = slot().as_ref().expect("session");
            seen.push(block(&session.state));
        }
        assert_eq!(seen, vec![3, 7, 12], "Malleable 3, then +4, then +5 (blocks accumulate)");

        // 3: 回合开始 ⇒ 增量清零，下一回合第一下又是 3。
        {
            let session = slot().as_mut().expect("session");
            session.state.current_round += 1;
            let mut host = rd_core::host::Host::new(&content);
            host.try_run_turn_started_triggers(&mut session.state, &cid_in("snake_plant"))
                .expect("turn started");
            host.try_resolve_pending_queues(&mut session.state).expect("drain");
        }
        hit(DamageKind::Attack);
        let session = slot().as_ref().expect("session");
        let after_reset = block(&session.state);
        assert_eq!(
            after_reset,
            12 + 3,
            "the counter reset, so the next hit pays the base 3 again (12 already banked)"
        );

        // 4: 毒**不**让它长大（`damage.isAttack` 为假）。
        {
            let before = block(&session.state);
            hit(DamageKind::Dot);
            let session = slot().as_ref().expect("session");
            assert_eq!(block(&session.state), before, "DoT is not an attack");
        }
        take_session();
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §311：**三只 byrd 各自的 Flying**。'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(anchor, TESTS + '\n' + anchor))
    print('malleable test added')


main()
