function onAlarm() {}

function finished() {}

function report(value) {}

function schedule() {
  setTimeout(onAlarm, 10); // a callback: linked
  const finished = 1;
  report(finished); // a variable that shadows a function: not linked
}
