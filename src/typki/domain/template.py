import re
from dataclasses import dataclass

PLACEHOLDER_PATTERN = re.compile(r"«[^«»\n]*»")
FUNCTION_DEFINITION = re.compile(r"^#let\s+([A-Za-z_][\w-]*)\(([^()]*)\)\s*=", re.M)
BLANK_TITLE = "Blank"


@dataclass(frozen=True)
class Template:
    name: str
    front: str

    @property
    def title(self) -> str:
        return self.name or BLANK_TITLE


BLANK = Template(name="", front="")


def positional_parameters(parameter_list: str) -> list[str]:
    parameters = [parameter.strip() for parameter in parameter_list.split(",")]
    return [
        parameter
        for parameter in parameters
        if parameter and ":" not in parameter and not parameter.startswith("..")
    ]


def template_call(name: str, parameter_list: str) -> str:
    parameters = positional_parameters(parameter_list)
    if not parameters:
        return f"#{name}()"
    return f"#{name}" + "".join(f"[«{parameter}»]" for parameter in parameters)


def templates_from_header(header: str) -> tuple[Template, ...]:
    templates: dict[str, Template] = {}
    for match in FUNCTION_DEFINITION.finditer(header):
        name = match.group(1)
        templates.setdefault(name, Template(name=name, front=template_call(name, match.group(2))))
    return (BLANK, *templates.values())


def find_template(name: str, templates: tuple[Template, ...]) -> Template:
    return next((template for template in templates if template.name == name), BLANK)


def placeholder_spans(text: str) -> list[tuple[int, int]]:
    return [(match.start(), match.end()) for match in PLACEHOLDER_PATTERN.finditer(text)]
