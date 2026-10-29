"""Minimal in-memory stand-in for Streamlit, used only by tests.

It executes the real app.py top to bottom, emulates widgets, session_state,
callbacks (run before the rerun, like Streamlit) and reruns, and enforces a few
of Streamlit's own constraints (progress in [0, 1], widget values inside their
min/max/options). It cannot check Streamlit's real rendering or API drift --
that is what tests/test_app_streamlit.py (AppTest) is for when Streamlit is installed.
"""
import sys
import types


class RerunSignal(Exception):
    pass


class AttrDict(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key) from None

    def __setattr__(self, key, value):
        self[key] = value


class Ctx:
    """Generic container/column/expander/tab: a context manager that forwards
    widget calls (cols[0].metric(...)) to the fake module."""

    def __init__(self, st):
        self._st = st

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getattr__(self, name):
        return getattr(self._st, name)


class FormCtx(Ctx):
    def __init__(self, st, key):
        super().__init__(st)
        self._key = key

    def __enter__(self):
        self._st._form = self._key
        return self

    def __exit__(self, *exc):
        self._st._form = None
        return False


class FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = AttrDict()
        self.out = []
        self.registered = {}
        self.change_callbacks = {}
        self.triggered = set()
        self._form = None
        self.sidebar = Ctx(self)

    # -- generic output ---------------------------------------------------- #
    def _rec(self, name, args, kwargs):
        text = " ".join(str(a) for a in args if isinstance(a, str))
        if isinstance(kwargs.get("text"), str):
            text += " " + kwargs["text"]
        self.out.append((name, text))
        return Ctx(self)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: self._rec(name, a, k)

    # -- layout ------------------------------------------------------------ #
    def columns(self, spec, **_):
        n = spec if isinstance(spec, int) else len(spec)
        return [Ctx(self) for _ in range(n)]

    def tabs(self, labels):
        return [Ctx(self) for _ in labels]

    def expander(self, label, **_):
        self._rec("expander", (label,), {})
        return Ctx(self)

    def container(self, **_):
        return Ctx(self)

    def spinner(self, *_):
        return Ctx(self)

    def form(self, key, **_):
        return FormCtx(self, key)

    def fragment(self, func=None, run_every=None):
        if func is not None:
            return func
        return lambda f: f

    def rerun(self, **_):
        raise RerunSignal()

    def progress(self, value, text=None, **_):
        assert 0.0 <= value <= 1.0, f"st.progress value out of range: {value}"
        self._rec("progress", (), {"text": text})

    # -- widgets ----------------------------------------------------------- #
    def _widget(self, key, default, on_change=None, options=None, lo=None, hi=None):
        if key is None:
            return default
        ss = self.session_state
        if key not in ss:
            ss[key] = default
        value = ss[key]
        if options is not None:
            assert value in options, f"widget {key!r}: {value!r} not in options"
        if lo is not None:
            assert value >= lo, f"widget {key!r}: {value!r} below min {lo}"
        if hi is not None:
            assert value <= hi, f"widget {key!r}: {value!r} above max {hi}"
        if on_change:
            self.change_callbacks[key] = on_change
        return value

    def text_input(self, label, value="", key=None, on_change=None, **_):
        return self._widget(key, value, on_change)

    def text_area(self, label, value="", key=None, **_):
        return self._widget(key, value)

    def number_input(self, label, min_value=None, max_value=None, value=None,
                     step=None, key=None, on_change=None, **_):
        default = value if value is not None else min_value
        return self._widget(key, default, on_change, lo=min_value, hi=max_value)

    def slider(self, label, min_value=None, max_value=None, value=None,
               step=None, key=None, on_change=None, **_):
        default = value if value is not None else min_value
        return self._widget(key, default, on_change, lo=min_value, hi=max_value)

    def selectbox(self, label, options, index=0, key=None, **_):
        options = list(options)
        return self._widget(key, options[index] if options else None, options=options)

    def multiselect(self, label, options, default=None, key=None, **_):
        return self._widget(key, list(default or []))

    def date_input(self, label, value=None, key=None, **_):
        return self._widget(key, value)

    def download_button(self, label, data=None, key=None, **_):
        assert isinstance(data, (str, bytes)), "download_button needs str/bytes data"
        self._rec("download_button", (label,), {})
        return False

    def button(self, label, key=None, on_click=None, args=(), kwargs=None, **_):
        self._rec("button", (label,), {})
        if key is not None:
            self.registered[key] = (on_click, args, kwargs or {})
        return key in self.triggered

    def form_submit_button(self, label, on_click=None, args=(), kwargs=None, **_):
        key = f"{self._form}:{label}"
        self.registered[key] = (on_click, args, kwargs or {})
        return key in self.triggered


class AppRunner:
    """Drives app.py like a user would."""

    def __init__(self, path="app.py"):
        self.path = path
        self.st = FakeStreamlit()

    def run(self):
        sys.modules["streamlit"] = self.st
        self.st.out = []
        self.st.registered = {}
        self.st.change_callbacks = {}
        with open(self.path, encoding="utf-8") as fh:
            source = fh.read()
        code = compile(source, self.path, "exec")
        for _ in range(6):
            try:
                exec(code, {"__name__": "__main__", "__file__": self.path})
                break
            except RerunSignal:
                self.st.triggered = set()
                self.st.out = []
                self.st.registered = {}
                continue
        self.st.triggered = set()
        return self

    def press(self, key):
        callback, args, kwargs = self.st.registered[key]
        if callback:
            callback(*args, **kwargs)
        self.st.triggered = {key}
        return self.run()

    def set(self, key, value):
        self.st.session_state[key] = value
        cb = self.st.change_callbacks.get(key)
        if cb:
            cb()
        return self.run()

    def set_many(self, values):
        for k, v in values.items():
            self.st.session_state[k] = v

    def texts(self, kind=None):
        return [t for n, t in self.st.out if kind is None or n == kind]

    def has_text(self, needle, kind=None):
        return any(needle in t for t in self.texts(kind))

    @property
    def tasks(self):
        return self.st.session_state.tasks
