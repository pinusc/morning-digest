#!/usr/bin/env python
from panflute import run_filters, Div, Header, Span, LineBreak, Str
from itertools import count
import logging
LOGGER = logging.getLogger()


def ancestor_classes(elem):
    classes = []
    for i in count(start=1):
        anc = elem.ancestor(i)
        if anc is None:
            return classes
        if type(anc) == Div:
            classes += anc.classes


def ancestor_ids(elem):
    ids = []
    for i in count(start=1):
        anc = elem.ancestor(i)
        if anc is None:
            return ids
        if type(anc) == Div:
            ids.append(anc.identifier)


def ignores(elem, doc):
    # if type(elem) == Div and "layout-article-header" in elem.classes:
    #     return []
    # if type(elem) == Header and "atitle" in elem.classes \
    #         and "sole24ore" in ancestor_ids(elem):
    #     print("found title", file=sys.stderr)
    #     return []
    if type(elem) == Span and "subhead" in elem.classes \
            and "meta-part" in elem.classes:
        return []
    if type(elem) == Div and "article-audio-player" in elem.classes:
        return []


def no_multiline_titles(elem, doc):
    if type(elem) == Header:
        return elem.walk(
            lambda elem, doc: Str(" — ") if type(elem) == LineBreak else  elem
        )


if __name__ == "__main__":
    run_filters([ignores, no_multiline_titles])
