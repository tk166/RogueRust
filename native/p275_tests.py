"""§275 判据：Act 1 硬池那三场（3 Louses / 2 Fungi Beasts / Blue Slaver solo）。

读**内容镜像**（`ENCT` 的 Enemies 列表），不是跑战斗 —— 这是"内容抄得对不对"的问题，
而一场战斗只看得见其中一两个数。同时钉住"遭遇里的 AI 必须是 roster 的副本"这条：
第一版我写了空 `IntentRules`，运行时不是崩溃，而是**那只怪永远用 Actions 的第一条**。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/host.rs'
ANCHOR = '''    /// §248：`Enlightenment` —— **降到至多 1**（`SetMin`），不是"设成 1"。'''

TEST = r'''    /// §275：Act 1 **硬**池里那三场的构成与 HP（wiki.gg `Exordium` + slayspiredb 一致）。
    ///
    /// 三件"只用现有怪物"的遭遇：`3 Louses`（1 绿 2 红）、`2 Fungi Beasts`、`Blue Slaver`。
    /// ⚠️ 静态内容只能写**一种** Louse 配色组合（原作是每只独立掷色）—— 这条偏差写在这里，
    /// 并且判据**故意**钉住我们选的那一种，这样"哪天改成随机的"会有人来看一眼。
    #[test]
    fn the_act_one_hard_pool_encounters_match_the_wiki_numbers() {
        let content = sts_image();
        // (遭遇, [(怪物, HP), ...]) —— 顺序就是出手顺序（`Position`）。
        let expectations: &[(&str, &[(&str, i32)])] = &[
            (
                "enc_three_louses",
                &[("louse_green", 11), ("louse_red", 10), ("louse_red", 10)],
            ),
            ("enc_two_fungi_beasts", &[("fungi_beast", 22), ("fungi_beast", 22)]),
            ("enc_blue_slaver", &[("blue_slaver", 46)]),
        ];
        for (encounter_id, enemies) in expectations {
            let entry = content
                .lookup_in(encounter_id, crate::content::EK_ENCOUNTER)
                .unwrap_or_else(|| panic!("{encounter_id} is in the image"));
            let list = content
                .encounter_enemies(u32::from(entry.index))
                .unwrap_or_else(|error| panic!("{encounter_id}: {error:?}"));
            assert_eq!(
                list.len(),
                enemies.len(),
                "{encounter_id}: the enemy count is the wiki's composition"
            );
            for (index, (enemy_id, hp)) in enemies.iter().enumerate() {
                let spec = list.get(index).expect("each enemy record decodes");
                assert_eq!(
                    spec.id().expect("an id"),
                    *enemy_id,
                    "{encounter_id}: enemy {index} is in the wiki's order"
                );
                assert_eq!(
                    spec.max_health().expect("a health cell"),
                    Some(*hp),
                    "{encounter_id}/{enemy_id}: wiki HP"
                );
            }
        }
    }

'''

def main():
    src = io.open(P, encoding='utf-8').read()
    assert src.count(ANCHOR) == 1
    assert 'the_act_one_hard_pool_encounters_match_the_wiki_numbers' not in src
    io.open(P, 'w', encoding='utf-8', newline='\n').write(src.replace(ANCHOR, TEST + ANCHOR))
    print('§275 test appended')


main()
