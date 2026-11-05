"""Move the §216 exec test into `mod tests` (the first attempt landed next to `empty_row`, which is
production code, so `cid`/`status` were out of scope)."""
import io

X = 'kernel/rd-core/src/exec.rs'
text = io.open(X, encoding='utf-8').read()

start_marker = '''    /// §216：`Slow` 的运算只在**有本回合牌数**的管线（伤害）里有意义。'''
end_marker = '''fn empty_row<'a>() -> Row<'a> {'''

start = text.index(start_marker)
end = text.index(end_marker)
block = text[start:end]
assert 'a_slow_spec_on_a_pipeline_without_a_card_count_is_refused' in block
text = text[:start] + text[end:]

anchor = '''    fn status(instance: &str, definition: &str, stacks: i32) -> StatusInstance {'''
assert text.count(anchor) == 1
test = block.replace('\n    /// §216', '    /// §216', 1)
text = text.replace(anchor, test + anchor)

io.open(X, 'w', encoding='utf-8', newline='\n').write(text)
print('moved into mod tests')
