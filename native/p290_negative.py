"""§290 负控。"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    (STATE, 'gold_all only takes a fixed amount',
     '''                let all = self.gold;
                self.adjust_gold(-all);''',
     '''                self.adjust_gold(-10);''',
     'rd-run', 'gold_all_takes_everything_and_never_refuses'),
    (STATE, 'a named card bypasses push_card',
     '''                self.push_card(*row)?;''',
     '''                let slot = self.deck_len as usize;
                if slot < MAX_RUN_DECK {
                    self.deck[slot] = RunId::new(row.id).map_err(|_| RunError::BadId)?;
                    self.deck_len += 1;
                }''',
     'rd-run', 'a_named_card_goes_through_the_one_add_card_path'),
    (WASM, 'event pool hides colorless cards',
     '''    let pool = match full_pool(content(), true) {''',
     '''    let pool = match full_pool(content(), false) {''',
     'rd-wasm', 'the_nest_grants_the_dagger_and_the_gold'),
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
