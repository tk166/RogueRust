"""§278：`content.rs` 里事件读取器整段重写（EventChoice -> EventOption + 分段）。"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'

OLD_START = '''/// One choice of a `?`-room event: the button text, the effect's name, and its amount.'''

# 老的 event 段：从 EventChoice 的文档注释到 effect_list 结束（含末尾的 `}` 前的 effect_list 整体）
NEW = '''/// §278：一个事件选项 —— 按钮文字、效果列表（§188 的形状）、以及**后继**。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct EventOption<'a> {
    /// What the button says.
    pub label: &'a str,
    /// The effects, in order (§188). `heal` / `gold` / `damage` / `max_hp` / `nothing` /
    /// `remove_card` / `upgrade_card` / `transform_card` / `curse:<id>` / `relic:<id>` -- a
    /// **closed** vocabulary, because the run layer has no program interpreter.
    pub effects: [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    /// How many of `effects` are real.
    pub count: u8,
    /// The A15 variant (wiki: *Unfavorable Events*). `asc_count == 0` = none: the base list applies
    /// at every level.
    pub asc: [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    /// How many of `asc` are real.
    pub asc_count: u8,
    /// §278：下一段的节点 id。**空串 = 这一段是终点**（选项生效后事件收尾）。
    pub next: &'a str,
}

impl<'a> EventOption<'a> {
    /// The list that applies at `ascension`: the A15 variant when the row has one, else the base.
    #[must_use]
    pub fn effects_at(&self, ascension: u8, a15: u8) -> &[EffectSpec<'a>] {
        if self.asc_count > 0 && ascension >= a15 {
            &self.asc[..usize::from(self.asc_count)]
        } else {
            &self.effects[..usize::from(self.count)]
        }
    }

    /// §278：这个选项是否把事件带向另一段。
    #[must_use]
    pub fn goes_on(&self) -> Option<&'a str> {
        if self.next.is_empty() {
            None
        } else {
            Some(self.next)
        }
    }
}

/// §278：事件的**一段** —— 正文 + 若干选项。事件是一棵树，`EV.Entry` 指向第一段。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct EventStep<'a> {
    /// 这一段的正文。
    pub text: &'a str,
    /// 选项（前 [`EventStep::count`] 条有效）。
    pub options: [EventOption<'a>; MAX_EVENT_OPTIONS],
    /// 选项条数。
    pub count: u8,
}

impl<'a> EventStep<'a> {
    /// 有效的选项切片。
    #[must_use]
    pub fn options(&self) -> &[EventOption<'a>] {
        &self.options[..usize::from(self.count)]
    }

    /// `Empty` 实现要一个 const：一个"没有正文也没有选项"的段。
    pub const EMPTY: Self = Self {
        text: "",
        options: [EventOption {
            label: "",
            effects: [EffectSpec {
                effect: "nothing",
                amount: 0,
            }; MAX_EVENT_EFFECTS],
            count: 0,
            asc: [EffectSpec {
                effect: "nothing",
                amount: 0,
            }; MAX_EVENT_EFFECTS],
            asc_count: 0,
            next: "",
        }; MAX_EVENT_OPTIONS],
        count: 0,
    };
}

/// One event effect: a closed-vocabulary word (with an optional `:` payload) and its amount.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EffectSpec<'a> {
    pub effect: &'a str,
    pub amount: i16,
}

impl crate::state::Empty for EffectSpec<'_> {
    const EMPTY: Self = Self {
        effect: "nothing",
        amount: 0,
    };
}

impl<'a> Content<'a> {
    /// `EV` 表的行数（= 事件的个数）。
    ///
    /// `count` is the table's row count; a row whose id cannot be read is skipped rather than
    /// reported as an empty event -- `usize::MAX` marks "unreadable" so a caller cannot mistake it
    /// for a valid event with no text.
    #[must_use]
    pub fn event_count(&self) -> u32 {
        self.section(S_EV).map_or(0, |section| section.count)
    }

    /// `EVND` 表的行数（= 事件段的总数）。
    #[must_use]
    pub fn event_step_count(&self) -> u32 {
        self.section(S_EVND).map_or(0, |section| section.count)
    }

    /// Event `index`: its id, its name, and the id of its **first step**.
    ///
    /// §278：正文不在这一层了 —— 一句话属于**某一段**，而一段事件可以有多段。要正文请用
    /// [`Content::event_step`]，它按节点 id 取。
    #[must_use]
    pub fn event(&'a self, index: u32) -> Option<(&'a str, &'a str, &'a str)> {
        let row = EvRow::new(self.row(Table::Event, index)?)?;
        let id = self.string(row.id())?;
        let name = self
            .string(row.name_key())
            .filter(|name| !name.is_empty())
            .unwrap_or(id);
        // 空 `Entry` 是内容错误（它会让页面显示一个没有任何按钮的房间），所以这里返回
        // `None` 而不是"一个没有正文的事件"。
        let entry = self.string(row.entry()).filter(|entry| !entry.is_empty())?;
        Some((id, name, entry))
    }

    /// §278：按节点 id 取一段事件。`None` = 内容里没有这一段。
    #[must_use]
    pub fn event_step(&'a self, node: &str) -> Option<EventStep<'a>> {
        let count = self.event_step_count();
        for index in 0..count {
            let row = EvndRow::new(self.row(Table::EventNode, index)?)?;
            if self.string(row.id())? != node {
                continue;
            }
            let text = self
                .string(row.text_key())
                .filter(|text| !text.is_empty())
                .unwrap_or("");
            let mut step = EventStep::EMPTY;
            step.text = text;
            let list = self.option_list(row.options(), &mut step.options)?;
            // `option_list` 已经把条数写进 `step.count`。
            let _ = list;
            return Some(step);
        }
        None
    }

    /// 读一个选项列表（`_arr` of `_obj{Label: F_STR, Effects: arr, EffectsAsc: arr, Next: F_STR}`）。
    ///
    /// 返回条数（同时写进 `out[..count]`）。缺席/null 是**合法的空列表**，但**越界**不是：
    /// 超过 [`MAX_EVENT_OPTIONS`] 直接报错，不截断。
    fn option_list(
        &'a self,
        cell: u16,
        out: &mut [EventOption<'a>; MAX_EVENT_OPTIONS],
    ) -> Option<u8> {
        let (start, count) = self.list_bounds(cell)?;
        let count = usize::from(count);
        if count > MAX_EVENT_OPTIONS {
            return None;
        }
        for index in 0..count {
            let element = self.aux(start.checked_add(index as u16)?)?;
            let node = crate::ir::NodeRef::new(self, element);
            let mut option = EventOption {
                label: node.str_field("Label").ok().flatten().unwrap_or(""),
                effects: [crate::state::Empty::EMPTY; MAX_EVENT_EFFECTS],
                count: 0,
                asc: [crate::state::Empty::EMPTY; MAX_EVENT_EFFECTS],
                asc_count: 0,
                next: node.str_field("Next").ok().flatten().unwrap_or(""),
            };
            let base = node.term_field("Effects").ok().flatten().unwrap_or(ABSENT16);
            let asc = node
                .term_field("EffectsAsc")
                .ok().flatten()
                .unwrap_or(ABSENT16);
            option.count = self.effect_list(base, &mut option.effects)?;
            option.asc_count = self.effect_list(asc, &mut option.asc)?;
            out[index] = option;
        }
        Some(count as u8)
    }

    /// 一个列表 term 的 `(起址, 条数)`；缺席/null ⇒ `Some((0, 0))`，形状不对 ⇒ `None`。
    fn list_bounds(&self, cell: u16) -> Option<(u16, u16)> {
        if cell == ABSENT16 || cell == NULL16 {
            return Some((0, 0));
        }
        let term = self.term(cell)?;
        if term.op != OP_ARR {
            return None;
        }
        let start = term.slot(0)?;
        let count = term.slot(1)?;
        if count == LIST_ABSENT || count == LIST_NULL {
            return Some((0, 0));
        }
        Some((start, count))
    }

    /// 读一个效果列表（`_arr` of `_obj{Effect: F_STR, Amount: F_INT}`，§188）。
    ///
    /// 返回条数。缺席/null 是**合法的空列表**（"这个选项没有效果"），但**越界**不是：
    /// 超过 [`MAX_EVENT_EFFECTS`] 直接报错，不截断。
    fn effect_list(
        &'a self,
        cell: u16,
        out: &mut [EffectSpec<'a>; MAX_EVENT_EFFECTS],
    ) -> Option<u8> {
        let (start, count) = self.list_bounds(cell)?;
        let count = usize::from(count);
        if count > MAX_EVENT_EFFECTS {
            return None;
        }
        for index in 0..count {
            let element = self.aux(start.checked_add(index as u16)?)?;
            let node = crate::ir::NodeRef::new(self, element);
            // 这里返回 Option（与 `Content::event` 的其他读取一致），所以 `Result` 要展开成
            // `None`：**类型不对**说明镜像坏了，不是"这个元素没有效果"。
            let effect = node.str_field("Effect").ok().flatten().unwrap_or("nothing");
            let amount = node.int_field("Amount").ok().flatten().unwrap_or(0);
            out[index] = EffectSpec {
                effect,
                amount: i16::try_from(amount).unwrap_or(0),
            };
        }
        Some(count as u8)
    }
'''


def main():
    s = io.open(P, encoding='utf-8').read()
    start = s.index(OLD_START)
    # 老的段落结尾：`effect_list` 函数的右花括号 + 紧接着的 `}`（关闭 impl）
    tail_anchor = '''        Some(count as u8)
    }

    /// An `F_INT` cell as a number.'''
    end = s.index(tail_anchor, start)
    # 保留 "An F_INT ... " 那段直到 impl 结束
    body = s[start:end]
    assert 'fn effect_list' in body and 'pub fn event(' in body, 'region looks wrong'
    # 用新段替换：从 OLD_START 到 effect_list 结束（`Some(count as u8)\n    }\n`)
    s = s[:start] + NEW + '\n' + s[end:]
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('content.rs: event reader rewritten (EventOption/EventStep/event_step)')


main()
