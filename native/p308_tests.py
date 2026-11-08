"""§308（三）：为两个"mark 遗留"缺陷各加一条判据，并给指纹加一条区分判据。

三个缺陷/风险的判据：
  1. 删掉一张带成长的牌 ⇒ 尾槽的 mark 必须归零（否则下一张牌继承它）；
  2. `push_card` 进来一张新牌 ⇒ 它的牌位必须没有 mark；
  3. 两局只在"某一张牌的 mark"上不同 ⇒ 指纹必须不同（审阅报告的最小复现 #5）。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
HASH = 'D:/Vibe/sts-tui/kernel/rd-run/src/hash.rs'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


MARK_TESTS = '''
    /// §308：删掉一张带成长的牌，**尾槽的 mark 必须归零**。
    ///
    /// 这个缺陷在 §253 修"删牌时 mark 跟着牌走"时漏了反方向：`remove_deck_card` 清了
    /// `deck` 的尾槽，却没清 `marks` 的尾槽。于是"被删那张牌的成长"留在原地 —— 而存档
    /// 只写活动前缀，尾槽有值会让 round-trip 报"丢数据"，更坏的是它会**被下一张牌继承**。
    #[test]
    fn a_removed_cards_mark_does_not_live_on_in_the_tail() {
        let mut run = campfire_run();
        run.push_relic("peace_pipe", &TYPED_CARDS).expect("peace pipe");
        let last = run.deck_len as usize - 1;
        run.set_mark(last, "standard.ritual_dagger_bonus", 7)
            .expect("the last slot exists");
        at_campfire(&mut run);
        assert_eq!(run.toke(last), Ok(()), "Toke removes the marked card");
        // 尾槽（新的 `deck_len`，也就是被腾出来的那一格）必须是空的。
        assert!(run.marks[run.deck_len as usize].is_none(), "the tail slot was cleared");
        assert_eq!(run.check_invariants(), Ok(()), "and the run is still legal");
    }

    /// §308：新加进来的牌**没有**跨场历史，哪怕它落在了一个曾经有 mark 的牌位上。
    #[test]
    fn a_newly_added_card_never_inherits_a_mark() {
        let mut run = campfire_run();
        run.push_relic("peace_pipe", &TYPED_CARDS).expect("peace pipe");
        // 先在**末尾之后**那一格放一条 mark（模拟"删牌留下的尾槽"这一种历史残骸）。
        run.marks[run.deck_len as usize] = RunMark {
            key: RunId::new("standard.ritual_dagger_bonus").expect("an id"),
            value: 5,
        };
        let card = run.deck()[0];
        run.push_card(PoolCard {
            id: card.as_str().trim_end_matches('+'),
            rarity: Rarity::Starter,
            ..*TYPED_CARDS.iter().find(|entry| entry.id == card.as_str())
                .expect("the first card is in the pool")
        })
        .expect("room for one more");
        assert!(run.mark(run.deck_len as usize - 1).is_none(), "a new card has no mark");
    }
'''

HASH_TESTS = '''
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
'''


def main():
    patch(STATE, '''    /// §259：`Dig` 只抽 **Common/Uncommon/Rare**''', MARK_TESTS + '''
    /// §259：`Dig` 只抽 **Common/Uncommon/Rare**''')

    patch(HASH, '''#[cfg(test)]
mod tests {''', '''#[cfg(test)]
mod tests {
    use crate::state::RunState;''' if False else '''#[cfg(test)]
mod tests {''')

    # 追加到 hash.rs 的 tests 模块末尾（用最后一条测试之后的 `}` 之前插入不可靠，
    # 所以把新测试追加在 `mod tests {` 的**最后**：找到文件末尾最后一个 `}`）。
    text = io.open(HASH, encoding='utf-8').read()
    assert text.rstrip().endswith('}')
    body = text.rstrip()
    closing = body.rfind('}')
    text = body[:closing] + HASH_TESTS + '}\n'
    io.open(HASH, 'w', encoding='utf-8', newline='\n').write(text)
    print('tests added')


main()
