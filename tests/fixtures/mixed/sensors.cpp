class Sensor {
public:
    void calibrate() {}
};

class Motor {
public:
    void calibrate() {}
};

class Thermometer : public Sensor {
    void boot() {
        calibrate();  // implicit this, inherited from Sensor
    }
};
