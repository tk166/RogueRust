"""§332 负控：三处各弄坏一次，判据必须红在**预期位置**。

1. **无色贵 20%** 改回普通价目 ⇒ 字面量断言 `wiki: 162-198`；
2. **遗物价目按稀有度** 改回"一律 143-158" ⇒ `wiki: 238-263`；
3. **"Shop 档只走最右"** 整条拿掉（最右不强制 + 三格都允许 Shop）⇒
   `only the rightmost slot may hold a Shop relic`。

⚠️ 第 1/2 条能红，靠的是判据里那份**字面量**（wiki 的数字）；如果判据只用
`*_price_band()` 去算期望区间，改坏那个函数时判据会跟着改坏 —— 负控第一次跑就是这样
"三条全 NOT CAUGHT"（§332 记录）。
"""

import io
import subprocess
import sys

STATE = 'kernel/rd-run/src/state.rs'


def run():
    p = subprocess.run(
        ['cargo', 'test', '-p', 'rd-run', '--release', '--', '--test-threads=1',
         'a_shop_stocks_all_four'],
        cwd='kernel', capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.stdout + p.stderr


def mutate(label, pairs, needle):
    raw = io.open(STATE, encoding='utf-8').read()
    broken = raw
    for old, new in pairs:
        assert broken.count(old) == 1, '%s: anchor %r' % (label, old[:60])
        broken = broken.replace(old, new)
    ok = False
    try:
        io.open(STATE, 'w', encoding='utf-8', newline='\n').write(broken)
        out = run()
        ok = needle in out
        print('  %-52s %s' % (label, 'RED at %r' % needle if ok else 'NOT CAUGHT'))
        if not ok:
            for line in out.splitlines():
                if 'error[' in line or 'panicked' in line:
                    print('      ', line.strip()[:120])
                    break
    finally:
        io.open(STATE, 'w', encoding='utf-8', newline='\n').write(raw)
    return ok


ok = True

ok &= mutate(
    '① 无色价目改回普通价目',
    [("""        Rarity::Rare => (162, 198),""", """        Rarity::Rare => (135, 165),""")],
    'wiki: 162-198',
)

ok &= mutate(
    '② 遗物价目改回一律 143-158',
    [("""        Rarity::Rare => (285, 315),
        Rarity::Uncommon => (238, 263),""",
      """        Rarity::Rare => (143, 158),
        Rarity::Uncommon => (143, 158),""")],
    'wiki: 238-263',
)

ok &= mutate(
    '③ "Shop 档只走最右"整条拿掉（先撞“最右必为 Shop”那句）',
    [("            let last = slot + 1 == MAX_SHOP_RELICS;", "            let last = false;"),
     ("""                self.pick_shop_relic_no_shop(RunStream::Shop, relic_pool, &shelved[..slot])?
            };""",
      """                self.pick_shop_relic_avoiding(RunStream::Shop, relic_pool, &shelved[..slot])?
            };""")],
    'Shop relic',
)

out = run()
print('  还原后：%s' % ('green' if 'test result: ok' in out else 'STILL RED'))
print('NEGATIVE CONTROL', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
