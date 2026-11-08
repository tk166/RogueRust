"""修 README 第 208 行：bash 把反引号里的内容吃掉了（FACT §2 的原形）。

只做一件事：把 `docs/` 那一格的尾巴补回完整的五个文档名与反引号。
"""
import io

PATH = 'D:/Vibe/sts-tui/README.md'
TICK = chr(96)

OLD = ('，闸门 21；带  的五个对抗性夹具）、（事件侧缺口，§306 全面核对）、'
       '（两个机制缺口的分析与**关闭状态**） |')
NEW = ('，闸门 21；带 ' + TICK + '--selftest' + TICK + ' 的五个对抗性夹具）、'
       + TICK + 'event-gaps.md' + TICK + '（事件侧缺口，§306 全面核对）、'
       + TICK + 'mechanism-gaps-analysis.md' + TICK + '（两个机制缺口的分析记录与**关闭状态**） |')


def main():
    s = io.open(PATH, encoding='utf-8').read()
    assert s.count(OLD) == 1, s.count(OLD)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(s.replace(OLD, NEW))
    print('row 208 repaired')


main()
