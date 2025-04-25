from typing import Literal, TypedDict


class SystemPrompts(TypedDict):
    html_css: str
    html_tailwind: str
    react_tailwind: str
    bootstrap: str
    ionic_tailwind: str
    vue_tailwind: str
    vue_element_tailwind: str
    vue_vant_tailwind: str
    svg: str


Stack = Literal[
    "html_css",
    "html_tailwind",
    "react_tailwind",
    "bootstrap",
    "ionic_tailwind",
    "vue_tailwind",
    "vue_element_tailwind",
    "vue_vant_tailwind",
    "svg",
]
