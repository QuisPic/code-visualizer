import threading


def crunch():
    pass


def spawn():
    return threading.Thread(target=crunch)
