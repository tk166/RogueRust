"""修闸门 33 里被我的括号补丁弄坏的 try/catch。"""

import io

P = 'native/ui_scene_check.mjs'
t = io.open(P, encoding='utf-8').read()

start = t.index('                for (const actionCount of [0, 3]) {')
end = t.index('  check(thrown === 0,')

block = '''                for (const actionCount of [0, 3]) {
                  for (const bossBeaten of [false, true]) {
                    total += 1;
                    try {
                      const got = resolveScene({
                        runExists,
                        inFight,
                        hasCombatSession,
                        pending,
                        over,
                        bossBeaten,
                        nodeKind,
                        nodeResolved,
                        unknownRoom: 0,
                        eventFight: 0,
                        actionCount,
                        pickupPicks: 0,
                        pickupAdd: 0,
                      });
                      if (typeof got.base !== "string") throw new Error("base 不是字符串");
                      if (!allScenes.has(got.base)) throw new Error(`未知 base ${got.base}`);
                      seen.add(got.base);
                      // `unknownPending` 只在 pending 越界时非 null。
                      const wantUnknown = pending < 0 || pending > 9;
                      if ((got.unknownPending !== null) !== wantUnknown) {
                        throw new Error(`unknownPending=${got.unknownPending} 与 pending=${pending} 不符`);
                      }
                    } catch (cause) {
                      thrown += 1;
                      if (thrown <= 3) console.log("   抛了:", String(cause));
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
'''
t = t[:start] + block + t[end:]
io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
print('gate33 loop fixed')
