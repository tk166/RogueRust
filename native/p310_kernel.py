"""§310（二）：`node.removeDebuffs` 的实现 + 判据重写。

内容改动在下一步（要重编镜像），这一轮先把内核做好。
"""
import io

EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'
HOST = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


NODE_FN = '''
/// `node.removeDebuffs`：**清掉目标身上所有负面状态**（`Orange Pellets`，§310）。
///
/// 与 `applyStatus` 的两处不同，都是按参考来的：
/// * **不进请求队列**：参考的 `RemoveDebuff` 就是逐个 `RemoveStatus`，没有拦截点
///   （Artifact 只拦"施加"，不拦"移除"）；
/// * **删实例，不是把层数减到 0**：0 层实例会留在状态表里（`remove_status` 的文档讲过为什么
///   那不是等价物），而"移除"意味着它不再存在 —— 所以这里用 `remove_status`。
///
/// 倒着删：`remove_status` 会把后面的前移，正着删会跳过每一个间隔的实例。
fn remove_debuffs_node(
    node: NodeRef<'_>,
    ctx: &mut ExecContext<'_>,
    frame: ProgramExecutionSlot,
    slot: u16,
    _stats: &mut ExecStats,
) -> Result<(), ExecError> {
    let selector = node
        .node_field("TargetSelector")?
        .ok_or(IrError::Missing("TargetSelector"))?;
    let mut targets = [CombatantId::EMPTY; MAX_COMBATANTS];
    let count = resolve_targets(selector, ctx, &mut targets)?;
    for target in targets.iter().take(count) {
        let Some(combatant) = ctx.state.combatant_mut(target) else {
            continue;
        };
        let mut doomed = [0usize; crate::state::MAX_STATUSES_PER_COMBATANT];
        let mut doomed_len = 0;
        for (index, instance) in combatant.statuses().iter().enumerate() {
            if instance.polarity == crate::state::StatusPolarity::Debuff {
                doomed[doomed_len] = index;
                doomed_len += 1;
            }
        }
        for offset in 0..doomed_len {
            combatant.remove_status(doomed[doomed_len - 1 - offset]);
        }
    }
    resume_later(ctx.state, frame, slot)
}

'''

TEST = '''    /// §310：`orange_pellets` —— 一回合里 Power / Attack / Skill 各打一张 ⇒ **清除所有负面状态**。
    ///
    /// wiki（两个独立来源）：*"Whenever you play a Power, Attack, and Skill in the same turn,
    /// **remove all debuffs**"*。旧实现在这里给 +3 力量/+3 敏捷 —— 那是**另一条规则**
    /// （`docs/sts-wiki-gap.md` §F.19 的"wiki"列也跟着抄错了）。
    ///
    /// 四侧：① 只有两类 ⇒ 不清；② 三类齐 ⇒ Weak / Frail / Vulnerable 都没了；
    /// ③ **Buff 必须留着**（Strength / Dexterity / Thorns 一条都不许掉 —— 这是"清 Debuff"
    ///    与"清全部状态"的分界）；④ 第四张牌不重复付（计数器已清零，且没有 debuff 时无事发生）。
    #[test]
    fn orange_pellets_removes_every_debuff_and_keeps_the_buffs() {
        use crate::state::ResourceId;

        let blob = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../tools/contentc/packages/sts/out/content.sts.rdcf"
        ))
        .expect("the sts image");
        let content = parse(&blob);
        let mut host = Host::new(&content);

        let stacks = |state: &crate::state::CombatState, definition: &str| -> i32 {
            state
                .combatant(&cid("hero"))
                .map(|hero| {
                    hero.statuses()
                        .iter()
                        .filter(|status| status.definition_id.as_str() == definition)
                        .map(|status| status.stacks)
                        .sum()
                })
                .unwrap_or(0)
        };
        // 起手：两个负面（Weak 2 / Frail 2）、三个正面（Strength 2 / Dexterity 2 / Thorns 3）。
        let play_all = |host: &mut Host, cards: &[&str]| -> (i32, i32, i32, i32, i32) {
            let mut state = arena();
            {
                let foe = state.combatant_mut(&cid("enemy_a")).expect("foe");
                foe.health_max = 400;
                foe.health_current = 400;
            }
            state
                .combatant_mut(&cid("hero"))
                .expect("hero")
                .set_resource(ResourceId::new("standard.energy").unwrap(), 20, Some(20))
                .expect("energy");
            give(&mut state, "hero", status("st_op", "standard.orange_pellets", 1));
            give(&mut state, "hero", status("st_weak", "standard.weak", 2));
            give(&mut state, "hero", status("st_frail", "standard.frail", 2));
            give(&mut state, "hero", status("st_str", "standard.strength", 2));
            give(&mut state, "hero", status("st_dex", "standard.dexterity", 2));
            give(&mut state, "hero", status("st_thorns", "standard.thorns", 3));
            for id in cards {
                let card = card_in_hand(&mut state, &content, "hero", id);
                let request =
                    crate::play::PlayRequest::new(cid("hero"), card, Some(cid("enemy_a")));
                crate::play::play_card(&mut state, Some(&content), &request)
                    .unwrap_or_else(|e| panic!("{id}: {e:?}"));
                host.try_resolve_pending_queues(&mut state).expect("triggers");
            }
            (
                stacks(&state, "standard.weak"),
                stacks(&state, "standard.frail"),
                stacks(&state, "standard.strength"),
                stacks(&state, "standard.dexterity"),
                stacks(&state, "standard.thorns"),
            )
        };

        // ① 只有 Attack + Skill：两个负面都还在。
        assert_eq!(
            play_all(&mut host, &["strike", "defend"]),
            (2, 2, 2, 2, 3),
            "two kinds is not enough"
        );
        // ② 三类齐（`metallicize` 是纯 Power）：负面清空，正面**一条都不许动**。
        assert_eq!(
            play_all(&mut host, &["strike", "defend", "metallicize"]),
            (0, 0, 2, 2, 3),
            "Power + Attack + Skill cleanses Weak and Frail and keeps the buffs"
        );
        // ③ 第四张牌不重复付：清过之后没有负面，正面仍然是原值。
        assert_eq!(
            play_all(&mut host, &["strike", "defend", "metallicize", "strike"]),
            (0, 0, 2, 2, 3),
            "the counters reset, so a fourth card does not fire again"
        );
    }


'''


def main():
    anchor = '''/// `Heal`：`Amount` → `TargetSelector` → **每个目标一条请求**（`:658-680`）。'''
    patch(EXEC, anchor, NODE_FN + anchor)

    # 旧的"+3/+3"判据整段换掉（它替错的规则站了岗）。
    text = io.open(HOST, encoding='utf-8').read()
    start = text.index('    /// §299：`orange_pellets` —— 一回合里 Power / Attack / Skill 各打一张 ⇒ +3 力量、+3 敏捷。')
    end = text.index('    /// §300：`warped_tongs` —— 回合开始**随机**升级手牌一张。', start)
    old = text[start:end]
    assert old.count('orange_pellets_pays_once_all_three_card_kinds_were_played') == 1
    io.open(HOST, 'w', encoding='utf-8', newline='\n').write(
        text[:start] + TEST + text[end:])
    print('node + test installed')


main()
