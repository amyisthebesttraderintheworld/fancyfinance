class _EmptyPalette:
    def __getattr__(self, _name: str) -> str:
        return ""


Fore = _EmptyPalette()
Style = _EmptyPalette()
Back = _EmptyPalette()


def init(*_args, **_kwargs):
    return None
