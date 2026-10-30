import re

BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"(?<!:)//.*$", re.M)
CODE_LINE = re.compile(r"^\s*#(import|include|let|set|show)\b.*$", re.M)
CODE_BLOCK_CALL = re.compile(r"#[\w.-]+\(\{.*?\}\)", re.S)
HASH_IDENTIFIER = re.compile(r"#[\w.-]+")
LINE_START_MARKER = re.compile(r"^\s*(=+|[-+]|\d+\.|/)\s+", re.M)
MARKUP_PUNCTUATION = re.compile(r"[\[\]$*_{}()\\^]")
PLACEHOLDER_GUILLEMETS = re.compile(r"[«»]")
WHITESPACE = re.compile(r"\s+")


def plain_text_from_source(source: str) -> str:
    text = BLOCK_COMMENT.sub(" ", source)
    text = LINE_COMMENT.sub(" ", text)
    text = CODE_LINE.sub(" ", text)
    text = CODE_BLOCK_CALL.sub(" ", text)
    text = HASH_IDENTIFIER.sub(" ", text)
    text = LINE_START_MARKER.sub(" ", text)
    text = MARKUP_PUNCTUATION.sub(" ", text)
    text = PLACEHOLDER_GUILLEMETS.sub("", text)
    text = WHITESPACE.sub(" ", text).strip()
    if text:
        return text
    return WHITESPACE.sub(" ", source).strip()
