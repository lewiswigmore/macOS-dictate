from __future__ import annotations

from dictate.code_grammar import transform


def test_empty_string_returns_empty() -> None:
    assert transform("") == ""


def test_text_with_no_triggers_returns_unchanged() -> None:
    assert transform("hello user model") == "hello user model"


def test_snake_case_two_words() -> None:
    assert transform("snake case user id") == "user_id"


def test_camel_case_three_words() -> None:
    assert transform("camel case get user name") == "getUserName"


def test_pascal_case_two_words() -> None:
    assert transform("pascal case user model") == "UserModel"


def test_kebab_case_two_words() -> None:
    assert transform("kebab case my var") == "my-var"


def test_screaming_snake_two_words() -> None:
    assert transform("screaming snake max retries") == "MAX_RETRIES"


def test_common_operator_symbols() -> None:
    assert transform("x equals y plus z minus one") == "x = y + z - one"


def test_double_equals_beats_equals() -> None:
    assert transform("if x double equals y") == "if x == y"


def test_arrow_substitution() -> None:
    assert transform("return foo arrow bar fat arrow baz") == "return foo -> bar => baz"


def test_grouping_symbol_substitution() -> None:
    assert transform("open paren x close paren open brace y close brace") == "( x ) { y }"


def test_bracket_symbol_substitution() -> None:
    assert transform("open bracket index close bracket semicolon") == "[ index ] ;"


def test_keywords_passthrough() -> None:
    assert transform("function hello return if else while for class def") == (
        "function hello return if else while for class def"
    )


def test_composition_case_and_symbols() -> None:
    assert transform("const snake case user id equals foo dot bar semicolon") == (
        "const user_id = foo . bar ;"
    )


def test_strips_trailing_whisper_punctuation() -> None:
    assert transform("return foo arrow bar.") == "return foo -> bar"
