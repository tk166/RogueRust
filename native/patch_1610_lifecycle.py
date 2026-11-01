"""§161.10: the fight lifecycle becomes an **explicit** flag on the run session.

`crate::slot().is_some()` was never a valid "a fight is in progress": the page boots a fight session
(`rd_env_reset`) before any fight, so the check was true from page load — my first attempt at the
guard refused every archive for a reason that was simply false.

So the run session carries the fact, and the two ABI calls that own the lifecycle maintain it:
`rd_run_fight_begin` sets it, `rd_run_fight_end` and `rd_run_start` clear it. The archive and the
restore ask **that**, which makes the guard authoritative (a host calling the ABI directly is refused
too) and leaves the page's `mode` check as pure user feedback.
"""
import io

PATH = "kernel/rd-wasm/src/run.rs"


def main():
    text = io.open(PATH, encoding="utf-8").read()

    def sub(old, new, count=1):
        nonlocal text
        assert text.count(old) == count, (text.count(old), old[:70])
        text = text.replace(old, new)

    # ---- the field -------------------------------------------------------------------------
    sub(
        '''    /// Was this fight started from an **elite** node? `fight_end` needs it for the reward tier
    /// (`inv:§5`: elite pays 25–35 gold, rare 10/40/50) and the cursor no longer says so.
    elite_fight: bool,
}''',
        '''    /// Was this fight started from an **elite** node? `fight_end` needs it for the reward tier
    /// (`inv:§5`: elite pays 25–35 gold, rare 10/40/50) and the cursor no longer says so.
    elite_fight: bool,
    /// Is a fight **in progress** right now? (§161.10)
    ///
    /// ⚠️ This is **not** "does a combat session exist": the page creates one at boot
    /// (`rd_env_reset`) so the fight view has something to draw, which made session-presence true
    /// from page load — a guard built on it refused every archive with a reason that was false.
    /// It is set by [`rd_run_fight_begin`] and cleared by [`rd_run_fight_end`] / [`rd_run_start`],
    /// so "a fight is running" has exactly one meaning and only the calls that own it move it.
    in_fight: bool,
}''',
    )

    # ---- every construction site ------------------------------------------------------------
    sub(
        '''        boss_fight: false,''',
        '''        boss_fight: false,
        in_fight: false,''',
        count=2,
    )

    # ---- the three transitions --------------------------------------------------------------
    sub(
        '''    session.boss_fight = kind == 7;''',
        '''    session.boss_fight = kind == 7;
    session.in_fight = true;''',
    )
    sub(
        '''    let boss_fight = run_slot().as_ref().is_some_and(|s| s.boss_fight);''',
        '''    let boss_fight = run_slot().as_ref().is_some_and(|s| s.boss_fight);
    if let Some(session) = run_slot().as_mut() {
        session.in_fight = false;
    }''',
    )
    sub(
        '''    crate::take_session();
    let content = content();''',
        '''    crate::take_session();
    // A new run is never mid-fight (§161.10): clear the bit here as well as the session, because a
    // page can start a run from the game-over screen while the old fight's flag is still set.
    if let Some(session) = run_slot().as_mut() {
        session.in_fight = false;
    }
    let content = content();''',
    )

    # ---- the guards ask the flag ------------------------------------------------------------
    sub(
        '''    if crate::slot().is_some() {
        set_error("战斗中没有存档：这份档案只描述整局，回档会让敌人满血。先打完这一场。");
        return -2;
    }''',
        '''    if session.in_fight {
        set_error("战斗中没有存档：这份档案只描述整局，回档会让敌人满血。先打完这一场。");
        return -2;
    }''',
    )
    sub(
        '''    if crate::slot().is_some() {
        set_error("战斗中没有回档：先打完这一场，或者重开一局。");
        return -2;
    }
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    let mut restored = *session.state;''',
        '''    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    if session.in_fight {
        set_error("战斗中没有回档：先打完这一场，或者重开一局。");
        return -2;
    }
    let mut restored = *session.state;''',
    )

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("in_fight flag: set on begin, cleared on end/start, asked by archive+restore")


if __name__ == "__main__":
    main()
