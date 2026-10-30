SEARCH_SPECIAL_CHARACTERS = ("\\", '"', "*", "_")


def escape_search_text(text: str) -> str:
    for character in SEARCH_SPECIAL_CHARACTERS:
        text = text.replace(character, "\\" + character)
    return text


def quoted_term(key: str, value: str) -> str:
    return f'"{key}:{escape_search_text(value)}"'
