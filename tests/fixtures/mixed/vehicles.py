class Engine:
    def ignite(self):
        pass


class Boat:
    def ignite(self):
        pass


class Car:
    def setup(self):
        self.motor = Engine()

    def drive(self, e: Engine):
        e.ignite()  # typed parameter
        self.motor.ignite()  # member assigned in another method
        spare = Engine()
        spare.ignite()  # local assigned from a constructor
