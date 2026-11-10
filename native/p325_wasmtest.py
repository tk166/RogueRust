"""§325 wasm 端到端：Act 1 的三条。

三条各挑"最有信息"的那个选项：

- `big_fish` 的 `[Box]`：`relic_random`（**wasm 解析**）+ `curse:regret`；
- `living_wall` 的 `[Forget]`：进**改牌问句**（`Pending::EventCard`），选完牌组 -1；
- `mushrooms` 的 `[Stomp]`：打 **3 只** Fungus Beast（池名走 hop 表 + 事件专属遭遇），
  战后 `After` 段给 `odd_mushroom`；
- 外加 `mushrooms` 的 `[Eat]`：`heal_pct:25` + `curse:parasite`（掉 3 张牌里那张）。

⚠️ `run_slot()` 是进程级单例：这些必须单线程跑（验收就是 `--test-threads=1`）。
"""

import io

WASM = 'kernel/rd-wasm/src/run.rs'
ANCHOR = """    /// §324：`augmenter` —— 三个选项各走一遍（`?` 房上手动开事件）。"""

TESTS = '''    /// 站在 `?` 房上、手动开 `event`，返回种子；开不起来就换下一个种子。
    fn open_event_at(event: &str, entry: &str, range: std::ops::Range<i32>) -> i32 {
        for seed in range {
            if !walk_until_unknown(seed) || rd_run_begin_node() != 0 {
                continue;
            }
            if run_slot()
                .as_mut()
                .expect("a run")
                .state
                .begin_event(event, entry)
                .is_ok()
            {
                return seed;
            }
        }
        panic!("no `?` room produced `{event}` in the range");
    }

    /// §325：`big_fish` 的 `[Box]` —— 随机遗物 + `Regret`。
    #[test]
    fn big_fish_box_pays_a_relic_and_a_regret() {
        let seed = open_event_at("big_fish", "big_fish", 0..2000);
        let relics_before = run_slot().as_ref().expect("a run").state.relics().len();
        assert_eq!(rd_run_choose(2), 0, "seed {seed}: Box -- {}", run_error_text());
        let state = &run_slot().as_ref().expect("a run").state;
        assert_eq!(state.relics().len(), relics_before + 1, "seed {seed}: a random relic");
        assert_eq!(
            state.deck().iter().filter(|card| card.as_str() == "regret").count(),
            1,
            "seed {seed}: and a Regret"
        );
        // Wiki：三个选项之后都给一个 `[Leave]`。
        assert_eq!(rd_run_event_option_count(), 1, "seed {seed}: the leave screen");
    }

    /// §325：`living_wall` 的 `[Forget]` —— 进改牌问句，选一张后牌组 -1。
    #[test]
    fn living_wall_forget_asks_which_card() {
        let seed = open_event_at("living_wall", "living_wall", 0..2000);
        let before = rd_run_deck_count();
        assert_eq!(rd_run_choose(0), 0, "seed {seed}: Forget -- {}", run_error_text());
        assert_eq!(
            run_slot().as_ref().expect("a run").state.pending(),
            rd_run::state::Pending::EventCard,
            "seed {seed}: it asks which card"
        );
        assert_eq!(rd_run_pick_event_card(0), 0, "seed {seed}: {}", run_error_text());
        assert_eq!(rd_run_deck_count(), before - 1, "seed {seed}: one card removed");
    }

    /// §325：`mushrooms` 的 `[Stomp]` —— **3 只** Fungus Beast，战后拿 `odd_mushroom`。
    #[test]
    fn mushrooms_stomp_fights_three_fungi_and_pays_the_odd_mushroom() {
        let seed = open_event_at("mushrooms", "mushrooms", 0..2000);
        assert_eq!(rd_run_choose(0), 0, "seed {seed}: Stomp -- {}", run_error_text());
        assert_eq!(rd_run_event_fight(), 1, "seed {seed}: a normal fight");
        assert_eq!(rd_run_fight_begin(), 0, "seed {seed}: {}", run_error_text());
        let mut names: Vec<String> = Vec::new();
        let mut index = 0;
        while rd_env_enemy_name_len(index) >= 0 {
            let n = rd_env_enemy_name_len(index);
            let mut buffer = vec![0u8; n as usize];
            unsafe { rd_env_enemy_name_into(index, buffer.as_mut_ptr()) };
            names.push(String::from_utf8(buffer).unwrap_or_default());
            index += 1;
        }
        assert_eq!(names.len(), 3, "seed {seed}: three beasts, got {names:?}");
        assert!(
            names.iter().all(|name| name.to_ascii_lowercase().contains("fungi")),
            "seed {seed}: all three are Fungi Beasts, got {names:?}"
        );
    }

    /// §325：`mushrooms` 的 `[Eat]` —— 回 25% 上限 + `Parasite`。
    #[test]
    fn mushrooms_eat_heals_and_infects() {
        let seed = open_event_at("mushrooms", "mushrooms", 0..2000);
        let before = *run_slot().as_ref().expect("a run").state;
        // 先掉点血，否则"回了 25%"看不出来。
        run_slot().as_mut().expect("a run").state.adjust_health(-20);
        let hurt = run_slot().as_ref().expect("a run").state.health();
        assert_eq!(rd_run_choose(1), 0, "seed {seed}: Eat -- {}", run_error_text());
        let state = &run_slot().as_ref().expect("a run").state;
        assert_eq!(
            state.health(),
            hurt + before.health_max() * 25 / 100,
            "seed {seed}: 25% of max HP"
        );
        assert_eq!(
            state.deck().iter().filter(|card| card.as_str() == "parasite").count(),
            1,
            "seed {seed}: infected"
        );
    }

'''

ANCHOR2 = ANCHOR


def main():
    t = io.open(WASM, encoding='utf-8').read()
    assert t.count(ANCHOR2) == 1, 'anchor'
    assert 'fn mushrooms_stomp_fights_three_fungi' not in t, 'already patched'
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(t.replace(ANCHOR2, TESTS + ANCHOR2))
    print('wasm Act-1 tests inserted')


main()
