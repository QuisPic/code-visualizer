class Pump {
  inflate() {}
}

class Valve {
  inflate() {}
}

class Shop {
  private valve: Valve;
  fix(p: Pump) {
    p.inflate(); // typed parameter
    this.valve.inflate(); // typed class field
  }
}
