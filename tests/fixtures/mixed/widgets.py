class Widget:
    def redraw(self):
        pass


class Canvas:
    def redraw(self):
        pass


class Button(Widget):
    def press(self):
        self.redraw()  # inherited from Widget
