import { render } from "./view.js";

class Counter {
  constructor() { this.count = 0; }
  increment() { this.count++; this.update(); }
  update() { render(this.count); }
}

// Create a counter and bump it once.
const start = () => {
  const c = new Counter();
  c.increment();
  console.log("started");
};

start();
