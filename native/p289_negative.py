"""§289 负控。"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    (STATE, 'the named relic falls back to the weighted pick',
     '''        if !named_relic.as_str().is_empty() {''',
     '''        if false {''',
     'rd-run', 'a_named_relic_is_paid_exactly_or_not_at_all'),
    (STATE, 'the independent roll moves the tracker',
     '''        if !independent {''',
     '''        if true {''',
     'rd-run', 'an_independent_potion_chance_leaves_the_tracker_alone'),
    (CORE, 'the upper bound is ignored',
     '''            if id.is_empty() || floor < min_floor || (max_floor != 0 && floor > max_floor) {''',
     '''            if id.is_empty() || floor < min_floor {''',
     'rd-core', 'the_unknown_room_events_are_readable'),
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
        print('%-44s -> %s' % (label, 'RED as expected' if not passed else 'STILL GREEN'))
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
