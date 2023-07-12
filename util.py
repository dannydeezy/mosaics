def dash_to_camelcase(value):
    def camelcase():
        yield str.lower
        while True:
            yield str.capitalize
    c = camelcase()
    return "".join(next(c)(x) if x else '-' for x in value.split("-"))