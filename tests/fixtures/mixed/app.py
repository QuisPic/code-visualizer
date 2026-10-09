from pkg import helpers


class Greeter:
    def __init__(self, name):
        self.name = name
        self.validate()

    def validate(self):
        return helpers.clean(self.name)

    def greet(self):
        return format_greeting(self.name)


def format_greeting(name):
    """Build the greeting text.

    The name is cleaned first."""
    return "Hello " + helpers.clean(name)


def main():
    g = Greeter("world")
    print(g.greet())


if __name__ == "__main__":
    main()
