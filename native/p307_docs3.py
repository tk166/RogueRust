"""README 的 docs 表格：补上 `event-gaps.md` / `mechanism-gaps-analysis.md`，改正闸门号。"""
import io

PATH = 'D:/Vibe/sts-tui/README.md'
OLD = '，闸门 13；带 `--selftest` 的五个对抗性夹具） |'
NEW = ('，闸门 21；带 `--selftest` 的五个对抗性夹具）、'
       '`event-gaps.md`（事件侧缺口，§306 全面核对）、'
       '`mechanism-gaps-analysis.md`（两个机制缺口的分析记录与**关闭状态**） |')


def main():
    s = io.open(PATH, encoding='utf-8').read()
    assert s.count(OLD) == 1, s.count(OLD)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(s.replace(OLD, NEW))
    print('ok')


main()
