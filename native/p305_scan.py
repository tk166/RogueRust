"""找 §305 注入块里的反引号 / 反斜杠（§2b 那个坑）。"""
import io

PATH = 'D:/Vibe/sts-tui/web/browser_test.mjs'
BACKTICK = chr(96)
BACKSLASH = chr(92)

s = io.open(PATH, encoding='utf-8').read()
start = s.index('  // (m) **§305')
end = s.index('  return out;', start)
block = s[start:end]
bad = 0
for index, line in enumerate(block.split(chr(10))):
    if BACKTICK in line or BACKSLASH in line:
        print(index, repr(line))
        bad += 1
print('suspect lines:', bad)
