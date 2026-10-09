import json

from other.text import clean


def summary(text):
    # `clean` is the imported one, not pkg/helpers.clean next door
    return json.dumps(clean(text))
