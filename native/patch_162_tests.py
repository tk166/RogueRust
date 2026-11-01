"""§162: `restore` asks `validate` before committing, and the tests that make it falsifiable.

Two directions:
  * **a real run validates at every step** —— 一个太严的校验器比没有更糟（它会把真人的局面判成非法）。
    这条走一整幕、每一步都问一次。
  * **每个不变量各有一条反例** —— 而且存档那条用"CRC 合法但状态非法"来测：先把一个非法状态
    `write` 出来（CRC 是照着它算的，所以一定对），`restore` 必须拒。
"""
import io

ARCHIVE = "kernel/rd-run/src/state/archive.rs"
STATE = "kernel/rd-run/src/state.rs"


def main():
    # ---- 1. ArchiveError gains an Invariant variant ----------------------------------------
    text = io.open(ARCHIVE, encoding="utf-8").read()

    def sub(old, new, count=1):
        nonlocal text
        assert text.count(old) == count, (text.count(old), old[:60])
        text = text.replace(old, new)

    sub(
        """    /// payload 读完了还有剩余字节 —— 这不是这个版本的产物。
    Trailing,
}""",
        """    /// payload 读完了还有剩余字节 —— 这不是这个版本的产物。
    Trailing,
    /// 解析成功，但这一局**自相矛盾**（`RunState::validate`）。名字指出是哪一条。
    ///
    /// 与 `BadField` 分开：那一类是"字节不对劲"，这一类是"字节都对，但这样的局面不可能存在"。
    /// CRC 只证明前者；后者只有整局的不变量能证明。
    Invariant(&'static str),
}""",
    )
    sub(
        """            Self::Trailing => f.write_str("archive has trailing bytes"),""",
        """            Self::Trailing => f.write_str("archive has trailing bytes"),
            Self::Invariant(what) => write!(f, "archive state is inconsistent: {what}"),""",
    )

    # ---- 2. restore validates before committing --------------------------------------------
    sub(
        """    let restored = read_payload(&payload[..payload_len])?;
    *state = restored;
    Ok(())""",
        """    let restored = read_payload(&payload[..payload_len])?;
    // §162：**提交前**问一次整局的不变量。CRC 证明"没被改坏"，这一句证明"这样的一局可能存在"。
    restored.validate().map_err(|error| match error {
        crate::streams::RunError::Invariant(what) => ArchiveError::Invariant(what),
        _ => ArchiveError::Invariant("validate"),
    })?;
    *state = restored;
    Ok(())""",
    )

    # ---- 3. the tests ----------------------------------------------------------------------
    sub(
        """    #[test]
    fn an_edited_or_truncated_archive_is_refused_not_guessed() {""",
        '''    /// **CRC 合法、状态非法**：`write` 一个自相矛盾的局，它的校验和当然是"对的"，
    /// 所以拒绝只能来自不变量（§162）。
    #[test]
    fn an_archive_whose_state_is_impossible_is_refused_even_with_a_valid_checksum() {
        let mut run = sample();
        // 血量超过上限：一个任何动作都造不出来的局面。
        run.health_max = 40;
        run.health = 41;
        let mut out = [0u8; MAX_ARCHIVE];
        let len = write(&run, &mut out).expect("write");
        let text = core::str::from_utf8(&out[..len]).expect("ascii");
        let mut target = sample();
        assert_eq!(
            restore(text, &mut target),
            Err(ArchiveError::Invariant("health must be in 0..=health_max")),
            "a checksum-valid archive of an impossible state must still be refused"
        );
        assert_eq!(target, sample(), "and the run is untouched");
    }

    #[test]
    fn an_edited_or_truncated_archive_is_refused_not_guessed() {''',
    )

    io.open(ARCHIVE, "w", encoding="utf-8", newline="").write(text)

    # ---- 4. the state-level tests ----------------------------------------------------------
    state = io.open(STATE, encoding="utf-8").read()
    anchor = "    #[test]\n    fn a_new_run_is_before_the_map_with_a_known_start() {"
    assert state.count(anchor) == 1, state.count(anchor)
    assert "fn a_real_run_validates_at_every_step" not in state, "already inserted"

    tests = '''    /// **真人的局面必须通过校验器**（§162）。太严的校验器比没有更糟。
    ///
    /// 走一整幕：每个节点都结算，每一步都问一次。这条测试存在的理由是"我加的那些不变量是从代码
    /// 里读出来的，而代码里有我不知道的例外" —— 只有真跑一遍才知道有没有。
    #[test]
    fn a_real_run_validates_at_every_step() {
        let mut run = ironclad();
        run.validate().expect("a fresh run");
        // 出发前：挑一个第一层的节点。
        let mut steps = 0;
        for _ in 0..40 {
            let mut moved = false;
            for target in 0..crate::map::BOSS_NODE {
                if run.enter_node(target).is_ok() {
                    moved = true;
                    break;
                }
            }
            if !moved {
                break;
            }
            run.validate().unwrap_or_else(|e| panic!("step {steps}: {e:?}"));
            // 结算这个节点：按类型走一条最便宜的合法路径。
            match run.node_at_cursor() {
                Some(NodeKind::Rest) => {
                    run.validate().expect("a rest site is pending");
                    run.rest().expect("rest");
                }
                Some(NodeKind::Treasure) => {
                    run.validate().expect("a chest is pending");
                    run.open_chest(&RELICS).expect("open");
                    run.validate().expect("after the chest");
                    run.leave().expect("leave");
                }
                Some(NodeKind::Shop) => {
                    run.validate().expect("a shop is pending");
                    run.leave().expect("leave");
                }
                _ => {}
            }
            run.mark_resolved();
            run.validate().unwrap_or_else(|e| panic!("resolved {steps}: {e:?}"));
            steps += 1;
            if run.node() == i32::from(crate::map::BOSS_NODE) {
                break;
            }
        }
        assert!(steps >= 8, "the fixture must actually walk, it took {steps} steps");
    }

    /// 每条不变量各一条反例，而且都指名它自己。**一条断言一个原因** —— 否则"拒绝了"什么都证明不了。
    #[test]
    fn every_invariant_names_itself_when_violated() {
        let base = || ironclad();

        let mut run = base();
        run.health = run.health_max + 1;
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("health must be in 0..=health_max"))
        );

        let mut run = base();
        run.gold = -1;
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("gold must not be negative"))
        );

        let mut run = base();
        run.act = 0;
        assert_eq!(run.validate(), Err(RunError::Invariant("act must be in 1..=MAX_ACTS")));

        let mut run = base();
        run.floor = 3;
        assert_eq!(run.validate(), Err(RunError::Invariant("no cursor means floor 0")));

        let mut run = base();
        run.node = 99;
        assert!(matches!(
            run.validate(),
            Err(RunError::Invariant("cursor is not on the map"))
        ));

        // 楼层与游标不一致：走到某一层，然后把楼层改掉。
        let mut run = base();
        assert!(run.enter_node(0).is_ok() || run.enter_node(1).is_ok() || run.enter_node(2).is_ok());
        run.floor += 1;
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("floor disagrees with the cursor's row"))
        );

        // §161.10 的那个坑：`len` 之后不是空的。
        let mut run = base();
        let stale = run.deck[run.deck_len as usize - 1];
        run.deck[run.deck_len as usize] = stale;
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("a deck slot past len is not empty"))
        );

        // 同一件遗物两份。
        let mut run = base();
        run.relics_len = 2;
        run.relics[0] = run.relics[1];
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("the same relic is held twice"))
        );

        // 药水比腰带格数多（没有 Potion Belt 就是 3 格）。
        let mut run = base();
        run.potions_len = run.potion_slots() + 1;
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("more potions than the belt has slots"))
        );

        // 问句与房间不一致：把 pending 设成 Rest 而脚下是战斗。
        let mut run = base();
        assert!(run.enter_node(0).is_ok() || run.enter_node(1).is_ok() || run.enter_node(2).is_ok());
        run.pending = Pending::Rest;
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("the pending screen is not this room"))
        );

        // 后续动作与问句脱钩。
        let mut run = base();
        run.event_follow = Some(DeckChange::Remove);
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("an event follow-up without its question"))
        );

        // 祝福不在表里。
        let mut run = base();
        run.start_offers = [0, 200];
        assert_eq!(
            run.validate(),
            Err(RunError::Invariant("a rolled blessing is not in the table"))
        );

        // 商店的空格子被当成活的报价。
        let mut run = base();
        run.pending = Pending::Shop;
        run.shop.cards_len = 1;
        run.shop.cards[0].price = -1;
        assert!(matches!(run.validate(), Err(RunError::Invariant(_))));
    }

'''
    state = state.replace(anchor, tests + anchor)
    io.open(STATE, "w", encoding="utf-8", newline="").write(state)
    print("validate wired into restore + tests in both crates")


if __name__ == "__main__":
    main()
