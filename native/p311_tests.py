"""§311（七）：两条判据 —— 三只 byrd 的 Flying 各自独立、Spheric Guardian 的开场状态。

第一条是**为刚修的那个 bug**写的：`flying_...` 只读了一只 byrd，所以"三份起始状态叠在
第一只身上"（9 层）与"每只各 3 层"在它眼里**同色**（读的都是 `byrd`，而且 9−1=8 也只是
让那条"剩 2 层"的断言红）。逐只断言才是这条规则的判据。

第二条把 Spheric Guardian 的三样开场状态钉住：Block 40（`StartingBlock`）、Artifact 3、
Barricade 1，以及"第一招是 Activate"。
"""
import io

PATH = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/lib.rs'

TESTS = '''
    /// §311：**三只 byrd 各自的 Flying**。
    ///
    /// 这条判据存在的理由：把 `enc_byrds` 从 1 只改成 3 只之后，`flying_...` 那一条当场红
    /// （读到 8 层），根因是 `apply_starting_statuses` 拿 **plain** id 去挂状态 —— 三份
    /// `StartingStatuses` 全叠到 `byrd` 身上，`byrd#2` / `byrd#3` 一层都没有。
    /// 只读一只的判据区分不了"每只各 3 层"与"一只 9 层"，所以这里**逐只**读。
    #[test]
    fn three_byrds_each_start_with_their_own_flying() {
        let session = build_session_at(11, "enc_byrds", 200, None, 0, 0)
            .expect("the byrd fight builds");
        install_session(session);
        let session = slot().as_ref().expect("session");
        let flying = |name: &str| -> Option<i32> {
            session.state.combatant(&cid_in(name)).map(|combatant| {
                combatant
                    .statuses()
                    .iter()
                    .filter(|status| status.definition_id.as_str() == "standard.flying")
                    .map(|status| status.stacks)
                    .sum()
            })
        };
        assert_eq!(flying("byrd"), Some(3), "the first byrd");
        assert_eq!(flying("byrd#2"), Some(3), "the second byrd is its own instance");
        assert_eq!(flying("byrd#3"), Some(3), "the third byrd too");
        take_session();
    }

    /// §311：Spheric Guardian 的开场 —— 40 Block / Artifact 3 / Barricade 1，第一招 Activate。
    ///
    /// 三样里有一样是**新基建**（`StartingBlock`），两样是状态；wiki 把三条都写在 `Powers` 列。
    #[test]
    fn the_spheric_guardian_starts_with_block_artifact_and_barricade() {
        let session = build_session_at(13, "enc_spheric_guardian", 200, None, 0, 0)
            .expect("the spheric guardian fight builds");
        install_session(session);
        let session = slot().as_ref().expect("session");
        let combatant = session.state.combatant(&cid_in("spheric_guardian"))
            .expect("the guardian is on the field");
        let block = combatant
            .defensive_pools()
            .iter()
            .find(|pool| pool.key.as_str() == "standard.block")
            .map_or(0, |pool| pool.pool.current);
        assert_eq!(block, 40, "wiki: Block 40");
        let stacks = |status_id: &str| -> i32 {
            combatant
                .statuses()
                .iter()
                .filter(|status| status.definition_id.as_str() == status_id)
                .map(|status| status.stacks)
                .sum()
        };
        assert_eq!(stacks("standard.artifact"), 3, "wiki: Artifact 3");
        assert_eq!(stacks("standard.barricade"), 1, "wiki: Barricade");
        // 第一招必须是 Activate（wiki: "always starts with Activate"）。
        let action = {
            let session = slot().as_mut().expect("session");
            rd_core::intent::select_action(
                &session.state,
                &content(),
                &cid_in("spheric_guardian"),
                1,
            )
            .expect("intent")
            .expect("an action")
            .action_id
        };
        assert_eq!(action, "spheric_guardian.activate", "round 1 is Activate");
        take_session();
    }
'''


def main():
    text = io.open(PATH, encoding='utf-8').read()
    anchor = '''    /// §208：Byrd 的 Flying —— **攻击**伤害减半，每被打一次掉一层；DoT 不算"被打"。'''
    assert text.count(anchor) == 1
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(text.replace(anchor, TESTS + '\n' + anchor))
    print('tests added')


main()
