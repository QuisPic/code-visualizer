def classify(n, strict=False):
    if n < 0 and strict:  # if, and
        raise ValueError(n)
    elif n == 0:  # elif
        return "zero"
    for d in (2, 3):  # for
        if n % d == 0:  # if
            return "small factor"

    def label(x):  # its branches count for label, not classify
        return "big" if x > 100 else "small"

    try:
        return label(n)
    except TypeError:  # except
        return "?"


def straight():
    return 1
