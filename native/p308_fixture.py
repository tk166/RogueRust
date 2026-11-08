"""§308（二）：把 round-trip 的夹具换成**每一格都非默认**的 `sample_full()`。

`sample()` 只设了 6 个字段，于是 `assert_eq!(restored, run)` 的"整局相等"对后来新增的
18 个字段完全瞎 —— 这是审阅报告 §2 真正扎人的地方（判据看起来最硬，实际覆盖为零）。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-run/src/state/archive.rs'


def patch(old, new, count=1):
    text = io.open(PATH, encoding='utf-8').read()
    assert text.count(old) == count, (text.count(old), old[:90])
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


SAMPLE_FULL = '''
    /// §308：**每一格都填上非默认值**的夹具。
    ///
    /// 为什么需要它：`sample()` 只设了六个字段（种子/牌组/金币/血/一瓶药水/一件遗物），于是
    /// `a_saved_run_round_trips_byte_identically` 的判据"整局相等"对后来新增的字段**完全瞎** ——
    /// 漏写 18 个字段它照样绿（审阅报告 §2 抓到的正是这一点）。
    ///
    /// 规矩：**`RunState` 每加一个字段，这里加一行**，然后拿"删掉对应那条 `writer...`"做负控，
    /// 确认那条判据会红。只加字节不加这一行，等于又养了一条瞎的判据。
    fn sample_full() -> RunState {
        let mut run = sample();
        // 每副本成长（`Ritual Dagger`）：两张牌各一条，**键与下标都不同** —— 只写值的话，
        // "第 0 张 9 点"与"第 1 张 9 点"会是同一局。
        run.set_mark(0, "standard.ritual_dagger_bonus", 9)
            .expect("slot 0 is in the deck");
        run.set_mark(1, "standard.ritual_dagger_bonus", 4)
            .expect("slot 1 is in the deck");
        // 事件链：正在第 2 段、打完伏击回到第 3 段、编辑完去第 4 段。
        run.event = RunId::new("dead_adventurer").expect("an id");
        run.event_step = RunId::new("dead_adventurer.ambush").expect("an id");
        run.event_resume = RunId::new("dead_adventurer.after").expect("an id");
        run.event_next = RunId::new("dead_adventurer.reward").expect("an id");
        run.event_fight = 2;
        run.event_fight_pool = RunId::new("EliteEvent").expect("an id");
        // 下一场战斗的六个覆盖（`Dead Adventurer` 那一套）。
        run.fight_gold_bonus = 30;
        run.fight_gold_set = 44;
        run.fight_no_relic = true;
        run.fight_relic_rarity = 3;
        run.fight_extra_relic = 1;
        run.fight_relic = RunId::new("thread_and_needle").expect("an id");
        run.fight_potion_chance = 70;
        // 宝箱与拾取欠账（`matryoshka` / `nloths_hungry_face` / `calling_bell` / `cauldron`）。
        run.chest_extra = 2;
        run.chest_empty = 1;
        run.pickup_relics = 3;
        run.pickup_potions = 5;
        // `A20` 的两场 Boss 进度。
        run.bosses_fought = 1;
        run
    }
'''


def main():
    patch('''        run.push_relic("burning_blood", &[]).expect("relic room");
        run
    }
''', '''        run.push_relic("burning_blood", &[]).expect("relic room");
        run
    }
''' + SAMPLE_FULL)

    patch('''    fn a_saved_run_round_trips_byte_identically() {
        let run = sample();''', '''    fn a_saved_run_round_trips_byte_identically() {
        // §308：`sample_full()` 而不是 `sample()` —— 后者每一个新字段都在默认值，
        // 于是"漏还原一个字段就红"这句注释是**假的**。
        let run = sample_full();''')

    print('fixture installed')


main()
