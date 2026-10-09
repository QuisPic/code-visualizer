function onTick() {}

function finished() {}

function report(value) {}

function schedule() {
  setTimeout(onTick, 10); // a callback: linked
  const finished = 1;
  report(finished); // a variable that shadows a function: not linked
}
