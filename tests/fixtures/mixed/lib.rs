struct Stack { items: Vec<i32> }

impl Stack {
    fn new() -> Self { Stack { items: Vec::new() } }
    fn push(&mut self, v: i32) { self.items.push(v); self.log(); }
    fn log(&self) {}
}

fn build() -> Stack {
    let mut s = Stack::new();
    s.push(1);
    s
}
