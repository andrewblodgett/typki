SEARCH_SPECIAL_CHARACTERS = ("\\", '"', "*", "_")


def escape_search_text(text: str) -> str:
    for character in SEARCH_SPECIAL_CHARACTERS:
        text = text.replace(character, "\\" + character)
    return text


def quoted_term(key: str, value: str) -> str:
    return f'"{key}:{escape_search_text(value)}"'


def deck_with_children_term(deck_name: str) -> str:
    return quoted_term("deck", deck_name)


def deck_exactly_terms(deck_name: str) -> str:
    return f'{quoted_term("deck", deck_name)} -"deck:{escape_search_text(deck_name)}::*"'
