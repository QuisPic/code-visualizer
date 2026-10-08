import { render } from "./view.js";

class Counter {
  constructor() { this.count = 0; }
  increment() { this.count++; this.update(); }
  update() { render(this.count); }
}

const start = () => {
  const c = new Counter();
  c.increment();
  console.log("started");
};

start();
