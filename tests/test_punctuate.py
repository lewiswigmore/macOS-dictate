from dictate.punctuate import smart_punctuate


def test_capitalizes_first_letter_and_appends_period():
    assert smart_punctuate("hello world") == "Hello world."


def test_leaves_terminal_punct_alone():
    assert smart_punctuate("hello!") == "Hello!"
    assert smart_punctuate("really?") == "Really?"
    assert smart_punctuate("done.") == "Done."


def test_lone_i_becomes_capital():
    assert smart_punctuate("i think i am right") == "I think I am right."


def test_i_contractions():
    assert smart_punctuate("i'm here and i've been") == "I'm here and I've been."
    assert smart_punctuate("i'll go and i'd like that") == "I'll go and I'd like that."


def test_does_not_uppercase_inside_words():
    assert smart_punctuate("kiwi is a fruit") == "Kiwi is a fruit."


def test_empty_input_returns_empty():
    assert smart_punctuate("") == ""
    assert smart_punctuate("   ") == ""


def test_idempotent():
    once = smart_punctuate("hello world")
    twice = smart_punctuate(once)
    assert once == twice


def test_collapses_double_spaces():
    assert smart_punctuate("hello  world") == "Hello world."


def test_strip_fillers_optional():
    assert smart_punctuate("um hello uh world", strip_fillers=True) == "Hello world."
    # default keeps them
    assert "um" in smart_punctuate("um hello uh world").lower()


def test_handles_leading_quote():
    assert smart_punctuate('"hello" world') == '"Hello" world.'
