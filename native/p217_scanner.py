"""§217: the coverage matrix stops flattering itself.

Three things the review (P2-A) got right, all fixed here:

1. `if not reachable and aid in everywhere` compared an action id with **dict keys** (the refactor that
   turned `everywhere` into a per-kind dict in §215 missed this line) -- the "referenced elsewhere"
   fallback could never fire.
2. The scanner did not recurse (`rd-run/src/state/archive.rs`: 8 tests invisible) and its head regex
   demanded that only `#[...]` may sit between `#[test]` and `fn` (1 test behind a doc comment,
   `rd-wasm/src/run.rs:7041` invisible).
3. Column names over-promised: `RuntimeTested` reads like "the behaviour is asserted" while it only
   means "this id is a string inside a test body". Now `TestNamed` / `HarnessOnly` / `SourceTie` /
   `DeclaredDeviation`, with a header that says no column claims behaviour.

Plus `--selftest`: five adversarial fixtures for the scanner itself.
"""
import io

P = 'native/coverage_matrix.py'
text = io.open(P, encoding='utf-8').read()


def one(old, new, what):
    global text
    assert text.count(old) == 1, '%s: expected 1, found %d' % (what, text.count(old))
    text = text.replace(old, new)


# ── 1) 注释剥离器（保留字符串）+ 递归 / 注释容错的扫描器 ──────────────────────────────────────
one('''def tests():
    """→ [(crate, fn_name, body)]。函数体按花括号配对切；`#[test]` 必须在 `fn` 头上。"""
    found = []
    head = re.compile(r'\\s*(?:#\\[[^\\]]*\\]\\s*)*fn\\s+([A-Za-z0-9_]+)')
    for crate in TEST_CRATES:
        src_dir = os.path.join(KERNEL, crate, 'src')
        if not os.path.isdir(src_dir):
            continue
        for name in sorted(os.listdir(src_dir)):
            if not name.endswith('.rs'):
                continue
            text = io.open(os.path.join(src_dir, name), encoding='utf-8',
                           errors='replace').read()
            for match in re.finditer(r'#\\[test\\]', text):
                got = head.match(text, match.end())
                if not got:
                    continue
                brace = text.find('{', got.end())
                if brace < 0:
                    continue
                skeleton = strip_rust(text[brace:])
                depth, end = 0, len(text) - 1
                for offset, ch in enumerate(skeleton):
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            end = brace + offset
                            break
                found.append((crate, got.group(1), text[brace:end + 1]))
    return found''',
    '''def tests(kernel_root=None, crates=None):
    """→ [(crate, fn_name, body)]，递归扫 `<kernel>/<crate>/src/**/*.rs`。

    §217 补的两处盲区（都是"对账"发现的，不是猜的）：

    * **不递归** ⇒ `rd-run/src/state/archive.rs` 的 8 条测试从来没被扫到；
    * **`#[test]` 与 `fn` 之间隔着 doc 注释** ⇒ 旧的 head 正则只允许中间有更多 `#[...]`，
      于是 `rd-wasm/src/run.rs:7041` 那 1 条也漏掉。

    对账：源码里 `#[test]` 共 906 处，其中 **4 处是注释里提到的**（`content.rs:4731` 等），
    真实 902；修前扫到 893（缺 9 = 8 + 1），修后 902。

    ⚠️ 注释里提到的 `#[test]` 必须**不算**测试：判据是"这个位置在 `strip_rust` 之后是空格"
    —— 那说明它落在注释或字符串里。（`strip_rust` 是等长替换，所以偏移可以直接比对。）
    """
    found = []
    root = kernel_root or KERNEL
    for crate in (crates or TEST_CRATES):
        src_dir = os.path.join(root, crate, 'src')
        if not os.path.isdir(src_dir):
            continue
        for directory, _dirs, files in os.walk(src_dir):
            for name in sorted(files):
                if not name.endswith('.rs'):
                    continue
                text = io.open(os.path.join(directory, name), encoding='utf-8',
                               errors='replace').read()
                skeleton = strip_rust(text)
                for match in re.finditer(r'#\\[test\\]', text):
                    if skeleton[match.start()] != "#":
                        continue          # 这条 `#[test]` 在注释或字符串里
                    got = head_of(text, match.end())
                    if not got:
                        continue
                    brace = text.find("{", got.end())
                    if brace < 0:
                        continue
                    depth, end = 0, len(text) - 1
                    for offset, ch in enumerate(strip_rust(text[brace:])):
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                end = brace + offset
                                break
                    found.append((crate, got.group(1), text[brace:end + 1]))
    return found


def head_of(text, position):
    """从 `#[test]` 之后找 `fn <名字>`：允许更多 `#[...]` 属性**和 doc/行注释**。

    ⚠️ 注释那一半是 §217 补的：`rd-wasm/src/run.rs:7041` 的 `#[test]` 与 `fn` 之间夹着
    `/// ...`，旧写法（只允许 `#[...]`）把那条测试整个丢掉了。
    """
    pattern = re.compile(r"\\s*(?:#\\[[^\\]\\n]*\\]\\s*|//[^\\n]*\\n\\s*)*fn\\s+([A-Za-z0-9_]+)")
    return pattern.match(text, position)


def strip_comments(text):
    """把注释替换成等长空格，**字符串原样保留**。

    为什么要与 `strip_rust` 分开：抽"测试体里出现的字符串字面量"时，注释里的 `"spiker"` 不能算
    引用（夹具 4 就是打这个）。花括号配对才需要连字符串一起抹掉。
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find(chr(10), i)
            j = n if j < 0 else j
            for position in range(i, j):
                out[position] = " "
            i = j
        elif ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for position in range(i, j):
                if out[position] != chr(10):
                    out[position] = " "
            i = j
        elif ch == '"' or (ch == "r" and i + 1 < n and text[i + 1] in '#"'):
            # 字符串整体跳过（不抹），其中的 `//` 不是注释。
            if ch == '"':
                j = i + 1
                while j < n and text[j] != '"':
                    j += 2 if text[j] == chr(92) else 1
                i = j + 1
            else:
                j, hashes = i + 1, 0
                while j < n and text[j] == "#":
                    hashes += 1
                    j += 1
                if j < n and text[j] == '"':
                    closing = '"' + "#" * hashes
                    k = text.find(closing, j + 1)
                    i = n if k < 0 else k + len(closing)
                else:
                    i += 1
        elif ch == "'":
            if i + 2 < n and text[i + 2] == "'":
                i += 3
            elif i + 2 < n and text[i + 1] == chr(92):
                j = text.find("'", i + 2)
                i = n if j < 0 else j + 1
            else:
                i += 1
        else:
            i += 1
    return "".join(out)''',
    'tests()')

