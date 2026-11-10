"""§331 修上一版把测试插进**另一个测试函数体内部**的事故（FACT §3 的老坑）。

现场：`assert_eq!(effect_of("purification_shrine")[0], "remove_card");` 之后本该是
`// The roguedeck image has no UnknownRooms...` 那三行，结果我的整块测试插在中间，
于是原函数在测试块结尾的 `}` 处**提前结束**，后面三行变成了模块级的野代码 ——
而"0 passed / 812 filtered"正是它唯一的指纹（那个测试名根本没被编译进来）。

修法：把测试块整块搬走，恢复原函数，再把测试块放到**原函数之后**的模块级位置。
"""

import io

PATH = 'kernel/rd-core/src/content.rs'

# 1) 把插进去的整块（从注释头到它自己的 `}`）剪出来。
START = """    /// §331：**事件级条件** —— `EventTables` 条目的 `Requires` 在**掷之前**筛池。"""
END = """            "without facts nothing is filtered out"
        );
    }
"""

t = io.open(PATH, encoding='utf-8').read()
a = t.index(START)
b = t.index(END) + len(END)
block = t[a:b]
t = t[:a] + t[b:]
print('block cut: %d bytes' % len(block))

# 2) 现在原函数应该恢复成"effect_of(...) 之后紧跟 roguedeck 三行"。
TAIL = """        assert_eq!(effect_of("purification_shrine")[0], "remove_card");

        // The roguedeck image has **no** `UnknownRooms` key, so it has no events -- not an error."""
assert t.count(TAIL) == 1, 'tail not restored'
print('original function restored')

# 3) 把测试块放到那个函数**结束之后**：找它结尾的 `    }\n` 再往后是下一个 `///` 注释。
MARKER = """        assert_eq!(core.event_count(), 0, "roguedeck has no events");
    }
"""
assert t.count(MARKER) == 1, 'function end'
t = t.replace(MARKER, MARKER + '\n' + block, 1)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('test moved to module level')
