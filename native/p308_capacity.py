"""§308（四）：最坏情况的容量判据 —— 60 个牌位各带一条成长必须装得下。

容量是语义（§162/§1620 那条裁决）：装不下必须**响亮失败**，而不是"某个存了很久的档突然存不上"。
夹具用满长度的 id（`standard.ritual_dagger_bonus` 是今天最长的那条 mark 键之一），
于是这条判据量的不是"两三条 mark"，而是这几百字节真的放得进去。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


TEST = '''
    /// §308：**最坏情况**要装得下 —— 60 个牌位各带一条成长（`Ritual Dagger` 的键是最长的之一）。
    ///
    /// 这条不是在测"能不能少写字节"，是在测"存档不会在某一天突然存不上"：容量如果不够，
    /// `write` 会返回 `TooLong`（响亮），但那时玩家的存档已经打不开了。所以先用满长度压一遍。
    #[test]
    fn a_deck_where_every_copy_carries_a_mark_still_fits() {
        let mut run = sample_full();
        let key = "standard.ritual_dagger_bonus";
        for slot in 0..MAX_RUN_DECK {
            run.deck[slot] = RunId::new(key).expect("an id");
            run.set_mark(slot, key, slot as i32 * 3)
                .expect("every slot exists once the deck is full");
        }
        run.deck_len = MAX_RUN_DECK as u8;
        let mut out = [0u8; MAX_ARCHIVE];
        let len = write(&run, CONTENT, &mut out).expect("the worst case still fits");
        assert!(len <= MAX_ARCHIVE, "the archive must fit its published capacity");
        let text = core::str::from_utf8(&out[..len]).expect("ascii");
        let mut restored = RunState::new_with_ascension(1, 80, 0, &[], 0).expect("a skeleton");
        restore(text, CONTENT, &mut restored).expect("restore the worst case");
        assert_eq!(restored, run, "60 marks survive the round trip");
    }
'''


def main():
    patch('''    #[test]
    fn the_archive_is_one_line_with_a_head_and_a_tail() {''',
          TEST + '''
    #[test]
    fn the_archive_is_one_line_with_a_head_and_a_tail() {''')
    print('capacity test added')


main()
