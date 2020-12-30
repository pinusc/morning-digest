#!/usr/bin/env python

from panflute import run_filters, Span, SmallCaps, Str, Header, Div


def uppercase(elem):
    if type(elem) == Str:
        elem.text = elem.text.upper()
        return elem


def lowercase(elem):
    if type(elem) == Str:
        elem.text = elem.text.lower()
        return elem


def demote(elem, doc):
    if type(elem) == Header:
        parent = elem.parent
        if not (type(parent) == Div and "collection" in parent.classes):
            elem.level += 1
            return elem


def smallcaps(elem, doc):
    def m(el):
        return type(el) == Span and \
            ('caps' in el.attributes or 'small' in el.classes)
    if m(elem) and m(elem.next):
        elem.next.content = [*elem.content, *elem.next.content]
        return []
    elif m(elem):
        content = list(elem.content)
        content = list(map(lowercase, content))
        if type(content[0]) == Str:
            content[0].text = content[0].text.upper()
        return SmallCaps(*elem.content)


def main(doc=None):
    return run_filters([smallcaps, demote], doc=doc)


if __name__ == "__main__":
    main()