# ── 2) 抽字符串字面量时先剥注释（夹具 4） ────────────────────────────────────────────────────
one('''        tokens = set()
        for match in re.finditer(r'"([^"\\\\\\n]{1,60})"', body):
            tokens.add(match.group(1))''',
    '''        tokens = set()
        # §217：先剥注释 —— 注释里写 `"spiker"` 不算引用（夹具 4 钉这个）。
        for match in re.finditer(r'"([^"\\\\\\n]{1,60})"', strip_comments(body)):
            tokens.add(match.group(1))''',
    'tests_by_entity strips comments')

# ── 3) 那个 dict 键 bug ───────────────────────────────────────────────────────────────────────
one('''        if not reachable and aid in everywhere:
            reachable, why = True, 'referenced elsewhere\'''',
    '''        # ⚠️ §217: 这里曾经写的是 `aid in everywhere` —— 而 `everywhere` 是**按类别的 dict**，
        # 于是它在比"动作 id 与 dict 的键"，永远不成立（审阅 P2-A 点出来的正是这一行）。
        if not reachable and aid in everywhere['EnemyActions']:
            reachable, why = True, 'referenced elsewhere\'''',
    'dict-key bug')

io.open(P, 'w', encoding='utf-8', newline='\n').write(text)
print('scanner patched')
