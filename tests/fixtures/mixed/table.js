import * as strings from "./util/strings.js";

function pad(s) {
  return s + " ";
}

export function row(cells) {
  return cells.map((c) => strings.pad(pad(c), 8)).join("|");
}
