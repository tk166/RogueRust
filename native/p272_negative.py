"""§272 负控：证明判据会红。

四处切口：
  1. 概率公式：把 `+ 1` 去掉（"每次都按基础概率"）→ 概率判据该红；
  2. 掷骰：把前缀累加改成三个独立判定（`roll < monster || roll < shop …` 之类）→ 分布判据该红；
  3. `tiny_chest`：把覆盖结果那一句删掉 → `tiny_chest_and_juzu_bracelet_change_the_roll` 该红；
  4. `?` 战斗：把 `fight_begin` 的 `unknown_fight` 放行删掉 → wasm 那条判据该红。
"""
import io
import subprocess
import sys

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
CARGO = r'C:\Users\TK11\.cargo\bin\cargo.exe'

CASES = [
    ('odds formula', STATE,
     '''            (UNKNOWN_MONSTER_BASE * (1 + self.unknown[0])).min(100)''',
     '''            (UNKNOWN_MONSTER_BASE * (1 + self.unknown[0] * 0)).min(100)''',
     'rd-run', 'the_unknown_room_odds_walk_the_wikis_base_values', 'formula'),
    ('roll bands', STATE,
     '''        let mut outcome = if roll < monster {
            UnknownRoom::Monster
        } else if roll < monster + shop {
            UnknownRoom::Shop
        } else if roll < monster + shop + treasure {
            UnknownRoom::Treasure
        } else {
            UnknownRoom::Event
        };''',
     '''        let mut outcome = if roll % 3 == 0 {
            UnknownRoom::Monster
        } else if roll % 3 == 1 {
            UnknownRoom::Event
        } else if roll < monster + shop + treasure {
            UnknownRoom::Treasure
        } else {
            UnknownRoom::Event
        };''',
     # ⚠️ 这条要打**分布**判据（`the_unknown_room_roll_matches_the_odds`），不是公式判据：
     # 公式判据不掷骰，把掷骰改坏它当然还是绿的 —— 负控第一次就点错了判据。
     'rd-run', 'the_unknown_room_roll_matches_the_odds', 'bands'),
    ('tiny chest force', STATE,
     '''        if self.holds_relic_effect(RelicEffect::TinyChestEveryFourth) {
            self.tiny_chest_rooms += 1;
            if self.tiny_chest_rooms >= TINY_CHEST_ROOMS {
                self.tiny_chest_rooms = 0;
                outcome = UnknownRoom::Treasure;
            }''',
     '''        if self.holds_relic_effect(RelicEffect::TinyChestEveryFourth) {
            self.tiny_chest_rooms += 1;
            if self.tiny_chest_rooms >= TINY_CHEST_ROOMS {
                self.tiny_chest_rooms = 0;
            }''',
     'rd-run', 'tiny_chest_and_juzu_bracelet_change_the_roll', 'tiny chest'),
    ('unknown fight gate', WASM,
     '''    if kind != 1 && kind != 2 && kind != 7 && !unknown_fight {''',
     '''    if kind != 1 && kind != 2 && kind != 7 {''',
     'rd-wasm', 'an_unknown_room_can_start_an_ordinary_fight', 'fight gate'),
]


def run(pkg, test):
    out = subprocess.run(
        [CARGO, 'test', '-p', pkg, '--release',
         '--target-dir', 'D:/Vibe/sts-tui/kernel/target-mine',
         '--', '--test-threads=1', '--quiet', test],
        cwd='D:/Vibe/sts-tui/kernel', capture_output=True, text=True, encoding='utf-8',
        errors='replace')
    text = out.stdout + out.stderr
    return '1 passed' in text, text


def main():
    originals = {}
    failures = 0
    for name, path, old, new, pkg, test, why in CASES:
        if path not in originals:
            originals[path] = io.open(path, encoding='utf-8').read()
        base = originals[path]
        assert base.count(old) == 1, '%s: anchor %d' % (name, base.count(old))
        io.open(path, 'w', encoding='utf-8', newline='\n').write(base.replace(old, new))
        ok, text = run(pkg, test)
        red = (not ok) and ('FAILED' in text or 'panicked' in text)
        print('%-20s -> %s  (%s)' % (name, 'RED as expected' if red else 'STILL GREEN', why))
        if not red:
            failures += 1
            print(text[-1200:])
        io.open(path, 'w', encoding='utf-8', newline='\n').write(base)
    print('restored; negative controls that failed to go red:', failures)
    sys.exit(1 if failures else 0)


main()
