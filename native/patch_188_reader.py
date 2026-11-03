"""§188 part 2: `MAX_EVENT_EFFECTS`, the effect-list reader, and the error it can raise."""
import io

PATH = "kernel/rd-core/src/content.rs"

CAP = '''pub const F_JSON: u8 = 7;

/// §188：一个事件选项最多有几条效果。
///
/// 四条是**容量**，不是规则：超了就是内容错误（`ContentError::TooManyEventEffects`），
/// **不截断** —— 截断会把"遗物 + 诅咒 + 金币"悄悄变成两条，而屏幕上仍然显示三条的文案。
pub const MAX_EVENT_EFFECTS: usize = 4;'''

READER = '''    /// 读一个效果列表（`_arr` of `_obj{Effect: F_STR, Amount: F_INT}`，§188）。
    ///
    /// 返回条数。缺席/null 是**合法的空列表**（"这个选项没有效果"），但**越界**不是：
    /// 超过 [`MAX_EVENT_EFFECTS`] 直接报错，不截断。
    fn effect_list(
        &self,
        cell: u16,
        out: &mut [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    ) -> Option<u8> {
        if cell == ABSENT16 || cell == NULL16 {
            return Some(0);
        }
        let term = self.term(cell)?;
        if term.op != OP_ARR {
            return None;
        }
        let start = term.slot(0)?;
        let count = term.slot(1)?;
        if count == LIST_ABSENT || count == LIST_NULL {
            return Some(0);
        }
        let count = usize::from(count);
        if count > MAX_EVENT_EFFECTS {
            return None;
        }
        for index in 0..count {
            let element = self.aux(start.checked_add(index as u16)?)?;
            let node = NodeRef::new(self, element);
            let effect = node.str_field("Effect")?.unwrap_or("nothing");
            let amount = node.int_field("Amount")?.unwrap_or(0);
            out[index] = EffectSpec {
                effect,
                amount: i16::try_from(amount).unwrap_or(0),
            };
        }
        Some(count as u8)
    }

    /// An `F_INT` cell as a number. `ABSENT16` / `NULL16` are zero; everything else is `i16`.'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    if "MAX_EVENT_EFFECTS" not in text:
        assert text.count("pub const F_JSON: u8 = 7;") == 1
        text = text.replace("pub const F_JSON: u8 = 7;", CAP)
        print("capacity constant added")
    if "fn effect_list(" not in text:
        anchor = """    /// An `F_INT` cell as a number. `ABSENT16` / `NULL16` are zero; everything else is `i16`."""
        assert text.count(anchor) == 1
        text = text.replace(anchor, READER)
        print("effect-list reader added")
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)


if __name__ == "__main__":
    main()
