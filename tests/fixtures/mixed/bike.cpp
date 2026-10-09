struct Wheel {
    void spin() {}
};

struct Gear {
    void spin() {}
};

struct Bike {
    Wheel* front;
    void ride(Gear& g) {
        g.spin();       // typed parameter
        front->spin();  // member declared in the class
        auto w = Wheel();
        w.spin();       // auto local from a constructor call
    }
};
