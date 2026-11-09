"""§316（三）：三条既有判据跟着"Spiker 不再单独出现"改。

wiki 的第三幕池子里**没有**单独一只 Spiker 的遭遇（它只在 Shapes 组里出现），所以
`enc_spiker` 删掉了。于是三条判据要换"怎么拿到一只 Spiker"：

1. `spiker_never_repeats_its_attack_...` —— 改成从 `enc_three_shapes` 里找；
2. `starting_statuses_follow_their_ascension_rows` —— 同上（Thorns 3→4→7 那三档还在，
   只是挂在 Shapes 组的候选记录上）；
3. `an_encounter_with_two_records_of_the_same_id_builds` —— `enc_darklings` 现在是**三只**
   （wiki 的 "3 Darklings"），期望跟着改成三条 id。

helper `shapes_session_with` 会**循环种子**直到那一组里真的出现目标怪 —— 组合槽是逐槽独立
按权重挑的（§316 的已知偏差），所以"某个种子下没有 Spiker"是正常的，不是失败。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

HELPER = '''
    /// §316：Spiker 现在只作为 Shapes 组的一员出现（wiki 的第三幕池子里没有单独的一只）。
    ///
    /// 组合槽（`Candidates`）是**逐槽独立按权重**挑的，所以"某个种子下这组里恰好没有 Spiker"
    /// 是正常的：这里循环种子，直到真的建出一只来。找不到就让测试**响亮地**失败
    /// （"永远找不到"必须能被看见，否则这条判据会退化成"什么都不检查"）。
    fn shapes_session_with(monster: &str, ascension: u8) -> rd_core::state::CombatantId {
        for seed in 0..64 {
            let session = build_session_at(seed, "enc_three_shapes", 200, None, 0, ascension)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            let found = session
                .state
                .combatants()
                .iter()
                .find(|combatant| {
                    combatant.team_id.as_str() == "enemy"
                        && combatant.id.as_str().split('#').next() == Some(monster)
                })
                .map(|combatant| combatant.id.as_str().to_string());
            install_session(session);
            if let Some(id) = found {
                return rd_core::state::CombatantId::new(&id).expect("a usable id");
            }
        }
        panic!("no seed in 0..64 put a `{monster}` into 3 Shapes");
    }

'''

OLD_SPIKER_HEAD = '''        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_spiker", rd_core::content::EK_ENCOUNTER)
                .expect("enc_spiker")
                .index,
        );
        let ask = |last: i32, buffs: i32, seed: i32| -> String {
            let session = build_session_at(seed, "enc_spiker", 200, None, 0, 0)
                .unwrap_or_else(|e| panic!("seed {seed}: {e}"));
            install_session(session);
            let session = slot().as_mut().expect("session");
            let id = cid_in("spiker");'''

NEW_SPIKER_HEAD = '''        let blob = crate::IMAGE;
        let content = rd_core::content::Content::parse(blob).expect("image");
        let row = u32::from(
            content
                .lookup_in("enc_three_shapes", rd_core::content::EK_ENCOUNTER)
                .expect("enc_three_shapes")
                .index,
        );
        let ask = |last: i32, buffs: i32, seed: i32| -> String {
            // §316：Spiker 只出现在 Shapes 组里；这个 helper 会找一个真的含它的种子。
            let id = shapes_session_with("spiker", 0);
            let session = slot().as_mut().expect("session");'''

OLD_BUILD = '''        assert_eq!(names, vec!["darkling", "darkling#2"], "the second one is suffixed");'''
NEW_BUILD = '''        assert_eq!(
            names,
            vec!["darkling", "darkling#2", "darkling#3"],
            "each duplicate gets the next `#<n>` suffix"
        );'''

OLD_CASES = '''        let cases: [(&str, &str, &str, [(u8, i32); 4]); 2] = [
            ("enc_spiker", "spiker", "standard.thorns", [(0, 3), (2, 4), (16, 4), (17, 7)]),
            ("enc_awakened_one", "awakened_one", "standard.regen",
             [(0, 10), (2, 10), (18, 10), (19, 15)]),
        ];
        for (encounter, who, status, points) in cases {
            for (ascension, expected) in points {
                let session = build_session_at(7, encounter, 200, None, 0, ascension)
                    .unwrap_or_else(|e| panic!("{encounter} at A{ascension}: {e}"));
                install_session(session);
                let stacks = slot()
                    .as_ref()
                    .expect("session")
                    .state
                    .combatant(&cid_in(who))'''

NEW_CASES = '''        // §316：Spiker 只在 Shapes 组里 —— `enc_three_shapes` 的候选记录带着同一组 `Asc` 行。
        let cases: [(&str, &str, &str, [(u8, i32); 4]); 2] = [
            ("enc_three_shapes", "spiker", "standard.thorns", [(0, 3), (2, 4), (16, 4), (17, 7)]),
            ("enc_awakened_one", "awakened_one", "standard.regen",
             [(0, 10), (2, 10), (18, 10), (19, 15)]),
        ];
        for (encounter, who, status, points) in cases {
            for (ascension, expected) in points {
                let who_id = if encounter == "enc_three_shapes" {
                    shapes_session_with(who, ascension)
                } else {
                    let session = build_session_at(7, encounter, 200, None, 0, ascension)
                        .unwrap_or_else(|e| panic!("{encounter} at A{ascension}: {e}"));
                    install_session(session);
                    cid_in(who)
                };
                let stacks = slot()
                    .as_ref()
                    .expect("session")
                    .state
                    .combatant(&who_id)'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    for old, new in ((OLD_SPIKER_HEAD, NEW_SPIKER_HEAD), (OLD_BUILD, NEW_BUILD),
                     (OLD_CASES, NEW_CASES)):
        assert text.count(old) == 1, old[:60]
        text = text.replace(old, new)
    anchor = '''    /// §207: a `CombatantId` from a literal, for the tests below.'''
    assert text.count(anchor) == 1
    text = text.replace(anchor, HELPER + anchor)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text)
    print('three tests adapted to the Shapes-only Spiker')


main()
