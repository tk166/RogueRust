"""§288 负控。"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    (WASM, 'the fight never returns to the event',
     '''        if session.state.resume_event_after_fight() {
            return 1;
        }''',
     '''        if false {
            return 1;
        }''',
     'rd-wasm', 'the_colosseum_fight_returns_and_the_victory_pays_exactly_once'),
    (CORE, 'the floor gate is ignored',
     '''            if id.is_empty() || floor < min_floor {''',
     '''            if id.is_empty() {''',
     'rd-core', 'the_unknown_room_events_are_readable'),
    (STATE, 'the exact gold is ignored',
     '''        if gold_set > 0 {''',
     '''        if false {''',
     'rd-run', 'the_fight_reward_overrides_are_exact'),
    (STATE, 'the resume is not one-shot',
     '''            self.event_resume = if fight_after.is_empty() {
                RunId::EMPTY
            } else {
                RunId::new(fight_after).map_err(|_| RunError::NoSuchEvent)?
            };''',
     '''            self.event_resume = RunId::EMPTY;''',
     'rd-run', 'a_fight_can_return_to_the_event'),
]


def run(package, test):
    out = subprocess.run(
        [CARGO, 'test', '-p', package, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True,
        encoding='utf-8', errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    failures = 0
    for path, label, old, new, package, test in CASES:
        original = io.open(path, encoding='utf-8').read()
        assert original.count(old) == 1, (label, original.count(old))
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original.replace(old, new))
        passed, text = run(package, test)
        print('%-38s -> %s' % (label, 'RED as expected' if not passed else 'STILL GREEN'))
        if passed:
            failures += 1
            print(text[-300:])
        io.open(path, 'w', encoding='utf-8', newline='\n').write(original)
    for _, _, _, _, package, test in CASES:
        passed, _ = run(package, test)
        assert passed, 'restore must make %s green again' % test
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
